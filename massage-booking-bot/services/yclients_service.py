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


def _staff_area(staff_name: str) -> str:
    """Classify a therapist's service area from the tag in their YClients name.

    The salon encodes the emirate directly in the master's display name, e.g.
    "Элиза Al Ain" → Al Ain, "Людмила Дубай" → Dubai. Untagged masters
    (e.g. "Наталья") work the home base — Abu Dhabi.

    Each master serves exactly ONE emirate: a client is only ever shown /
    booked with masters from their own area, because cross-emirate drives
    (Abu Dhabi ↔ Al Ain ↔ Dubai) aren't offered.

    Returns one of: "al_ain", "dubai", "abu_dhabi".
    """
    n = (staff_name or "").lower()
    # Latin + Cyrillic spellings — a Cyrillic "Аль-Айн" marker/tag used to fall
    # through to Abu Dhabi and misroute the master.
    if "al ain" in n or "al-ain" in n or "alain" in n or "аль айн" in n or "аль-айн" in n:
        return "al_ain"
    if "дубай" in n or "dubai" in n:
        return "dubai"
    return "abu_dhabi"


_EMIRATE_KW_RE = re.compile(r"(al\s*ain|аль.?айн|абу.?даб|dubai|дубай|abu\s*dhabi)", re.I)


def _is_emirate_marker(rec: dict) -> bool:
    """True for an admin 'pin' record, not a real client visit.

    The salon marks a FLOATING master's emirate-of-the-day with a daily ~09:00
    record that has NO client and whose comment is just the emirate
    ("Дубай" / "Абу-Даби" / "Al ain"). Confirmed live in YClients for Людмила,
    whose name tag ("Дубай") is only her default — her real emirate varies by
    day. Such a record must NOT count as a visit (it would consume a booking
    slot + travel buffer, hiding her 10:00/10:30), and its comment tells us her
    area for that date.
    """
    c = (rec.get("comment") or "").strip()
    if not c or len(c) > 20:
        return False
    if rec.get("client"):
        return False
    return _EMIRATE_KW_RE.search(c) is not None


def _marker_area_from_records(records) -> Optional[str]:
    """A floating master's emirate for the day, read from the 09:00 pin record.
    None when there's no marker (→ caller falls back to the name-tag area)."""
    for rec in (records or []):
        if _is_emirate_marker(rec):
            return _staff_area(rec.get("comment") or "")
    return None


