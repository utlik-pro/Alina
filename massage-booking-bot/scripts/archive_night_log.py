#!/usr/bin/env python3
"""Archive the prod night log to disk, restart-proof.

The ring at /admin/night-log lives in prod memory and dies with every
restart — on 2026-08-15 three deploys erased half an hour of the LIVE
window. This pulls the ring every few minutes (launchd) and appends only
NEW events to logs/night_archive/<date>.jsonl, so the morning analysis has
every inbound, every reply and every booking regardless of restarts.

Usage:
    python3.11 scripts/archive_night_log.py          # one pull (launchd mode)
    python3.11 scripts/archive_night_log.py --status # archive health
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "https://crystal-lab-bot.onrender.com"
ARCHIVE_DIR = ROOT / "logs" / "night_archive"
STATE = ARCHIVE_DIR / "_seen.json"
UAE = timezone(timedelta(hours=4))


def _key(e: dict) -> str:
    return f"{e.get('ts')}|{e.get('kind')}|{e.get('who')}|{str(e.get('text'))[:80]}"


def pull() -> None:
    from config import config

    if not config.MANYCHAT_WEBHOOK_SECRET:
        sys.exit("MANYCHAT_WEBHOOK_SECRET is not set")
    q = urllib.parse.urlencode(
        {"secret": config.MANYCHAT_WEBHOOK_SECRET, "limit": 1000})
    with urllib.request.urlopen(f"{BASE}/admin/night-log?{q}", timeout=30) as r:
        data = json.loads(r.read())

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        seen = set(json.loads(STATE.read_text()))
    except Exception:
        seen = set()

    # A shift spans midnight — file by the UAE date the shift STARTED on
    # (22:00 UAE opens the window), so one night = one file.
    now = datetime.now(UAE)
    shift_date = (now - timedelta(hours=9)).strftime("%Y-%m-%d")
    out = ARCHIVE_DIR / f"{shift_date}.jsonl"

    new = 0
    with out.open("a") as f:
        for e in data.get("events") or []:
            k = _key(e)
            if k in seen:
                continue
            seen.add(k)
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
            new += 1

    # The seen-set only needs to cover what the ring can still contain.
    STATE.write_text(json.dumps(sorted(seen)[-4000:]))
    print(f"{now:%H:%M} archived {new} new events → {out.name}")


def status() -> None:
    files = sorted(ARCHIVE_DIR.glob("2*.jsonl"))
    if not files:
        print("no archive files yet")
        return
    for p in files[-3:]:
        n = sum(1 for _ in p.open())
        print(f"{p.name}: {n} events, last write "
              f"{datetime.fromtimestamp(p.stat().st_mtime):%H:%M}")


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    else:
        pull()
