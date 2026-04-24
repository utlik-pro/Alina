"""YClients API Service — READ + CREATE ONLY.

CRITICAL SAFETY RULE:
    ⚠️ NEVER modify, move, or delete existing records.
    ⚠️ Only GET (read) and POST (create new) operations allowed.
    ⚠️ No PUT/PATCH/DELETE on records endpoints.
    ⚠️ Test bookings must be marked with [TEST] comment.
"""

import time
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from loguru import logger

from config import config


class _Cache:
    """Simple TTL cache for API responses."""

    def __init__(self, ttl: int = 300):
        self._ttl = ttl
        self._data: Dict[str, Any] = {}
        self._timestamps: Dict[str, float] = {}

    def get(self, key: str):
        ts = self._timestamps.get(key)
        if ts and (time.time() - ts) < self._ttl:
            return self._data.get(key)
        return None

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._timestamps[key] = time.time()

    def invalidate(self, key: str = None):
        if key:
            self._data.pop(key, None)
            self._timestamps.pop(key, None)
        else:
            self._data.clear()
            self._timestamps.clear()


class YClientsService:
    """YClients API wrapper — safe, read + create only."""

    BASE_URL = "https://api.yclients.com/api/v1"

    def __init__(self):
        self.partner_token = config.YCLIENTS_PARTNER_TOKEN
        self.user_token = config.YCLIENTS_USER_TOKEN
        self.company_id = config.YCLIENTS_COMPANY_ID
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = _Cache(ttl=300)  # 5 min cache for staff/services

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.partner_token}, User {self.user_token}",
            "Accept": "application/vnd.yclients.v2+json",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── READ OPERATIONS ────────────────────────────────────

    async def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Safe GET request.

        Returns the response dict ONLY on HTTP 2xx AND success=true. On
        any failure (network, 4xx/5xx, success=false) logs and returns
        None. Callers MUST distinguish None (API failure) from an empty
        data list (legitimate "no results") — otherwise we end up
        showing made-up content when auth expires.
        """
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self._headers, params=params) as resp:
                try:
                    data = await resp.json()
                except Exception as e:
                    logger.error(
                        f"YClients GET {endpoint}: non-JSON response "
                        f"(status={resp.status}): {e}"
                    )
                    return None

                if resp.status >= 400 or not data.get("success"):
                    msg = (data.get("meta") or {}).get("message", "Unknown error")
                    logger.error(
                        f"YClients GET {endpoint} failed "
                        f"(status={resp.status}, success={data.get('success')}): {msg}"
                    )
                    return None
                return data
        except Exception as e:
            logger.error(f"YClients GET {endpoint} exception: {e}")
            return None

    async def get_staff(self) -> List[Dict]:
        """Get list of therapists/staff (cached 5 min)."""
        cached = self._cache.get("staff")
        if cached is not None:
            return cached
        data = await self._get(f"staff/{self.company_id}")
        if data and data.get("success"):
            staff = data["data"]
            self._cache.set("staff", staff)
            logger.info(f"YClients: loaded {len(staff)} staff members")
            return staff
        return []

    async def get_services(self) -> List[Dict]:
        """Get list of services (cached 5 min)."""
        cached = self._cache.get("services")
        if cached is not None:
            return cached
        data = await self._get(f"services/{self.company_id}")
        if data and data.get("success"):
            services = data["data"]
            self._cache.set("services", services)
            logger.info(f"YClients: loaded {len(services)} services")
            return services
        return []

    async def get_available_dates(self, staff_id: int = None, service_ids: List[int] = None) -> List[str]:
        """Get available booking dates for next 14 days."""
        params = {}
        if staff_id:
            params["staff_id"] = staff_id
        if service_ids:
            params["service_ids[]"] = service_ids

        data = await self._get(f"book_dates/{self.company_id}", params)
        if data and isinstance(data.get("data"), dict):
            # Returns dict of date: is_available
            available = [date for date, avail in data["data"].items() if avail]
            return available
        elif data and isinstance(data.get("data"), list):
            return data["data"]
        return []

    async def get_available_times(self, staff_id: int, date: str, service_id: int = None) -> List[Dict]:
        """Get available time slots for a specific staff member and date.

        Args:
            staff_id: Staff member ID
            date: Date in YYYY-MM-DD format
            service_id: Optional service ID for duration-aware slots

        Returns:
            List of available time slots
        """
        params = {}
        if service_id:
            params["service_ids[]"] = service_id

        data = await self._get(f"book_times/{self.company_id}/{staff_id}/{date}", params)
        if data and isinstance(data.get("data"), list):
            return data["data"]
        return []

    async def get_available_slots_summary(self, date: str = None, service_name: str = None, service_category: str = None, service_id: int = None) -> str:
        """Get human-readable available slots for GPT context.

        Filters by:
        - Current time (no past slots for today)
        - Staff specialization (massage therapists for massage, nail techs for nails)
        - Minimum 60 min between offered slots

        Returns a formatted string like:
        "Tomorrow: Svetlana 10am, 12pm, 4pm | Marina 2pm, 7pm"
        """
        # Use UAE timezone (UTC+4) — Crystal Lab is in Abu Dhabi/Al Ain
        from datetime import timezone
        uae_tz = timezone(timedelta(hours=4))
        now_uae = datetime.now(uae_tz)

        if not date:
            date = (now_uae + timedelta(days=1)).strftime("%Y-%m-%d")

        is_today = date == now_uae.strftime("%Y-%m-%d")
        now_hour = now_uae.hour if is_today else 0
        now_minute = now_uae.minute if is_today else 0

        # Determine if we need massage therapists or nail techs
        is_nails = service_category == "nails" or (service_name and any(
            kw in (service_name or "").lower() for kw in ["mani", "pedi", "nail", "gel", "маникюр"]
        ))

        staff_list = await self.get_staff()
        if not staff_list:
            return "No available slots for this date"

        slots_info = []
        for staff in staff_list:
            staff_name = (staff.get("name", "") or "")
            spec = (staff.get("specialization", "") or "").lower()

            # Skip admin/waiting list
            if "АДМИНИСТРАТОР" in staff_name.upper() or "ЛИСТ ОЖИДАНИЯ" in staff_name.upper():
                continue

            # Filter by specialization
            is_nail_tech = "маникюр" in spec or "nail" in spec.lower()
            is_massage_therapist = "массажист" in spec or "massage" in spec.lower()

            if is_nails and not is_nail_tech:
                continue
            if not is_nails and is_nail_tech:
                continue

            # Find service_id for accurate slot duration
            svc_id = service_id
            if not svc_id and service_name:
                svc_id = await self.find_service_id(service_name)
            # Default: use body massage 60min for massage, Russian mani for nails
            if not svc_id:
                if is_nail_tech:
                    svc_id = await self.find_service_id("Russian gelish manicure")
                else:
                    svc_id = await self.find_service_id("Lymphatic drainage 60 min (new)")

            # Use records-based slot calculation (accounts for travel time)
            time_strs = await self.get_real_available_slots(staff["id"], date, service_duration=60)
            if time_strs:
                time_strs = time_strs[:5]  # Limit to 5 best slots

                if time_strs:
                    # Build display name — transliterate Russian to English
                    NAMES_RU_EN = {
                        "Макхабат": "Makhabat", "Алеся": "Olesya", "Елена": "Elena",
                        "Маша": "Masha", "Светлана": "Svetlana", "Марина": "Marina",
                        "Сафина": "Safina",
                    }
                    first_name_raw = staff_name.split()[0]
                    first_name = NAMES_RU_EN.get(first_name_raw, first_name_raw)
                    if "Al Ain" in staff_name:
                        display_name = first_name + " (Al Ain)"
                    elif is_nail_tech:
                        display_name = first_name + " (nails)"
                    else:
                        display_name = first_name

                    # Check for duplicate first names — add spec to both
                    existing_names = [s.split(":")[0] for s in slots_info]
                    if display_name in existing_names:
                        # Rename the existing one too
                        for idx, s in enumerate(slots_info):
                            if s.startswith(display_name + ":"):
                                slots_info[idx] = s.replace(display_name + ":", display_name + " (massage):")
                        display_name = display_name + " (nails)" if is_nail_tech else display_name + " (massage)"

                    slots_info.append(f"{display_name}: {', '.join(time_strs)}")

        if slots_info:
            return f"Available on {date}:\n" + "\n".join(slots_info)
        # No mock/hardcoded fallback here — if every therapist returned
        # empty slots (day off OR records API failure) we must tell the
        # agent the truth so it doesn't fabricate times.
        return (
            "No slots available for this date from the schedule. "
            "Tell the client honestly there's no availability and "
            "offer to check another day — do NOT invent times."
        )

    # Keyword synonyms: agent-side term → YClients catalog term.
    # Keep short — just enough to bridge common model choices to catalog reality.
    _SERVICE_SYNONYMS = {
        "body_massage": ["lymphatic drainage"],  # "body massage" is too generic; catalog uses lymphatic drainage as the default body offer (new price list)
        "body": ["body massage", "lymphatic drainage"],
        "face_massage": ["lifting drainage facial massage"],
        "facial_massage": ["lifting drainage facial massage"],
        "face": ["facial massage"],
        "lymphatic_drainage": ["lymphatic drainage"],
        "deep_tissue": ["deep tissue"],
        "postpartum": ["postpartum"],
        "prenatal": ["prenatal"],
        "anti_cellulite": ["anti cellulite"],
        "maderatherapie": ["maderatherapie"],
        "russian_manicure": ["russian gelish manicure"],
        "russian_gelish_manicure": ["russian gelish manicure"],
        "japanese_manicure": ["japanese mani"],
        "pedicure": ["russian gelish pedicure", "pedicure"],
        "combo_mani_pedi": ["combo russian gellish mani + pedi", "russian gelish manicure+pedicure"],
        "eyelash_extensions": ["classical volume", "2d volume", "russian volume"],
        "eyelash_lifting": ["eyelash lifting"],
        "eyebrow_lamination": ["eyebrow lamination"],
        "cupping": ["cupping"],
        "guasha": ["goasha", "guasha"],
    }

    async def find_service_id(
        self,
        service_name: str,
        duration_minutes: Optional[int] = None,
    ) -> Optional[int]:
        """Find YClients service ID by name — scored fuzzy match.

        Score components per candidate:
        + 10   all normalized keywords appear in the title
        + 8    title matches a known synonym for this service_name
        + 6    '(new)' tag (Alina's current price list)
        + 4    duration_minutes matches a "<N> min" token in title
        - 6    title is an OFFER / WINTER / CHRISTMAS / NEW YEAR promo
               (unless user explicitly asked for one)
        - 3    title is a (bonus) / (package) variant
               (unless user explicitly asked for one)
        - shortest title among ties wins (fewer extra words = closer match)

        Returns None if no candidate matches all keywords — caller must
        handle None (either ask for clarification or notify admin).
        """
        services = await self.get_services()

        # Normalize incoming name: snake_case → spaces, lowercase, strip.
        raw = (service_name or "").strip()
        name_norm = raw.lower().replace("_", " ").strip()
        keywords = [kw for kw in name_norm.split() if kw]

        # Exact match — only when caller passed the raw YClients title
        # verbatim (e.g. find_service_id("Lymphatic drainage 60 min (new)")).
        # We deliberately do NOT match on the snake-case-normalized form
        # (e.g. "face massage" via "face_massage") because the agent's
        # generic snake_case names collide with short generic titles in
        # the catalog (old "Face massage" 175 AED) and win over the
        # intended synonym ("Lifting drainage facial massage").
        for svc in services:
            if (svc.get("title") or "").lower() == raw.lower():
                return svc["id"]

        # Build list of synonym-expanded keyword sets. If we have a
        # curated synonym for this service_name, use ONLY those — the
        # raw snake_case often matches unrelated generic titles
        # (e.g. "body_massage" → "Body massage" 150 AED, while the
        # intended offering is "Lymphatic drainage …"). Synonyms
        # encode what's actually in the catalog.
        synonyms = self._SERVICE_SYNONYMS.get(raw.lower().strip()) or \
                   self._SERVICE_SYNONYMS.get(name_norm.replace(" ", "_"))
        keyword_sets: List[List[str]] = []
        if synonyms:
            for syn in synonyms:
                keyword_sets.append([kw for kw in syn.lower().split() if kw])
        elif keywords:
            keyword_sets.append(keywords)

        user_wants_offer = any(
            w in name_norm for w in ("offer", "winter", "christmas", "new year")
        )
        user_wants_bonus = any(w in name_norm for w in ("bonus", "package"))

        candidates = []
        for svc in services:
            title = (svc.get("title") or "").lower()
            if not title:
                continue

            # Must match at least one full keyword set.
            matched_set = None
            for ks in keyword_sets:
                if ks and all(kw in title for kw in ks):
                    matched_set = ks
                    break
            if matched_set is None:
                continue

            score = 10

            if "(new)" in title:
                score += 6

            if duration_minutes:
                if f"{duration_minutes} min" in title or f"{duration_minutes}min" in title:
                    score += 4

            if not user_wants_offer and any(
                tag in title
                for tag in ("offer:", "winter offer", "christmas offer",
                            "new year offer", "may offer")
            ):
                score -= 6

            if not user_wants_bonus and (
                "(bonus)" in title or "(package)" in title
            ):
                score -= 3

            candidates.append((score, len(title), svc))

        if not candidates:
            logger.warning(
                f"YClients: no service match for {service_name!r} "
                f"duration={duration_minutes}. Keyword sets tried: {keyword_sets}"
            )
            return None

        # Highest score wins; on tie prefer shorter title (closer match).
        candidates.sort(key=lambda x: (-x[0], x[1], x[2]["id"]))
        best = candidates[0][2]
        logger.info(
            f"YClients: matched {service_name!r} → #{best['id']} "
            f"{best['title']!r} (score={candidates[0][0]}, "
            f"{len(candidates)} candidates)"
        )
        return best["id"]

    async def find_staff_id(self, name: str = None) -> Optional[int]:
        """Find staff ID by name. Returns first available therapist if no name given."""
        staff = await self.get_staff()
        if not staff:
            return None

        if name:
            name_lower = name.lower()
            for s in staff:
                staff_name = (s.get("name", "") or "").lower()
                if name_lower in staff_name or staff_name.startswith(name_lower):
                    return s["id"]
            # Name given but not found — return None (don't fallback to random therapist)
            return None

        # No name given — return first non-admin staff
        for s in staff:
            sname = (s.get("name", "") or "").upper()
            if "АДМИНИСТРАТОР" not in sname and "ЛИСТ ОЖИДАНИЯ" not in sname:
                return s["id"]

        return staff[0]["id"] if staff else None

    async def find_client_by_phone(self, phone: str) -> Optional[Dict]:
        """Search for a client in YClients by phone number. Returns first match or None.

        Phone should be in international format (e.g. "971501234567" or "+971501234567").
        """
        if not phone:
            return None
        # Normalize: strip non-digits
        phone_clean = "".join(c for c in phone if c.isdigit())
        if not phone_clean:
            return None

        # YClients supports search by phone via ?phone= or ?q= param
        data = await self._get(f"company/{self.company_id}/clients/search", params={
            "phone": phone_clean,
        })
        if not data:
            # Fallback: old-style /clients/search might not exist, try records?phone=
            return None

        clients_list = data.get("data") if isinstance(data, dict) else data
        if not isinstance(clients_list, list) or not clients_list:
            return None
        return clients_list[0]

    async def get_client_bookings(self, client_id: int, limit: int = 10) -> List[Dict]:
        """Get recent bookings (records) for a client."""
        data = await self._get(f"records/{self.company_id}", params={
            "client_id": client_id,
            "count": limit,
        })
        if data and isinstance(data.get("data"), list):
            return data["data"]
        return []

    async def get_records(self, staff_id: int, date: str) -> Optional[List[Dict]]:
        """Get existing bookings for a staff member on a date. READ ONLY.

        Returns None on API failure (auth, network, server error) so the
        caller can distinguish "schedule unavailable" from "schedule is
        empty". Returns [] when the API succeeds but the staff member
        has zero bookings that day.
        """
        data = await self._get(f"records/{self.company_id}", params={
            "staff_id": staff_id,
            "start_date": date,
            "end_date": date,
        })
        if data is None:
            return None  # API failure — propagate upward
        if isinstance(data.get("data"), list):
            return data["data"]
        return []

    async def get_real_available_slots(self, staff_id: int, date: str, service_duration: int = 60) -> List[str]:
        """Calculate truly available slots based on existing records + travel buffer.

        Logic:
        - Get all existing bookings for the day
        - For each booking: end_time = start + duration + 60 min buffer (travel)
        - Available slot = gap of at least (service_duration) between buffered bookings
        - Start from 10:00, end at 21:00
        - Only :00 and :30 slots
        """
        from datetime import timezone
        uae_tz = timezone(timedelta(hours=4))
        now_uae = datetime.now(uae_tz)
        is_today = date == now_uae.strftime("%Y-%m-%d")

        # First check if staff works this day (book_times = 0 means day off)
        book_times = await self.get_available_times(staff_id, date)
        if not book_times:
            return []  # Day off — no slots

        records = await self.get_records(staff_id, date)
        if records is None:
            # YClients records API failed (auth, network, 5xx). Returning
            # a slot grid with 0 bookings subtracted would produce fake
            # availability — worse than saying nothing. Refuse to guess.
            logger.error(
                f"YClients: records API unavailable for staff {staff_id} "
                f"on {date} — refusing to generate slots (would be fake)"
            )
            return []

        # Parse booking blocks: [(start_min, end_min_with_buffer), ...]
        blocks = []
        for rec in records:
            dt_str = rec.get("datetime", "")
            length = rec.get("seance_length", 3600)  # seconds

            try:
                dt = datetime.fromisoformat(dt_str)
                start_min = dt.hour * 60 + dt.minute
                duration_min = length // 60
                # Block = 60 min before arrival + session + 60 min travel after
                block_start = start_min - 60  # 60 min travel TO client
                block_end = start_min + duration_min + 60  # session + 60 min travel AFTER
                blocks.append((block_start, block_end))
            except (ValueError, AttributeError):
                continue

        blocks.sort()

        # Find free slots between blocks
        WORK_START = 10 * 60  # 10:00
        WORK_END = 21 * 60    # 21:00 (last booking)

        available = []
        cursor = WORK_START

        # Skip past times for today
        if is_today:
            current_min = now_uae.hour * 60 + now_uae.minute + 30  # +30 min minimum
            cursor = max(cursor, current_min)

        for block_start, block_end in blocks:
            # Check gap before this block
            while cursor + service_duration <= block_start and cursor < WORK_END:
                # Round to :00 or :30
                h, m = divmod(cursor, 60)
                if m < 15:
                    slot_min = h * 60
                elif m < 45:
                    slot_min = h * 60 + 30
                else:
                    slot_min = (h + 1) * 60

                if slot_min >= cursor and slot_min + service_duration <= block_start and slot_min < WORK_END:
                    sh, sm = divmod(slot_min, 60)
                    available.append(f"{sh}:{sm:02d}")
                    cursor = slot_min + service_duration + 60  # Next slot after this + buffer
                else:
                    cursor += 30
            # Skip past this block
            cursor = max(cursor, block_end)

        # Check gap after last block
        while cursor < WORK_END:
            h, m = divmod(cursor, 60)
            if m < 15:
                slot_min = h * 60
            elif m < 45:
                slot_min = h * 60 + 30
            else:
                slot_min = (h + 1) * 60

            if slot_min >= cursor and slot_min + service_duration <= WORK_END + 60:
                sh, sm = divmod(slot_min, 60)
                available.append(f"{sh}:{sm:02d}")
                cursor = slot_min + service_duration + 60
            else:
                cursor += 30

        return available

    # ─── CREATE OPERATIONS (NEW RECORDS ONLY) ───────────────

    async def create_booking(
        self,
        staff_id: int,
        service_ids: List[int],
        date: str,
        time: str,
        client_name: str = "",
        client_phone: str = "",
        client_email: str = "",
        comment: str = "",
        is_test: bool = True,
    ) -> Optional[Dict]:
        """Create a NEW booking in YClients.

        ⚠️ SAFETY: This ONLY creates new records. Never modifies existing ones.
        Test bookings are marked with [TEST] in comment.

        Args:
            staff_id: Therapist ID
            service_ids: List of service IDs
            date: Date in YYYY-MM-DD format
            time: Time in HH:MM format (24h)
            client_name: Client name
            client_phone: Client phone
            client_email: Client email
            comment: Additional comment
            is_test: If True, adds [TEST] prefix to comment

        Returns:
            Created record data or None
        """
        if is_test:
            comment = f"[TEST] {comment}".strip()

        # Build services array
        services = [{"id": sid} for sid in service_ids]

        payload = {
            "staff_id": staff_id,
            "services": services,
            "datetime": f"{date}T{time}:00+03:00",  # YClients uses Europe/Minsk (UTC+3)
            "seance_length": 3600,  # Default 60 min in seconds
            "save_if_busy": False,
            "comment": comment,
            "client": {},
        }

        # Add client info
        if client_name:
            payload["client"]["name"] = client_name
        if client_phone:
            payload["client"]["phone"] = client_phone
        if client_email:
            payload["client"]["email"] = client_email

        url = f"{self.BASE_URL}/records/{self.company_id}"

        try:
            session = await self._get_session()
            async with session.post(url, headers=self._headers, json=payload) as resp:
                data = await resp.json()
                if data.get("success"):
                    record_id = data["data"].get("id", "?")
                    logger.info(f"YClients: created booking #{record_id} for {client_name} on {date} {time}")
                    return data["data"]
                else:
                    error_msg = data.get("meta", {}).get("message", "Unknown error")
                    logger.error(f"YClients: failed to create booking: {error_msg}")
                    return None
        except Exception as e:
            logger.error(f"YClients: create booking exception: {e}")
            return None

    # ─── FORBIDDEN OPERATIONS ───────────────────────────────
    # These methods are intentionally NOT implemented.
    # DO NOT add update_booking(), delete_booking(), or any PUT/PATCH/DELETE methods.
