#!/usr/bin/env python3
"""Print the durable funnel/reconciliation report. Never sends messages.

python scripts/operations_report.py --hours 24
python scripts/operations_report.py --reconcile --limit 20 --json
"""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fetch_report(path, params=None):
    from config import config
    secret = config.MANYCHAT_WEBHOOK_SECRET or config.WEBHOOK_SECRET
    if not secret:
        raise RuntimeError('Set MANYCHAT_WEBHOOK_SECRET or WEBHOOK_SECRET')
    base = os.getenv('PROD_URL', 'https://crystal-lab-bot.onrender.com').rstrip('/')
    request = urllib.request.Request(base + path + '?' + urllib.parse.urlencode(params or {}),
                                     headers={'X-Admin-Secret': secret})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hours', type=int, default=24)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.hours <= 168 or not 1 <= args.limit <= 50 or args.offset < 0:
        parser.error('hours must be 1..168; limit must be 1..50')
    if args.reconcile:
        result = fetch_report('/admin/reconciliation', {'limit': args.limit, 'offset': args.offset})
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            from services.operations_report import format_reconciliation_report
            print(format_reconciliation_report(result))
    else:
        result = fetch_report('/admin/funnel-report', {'hours': args.hours})
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            from services.operations_report import format_funnel_report
            print(format_funnel_report(result))


if __name__ == '__main__':
    main()
