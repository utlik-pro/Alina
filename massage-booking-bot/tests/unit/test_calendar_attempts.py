"""Database-backed duplicate protection, including concurrent workers."""
import asyncio
import pytest
from database.db import Database
from database.models import Base, BookingAttempt
from database.services import BookingService


@pytest.mark.asyncio
async def test_concurrent_claim_has_one_winner_and_survives_restart(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'claims.db'}"
    db = Database(url)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    service = BookingService(db)
    results = await asyncio.gather(*(service.claim_calendar_attempt('same') for _ in range(8)))
    assert results.count(True) == 1
    await service.complete_calendar_attempt('same', 456)
    await db.engine.dispose()
    reopened = Database(url)
    try:
        assert not await BookingService(reopened).claim_calendar_attempt('same')
        assert await BookingService(reopened).claim_calendar_attempt('different')
        async with reopened.session() as session:
            attempt = await session.get(BookingAttempt, 'same')
            assert attempt.status == 'accepted'
            assert attempt.yclients_id == '456'
    finally:
        await reopened.engine.dispose()


@pytest.mark.asyncio
async def test_missing_schema_raises_instead_of_allowing_write(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}")
    try:
        from sqlalchemy.exc import OperationalError
        with pytest.raises(OperationalError):
            await BookingService(db).claim_calendar_attempt('same')
    finally:
        await db.engine.dispose()
