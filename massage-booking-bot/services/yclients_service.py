"""YClients API Service — READ + CREATE ONLY.

CRITICAL SAFETY RULE:
    ⚠️ NEVER modify, move, or delete existing records.
    ⚠️ Only GET (read) and POST (create new) operations allowed.
    ⚠️ No PUT/PATCH/DELETE on records endpoints.
    ⚠️ Test bookings must be marked with [TEST] comment.
"""

import re
import time
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from loguru import logger

from config import config


# Russian → English transliteration for the real Crystal Lab staff. The
# YClients name field often carries area + handover notes ("Людмила/с 20.06
# Махабат", "Элиза Al Ain", "Маша с 23.06"), so we extract the leading clean
# name token and transliterate it for English-speaking UAE clients.
STAFF_NAMES_RU_EN = {
    "Элиза": "Eliza",
    "Фарида": "Farida",
    "Наталья": "Natalia",
    "Наталия": "Natalia",
    "Татьяна": "Tatyana",
    "Марина": "Marina",
    "Людмила": "Lyudmila",
    "Махабат": "Makhabat",
    "Макхабат": "Makhabat",
    "Екатерина": "Ekaterina",
    "Катя": "Ekaterina",
    "Алеся": "Olesya",
    "Олеся": "Olesya",
    "Елена": "Elena",
    "Маша": "Masha",
    "Мария": "Maria",
    "Светлана": "Svetlana",
    "Сафина": "Safina",
    "Ольга": "Olga",
}


