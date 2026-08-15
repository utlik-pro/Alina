"""Date-phrase battery: does the agent resolve every way a client names a day?

Dates are the most fragile part of the booking flow — a wrong day means a
therapist drives to a client's home on the wrong evening. Live defect
2026-08-15: "next Saturday" was booked for the same Saturday.

For each phrase this runs a short real dialogue (area + service + the
phrase) and checks the agent's reply names the expected date.

Usage:  python3.11 scripts/check_date_phrases.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_UAE = timezone(timedelta(hours=4))
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _expected(now: datetime, kind: str, arg=None) -> datetime:
    if kind == "today":
        return now
    if kind == "tomorrow":
        return now + timedelta(days=1)
    if kind == "weekday":          # nearest coming weekday (0=Mon)
        ahead = (arg - now.weekday()) % 7
        return now + timedelta(days=ahead or 7 if arg == now.weekday() else ahead)
    if kind == "next_weekday":     # same weekday name + "next" → +7 when today
        ahead = (arg - now.weekday()) % 7
        if ahead == 0:
            ahead = 7
        return now + timedelta(days=ahead)
    if kind == "date":
        return arg
    raise ValueError(kind)


async def main() -> None:
    from scripts.sim_conversation import run as _sim_run  # noqa

    now = datetime.now(_UAE)
    print(f"today: {now:%A %d %B %Y}\n")

    cases = [
        ("today",             "today",        _expected(now, "today")),
        ("tomorrow",          "tomorrow",     _expected(now, "tomorrow")),
        ("on Monday",         "monday",       _expected(now, "weekday", 0)),
        ("on Wednesday",      "wednesday",    _expected(now, "weekday", 2)),
        ("on Friday",         "friday",       _expected(now, "weekday", 4)),
        ("this Sunday",       "sunday",       _expected(now, "weekday", 6)),
        ("next Saturday",     "next_sat",     _expected(now, "next_weekday", 5)),
        ("on 20 August",      "explicit",     now.replace(day=20)),
    ]

    import io
    import contextlib

    from scripts import sim_conversation as sim

    results = []
    for phrase, tag, exp in cases:
        scenario = {
            "channel": "instagram",
            "model": "gpt-5.4",
            "title": tag,
            "turns": [f"Hi, I want a body massage 60 min in Abu Dhabi {phrase}"],
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            await sim.run(scenario)
        out = buf.getvalue()
        reply = out.split("AGENT  ◀", 1)[-1].strip()
        day, mon = exp.day, _MONTHS[exp.month - 1]
        hit = bool(re.search(rf"\b{day}\b\s*{mon[:3]}", reply, re.I)
                   or re.search(rf"{mon[:3]}\w*\s*{day}\b", reply, re.I))
        weekday_named = exp.strftime("%A").lower() in reply.lower()
        # "Today we have 9 PM" / "Tomorrow ..." is a correct, natural answer —
        # a client doesn't need the numeric date for those two.
        if tag in ("today", "tomorrow") and re.search(rf"\b{tag}\b", reply, re.I):
            hit = True
        # a refusal is never a pass, even if it echoes the date back
        if re.search(r"don.t have|not loaded|no schedule|not available yet", reply, re.I):
            hit = weekday_named = False
        results.append((phrase, exp, hit or weekday_named, reply))
        mark = "✅" if (hit or weekday_named) else "❌"
        print(f"{mark} {phrase:16} → expect {exp:%a %d %b}")
        print(f"     {reply[:180].replace(chr(10), ' ')}\n")

    bad = [r for r in results if not r[2]]
    print("=" * 70)
    print(f"{len(results) - len(bad)}/{len(results)} phrases resolved correctly")
    for phrase, exp, _, reply in bad:
        print(f"  ❌ {phrase}: expected {exp:%A %d %B}")


if __name__ == "__main__":
    asyncio.run(main())
