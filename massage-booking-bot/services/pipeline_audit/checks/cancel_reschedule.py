"""Check #7 — cancel / reschedule completion.

Since 2026-07-10 the agent manages YClients itself and confirms completion
("Your appointment is cancelled ✅", "moved to 5:00 PM ✅"). When it makes a
DEFINITIVE completion claim, reality must match: a cancelled booking is deleted,
a moved booking sits at the new time.

Deliberately conservative: it fires ONLY on completion wording, never on the old
team-mediated phrasing ("passed your cancellation to the team … shortly"), so
pre-automation history isn't flagged as failures.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..findings import Finding, FAIL, OK, FLAG_HUMAN
from ..loader import phone_key
from ..parsing import (
    parse_date, parse_time, parse_ts_date,
    record_hhmm, record_iso_date, norm_hhmm,
)

# "passed to the team … shortly" = the OLD flow — never a completion claim.
_TEAM_MEDIATED = re.compile(r"passed .*(cancellation|reschedule)|to the team|shortly|will confirm", re.I)
_CANCEL_DONE = re.compile(r"\bis cancelled\b|\bhas been cancelled\b|cancelled\s*✅|✅.*cancelled", re.I)
_MOVE_DONE = re.compile(r"\bis moved\b|moved to\b.*✅|✅.*moved|appointment is moved", re.I)


def _completion_claim(episode) -> Optional[Dict]:
    for m in episode.agent_msgs():
        body = m.get("body") or ""
        if _TEAM_MEDIATED.search(body):
            continue
        if _CANCEL_DONE.search(body):
            return {"kind": "cancel", "msg": body, "t": m.get("t")}
        if _MOVE_DONE.search(body):
            return {"kind": "move", "msg": body, "t": m.get("t")}
    return None


def check(episode, records_by_phone: Dict[str, List[Dict]],
          window: Optional[tuple] = None) -> List[Finding]:
    claim = _completion_claim(episode)
    if not claim:
        return []

    recs = records_by_phone.get(phone_key(episode.phone), [])
    ev = {"agent_msg": claim["msg"][:200]}

    if claim["kind"] == "cancel":
        # A cancellation is done when no LIVE record remains for this client in
        # the loaded window (records are deleted, not marked). If a live record
        # still stands, the "cancelled ✅" was a lie.
        live = [r for r in recs if not r.get("deleted")]
        if not live:
            return [Finding(
                pipeline="cancel_reschedule", severity=OK, confidence=0.8,
                summary="Agent confirmed cancellation and no live record remains.",
                phone=episode.phone, episode_ts=episode.start_t, evidence=ev,
            )]
        return [Finding(
            pipeline="cancel_reschedule", severity=FAIL, confidence=0.7,
            summary="Agent said 'cancelled ✅' but a live YClients record still stands.",
            phone=episode.phone, episode_ts=episode.start_t,
            evidence={**ev, "live_records": [r.get("id") for r in live][:5]},
        )]

    # move: a record must exist at the NEW time the agent stated.
    ref = parse_ts_date(episode.start_t)
    new_date = parse_date(claim["msg"], ref)
    new_time = parse_time(claim["msg"])
    if not new_time:
        return [Finding(
            pipeline="cancel_reschedule", severity=FLAG_HUMAN, confidence=0.4,
            summary="Agent claimed a move but the new time couldn't be parsed to verify.",
            phone=episode.phone, episode_ts=episode.start_t, evidence=ev,
        )]
    want = norm_hhmm(new_time)
    for r in recs:
        if r.get("deleted"):
            continue
        if record_hhmm(r) == want and (new_date is None or record_iso_date(r) == new_date):
            return [Finding(
                pipeline="cancel_reschedule", severity=OK, confidence=0.8,
                summary=f"Agent moved the booking and a record sits at {new_time}.",
                phone=episode.phone, episode_ts=episode.start_t,
                evidence={**ev, "yclients_id": r.get("id")},
            )]
    return [Finding(
        pipeline="cancel_reschedule", severity=FAIL, confidence=0.6,
        summary=f"Agent said 'moved to {new_time}' but no record sits at that time.",
        phone=episode.phone, episode_ts=episode.start_t,
        evidence={**ev, "expected_time": new_time, "new_date": new_date},
    )]
