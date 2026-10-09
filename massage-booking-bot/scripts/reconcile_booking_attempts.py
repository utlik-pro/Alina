"""Read-only report for v2 attempts. Run from the bot directory with PYTHONPATH=."""
import argparse
import asyncio
import json
from database.db import Database
from services.operations_report import reconciliation_report
from services.yclients_service import YClientsService
from config import config


async def main(limit):
    db = Database(config.DATABASE_URL)
    calendar = YClientsService()
    try:
        from services.admin_reports import testers
        report = await reconciliation_report(db, calendar, limit=limit, tester_ids=testers())
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await calendar.close()
        await db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error('--limit must be 1..50')
    asyncio.run(main(args.limit))
