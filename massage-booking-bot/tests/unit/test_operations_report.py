from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import json
import pytest
from services.operations_report import build_funnel_report, load_funnel_report, reconciliation_report

NOW = datetime(2026, 10, 9, 9)


def event(who, kind, ago=60, **data):
    return NS(id=1, who=who, kind=kind, created_at=NOW-timedelta(minutes=ago), data=json.dumps(data))


def snapshot(who, **booking):
    return NS(user_id='ig_'+who, updated_at=NOW-timedelta(minutes=20), payload={
        'client_data': {'area': 'dubai', 'phone': '971500000000'},
        'booking_data': {'service_type': 'face_massage', **booking}})


def report(events, **kwargs):
    return build_funnel_report(events, kwargs.pop('clients', []), kwargs.pop('snapshots', []),
                               kwargs.pop('bookings', []), kwargs.pop('attempts', []),
                               start=NOW-timedelta(days=1), end=NOW, **kwargs)


def test_bubbles_and_failed_tools_are_not_bookings_and_testers_are_excluded():
    events = [event('1', 'inbound'), event('1', 'routed_to_booking'), event('ig:1', 'sent', 59),
              event('ig:1', 'sent', 59), event('1', 'booking_sync_failed', 58),
              event('770099110', 'inbound'), event('tester', 'inbound')]
    data = report(events, tester_ids=['tester'], snapshots=[snapshot('1')])
    assert data['summary']['inbound_contacts'] == 1
    assert data['summary']['answered_contacts'] == 1
    assert data['summary']['calendar_records_created'] == 0
    assert data['summary']['conversion_percent'] == 0
    assert data['summary']['excluded_test_contacts'] == 2
    assert data['needs_attention'][0]['stage'] == 'date_time'


def test_conversion_counts_unique_calendar_records_and_unique_routed_contacts():
    c = NS(telegram_id='ig_1', phone='971500000000')
    b = NS(yclients_appointment_id='123', status='confirmed')
    data = report([event('1', 'inbound'), event('1', 'routed_to_booking'), event('1', 'inbound', 59)],
                  bookings=[(b, c), (b, c)])
    assert data['summary']['calendar_records_created'] == 1
    assert data['summary']['converted_contacts'] == 1
    assert data['summary']['conversion_percent'] == 100
    assert not data['needs_attention']


@pytest.mark.parametrize('stage,events,snaps', [
    ('human_owned', [event('1', 'inbound'), event('1', 'human_led_skip')], []),
    ('outside_window', [event('1', 'inbound', live=False)], []),
    ('not_ad', [event('1', 'inbound', live=True), event('1', 'not_ad_skip')], []),
    ('closed', [event('1', 'inbound'), event('1', 'routed_to_booking')], [snapshot('1', closed_politely=True)]),
    ('out_of_area', [event('1', 'inbound'), event('1', 'routed_to_booking')], [snapshot('1', out_of_area='Sharjah')]),
    ('in_progress', [event('1', 'inbound', 1), event('1', 'routed_to_booking', 1)], []),
])
def test_normal_silence_and_recent_dialogues_are_not_lost_sales(stage, events, snaps):
    data = report(events, snapshots=snaps)
    assert data['contacts'][0]['stage'] == stage
    assert not data['needs_attention']


def test_unanswered_latest_message_and_delivery_failure_are_actionable():
    for last_kind, expected in [('inbound', 'unanswered'), ('send_failed', 'delivery_failed')]:
        events = [event('1', 'inbound', 120), event('1', 'routed_to_booking', 120),
                  event('1', 'sent', 119), event('1', last_kind, 60)]
        data = report(events)
        assert data['needs_attention'][0]['stage'] == expected
        assert data['needs_attention'][0]['priority'] == 'high'


def test_truncated_report_does_not_claim_a_conversion_rate():
    data = report([event('1', 'inbound'), event('1', 'routed_to_booking')], truncated=True)
    assert data['summary']['conversion_percent'] is None


