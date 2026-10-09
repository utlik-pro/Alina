from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from services.booking_reconciliation import check_calendar_record


@pytest.mark.asyncio
@pytest.mark.parametrize('change,expected', [
    ({}, 'needs_review'),
    ({'deleted': True}, 'mismatch'),
    ({'datetime': '2026-09-12T15:00:00+03:00'}, 'mismatch'),
    ({'seance_length': 1800}, 'mismatch'),
    ({'seance_length': None}, 'unverified'),
    ({'id': 777}, 'needs_review'),
])
async def test_calendar_comparison(change, expected):
    record = dict(id=456, datetime='2026-09-12T14:00:00+03:00', seance_length=3600)
    record.update(change)
    yc = SimpleNamespace(get_record=AsyncMock(return_value=record))
    attempt = SimpleNamespace(operation_key='op', booking_id=1, yclients_id='456')
    booking = SimpleNamespace(booking_date=datetime(2026, 9, 12, 14), duration=60)
    assert (await check_calendar_record(attempt, booking, yc))['state'] == expected


@pytest.mark.asyncio
async def test_uncertain_write_and_outage_never_claim_record_absent():
    yc = SimpleNamespace(get_record=AsyncMock(return_value=None), find_operation_candidates=AsyncMock(return_value=[]))
    attempt = SimpleNamespace(operation_key='op', booking_id=1, yclients_id=None)
    booking = SimpleNamespace(booking_date=datetime(2026, 9, 12, 14), duration=60)
    assert (await check_calendar_record(attempt, booking, yc))['state'] == 'needs_review'
    yc.get_record.assert_not_awaited()
    attempt.yclients_id = '456'
    assert (await check_calendar_record(attempt, booking, yc))['state'] == 'unverified'


@pytest.mark.asyncio
async def test_lost_response_recovered_by_marker_without_writing():
    record = dict(id=456, datetime='2026-09-12T14:00:00+03:00', seance_length=3600)
    yc = SimpleNamespace(find_operation_candidates=AsyncMock(return_value=[record]))
    attempt = SimpleNamespace(operation_key='op', booking_id=1, yclients_id=None)
    booking = SimpleNamespace(booking_date=datetime(2026, 9, 12, 14), duration=60)
    result = await check_calendar_record(attempt, booking, yc)
    assert result['state'] == 'needs_review'
    assert result['record_id'] == '456'
    assert attempt.yclients_id is None

@pytest.mark.asyncio
@pytest.mark.parametrize('records,expected', [(None, None), ([{'comment': '[operation:op]', 'id': 1}], [1]),
                                              ([{'comment': '[operation:other]', 'id': 2}], []),
                                              ([{'id': 1}] * 100, None)])
async def test_operation_lookup_requires_complete_response(records, expected):
    from services.yclients_service import YClientsService
    yc = YClientsService()
    yc._get = AsyncMock(return_value={'data': records})
    result = await yc.find_operation_candidates('op', '2026-09-12')
    assert (None if result is None else [r['id'] for r in result]) == expected


def full_record():
    return dict(id=456, datetime='2026-09-12T14:00:00+03:00', seance_length=3600,
                deleted=False, staff_id=7, services=[{'id': 9, 'cost': 350}],
                client={'phone': '+971 50 000 0000', 'name': 'Test Client'},
                comment='Payment: cash — tax free. [operation:op]', paid_full=False)


def expectation():
    return dict(datetime='2026-09-12T14:00:00', duration_seconds=3600,
                staff_id=7, service_ids=[9], client_phone='0500000000',
                client_name='Test Client', payment_method='cash', base_price=350)


@pytest.mark.asyncio
@pytest.mark.parametrize('change,field', [
    ({'staff_id': 8}, 'staff'),
    ({'services': [{'id': 10, 'cost': 350}]}, 'services'),
    ({'services': [{'id': 9, 'cost': 550}]}, 'base_price'),
    ({'client': {'phone': '+973500000000', 'name': 'Test Client'}}, 'phone'),
    ({'client': {'phone': '971500000000', 'name': 'Other Client'}}, 'client_name'),
    ({'comment': 'Payment: bank transfer +5% VAT. [operation:op]'}, 'payment_method'),
    ({'comment': 'Payment: cash. [operation:op]'}, 'vat_terms'),
    ({'comment': 'Payment: cash — tax free. [operation:other]'}, 'operation_marker'),
    ({'paid_full': True}, 'payment_status'),
])
async def test_full_comparison_detects_each_booking_dimension(change, field):
    record = full_record(); record.update(change)
    yc = SimpleNamespace(get_record=AsyncMock(return_value=record))
    attempt = SimpleNamespace(operation_key='op', booking_id=1, yclients_id='456')
    booking = SimpleNamespace(booking_date=datetime(2026, 9, 12, 14), duration=60, payment_status='pending', yclients_appointment_id='456')
    result = await check_calendar_record(attempt, booking, yc, expectation())
    assert result['state'] == 'mismatch'
    assert result['checks'][field] == 'mismatch'


@pytest.mark.asyncio
@pytest.mark.parametrize('recover', [True, False])
async def test_fully_matching_record_and_normalized_phone(recover):
    yc = SimpleNamespace(get_record=AsyncMock(return_value=full_record()),
                         find_operation_candidates=AsyncMock(return_value=[full_record()]))
    attempt = SimpleNamespace(operation_key='op', booking_id=1, yclients_id=None if recover else '456')
    booking = SimpleNamespace(booking_date=datetime(2026, 9, 12, 14), duration=60, payment_status='pending', yclients_appointment_id='456')
    result = await check_calendar_record(attempt, booking, yc, expectation())
    assert result['state'] == ('recovered_matches' if recover else 'matches')
    assert all(s == 'match' for s in result['checks'].values())
    assert attempt.yclients_id == (None if recover else '456')


@pytest.mark.asyncio
async def test_missing_payment_evidence_never_becomes_paid():
    record = full_record(); record.pop('paid_full')
    yc = SimpleNamespace(get_record=AsyncMock(return_value=record))
    attempt = SimpleNamespace(operation_key='op', booking_id=1, yclients_id='456')
    booking = SimpleNamespace(booking_date=datetime(2026, 9, 12, 14), duration=60, payment_status='paid')
    result = await check_calendar_record(attempt, booking, yc, expectation())
    assert result['state'] == 'needs_review'
    assert result['checks']['payment_status'] == 'unknown'
