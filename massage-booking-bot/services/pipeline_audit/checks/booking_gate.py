"""Check #4 — booking-gate enforcement.

A record must never be created without the client's explicit confirmation and a
location. These are binding CODE gates in the agent, so this check is mostly
regression insurance — if it ever FAILs, a gate was bypassed.

Confirmation is verified from the dialogue (a client go-ahead before the 'booked
✅'); location from the record's own 'Address:' stamp (the agent writes it only
when it has the location — a GPS share we can't see in text is covered by that).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from webhook_app import _client_confirmed
from ..findings import Finding, FAIL, WARN, OK
from ..loader import phone_key
from ..parsing import record_iso_date, record_hhmm, norm_hhmm, parse_time, parse_date, parse_ts_date
from .booking_integrity import _find_booked_claim
from .manual_override import is_agent_booking

_ADDRESS_STAMP = re.compile(r"Address:\s*\S", re.I)


def _landed_record(episode, records_by_phone, the_date) -> Optional[Dict]:
    recs = records_by_phone.get(phone_key(episode.phone), [])
    for r in recs:
        if r.get("deleted"):
            continue
        if is_agent_booking(r) and record_iso_date(r) == the_date:
            return r
    return None


def check(episode, records_by_phone: Dict[str, List[Dict]], window=None) -> List[Finding]:
    claim = _find_booked_claim(episode)
    if not claim or not claim.get("date"):
        return []
    rec = _landed_record(episode, records_by_phone, claim["date"])
    if rec is None:
        return []  # nothing landed — booking_integrity owns that case

    # Confirmation: any client message before the 'booked ✅' that reads as a go-ahead.
    claim_t = claim.get("t") or episode.end_t
    confirmed = any(
        _client_confirmed(m.get("body") or "")
        for m in episode.client_msgs()
        if (m.get("t") or 0) <= claim_t
    )
    has_address = bool(_ADDRESS_STAMP.search(rec.get("comment") or ""))

    ev = {"yclients_id": rec.get("id"), "date": rec.get("date"),
          "agent_msg": claim["msg"][:160]}

    if not confirmed:
        return [Finding(
            pipeline="booking_gate", severity=FAIL, confidence=0.7,
            summary="Record created but no explicit client confirmation appears in "
                    "the dialogue before 'booked ✅'.",
            phone=episode.phone, episode_ts=episode.start_t, evidence=ev,
        )]
    if not has_address:
        return [Finding(
            pipeline="booking_gate", severity=WARN, confidence=0.5,
            summary="Booking confirmed but the record carries no 'Address:' stamp "
                    "(location may have been a GPS share, or was skipped).",
            phone=episode.phone, episode_ts=episode.start_t, evidence=ev,
        )]
    return [Finding(
        pipeline="booking_gate", severity=OK, confidence=0.8,
        summary="Booking had explicit confirmation and a location.",
        phone=episode.phone, episode_ts=episode.start_t, evidence=ev,
    )]
