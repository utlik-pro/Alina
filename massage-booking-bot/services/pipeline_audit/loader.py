"""Data loading for the pipeline auditor — read-only, no side effects.

Two independent sources of truth:
  1. wappi_chats/<phone>.jsonl  — what the agent SAID (the dialogue)
  2. YClients records            — what actually HAPPENED (the calendar)

The auditor joins them to check say-do consistency. turn_logs.jsonl (the richest
structured signal) is prod-only and optional — loaded when present as a bonus
cross-check, never required.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# Last-9-digit phone join (country formats vary: +375…, 971…, 79…).
def phone_key(raw: Any) -> str:
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 else d


def _default_chat_dir() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "logs", "wappi_chats")


def load_dialogues(chat_dir: Optional[str] = None) -> Dict[str, List[Dict]]:
    """phone → chronologically sorted messages (dicts: id, t, from_me, type, body)."""
    chat_dir = chat_dir or _default_chat_dir()
    out: Dict[str, List[Dict]] = {}
    if not os.path.isdir(chat_dir):
        return out
    for fn in os.listdir(chat_dir):
        if not fn.endswith(".jsonl") or fn.startswith("_"):
            continue
        phone = fn[: -len(".jsonl")]
        msgs: List[Dict] = []
        with open(os.path.join(chat_dir, fn), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if m.get("type") == "chat" and m.get("body"):
                    msgs.append(m)
        if msgs:
            msgs.sort(key=lambda m: m.get("t", 0))
            out[phone] = msgs
    return out


async def load_yclients_records(svc, date_from: str, date_to: str) -> List[Dict]:
    """All records in [date_from, date_to] inclusive (YYYY-MM-DD). Raw dicts.

    Uses the same YClientsService the agent uses, so the auditor and the agent
    can never disagree about what a record looks like. Read-only.
    """
    from datetime import date, timedelta

    def _d(s: str) -> date:
        y, m, dd = (int(x) for x in s.split("-"))
        return date(y, m, dd)

    records: List[Dict] = []
    day = _d(date_from)
    end = _d(date_to)
    while day <= end:
        iso = day.isoformat()
        recs = await svc.get_records_for_date(iso) if hasattr(svc, "get_records_for_date") else None
        if recs is None:
            recs = await _fetch_day(svc, iso)
        records.extend(recs or [])
        day += timedelta(days=1)
    return records


async def _fetch_day(svc, iso: str) -> List[Dict]:
    """Fetch all records for one date via the service's raw GET helper."""
    data = await svc._get(f"records/{svc.company_id}", params={
        "start_date": iso, "end_date": iso, "count": 300,
    })
    if isinstance(data, dict):
        return data.get("data") or []
    return data or []


def index_records_by_phone(records: List[Dict]) -> Dict[str, List[Dict]]:
    """phone_key → records for that client (deleted included; checks decide)."""
    out: Dict[str, List[Dict]] = {}
    for r in records:
        cli = r.get("client") or {}
        k = phone_key(cli.get("phone"))
        if not k:
            continue
        out.setdefault(k, []).append(r)
    return out


def load_turn_logs(path: Optional[str] = None) -> List[Dict]:
    """Optional prod structured turn log. Empty list if absent (never required)."""
    if path is None:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(here, "logs", "turn_logs.jsonl")
    out: List[Dict] = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
