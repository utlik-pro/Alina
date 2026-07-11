"""Orchestrator — wires loaders → episodes → checks → findings.

Pure coordination, read-only. Given a date window it loads both sources, runs the
v1 check battery (say-do #1, cancel/reschedule #7, manual-override #6) plus the
gap-to-admin map, and returns (findings, gap, meta).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .findings import Finding
from .loader import (
    load_dialogues, load_yclients_records, index_records_by_phone, load_turn_logs,
)
from .episodes import segment_all
from .gap_report import classify_comments
from .checks import booking_integrity, cancel_reschedule, manual_override


async def run_audit(svc, date_from: str, date_to: str,
                    chat_dir: Optional[str] = None) -> Tuple[List[Finding], Dict, Dict]:
    dialogues = load_dialogues(chat_dir)
    records = await load_yclients_records(svc, date_from, date_to)
    by_phone = index_records_by_phone(records)
    episodes = segment_all(dialogues)
    turn_logs = load_turn_logs()
    window = (date_from, date_to)

    findings: List[Finding] = []

    # episode-level checks
    for ep in episodes:
        findings += booking_integrity.check(ep, by_phone, window)
        findings += cancel_reschedule.check(ep, by_phone, window)

    # record-level check (manual override of agent bookings)
    findings += manual_override.check_records(records)

    # gap-to-administrator coverage map (from record comments)
    comments = [r.get("comment") or "" for r in records if (r.get("comment") or "").strip()]
    gap = classify_comments(comments)

    meta = {
        "date_from": date_from, "date_to": date_to,
        "episodes": len(episodes), "records": len(records),
        "turn_logs": len(turn_logs),
    }
    return findings, gap, meta
