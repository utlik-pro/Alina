"""Morning retro for the Instagram night shift.

Pulls /admin/night-log from prod and prints what actually happened:
how many people wrote, how many were answered, what got booked, and
every failure. Use it instead of reconstructing the night by hand from
the ManyChat inbox.

Usage:
    python3.11 scripts/night_report.py            # summary + bookings
    python3.11 scripts/night_report.py --full     # every event
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = os.getenv("PROD_URL", "https://crystal-lab-bot.onrender.com")


def _secret() -> str:
    from config import config

    if not config.MANYCHAT_WEBHOOK_SECRET:
        sys.exit("MANYCHAT_WEBHOOK_SECRET is not set in .env")
    return config.MANYCHAT_WEBHOOK_SECRET


def fetch(limit: int) -> dict:
    q = urllib.parse.urlencode({"secret": _secret(), "limit": limit})
    with urllib.request.urlopen(f"{BASE}/admin/night-log?{q}", timeout=30) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="print every event")
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args()

    data = fetch(args.limit)
    events = data.get("events") or []
    if not events:
        print("Night log is empty — the instance may have restarted "
              "(the ring lives in memory).")
        return

    print(f"NIGHT LOG  ({events[0]['ts']} → {events[-1]['ts']}, Abu Dhabi time)")
    print(f"  contacts: {data.get('unique_contacts')}   events: {data.get('total_kept')}")
    for kind, n in sorted(data.get("summary", {}).items(), key=lambda x: -x[1]):
        print(f"    {kind:24} {n}")

    bookings = data.get("bookings") or []
    print(f"\nBOOKINGS: {len(bookings)}")
    for b in bookings:
        print(f"  #{b.get('record')}  {b.get('service')}  {b.get('date')} "
              f"{b.get('time')}  {b.get('master')}  ({b.get('who')})")

    problems = [e for e in events
                if e["kind"] in ("send_failed", "send_blocked_daytime")]
    if problems:
        print(f"\nPROBLEMS: {len(problems)}")
        for e in problems[:20]:
            print(f"  {e['ts']}  {e['kind']}  {e.get('who')}  {e.get('text', '')[:90]}")

    # per-contact trail: did everyone who wrote get an answer?
    by_contact: dict[str, list] = defaultdict(list)
    for e in events:
        who = str(e.get("who") or "").replace("ig:", "")
        if who:
            by_contact[who].append(e)
    # Кто вёл диалог. Без этого разделения отчёт врёт: сообщения клиента,
    # которому отвечал ЖИВОЙ админ из Instagram, выглядели как «агент
    # промолчал» (дважды ввело в заблуждение 2026-08-18).
    human_led, agent_led, unanswered = [], [], []
    for who, evs in by_contact.items():
        if not any(e["kind"] == "inbound" for e in evs):
            continue
        if any(e["kind"] == "human_led_skip" for e in evs):
            human_led.append(who)
        elif any(e["kind"] == "sent" for e in evs):
            agent_led.append(who)
        else:
            in_window = [e for e in evs
                         if e["kind"] == "inbound" and e.get("live")]
            # 3+ сообщения в окне без единого нашего ответа — почти наверняка
            # клиента вёл человек, просто до нашей проверки очередь не дошла.
            (human_led if len(in_window) >= 3 else unanswered).append(who)

    print(f"\nВЁЛ АГЕНТ: {len(agent_led)}   ВЁЛ ЧЕЛОВЕК: {len(human_led)}")
    if human_led:
        print("  диалоги админов (агент молчал — это норма):")
        for who in human_led[:20]:
            first = next(e for e in by_contact[who] if e["kind"] == "inbound")
            print(f"    {who}: {first.get('text', '')[:70]!r}")

    if unanswered:
        print(f"\nWROTE BUT GOT NO REPLY: {len(unanswered)}")
        for who in unanswered[:20]:
            first = next(e for e in by_contact[who] if e["kind"] == "inbound")
            print(f"  {who}: {first.get('text', '')[:80]!r} "
                  f"(live={first.get('live')})")

    if args.full:
        print("\nALL EVENTS")
        for e in events:
            extra = {k: v for k, v in e.items() if k not in ("ts", "kind")}
            print(f"  {e['ts']}  {e['kind']:22} {extra}")


if __name__ == "__main__":
    main()
