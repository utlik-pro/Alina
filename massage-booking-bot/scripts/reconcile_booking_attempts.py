"""Read-only report for v2 attempts. Run from the bot directory with PYTHONPATH=."""
import argparse
import asyncio
import json
from sqlalchemy import select
from database.db import Database
from database.models import BookingAttempt, Booking
from services.booking_reconciliation import check_calendar_record
from services.yclients_service import YClientsService
from config import config


async def main(limit):
    db = Database(config.DATABASE_URL)
    calendar = YClientsService()
    try:
        async with db.session() as session:
            rows = (await session.execute(
                select(BookingAttempt, Booking).outerjoin(
                    Booking, Booking.id == BookingAttempt.booking_id
                ).order_by(BookingAttempt.created_at.desc()).limit(limit)
            )).all()
        for attempt, booking in rows:
            print(json.dumps(await check_calendar_record(attempt, booking, calendar), ensure_ascii=False))
    finally:
        await calendar.close()
        await db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    asyncio.run(main(args.limit))
