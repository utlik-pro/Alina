"""Live tail of the Instagram night log while a test dialogue is running.

night_report.py is the morning retro; this is the during-the-shift view:
it polls /admin/night-log and prints only what appeared since the last
poll, so a live test can be followed turn by turn without re-reading the
whole ring. Stops early the moment a record is created.

Usage:
    python3.11 scripts/watch_night_log.py                 # ~5 min, all contacts
    python3.11 scripts/watch_night_log.py --who 868311272 # one tester only
    python3.11 scripts/watch_night_log.py --seconds 540
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = os.getenv("PROD_URL", "https://crystal-lab-bot.onrender.com")


def _secret() -> str:
    from config import config

    if not config.MANYCHAT_WEBHOOK_SECRET:
        sys.exit("MANYCHAT_WEBHOOK_SECRET is not set in .env")
    return config.MANYCHAT_WEBHOOK_SECRET


def fetch(secret: str, limit: int = 1000) -> dict:
    q = urllib.parse.urlencode({"secret": secret, "limit": limit})
    with urllib.request.urlopen(f"{BASE}/admin/night-log?{q}", timeout=30) as r:
        return json.loads(r.read())


def key(e: dict) -> str:
    return f"{e.get('ts')}|{e.get('kind')}|{e.get('who')}|{str(e.get('text'))[:60]}"


def show(e: dict) -> None:
    ts = str(e.get("ts", ""))[11:19]
    kind = e.get("kind", "")
    who = str(e.get("who") or "").replace("ig:", "")
    text = e.get("text")
    arrow = {"inbound": "→ CLIENT", "sent": "← AGENT "}.get(kind)
    if arrow and text:
        print(f"  {ts}  {arrow} [{who}]")
        for line in str(text).splitlines():
            print(f"            {line}")
    else:
        extra = {k: v for k, v in e.items() if k not in ("ts", "kind", "who")}
        print(f"  {ts}  {kind:22} {who} {extra if extra else ''}")
    sys.stdout.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=280, help="how long to watch")
    ap.add_argument("--every", type=int, default=10, help="poll interval")
    ap.add_argument("--who", help="only this subscriber id")
    ap.add_argument("--tail", type=int, default=4,
                    help="how many past events to reprint on start")
    args = ap.parse_args()

    secret = _secret()
    seen: set[str] = set()
    deadline = time.time() + args.seconds
    first = True

    while True:
        try:
            data = fetch(secret)
        except Exception as exc:  # prod hiccup must not kill the watch
            print(f"  !! night-log unreachable: {exc}")
            sys.stdout.flush()
            data = {"events": []}

        events = data.get("events") or []
        if first and not events:
            print("Ring is empty — instance restarted (memory-only log).")
        mine = [e for e in events
                if not args.who or args.who in str(e.get("who") or "")]
        if first:
            # the tail is reprinted so the watch starts where the last
            # manual pull ended — a turn must never fall into the gap
            baseline, tail = mine[:-args.tail or None], mine[-args.tail:]
            seen.update(key(e) for e in baseline)
            print(f"...{len(baseline)} earlier events; last {len(tail)}:")
            for e in tail:
                seen.add(key(e))
                show(e)
            print(f"--- watching for new turns ({args.seconds}s) ---")
            sys.stdout.flush()
            first = False
        else:
            for e in mine:
                k = key(e)
                if k in seen:
                    continue
                seen.add(k)
                show(e)
                if e.get("kind") == "booking_created":
                    print("\n*** BOOKING CREATED — stopping the watch ***")
                    return

        if time.time() >= deadline:
            print(f"\n(no record yet after {args.seconds}s — still watching on next call)")
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
