"""Check #1 — say-do integrity.

When the agent tells the client "booked ✅", a matching record MUST exist in
YClients. A confirmation with no record is a phantom booking — the highest-value
class of failure (the client believes they have an appointment that doesn't exist).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..findings import Finding, FAIL, WARN, OK, FLAG_HUMAN
from ..loader import phone_key
from ..parsing import (
    parse_date, parse_time, parse_ts_date,
    record_hhmm, record_iso_date, norm_hhmm,
)
from .manual_override import is_agent_booking

# A positive booking confirmation — NOT "we are fully booked" / "booked out".
_POS_BOOKED = re.compile(r"(?:is|it'?s|been|was|now)\s+booked|booked\s*✅|✅\s*booked", re.I)
_NEG_BOOKED = re.compile(r"fully booked|booked out|not booked|no longer booked", re.I)


def _find_booked_claim(episode) -> Optional[Dict]:
    """The agent message that claims a booking, plus the date/time it refers to.

    Details are sometimes split across messages ("it's booked ✅" after a recap
    line), so if the booked message itself has no time we scan the agent messages
    just before it within the same episode.
    """
    agent = episode.agent_msgs()
    ref = parse_ts_date(episode.start_t)
    for i, m in enumerate(agent):
        body = m.get("body") or ""
        if not _POS_BOOKED.search(body) or _NEG_BOOKED.search(body):
            continue
        # gather date/time from this message, falling back to the 3 preceding
        window = [body] + [ (agent[j].get("body") or "") for j in range(i - 1, max(-1, i - 4), -1) ]
        the_date = the_time = None
        for txt in window:
            the_date = the_date or parse_date(txt, ref)
            the_time = the_time or parse_time(txt)
            if the_date and the_time:
                break
        return {"msg": body, "t": m.get("t"), "date": the_date, "time": the_time}
    return None


def check(episode, records_by_phone: Dict[str, List[Dict]],
          window: Optional[tuple] = None) -> List[Finding]:
    claim = _find_booked_claim(episode)
    if not claim:
        return []

    ev_base = {"agent_msg": claim["msg"][:200]}
    the_date, the_time = claim["date"], claim["time"]

    if not the_date or not the_time:
        # Agent claimed a booking but we can't extract when — can't verify.
        return [Finding(
            pipeline="booking_integrity", severity=FLAG_HUMAN, confidence=0.5,
            summary="Agent said 'booked ✅' but the date/time couldn't be parsed to verify.",
            phone=episode.phone, episode_ts=episode.start_t,
            evidence={**ev_base, "parsed_date": the_date, "parsed_time": the_time},
        )]

    # If the booked date is outside the records we loaded, we simply can't judge.
    if window and not (window[0] <= the_date <= window[1]):
        return [Finding(
            pipeline="booking_integrity", severity=FLAG_HUMAN, confidence=0.4,
            summary=f"Booking claimed for {the_date} {the_time}, outside the loaded "
                    f"records window — not verified.",
            phone=episode.phone, episode_ts=episode.start_t,
            evidence={**ev_base, "date": the_date, "time": the_time},
        )]

    want = norm_hhmm(the_time)
    recs = records_by_phone.get(phone_key(episode.phone), [])
    same_day_agent = None
    for r in recs:
        if r.get("deleted"):
            continue
        if record_iso_date(r) == the_date and record_hhmm(r) == want:
            return [Finding(
                pipeline="booking_integrity", severity=OK, confidence=1.0,
                summary=f"Booking confirmed to client matches YClients record on "
                        f"{the_date} {the_time}.",
                phone=episode.phone, episode_ts=episode.start_t,
                evidence={**ev_base, "yclients_id": r.get("id"),
                          "date": the_date, "time": the_time},
            )]
        if record_iso_date(r) == the_date and is_agent_booking(r):
            same_day_agent = r  # landed, but not at the confirmed time

    if same_day_agent is not None:
        # The record exists on the right day at a DIFFERENT time — the booking
        # landed and was moved (admin/agent) after confirmation. Not phantom;
        # manual_override tracks the move. Lower-severity: the client was told
        # a time that no longer matches the calendar.
        actual = same_day_agent.get("date")
        return [Finding(
            pipeline="booking_integrity", severity=WARN, confidence=0.7,
            summary=f"Booking confirmed for {the_date} {the_time} landed but the "
                    f"record now sits at a different time ({actual}) — moved after "
                    f"confirmation.",
            phone=episode.phone, episode_ts=episode.start_t,
            evidence={**ev_base, "expected": f"{the_date} {the_time}",
                      "actual": actual, "yclients_id": same_day_agent.get("id")},
        )]

    return [Finding(
        pipeline="booking_integrity", severity=FAIL, confidence=0.9,
        summary=f"PHANTOM BOOKING: agent told the client 'booked ✅' for {the_date} "
                f"{the_time}, but no matching YClients record exists.",
        phone=episode.phone, episode_ts=episode.start_t,
        evidence={**ev_base, "expected": f"{the_date} {the_time}",
                  "actual": "no record", "client_records": len(recs)},
    )]
