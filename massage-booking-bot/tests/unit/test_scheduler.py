"""Integration tests for the reminder scheduler (FR-3.1, FR-4.x).

Uses a real (temp file) SQLite DB so multi-session async queries behave
like production.
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from database.db import Database
from database.services import ClientService, BookingService, PackageService
from services.scheduler import ReminderScheduler


@pytest.fixture
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.create_tables()
    yield database
    await database.close()
    os.unlink(path)


class _Sink:
    """Collects (phone, text) the scheduler would send."""
    def __init__(self):
        self.sent = []

    async def __call__(self, phone, text):
        self.sent.append((phone, text))


@pytest.mark.asyncio
async def test_day_before_confirmation_fires_once(db):
    clients = ClientService(db)
    bookings = BookingService(db)
    sink = _Sink()

    tid = "wappi_+971500000001"
    await clients.get_or_create_client(tid)
    await clients.update_client(tid, name="Sara", phone="+971500000001")

    # "Now" = today 11:30 UAE; booking is tomorrow at 19:00.
    current = datetime(2026, 6, 2, 11, 30)
    tomorrow = (current + timedelta(days=1)).replace(hour=19, minute=0)

    b = await bookings.create_booking(
        telegram_id=tid, service_name="Body massage", duration=60,
        base_price=350.0, booking_date=tomorrow, payment_method="cash",
    )
    await bookings.update_booking_status(b.id, "confirmed")

    sched = ReminderScheduler(booking_service=bookings, send_message=sink)
    await sched.run_once(current=current)

    assert len(sink.sent) == 1
    phone, text = sink.sent[0]
    assert phone == "+971500000001"
    assert "Body massage" in text

    # Second run in the same window must NOT resend (idempotent).
    await sched.run_once(current=current)
    assert len(sink.sent) == 1


@pytest.mark.asyncio
async def test_day_before_outside_window_does_not_fire(db):
    clients = ClientService(db)
    bookings = BookingService(db)
    sink = _Sink()

    tid = "wappi_+971500000002"
    await clients.get_or_create_client(tid)
    await clients.update_client(tid, phone="+971500000002")

    current = datetime(2026, 6, 2, 9, 0)  # 09:00 — before the 11–12 window
    tomorrow = (current + timedelta(days=1)).replace(hour=15, minute=0)
    b = await bookings.create_booking(
        telegram_id=tid, service_name="Face massage", duration=50,
        base_price=370.0, booking_date=tomorrow, payment_method="cash",
    )
    await bookings.update_booking_status(b.id, "confirmed")

    sched = ReminderScheduler(booking_service=bookings, send_message=sink)
    await sched.run_once(current=current)
    assert sink.sent == []


@pytest.mark.asyncio
async def test_post_session_survey_and_completion(db):
    clients = ClientService(db)
    bookings = BookingService(db)
    sink = _Sink()

    tid = "wappi_+971500000003"
    await clients.get_or_create_client(tid)
    await clients.update_client(tid, name="Mona", phone="+971500000003")

    current = datetime(2026, 6, 2, 18, 0)
    past = current - timedelta(hours=2)  # session finished 2h ago
    b = await bookings.create_booking(
        telegram_id=tid, service_name="Body massage", duration=60,
        base_price=350.0, booking_date=past, payment_method="cash",
    )
    await bookings.update_booking_status(b.id, "confirmed")

    sched = ReminderScheduler(booking_service=bookings, send_message=sink)
    await sched.run_once(current=current)

    # Survey + offer (new client → package offer)
    assert len(sink.sent) == 2
    assert "Mona" in sink.sent[0][1]
    assert "package" in sink.sent[1][1].lower()

    # Idempotent: no resend, and booking is now completed
    await sched.run_once(current=current)
    assert len(sink.sent) == 2


@pytest.mark.asyncio
async def test_post_session_package_last_session_offers_renewal(db):
    clients = ClientService(db)
    bookings = BookingService(db)
    packages = PackageService(db)
    sink = _Sink()

    tid = "wappi_+971500000004"
    c = await clients.get_or_create_client(tid)
    await clients.update_client(tid, name="Lina", phone="+971500000004")

    pkg = await packages.create_package(
        client_id=c.id, package_type="5_sessions", sessions_total=5,
        base_price=1550.0,
    )
    # Pretend 4 already used → this is the last one.
    for _ in range(4):
        await packages.consume_session(pkg["id"])

    current = datetime(2026, 6, 2, 18, 0)
    past = current - timedelta(hours=1)
    b = await bookings.create_booking(
        telegram_id=tid, service_name="Body massage", duration=60,
        base_price=0.0, booking_date=past, payment_method="cash",
    )
    # link booking to the package
    async with db.session() as s:
        from database.models import Booking
        from sqlalchemy import select
        row = (await s.execute(select(Booking).where(Booking.id == b.id))).scalar_one()
        row.package_id = pkg["id"]
        row.status = "confirmed"

    sched = ReminderScheduler(
        booking_service=bookings, send_message=sink, package_service=packages,
    )
    await sched.run_once(current=current)

    assert len(sink.sent) == 2
    assert "renew" in sink.sent[1][1].lower()
