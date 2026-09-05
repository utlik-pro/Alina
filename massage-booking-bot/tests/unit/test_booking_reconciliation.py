from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from services.booking_reconciliation import check_calendar_record


@pytest.mark.asyncio
@pytest.mark.parametrize('change,expected', [
    ({}, 'schedule_matches'),
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
    assert result['state'] == 'recovered_schedule_matches'
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
