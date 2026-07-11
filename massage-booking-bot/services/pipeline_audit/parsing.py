"""Deterministic extractors for confirmation/cancel/move statements the agent
makes to the client. Pure regex — the auditor re-derives structure from the
agent's own words rather than trusting a log.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Sat 11 Jul", "11 Jul", "Saturday, July 11", "July 11"
_DATE_DM = re.compile(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)
_DATE_MD = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})\b", re.I)

# "12:00 PM", "5:30 PM", "10 AM"
_TIME_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
# 24h fallback "17:30"
_TIME_24 = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

BOOKED_RE = re.compile(r"\bbooked\b|\bis booked\b|✅", re.I)
CANCELLED_RE = re.compile(r"\bcancel(?:led|ed)?\b|отмен", re.I)
MOVED_RE = re.compile(r"\bmoved\b|\brescheduled\b|перенес", re.I)


def to_24h(hour: int, minute: int, ampm: Optional[str]) -> Tuple[int, int]:
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    return hour, minute


def parse_date(text: str, ref: Optional[date] = None) -> Optional[str]:
    """Return ISO date (YYYY-MM-DD) for a 'DD Mon' / 'Mon DD' mention.

    Year is inferred against `ref` (default: the reference date passed by the
    caller — the auditor passes the episode's own day so 'next year' rollover is
    correct). Chooses the year that puts the date within ~11 months of ref.
    """
    ref = ref or date(2026, 1, 1)
    m = _DATE_DM.search(text)
    if m:
        day, mon = int(m.group(1)), _MONTHS[m.group(2).lower()]
    else:
        m = _DATE_MD.search(text)
        if not m:
            return None
        mon, day = _MONTHS[m.group(1).lower()], int(m.group(2))
    for yr in (ref.year, ref.year + 1, ref.year - 1):
        try:
            cand = date(yr, mon, day)
        except ValueError:
            continue
        if -31 <= (cand - ref).days <= 330:
            return cand.isoformat()
    try:
        return date(ref.year, mon, day).isoformat()
    except ValueError:
        return None


def parse_time(text: str) -> Optional[str]:
    """Return 'H:MM' 24h for the first time mention (AM/PM preferred)."""
    m = _TIME_AMPM.search(text)
    if m:
        h, mm = to_24h(int(m.group(1)), int(m.group(2) or 0), m.group(3))
        return f"{h}:{mm:02d}"
    m = _TIME_24.search(text)
    if m:
        return f"{int(m.group(1))}:{int(m.group(2)):02d}"
    return None


def norm_hhmm(hhmm: str) -> Optional[Tuple[int, int]]:
    try:
        h, mm = hhmm.split(":")
        return int(h), int(mm)
    except (ValueError, AttributeError):
        return None


def record_hhmm(rec: dict) -> Optional[Tuple[int, int]]:
    """(hour, minute) of a YClients record from its 'date' field."""
    d = rec.get("date") or ""
    m = re.search(r"\b(\d{1,2}):(\d{2})", d)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def record_iso_date(rec: dict) -> Optional[str]:
    d = rec.get("date") or ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", d)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_ts_date(unix_ts: int) -> date:
    """Episode timestamp → UAE calendar date (UTC+4) for year inference."""
    return (datetime.utcfromtimestamp(unix_ts) + timedelta(hours=4)).date()
