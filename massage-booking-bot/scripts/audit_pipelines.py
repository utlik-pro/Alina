#!/usr/bin/env python3.11
"""Pipeline auditor CLI — deterministic, read-only quality control for the
Crystal Lab WhatsApp agent.

Replays real dialogues against real YClients state and reports:
  - regression health of the existing pipelines (booking / cancel / reschedule),
  - the gap between the agent and a full human administrator.

Usage:
  python3.11 scripts/audit_pipelines.py                       # last 7 days
  python3.11 scripts/audit_pipelines.py --from 2026-07-04 --to 2026-07-11
  python3.11 scripts/audit_pipelines.py --json out.json       # + machine dump
"""

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.pipeline_audit.auditor import run_audit
from services.pipeline_audit.report import render


def _default_window():
    # Anchor to a fixed "today" isn't available (no Date.now guarantees here);
    # use the system date only for the CLI default — explicit --from/--to for
    # reproducible runs.
    today = date.today()
    return (today - timedelta(days=7)).isoformat(), today.isoformat()


async def main():
    df_default, dt_default = _default_window()
    ap = argparse.ArgumentParser(description="Crystal Lab pipeline auditor")
    ap.add_argument("--from", dest="date_from", default=df_default, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", default=dt_default, help="YYYY-MM-DD")
    ap.add_argument("--chat-dir", default=None, help="override wappi_chats dir")
    ap.add_argument("--json", dest="json_out", default=None, help="dump findings JSON")
    args = ap.parse_args()

    from services.yclients_service import YClientsService
    svc = YClientsService()

    findings, gap, meta = await run_audit(
        svc, args.date_from, args.date_to, chat_dir=args.chat_dir
    )

    print(render(findings, gap, meta))

    if args.json_out:
        payload = {
            "meta": meta,
            "gap": gap,
            "findings": [f.to_dict() for f in findings],
        }
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n[json dumped → {args.json_out}]", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