@pytest.mark.asyncio
async def test_reports_read_durable_data_after_restart_without_calendar_writes(tmp_path):
    from database.db import Database
    from database.models import Client, Booking, BookingAttempt, CalendarExpectation, NightEvent
    from database.services import BookingService
    url = f"sqlite+aiosqlite:///{tmp_path / 'report.db'}"
    db = Database(url)
    await db.create_tables()
    async with db.session() as session:
        session.add(Client(id=1, telegram_id='ig_1', phone='971500000000'))
        session.add(Booking(id=1, client_id=1, service_name='Face', duration=50,
                            booking_date=NOW, created_at=NOW-timedelta(hours=1), status='confirmed',
                            yclients_appointment_id='456'))
        session.add(BookingAttempt(operation_key='op', status='pending', booking_id=1,
                                   created_at=NOW-timedelta(hours=1)))
        for kind in ('inbound', 'routed_to_booking'):
            session.add(NightEvent(kind=kind, who='1', ts=NOW.isoformat(), created_at=NOW-timedelta(hours=1)))
    await BookingService(db).save_calendar_expectation('op', {'staff_id': 7, 'is_test': False})
    await db.close()
    db = Database(url)
    yc = NS(find_operation_candidates=AsyncMock(return_value=None), create_booking=AsyncMock())
    try:
        data = await load_funnel_report(db, now=NOW)
        assert data['summary']['calendar_records_created'] == 1
        recon = await reconciliation_report(db, yc, now=NOW)
        assert recon['needs_attention'][0]['state'] == 'unverified'
        assert recon['needs_attention'][0]['age_minutes'] == 60
        assert recon['needs_attention'][0]['priority'] == 'high'
        yc.create_booking.assert_not_awaited()
        async with db.session() as session:
            assert (await session.get(BookingAttempt, 'op')).status == 'pending'
            assert (await session.get(CalendarExpectation, 'op')).payload['staff_id'] == 7
    finally:
        await db.close()


def test_previous_completed_booking_is_not_a_new_conversion_or_drop_off():
    snap = snapshot('1'); snap.payload['state'] = 'completed'
    data = report([event('1', 'inbound'), event('1', 'routed_to_booking'), event('1', 'sent', 59)], snapshots=[snap])
    assert data['contacts'][0]['stage'] == 'existing_booking'
    assert data['summary']['converted_contacts'] == 0
    assert not data['needs_attention']


@pytest.mark.asyncio
async def test_reconciliation_paginates_after_excluding_test_accounts(tmp_path):
    from database.db import Database
    from database.models import Client, Booking, BookingAttempt, CalendarExpectation
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'pages.db'}")
    await db.create_tables()
    async with db.session() as session:
        for n, who in enumerate(('ig_770099123', 'ig_tester', 'ig_real1', 'ig_real2', 'wappi_971500000000'), 1):
            session.add(Client(id=n, telegram_id=who))
            session.add(Booking(id=n, client_id=n, service_name='Face', duration=50, booking_date=NOW,
                                created_at=NOW-timedelta(hours=1), yclients_appointment_id=str(n)))
            session.add(BookingAttempt(operation_key=str(n), status='pending', booking_id=n,
                                       created_at=NOW-timedelta(hours=6-n)))
        session.add(CalendarExpectation(operation_key='5', payload={'is_test': True}))
    yc = NS(find_operation_candidates=AsyncMock(return_value=[]))
    try:
        one = await reconciliation_report(db, yc, now=NOW, limit=1, tester_ids=['tester'])
        two = await reconciliation_report(db, yc, now=NOW, limit=1, offset=one['next_offset'], tester_ids=['tester'])
        assert one['total_attempts'] == 2
        assert one['records'][0]['contact'] == 'ig_real1'
        assert two['records'][0]['contact'] == 'ig_real2'
        assert two['next_offset'] is None
        funnel = await load_funnel_report(db, now=NOW, tester_ids=['tester'])
        assert funnel['summary']['calendar_records_created'] == 2
    finally:
        await db.close()


def test_existing_daily_report_uses_calendar_based_summary(monkeypatch):
    from scripts import daily_report, operations_report
    data = report([event('1', 'inbound'), event('1', 'routed_to_booking')])
    monkeypatch.setattr(operations_report, 'fetch_report', lambda *args, **kwargs: data)
    text = daily_report.agent_metrics()
    assert 'Записей с ID YClients: 0' in text
    assert 'Конверсия обращений агента: 0.0%' in text