def _to_ampm(hhmm: str) -> str:
    """Format a 24-hour "H:MM" slot as 12-hour AM/PM for the client.

    UAE clients read time as AM/PM, not 24-hour ("17:00" reads as wrong/odd).
    "17:00" → "5:00 PM", "9:30" → "9:30 AM", "0:00" → "12:00 AM". Booking stays
    24-hour internally; this is display-only. Unparseable input passes through.
    """
    try:
        h_str, m_str = hhmm.split(":")
        h, m = int(h_str), int(m_str)
    except (ValueError, AttributeError):
        return hhmm
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


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
            # Hard timeout so a hung YClients backend can't stall a whole
            # conversation for aiohttp's 300s default while holding the
            # per-phone lock. A timeout raises → _get returns None → callers
            # treat it as an outage (fail-open on the gate, "checking with the
            # team" to the client) rather than a 5-minute freeze.
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
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

    async def get_available_times(self, staff_id: int, date: str, service_id: int = None) -> Optional[List[Dict]]:
        """Get available time slots for a specific staff member and date.

        Returns:
            list of slots on success (possibly empty = real day off / fully booked),
            or **None** when the YClients API call FAILED (auth/5xx/network). The
            None-vs-[] distinction is load-bearing: an outage must never be shown
            to a client as "no availability" nor block a real booking (see
            get_real_available_slots / get_available_slots_summary / is_slot_available).
        """
        params = {}
        if service_id:
            params["service_ids[]"] = service_id

        data = await self._get(f"book_times/{self.company_id}/{staff_id}/{date}", params)
        if data is None:
            return None  # API failure — propagate, do NOT conflate with a day off
        if isinstance(data.get("data"), list):
            return data["data"]
        return []

    async def get_available_slots_summary(self, date: str = None, service_name: str = None, service_category: str = None, service_id: int = None, area: str = None, service_duration: int = None) -> str:
        """Get human-readable available slots for GPT context.

        Filters by:
        - Current time (no past slots for today)
        - Staff specialization (massage therapists for massage, nail techs for nails)
        - Area (abu_dhabi / al_ain / dubai) — each master serves one emirate
          only; a client is never shown masters from another emirate (no
          cross-emirate drives)
        - Service duration — a slot is only offered if the FULL session fits
          before the next visit (a 90-min service needs a 90-min gap, not 60).
          Defaults to 60 min when the client hasn't stated a duration yet.

        Returns a formatted string like:
        "Tomorrow: Svetlana 10am, 12pm, 4pm | Marina 2pm, 7pm"
        """
        # Determine if we need massage therapists or nail techs
        is_nails = service_category == "nails" or (service_name and any(
            kw in (service_name or "").lower() for kw in ["mani", "pedi", "nail", "gel", "маникюр"]
        ))

        # How long the actual session runs. If the client asked for a 90-min
        # massage we must not offer a slot that only has 60 min free. When the
        # duration is unknown, default to the service's realistic minimum: nail
        # services run ≥2h (a "manicure" with no "gel" keyword used to fall back
        # to 60 min and get offered back-to-back slots — впритык), massages 60.
        if service_duration:
            slot_duration = int(service_duration)
        elif is_nails:
            slot_duration = 120
        else:
            slot_duration = 60
        # Use UAE timezone (UTC+4) — Crystal Lab is in Abu Dhabi/Al Ain
        from datetime import timezone
        uae_tz = timezone(timedelta(hours=4))
        now_uae = datetime.now(uae_tz)

        if not date:
            date = (now_uae + timedelta(days=1)).strftime("%Y-%m-%d")

        is_today = date == now_uae.strftime("%Y-%m-%d")
        now_hour = now_uae.hour if is_today else 0
        now_minute = now_uae.minute if is_today else 0

        staff_list = await self.get_staff()
        if not staff_list:
            return "No available slots for this date"

        import asyncio as _asyncio

        # 1a) Roster: drop admin + wrong specialisation (pure, no API). Area is
        #     resolved NEXT, per date — a floating master's emirate can differ
        #     from her name tag on a given day (see _is_emirate_marker).
        roster = []
        for staff in staff_list:
            staff_name = (staff.get("name", "") or "")
            spec = (staff.get("specialization", "") or "").lower()
            if "АДМИНИСТРАТОР" in staff_name.upper() or "ЛИСТ ОЖИДАНИЯ" in staff_name.upper():
                continue
            is_nail_tech = "маникюр" in spec or "nail" in spec.lower()
            if is_nails and not is_nail_tech:
                continue
            if not is_nails and is_nail_tech:
                continue
            roster.append((staff, is_nail_tech))

        # 1b) Fetch each roster member's records ONCE (parallel) — reused for
        #     the per-date emirate marker AND (passed down) the travel buffer.
        _recs_list = await _asyncio.gather(
            *[self.get_records(s["id"], date) for s, _ in roster],
            return_exceptions=True,
        )

        # 1c) Area filter using the EFFECTIVE area for THIS date: the daily
        #     emirate marker wins, else the name tag. A client only ever sees
        #     masters actually in their emirate that day — no cross-emirate drive.
        candidates = []
        for (staff, is_nail_tech), recs in zip(roster, _recs_list):
            if isinstance(recs, Exception):
                recs = None
            eff_area = _marker_area_from_records(recs) or _staff_area(staff.get("name", "") or "")
            if area and eff_area != area:
                continue
            candidates.append((staff, is_nail_tech, recs, eff_area))

        # Nails are offered in Abu Dhabi ONLY (no nail tech works Al Ain/Dubai).
        # Without this, a Dubai client asking for a manicure got the generic
        # "no availability, try another day" — an endless dead-end (they'd keep
        # asking "Saturday? Sunday?"). Tell them the truth: it's the emirate,
        # not the day. Report where nails ARE available, data-driven.
        if is_nails and not candidates:
            nail_areas = {
                _staff_area(s.get("name", "") or "")
                for s in staff_list
                if ("маникюр" in (s.get("specialization", "") or "").lower()
                    or "nail" in (s.get("specialization", "") or "").lower())
            }
            if nail_areas and area and area not in nail_areas:
                pretty = {"abu_dhabi": "Abu Dhabi", "al_ain": "Al Ain", "dubai": "Dubai"}
                where = ", ".join(sorted(pretty.get(a, a) for a in nail_areas))
                return (
                    f"NAILS ARE NOT AVAILABLE in this area. Nail services are "
                    f"offered in {where} only. Tell the client honestly that "
                    f"nails aren't available in their emirate (do NOT offer "
                    f"another day — it's the location, not the schedule)."
                )

        # 2) Fetch every candidate's slots IN PARALLEL. This loop used to run
        #    sequentially (~9 masters × 2+ YClients calls each), which pushed a
        #    single turn past the 30s agent timeout on prod ("Sorry dear, one
        #    moment, please repeat"). asyncio.gather collapses it to ~one round
        #    trip. Every master gets the SAME slot_duration (a service's length
        #    is the same whoever performs it), so we resolve it once above.
        slot_lists = await _asyncio.gather(
            *[self.get_real_available_slots(s["id"], date, slot_duration, records=recs)
              for s, _, recs, _ in candidates],
            return_exceptions=True,
        )

        # An API outage returns None (or raises) per master — distinct from an
        # empty list (real day off). If EVERY candidate is unavailable due to an
        # outage we must NOT tell the client "no availability" (that's a lie that
        # sends them away during a YClients blip). Track it.
        had_outage = any(r is None or isinstance(r, Exception) for r in slot_lists)

        slots_info = []
        for (staff, is_nail_tech, _recs, eff_area), time_strs in zip(candidates, slot_lists):
            if isinstance(time_strs, Exception) or not time_strs:
                continue
            staff_name = (staff.get("name", "") or "")
            # Show ALL free slots (ground truth) so the agent can confirm a
            # specific requested time ("17:30?") instead of wrongly rejecting it.
            # The prompt still tells the agent to OFFER only 2-3 to the client.
            # Cap high enough to keep an ENTIRE open day (10:00–21:00 at 30-min
            # granularity ≈ 23 slots) — the old cap of 12 thinned out interior
            # times, so a client asking for a dropped slot was told it's taken.
            _CAP = 24
            if len(time_strs) > _CAP:
                step = (len(time_strs) - 1) / float(_CAP - 1)
                idxs = sorted({round(i * step) for i in range(_CAP)})
                time_strs = [time_strs[i] for i in idxs]

            # Display name — transliterate Russian to English. Use the EFFECTIVE
            # area for the date (marker-aware), so a floating master isn't
            # mislabelled "(Dubai)" on a day her marker puts her in Abu Dhabi.
            first_name = _display_first_name(staff_name)
            _area_tag = eff_area
            if _area_tag == "al_ain":
                display_name = first_name + " (Al Ain)"
            elif _area_tag == "dubai":
                display_name = first_name + " (Dubai)"
            elif is_nail_tech:
                display_name = first_name + " (nails)"
            else:
                display_name = first_name

            # Disambiguate duplicate first names.
            existing_names = [s.split(":")[0] for s in slots_info]
            if display_name in existing_names:
                for idx, s in enumerate(slots_info):
                    if s.startswith(display_name + ":"):
                        slots_info[idx] = s.replace(display_name + ":", display_name + " (massage):")
                display_name = display_name + " (nails)" if is_nail_tech else display_name + " (massage)"

            slots_info.append(f"{display_name}: {', '.join(_to_ampm(t) for t in time_strs)}")

        if slots_info:
            return f"Available on {date}:\n" + "\n".join(slots_info)
        # Nothing to show. Distinguish a genuine empty schedule from a YClients
        # OUTAGE — telling a client "no availability, try another day" during an
        # API blip sends them away wrongly. On outage, ask them to hold instead.
        if had_outage:
            return (
                "SCHEDULE TEMPORARILY UNAVAILABLE (YClients did not respond). Do "
                "NOT tell the client the day is fully booked and do NOT invent "
                "times — tell them warmly you're checking with the team and will "
                "confirm a time shortly."
            )
        # No mock/hardcoded fallback here — a real empty schedule: tell the agent
        # the truth so it doesn't fabricate times.
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
        date: Optional[str] = None,
    ) -> Optional[int]:
        """Find staff ID by name and/or area.

        Args:
            name: therapist first name (English or Russian). Matched
                by substring, case-insensitive.
            area: "abu_dhabi" | "al_ain" | "dubai" | None. When set, keeps
                only therapists whose YClients name tags them to that emirate
                ("Al Ain" / "Дубай"; untagged = Abu Dhabi). Each master serves
                exactly one emirate — a booking is never routed across emirates
                (that would cost a 90-minute drive each way). None → no filter.

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

        def _is_admin(s: Dict) -> bool:
            n = (s.get("name", "") or "").upper()
            return "АДМИНИСТРАТОР" in n or "ЛИСТ ОЖИДАНИЯ" in n

        # Apply area filter first. A booking is only routed to a master in the
        # client's own emirate (never across emirates). Area comes from the
        # name tag, EXCEPT a floating master whose daily marker (for `date`)
        # overrides it — matches what get_available_slots_summary offered.
        pool = [s for s in staff if not _is_admin(s)]
        if area in ("al_ain", "abu_dhabi", "dubai"):
            if date:
                import asyncio as _asyncio
                _recs = await _asyncio.gather(
                    *[self.get_records(s["id"], date) for s in pool],
                    return_exceptions=True,
                )
                _kept = []
                for s, recs in zip(pool, _recs):
                    if isinstance(recs, Exception):
                        recs = None
                    eff = _marker_area_from_records(recs) or _staff_area(s.get("name", ""))
                    if eff == area:
                        _kept.append(s)
                pool = _kept
            else:
                pool = [s for s in pool if _staff_area(s.get("name", "")) == area]

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

    async def staff_area_of(self, staff_id: int, date: Optional[str] = None) -> Optional[str]:
        """Emirate a specific staff_id serves, or None if no such staff. Used to
        reject a booking whose model-supplied master_id belongs to a different
        emirate than the client's area (a cross-emirate misroute).

        When `date` is given, a floating master's daily emirate marker wins over
        her name tag (so Lyudmila, tag=Dubai, validates as Abu Dhabi on a day
        her marker puts her there — otherwise the guard would drop her and the
        client gets a DIFFERENT therapist than the one they confirmed)."""
        try:
            sid = int(staff_id)
        except (TypeError, ValueError):
            return None
        for s in (await self.get_staff() or []):
            if s.get("id") == sid:
                if date:
                    marker = _marker_area_from_records(await self.get_records(sid, date))
                    if marker:
                        return marker
                return _staff_area(s.get("name", ""))
        return None

    async def is_slot_available(self, area: str, date: str, hhmm: str, duration: int = 60,
                                exclude_record_id=None) -> bool:
        """True if `hhmm` (24h 'H:MM') is a genuinely free slot for ANY master
        in `area` on `date` for a `duration`-min session. Coarse guard used by
        reschedule so we never confirm an occupied/off-day/travel-conflicting
        slot. Fails OPEN semantics are the caller's responsibility.

        `exclude_record_id` drops that YClients record from every master's
        schedule before computing free slots — used by reschedule so a booking
        can move to a time that overlaps ITS OWN current slot (moving a 50-min
        4:00 booking to 4:30 must not be blocked by the very record being moved;
        live-caught 2026-07-15 "время есть, но не переносит")."""
        try:
            h, m = hhmm.split(":")
            want = f"{int(h)}:{int(m):02d}"
        except (ValueError, AttributeError):
            return True  # can't parse — don't block
        outage = False
        for s in (await self.get_staff() or []):
            nm = s.get("name", "") or ""
            if "АДМИНИСТРАТОР" in nm.upper() or "ЛИСТ ОЖИДАНИЯ" in nm.upper():
                continue
            recs = await self.get_records(s["id"], date)
            if exclude_record_id is not None and recs:
                recs = [r for r in recs if str(r.get("id")) != str(exclude_record_id)]
            eff_area = _marker_area_from_records(recs) or _staff_area(nm)
            if area and eff_area != area:
                continue
            slots = await self.get_real_available_slots(s["id"], date, int(duration or 60), records=recs)
            if slots is None:
                outage = True  # couldn't fetch this master's schedule
                continue
            if want in slots:
                return True
        # Fail OPEN on an outage: never BLOCK a client-confirmed slot just because
        # YClients was unreachable (the gate's job is to catch invented times, not
        # to reject real ones during a blip).
        if outage:
            return True
        return False

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

    async def get_real_available_slots(self, staff_id: int, date: str, service_duration: int = 60, records=None) -> Optional[List[str]]:
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
        if book_times is None:
            return None  # API outage — caller must NOT treat as a day off
        if not book_times:
            return []  # Day off / fully booked — no slots

        # Existing visits → raw (start, end) minute intervals for travel-gap.
        # Caller (get_available_slots_summary) may pass records it already
        # fetched (to also read the emirate marker) — avoid a double fetch.
        if records is None:
            records = await self.get_records(staff_id, date)
            if records is None:
                logger.error(
                    f"YClients: records API unavailable for staff {staff_id} "
                    f"on {date} — slots may not account for travel buffer"
                )
                records = []

        raw_blocks = []
        for rec in records:
            # Admin emirate-pin (no client, comment = emirate) is not a real
            # visit — it must not consume a slot / travel buffer.
            if _is_emirate_marker(rec):
                continue
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
        # Business rule (ТЗ / prompt: "10:00 AM – 10:00 PM, last booking at 9pm"):
        # the salon does NOT book before 10:00 and takes NO booking that STARTS
        # after 21:00 — never offer 9:00/9:30 or 21:30/22:00 even if YClients
        # lists them (a master's YClients hours sometimes run later than the
        # salon actually serves home visits).
        WORK_START = 10 * 60        # 10:00 — first booking
        # Last START is 21:00, but the SESSION may run only until the 23:00
        # close — so a long service must start earlier (a 3h combo can't start
        # at 21:00 → ends midnight). Cap = min(21:00, 23:00 − duration).
        WORK_CLOSE = 23 * 60
        WORK_LAST_START = min(21 * 60, WORK_CLOSE - int(service_duration or 60))

        # Keep EVERY genuinely-free slot (10:00+, past-time filtered for today,
        # travel-buffer clear of existing visits). We deliberately do NOT thin
        # the list here: the agent needs the full set so that when a client
        # asks for a specific time ("17:00?") it can confirm a real free slot
        # instead of wrongly rejecting it because a display-sample dropped it.
        chosen = []
        for m in candidates:
            if m < WORK_START or m > WORK_LAST_START:
                continue
            if is_today and m < min_today:
                continue
            if _conflicts(m):
                continue
            chosen.append(m)

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

        async def _post(pl):
            session = await self._get_session()
            async with session.post(url, headers=self._headers, json=pl) as resp:
                return await resp.json()

        try:
            data = await _post(payload)
            if data.get("success"):
                record_id = data["data"].get("id", "?")
                logger.info(f"YClients: created booking #{record_id} for {client_name} on {date} {time}")
                return data["data"]

            error_msg = data.get("meta", {}).get("message", "Unknown error")
            logger.error(f"YClients: failed to create booking: {error_msg}")

            # FALLBACK — the record MUST land in the calendar. The most common
            # rejection is a service not attached to the therapist in YClients
            # (live case 2026-07-10: 'Deep facial cleansing' is attached to NO
            # master at all, so every booking for it died while the client was
            # told ✅). Retry WITHOUT the services array: a bare time-block
            # record with the service named in the comment. The admin attaches
            # the service manually — but the slot is HELD and the client is
            # not lost.
            if payload.get("services"):
                fb = dict(payload)
                fb.pop("services", None)
                fb["comment"] = (f"{comment} | УСЛУГА НЕ ПРИВЯЗАНА к мастеру в YClients — "
                                 f"добавьте услугу вручную (id {service_ids}).").strip()
                data2 = await _post(fb)
                if data2.get("success"):
                    record_id = data2["data"].get("id", "?")
                    logger.warning(
                        f"YClients: booking #{record_id} created WITHOUT services "
                        f"(fallback; original error: {error_msg})"
                    )
                    return data2["data"]
                logger.error(
                    f"YClients: fallback (no services) also failed: "
                    f"{(data2.get('meta') or {}).get('message', 'Unknown error')}"
                )
            return None
        except Exception as e:
            logger.error(f"YClients: create booking exception: {e}")
            return None

    # ─── RECORD MUTATIONS (owner decision 2026-07-10) ─────────────────────
    # The agent fully manages YClients for ITS OWN clients: create, cancel
    # (delete the record), reschedule (move the record). This replaced the old
    # "never modify YClients" safety rule at the owner's explicit request —
    # no Telegram hand-off, the calendar itself must be correct.
    #
    # HARD GUARD (do not weaken): a record is only ever mutated when its
    # client phone matches the WhatsApp client asking. Other clients' records,
    # admin records and the emirate marker records (no client at all) can
    # never be touched — a phone mismatch refuses and reports instead.

    @staticmethod
    def _phones_match(a: Optional[str], b: Optional[str]) -> bool:
        """Compare phones by their last 9 digits (country formats vary)."""
        da = "".join(ch for ch in str(a or "") if ch.isdigit())
        db = "".join(ch for ch in str(b or "") if ch.isdigit())
        if len(da) < 7 or len(db) < 7:
            return False
        return da[-9:] == db[-9:]

    async def get_record(self, record_id) -> Optional[Dict]:
        """Fetch a single record by id. None on failure/not found."""
        data = await self._get(f"record/{self.company_id}/{record_id}")
        if isinstance(data, dict):
            rec = data.get("data")
            return rec if isinstance(rec, dict) else None
        return None

    async def find_record_by_phone(self, phone: str, date: str) -> Optional[Dict]:
        """Find this client's record on `date` by phone (for bookings created
        before we started persisting the YClients id locally). Returns the
        record dict, or None if there is no UNIQUE live match — never guesses
        between two records."""
        data = await self._get(f"records/{self.company_id}", params={
            "start_date": date, "end_date": date, "count": 100,
        })
        if not isinstance(data, dict):
            return None
        matches = [
            r for r in (data.get("data") or [])
            if not r.get("deleted")
            and self._phones_match((r.get("client") or {}).get("phone"), phone)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.warning(
                f"YClients: {len(matches)} records for {phone} on {date} — ambiguous, not guessing"
            )
        return None

    async def _guarded_record(self, record_id, client_phone: str, action: str) -> Optional[Dict]:
        rec = await self.get_record(record_id)
        if not rec:
            logger.error(f"YClients {action}: record {record_id} not found / API failure")
            return None
        rec_phone = (rec.get("client") or {}).get("phone")
        if not self._phones_match(rec_phone, client_phone):
            logger.error(
                f"YClients {action} REFUSED: record {record_id} belongs to "
                f"{rec_phone!r}, not to requester {client_phone!r}"
            )
            return None
        return rec

    async def cancel_record(self, record_id, client_phone: str) -> bool:
        """Delete the client's record from the calendar (client-initiated
        cancellation). True only on confirmed deletion."""
        rec = await self._guarded_record(record_id, client_phone, "cancel")
        if not rec:
            return False
        url = f"{self.BASE_URL}/record/{self.company_id}/{record_id}"
        try:
            session = await self._get_session()
            async with session.delete(url, headers=self._headers) as resp:
                if resp.status in (200, 204):
                    logger.info(f"YClients: record {record_id} deleted (cancel by {client_phone})")
                    return True
                body = await resp.text()
                logger.error(f"YClients: delete record {record_id} failed: {resp.status} {body[:200]}")
                return False
        except Exception as e:
            logger.error(f"YClients: delete record {record_id} exception: {e}")
            return False

    async def reschedule_record(
        self,
        record_id,
        client_phone: str,
        new_date: str,
        new_time: str,
        duration_minutes: Optional[int] = None,
    ) -> bool:
        """Move the client's record to a new date/time (same therapist).
        Preserves services/costs/comment. True only on confirmed update."""
        rec = await self._guarded_record(record_id, client_phone, "reschedule")
        if not rec:
            return False
        staff_id = (rec.get("staff") or {}).get("id") or rec.get("staff_id")
        if not staff_id:
            logger.error(f"YClients: reschedule {record_id}: no staff_id on record")
            return False
        if duration_minutes:
            seance = max(int(duration_minutes), 15) * 60
        else:
            seance = int(rec.get("seance_length") or 3600)
        # Preserve existing service linkage incl. costs (package pricing must
        # survive the move).
        services = []
        for s in rec.get("services") or []:
            if s.get("id"):
                item = {"id": s["id"]}
                for k in ("cost", "first_cost", "discount", "amount"):
                    if s.get(k) is not None:
                        item[k] = s[k]
                services.append(item)
        cli = rec.get("client") or {}
        old_when = rec.get("date") or "?"
        payload = {
            "staff_id": staff_id,
            "services": services,
            # Same wall-clock convention as create_booking (account is UTC+3,
            # salon enters UAE wall-clock against it).
            "datetime": f"{new_date}T{new_time}:00+03:00",
            "seance_length": seance,
            "save_if_busy": False,
            "attendance": rec.get("attendance", 0),
            "comment": ((rec.get("comment") or "").strip()
                        + f" | Перенесено агентом: было {old_when}").strip(" |"),
            "client": {
                "name": cli.get("name") or "Client",
                "phone": cli.get("phone") or client_phone,
            },
        }
        url = f"{self.BASE_URL}/record/{self.company_id}/{record_id}"
        try:
            session = await self._get_session()
            async with session.put(url, headers=self._headers, json=payload) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                if resp.status in (200, 201) and (data.get("success") or data.get("data")):
                    logger.info(
                        f"YClients: record {record_id} moved {old_when} → {new_date} {new_time}"
                    )
                    return True
                logger.error(
                    f"YClients: move record {record_id} failed: {resp.status} "
                    f"{(data.get('meta') or {}).get('message', '')}"
                )
                return False
        except Exception as e:
            logger.error(f"YClients: move record {record_id} exception: {e}")
            return False
