from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import bot
import webhook_app as wh
from agents.tools import CancelCall, RescheduleCall


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['cancel', 'reschedule'])
@pytest.mark.parametrize('accepted', [True, False])
async def test_local_changes_require_calendar_acceptance(monkeypatch, action, accepted):
    day = datetime.now() + timedelta(days=3)
    record = dict(booking_id=1, booking_date=day, duration=60, service_name='Body massage',
                  base_price=300, yclients_appointment_id=456, area='abu_dhabi')
    bs = SimpleNamespace(get_active_bookings=AsyncMock(return_value=[record]),
         create_booking=AsyncMock(return_value=SimpleNamespace(id=2)),
         update_booking_status=AsyncMock(), set_rescheduled=AsyncMock(),
         set_yclients_id=AsyncMock(), apply_penalty=AsyncMock())
    yc = SimpleNamespace(cancel_record=AsyncMock(return_value=accepted),
         reschedule_record=AsyncMock(return_value=accepted),
         is_slot_available=AsyncMock(return_value=True))
    monkeypatch.setattr(bot, 'booking_service', bs)
    monkeypatch.setattr(bot, 'yclients_service', yc)
    monkeypatch.setattr(wh, '_admin_text', AsyncMock())
    monkeypatch.setattr(wh, '_send_to_client', AsyncMock())
    monkeypatch.setattr(wh, '_notify_waiting_list', AsyncMock())
    if action == 'cancel':
        await wh._handle_cancellation('test', 'ig:555', CancelCall(confirmed=True))
    else:
        await wh._handle_reschedule('test', 'ig:555', RescheduleCall(day.strftime('%Y-%m-%d'), '14:00'),
                                    SimpleNamespace(client_data={'area': 'abu_dhabi'}))
    if accepted:
        bs.update_booking_status.assert_awaited_once()
    else:
        bs.update_booking_status.assert_not_awaited()
        bs.create_booking.assert_not_awaited()
        bs.set_rescheduled.assert_not_awaited()
        bs.apply_penalty.assert_not_awaited()
        wh._notify_waiting_list.assert_not_awaited()
        assert 'awaiting' in wh._send_to_client.await_args.args[1]
