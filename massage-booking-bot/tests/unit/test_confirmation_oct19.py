import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import bot
import webhook_app as wh
from agents.tools import BookingCall

@pytest.mark.parametrize('text', ['If it’s not ADIB , cash 👍🏻', 'Cash 👍', 'Yes but tomorrow',
    'No 👍', 'Not confirmed', 'Can you confirm?', 'Yes, change it to 2 pm', '👍?', '!!!',
    'I will confirm later', 'Да, но наличными', 'confirm my bank details', 'Thanks', 'Please', 'dear'])
def test_changed_or_conditional_details_are_not_approval(text):
    assert not wh._client_confirmed(text)

@pytest.mark.parametrize('text', ['👍🏻', '✅', 'Yes, please confirm', 'да, записывайте', 'sure, go ahead'])
def test_unambiguous_approval(text):
    assert wh._client_confirmed(text)

@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['conditional', 'missing_offer', 'changed_payment', 'changed_time'])
async def test_record_write_requires_matching_offer(monkeypatch, case):
    day = (datetime.now(timezone(timedelta(hours=4))) + timedelta(days=2)).strftime('%Y-%m-%d')
    call = BookingCall('face_massage', 50, day, '13:00', 'abu_dhabi', 'cash', 'Test', 370,
                       client_phone='+971500000000', address='Test villa')
    offered = dataclasses.asdict(call)
    text = 'If it’s not ADIB , cash 👍🏻' if case == 'conditional' else 'Yes'
    if case == 'changed_payment': offered['payment_method'] = 'bank_transfer'
    if case == 'changed_time': offered['time'] = '14:00'
    ctx = SimpleNamespace(booking_data={'confirmation_offer': offered} if case != 'missing_offer' else {},
                           client_data={}, recent_messages=[{'role': 'user', 'content': text}])
    records = SimpleNamespace(create_booking=AsyncMock())
    calendar = SimpleNamespace(create_booking=AsyncMock())
    monkeypatch.setattr(bot, 'booking_service', records)
    monkeypatch.setattr(bot, 'yclients_service', calendar)
    monkeypatch.setattr(bot, 'notification_service', None)
    await wh._maybe_create_booking('test', 'test', '+971500000000', 'Test', ctx, 'Booked!', call)
    records.create_booking.assert_not_awaited()
    calendar.create_booking.assert_not_awaited()
    assert ctx.booking_data['pending_booking'] == dataclasses.asdict(call)
