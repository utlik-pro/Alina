"""Calendar failure must not confirm locally or dispatch a driver."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import bot
import webhook_app as wh
from agents.tools import BookingCall


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["rejected", "exception", "missing", "accepted"])
async def test_calendar_sync_controls_confirmation_and_dispatch(monkeypatch, outcome):
    day = (datetime.now(timezone(timedelta(hours=4))) + timedelta(days=2)).strftime("%Y-%m-%d")
    call = BookingCall("Body massage", 60, day, "14:00", "abu_dhabi", "cash",
                       "Test Client", 300, master_id=7, address="Test villa 5")
    ctx = SimpleNamespace(booking_data={}, client_data={},
                          recent_messages=[{"role": "user", "content": "yes"}])
    client = SimpleNamespace(phone="971500000000", name="Test Client", location_details="Test villa 5")
    booking = SimpleNamespace(id=123, status="draft")
    bs = SimpleNamespace(create_booking=AsyncMock(return_value=booking),
                         update_booking_status=AsyncMock(return_value=booking),
                         set_yclients_id=AsyncMock())
    cs = SimpleNamespace(get_or_create_client=AsyncMock(return_value=client), update_client=AsyncMock())
    ns = SimpleNamespace(send_booking_failed=AsyncMock(), send_booking_confirmed=AsyncMock())
    yc = SimpleNamespace(is_slot_available=AsyncMock(return_value=True),
                         find_service_id=AsyncMock(return_value=9),
                         staff_area_of=AsyncMock(return_value="abu_dhabi"),
                         get_staff=AsyncMock(return_value=[]),
                         create_booking=AsyncMock(return_value={"id": 456} if outcome == "accepted" else None))
    if outcome == "exception":
        yc.create_booking.side_effect = TimeoutError("calendar timeout")
    monkeypatch.setattr(bot, "booking_service", bs)
    monkeypatch.setattr(bot, "client_service", cs)
    monkeypatch.setattr(bot, "notification_service", ns)
    monkeypatch.setattr(bot, "yclients_service", None if outcome == "missing" else yc)
    monkeypatch.setattr(wh.config, "MOCK_YCLIENTS", False)
    monkeypatch.setattr(wh, "_notify_driver", AsyncMock())
    monkeypatch.setattr(wh, "_night_event", Mock())
    monkeypatch.setattr(wh.dialog_manager, "update_state", Mock())
    await wh._maybe_create_booking("test", "test", client.phone, client.name, ctx,
                                   "Your booking is confirmed ✅", call)
    if outcome == "accepted":
        bs.update_booking_status.assert_awaited_once_with(123, "confirmed")
        ns.send_booking_confirmed.assert_awaited_once()
        wh._notify_driver.assert_awaited_once()
        assert ctx.last_booking_sig == (call.service, day, "14:00")
        assert ctx.booking_data["yc_sync_ok"] is True
    else:
        bs.update_booking_status.assert_not_awaited()
        ns.send_booking_confirmed.assert_not_awaited()
        wh._notify_driver.assert_not_awaited()
        wh.dialog_manager.update_state.assert_not_called()
        ns.send_booking_failed.assert_awaited()
        assert not hasattr(ctx, "last_booking_sig")
        assert ctx.booking_data["yc_sync_ok"] is False