def _display_first_name(staff_name: str) -> str:
    """Extract a clean, English first name from a messy YClients staff label.

    Handles embedded area/handover noise: "Людмила/с 20.06 Махабат" → "Lyudmila",
    "Элиза Al Ain" → "Eliza", "Фарида Абу Даби" → "Farida".
    """
    if not staff_name:
        return "Therapist"
    # First run of letters (Cyrillic or Latin), dropping "/с", dates, digits.
    m = re.match(r"[A-Za-zА-Яа-яЁё]+", staff_name.strip())
    token = m.group(0) if m else staff_name.split()[0]
    return STAFF_NAMES_RU_EN.get(token, token)


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
                # Offer up to 5 slots SPREAD across the day (morning → evening)
                # rather than the first 5 (which were always morning and hid
                # the "после 6 всё свободно" evening availability).
                if len(time_strs) > 5:
                    step = (len(time_strs) - 1) / 4.0  # 5 picks incl. first & last
                    idxs = sorted({round(i * step) for i in range(5)})
                    time_strs = [time_strs[i] for i in idxs]

                if time_strs:
                    # Build display name — transliterate Russian to English so
                    # English-speaking UAE clients never see Cyrillic.
                    first_name = _display_first_name(staff_name)
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
        # Body + Face combo — catalog title is "Face + body 110 min (new)"
        "body_face_combo": ["face + body"],
        "combo_body_face": ["face + body"],
        "face_body_combo": ["face + body"],
        "lymphatic_drainage": ["lymphatic drainage"],
        "deep_tissue": ["deep tissue"],
        "postpartum": ["postpartum"],
        "postpartum_massage": ["postpartum"],
        "prenatal": ["prenatal"],
        "prenatal_massage": ["prenatal"],
        "anti_cellulite": ["anti cellulite"],
        "maderatherapie": ["maderatherapie"],
        "russian_manicure": ["russian gelish manicure"],
        "russian_gelish_manicure": ["russian gelish manicure"],
        "japanese_manicure": ["japanese mani"],
        # Bare "pedicure" must NOT fall back to "Men's pedicure" (won on
        # shortness) — default to the women's standalone gelish pedicure.
        # Catalog title: "Gellish Russian pedicure with machine (smart disc)".
        # Default any bare "pedicure" to the women's Russian pedicure, never
        # "Men's pedicure" (which used to win on title shortness).
        "pedicure": ["russian pedicure"],
        "russian_pedicure": ["russian pedicure"],
        "russian_gelish_pedicure": ["gellish russian pedicure"],
        "combo_mani_pedi": ["combo russian gellish mani + pedi", "russian gelish manicure+pedicure"],
        "eyelash_extensions": ["classical volume", "2d volume", "russian volume"],
        "eyelash_extension": ["classical volume", "2d volume", "russian volume"],
        # "classic/classical" eyelashes → the "Classical volume" catalog title
        "classic_eyelash_extension": ["classical volume"],
        "classical_eyelash_extension": ["classical volume"],
        "lash_ext_classic": ["classical volume"],
        "classic_volume": ["classical volume"],
        "classical_volume": ["classical volume"],
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
        user_wants_combo = any(
            w in name_norm for w in ("combo", "+", "mani pedi", "mani and pedi",
                                     "manicure pedicure", "and pedi", "both")
        )

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

            # Combo/multi-service titles ("… manicure + pedicure", "mani + pedi")
            # must not win a single-service query — "pedicure" was resolving to
            # "Russian gellish manicure+pedicure" because "pedicure" is a
            # substring of the combo title. Penalise combos unless the client
            # explicitly asked for one.
            is_combo_title = (
                "+" in title
                or ("mani" in title and "pedi" in title)
                or ("manicure" in title and "pedicure" in title)
            )
            if is_combo_title and not user_wants_combo:
                score -= 5

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

    async def find_staff_id(
        self,
        name: Optional[str] = None,
        area: Optional[str] = None,
    ) -> Optional[int]:
        """Find staff ID by name and/or area.

        Args:
            name: therapist first name (English or Russian). Matched
                by substring, case-insensitive.
            area: "abu_dhabi" | "al_ain" | None. When set, filters out
                therapists based on the "Al Ain" marker in their name:
                  - abu_dhabi → exclude "Al Ain" therapists (they work
                    in a different emirate; sending them to Abu Dhabi
                    costs a 90-minute drive each way).
                  - al_ain → only "Al Ain" therapists.
                  - None → no area filter.

        When both name and area are set, area is the hard filter; name
        is matched within the area-filtered pool.

        Returns None if nothing matches.  Callers that got None should
        NOT fall back to a random therapist — they should surface the
        problem to the admin instead, otherwise the therapist is sent
        to the wrong city.
        """
        staff = await self.get_staff()
        if not staff:
            return None

        def _is_al_ain(s: Dict) -> bool:
            return "al ain" in (s.get("name", "") or "").lower()

        def _is_admin(s: Dict) -> bool:
            n = (s.get("name", "") or "").upper()
            return "АДМИНИСТРАТОР" in n or "ЛИСТ ОЖИДАНИЯ" in n

        # Apply area filter first.
        pool = [s for s in staff if not _is_admin(s)]
        if area == "al_ain":
            pool = [s for s in pool if _is_al_ain(s)]
        elif area == "abu_dhabi":
            pool = [s for s in pool if not _is_al_ain(s)]

        if not pool:
            logger.warning(
                f"YClients.find_staff_id: no candidates for "
                f"area={area!r} name={name!r}"
            )
            return None

        if name:
            # Catalog names are in Russian ("Алеся", "Марина", …) but
            # clients and the agent use English names. Expand the query
            # to both languages. Reverse of NAMES_RU_EN from
            # get_available_slots_summary.
            EN_TO_RU = {
                "makhabat": "махабат",   # catalog spelling is "Махабат"
                "olesya":   "алеся",
                "elena":    "елена",
                "masha":    "маша",
                "maria":    "мария",
                "svetlana": "светлана",
                "marina":   "марина",
                "safina":   "сафина",
                "eliza":    "элиза",     # Al Ain's sole master — was missing → Al-Ain sync failed
                "farida":   "фарида",    # main Abu Dhabi master — was missing → sync failed
                "natalia":  "наталья",
                "natalya":  "наталья",
                "lyudmila": "людмила",
                "tatyana":  "татьяна",
                "ekaterina": "екатерина",
                "olga":     "ольга",
            }
            needle = name.lower().strip()
            aliases = {needle}
            # If English → add Russian form, and vice-versa.
            if needle in EN_TO_RU:
                aliases.add(EN_TO_RU[needle])
            # Also add a couple of common spelling variants.
            if needle == "makhabat":
                aliases.add("макхабат")
            for en, ru in EN_TO_RU.items():
                if needle == ru:
                    aliases.add(en)
            for s in pool:
                raw_name = s.get("name", "") or ""
                staff_name = raw_name.lower()
                # Also compare against the transliterated first name (single
                # source of truth STAFF_NAMES_RU_EN) so matching survives
                # roster renames without touching EN_TO_RU. e.g. catalog
                # "Людмила Дубай" → display "lyudmila" matches agent "Lyudmila".
                disp = _display_first_name(raw_name).lower()
                if any(a in staff_name or staff_name.startswith(a) for a in aliases) \
                        or needle == disp or needle in disp.split():
                    return s["id"]

            # Name didn't match, but if the area filter left exactly ONE real
            # candidate (e.g. Al Ain = only "Элиза Al Ain"), that IS who the
            # client gets — return it instead of None (None skips the YClients
            # sync entirely, so the appointment never reaches the calendar).
            if len(pool) == 1:
                logger.info(
                    f"YClients.find_staff_id: name {name!r} unmatched but only "
                    f"one master in area={area!r} → using {pool[0].get('name')!r}"
                )
                return pool[0]["id"]

            logger.warning(
                f"YClients.find_staff_id: name {name!r} (aliases={aliases}) "
                f"not found in area={area!r} pool (size={len(pool)})"
            )
            return None

        # No name — return first from filtered pool.
        return pool[0]["id"]

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
        """Truly available slots = YClients' own bookable times, minus a
        60-min travel buffer around existing home visits.

        Why this shape:
        - `book_times` is YClients' GROUND TRUTH — it already respects each
          master's real working hours (e.g. evening-only), day-offs, and
          existing bookings. We must NOT recompute a hardcoded 10:00–21:00
          grid (the old bug: it invented morning slots for evening-only
          masters and dropped genuine evening availability — "после 6 всё
          свободно" never showed).
        - The ONE thing book_times doesn't know is our outbound travel time
          between two home visits, so we additionally drop any native slot
          that lands within 60 min of an existing booking.
        - For today we drop past times (+30 min lead).
        """
        from datetime import timezone
        uae_tz = timezone(timedelta(hours=4))
        now_uae = datetime.now(uae_tz)
        is_today = date == now_uae.strftime("%Y-%m-%d")

        # Native bookable times (already working-hours & booking aware).
        book_times = await self.get_available_times(staff_id, date)
        if not book_times:
            return []  # Day off / fully booked — no slots

        # Existing visits → raw (start, end) minute intervals for travel-gap.
        records = await self.get_records(staff_id, date)
        if records is None:
            logger.error(
                f"YClients: records API unavailable for staff {staff_id} "
                f"on {date} — slots may not account for travel buffer"
            )
            records = []

        raw_blocks = []
        for rec in records:
            try:
                dt = datetime.fromisoformat(rec.get("datetime", ""))
                start_min = dt.hour * 60 + dt.minute
                dur_min = int(rec.get("seance_length", 3600)) // 60
                raw_blocks.append((start_min, start_min + dur_min))
            except (ValueError, AttributeError, TypeError):
                continue

        TRAVEL = 60  # minutes between two home visits

        def _conflicts(slot_min: int) -> bool:
            """True if a new session at slot_min can't fit around existing
            visits with TRAVEL minutes on each side."""
            ns, ne = slot_min, slot_min + service_duration
            for rs, re_ in raw_blocks:
                if ns < re_ + TRAVEL and rs < ne + TRAVEL:
                    return True
            return False

        # Parse native slot times → minutes.
        candidates = []
        for t in book_times:
            ts = (t.get("time") or "").strip()
            try:
                hh, mm = ts.split(":")
                candidates.append(int(hh) * 60 + int(mm))
            except (ValueError, AttributeError):
                continue
        candidates = sorted(set(candidates))

        min_today = now_uae.hour * 60 + now_uae.minute + 30  # +30 min lead

        # Greedily keep valid slots, spaced by at least one service length so
        # the offered set spreads across the day (morning → evening) instead
        # of clustering in the first hour.
        chosen = []
        last = -10 ** 9
        for m in candidates:
            if is_today and m < min_today:
                continue
            if _conflicts(m):
                continue
            if m - last < service_duration:
                continue
            chosen.append(m)
            last = m

        return [f"{m // 60}:{m % 60:02d}" for m in chosen]

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
        duration_minutes: int = 60,
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

        # Seance length must match the real service duration — a 90-min
        # massage written as 60 min overlaps the next slot in the calendar.
        seance_length = max(int(duration_minutes or 60), 15) * 60

        payload = {
            "staff_id": staff_id,
            "services": services,
            # NOTE: the YClients account is configured in UTC+3 and the salon
            # enters Abu-Dhabi wall-clock times against it, so existing records
            # read back as "<UAE local>T..+03:00". We send the same convention
            # (client's UAE wall-clock + +03:00) so our record lands at the
            # exact hour the admin sees. Verified against live records.
            "datetime": f"{date}T{time}:00+03:00",
            "seance_length": seance_length,
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
