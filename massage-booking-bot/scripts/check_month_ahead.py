"""Month-ahead sweep: date parsing + real availability for every day.

Two independent checks for each of the next 30 days:

1. PARSER — every way a client might spell that day ("20 August",
   "August 20", "20/08", "20.08", "the 20th") must resolve to exactly
   that date. Pure logic, no LLM.
2. SCHEDULE — what YClients actually returns for that day per emirate,
   so an empty day is a known fact rather than a surprise at 3 AM.

Usage:  python3.11 scripts/check_month_ahead.py [--days 30]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webhook_app as wh  # noqa: E402
from services.yclients_service import YClientsService  # noqa: E402

_UAE = timezone(timedelta(hours=4))
_MON = ["January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December"]


def parser_forms(d: datetime) -> list[tuple[str, str]]:
    mon = _MON[d.month - 1]
    suffix = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}.get(d.day, "th")
    return [
        (f"on {d.day} {mon}", "day month"),
        (f"{mon} {d.day} please", "month day"),
        (f"{d.day:02d}/{d.month:02d}", "dd/mm"),
        (f"{d.day:02d}.{d.month:02d}", "dd.mm"),
        (f"book me {d.day}{suffix} of {mon}", "ordinal"),
    ]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    now = datetime.now(_UAE)
    yc = YClientsService()
    print(f"today: {now:%A %d %B %Y}   sweeping {args.days} days\n")

    parse_fail: list[str] = []
    empty_days: list[str] = []
    rows = []

    for i in range(1, args.days + 1):
        d = now + timedelta(days=i)
        iso = d.strftime("%Y-%m-%d")

        # 1) parser
        bad_forms = []
        for text, label in parser_forms(d):
            got = wh._detect_explicit_date(text, now)
            if got != iso:
                bad_forms.append(f"{label}={got}")
        if bad_forms:
            parse_fail.append(f"{iso} ({d:%a}): " + ", ".join(bad_forms))

        # 2) real schedule per emirate
        counts = {}
        for area in ("abu_dhabi", "al_ain", "dubai"):
            try:
                s = await yc.get_available_slots_summary(
                    date=iso, service_name="body massage",
                    area=area, service_duration=60)
            except Exception as e:
                s = f"ERROR {e}"
            has = "Available on" in str(s)
            n_masters = str(s).count(":") - 1 if has else 0
            counts[area] = max(n_masters, 0) if has else 0
        if sum(counts.values()) == 0:
            empty_days.append(f"{iso} ({d:%a})")
        rows.append((iso, d.strftime("%a"), counts, "ok" if not bad_forms else "PARSE"))

    print(f"{'date':12} {'day':4} {'AD':>3} {'AlAin':>6} {'Dubai':>6}  parser")
    print("-" * 46)
    for iso, wd, c, st in rows:
        flag = "" if st == "ok" else "  ❌"
        mark = "" if sum(c.values()) else "   ← no slots"
        print(f"{iso:12} {wd:4} {c['abu_dhabi']:>3} {c['al_ain']:>6} {c['dubai']:>6}{flag}{mark}")

    print("\n" + "=" * 60)
    print(f"PARSER: {args.days - len(parse_fail)}/{args.days} days resolved in all 5 forms")
    for line in parse_fail:
        print(f"  ❌ {line}")
    print(f"DAYS WITH NO AVAILABILITY ANYWHERE: {len(empty_days)}")
    for line in empty_days:
        print(f"  · {line}")


if __name__ == "__main__":
    asyncio.run(main())
