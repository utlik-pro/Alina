"""Unit tests for driver/logistics notification (FR 5.2 'share with driver').

Covers the message builder and the send helper that now fires automatically
on booking creation and is reused by the manual admin endpoint.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import webhook_app
from webhook_app import _driver_request_text, _notify_driver


def _booking():
    return SimpleNamespace(
        id=7,
        booking_date=datetime(2026, 7, 8, 19, 30),
        service_name="Body massage",
        duration=90,
    )


def _client(with_location=True):
    return SimpleNamespace(
        name="Sara",
        phone="971501234567",
        location_details="Villa 20, Al Barsha",
        location_latitude=25.1 if with_location else None,
        location_longitude=55.2 if with_location else None,
    )


# ==================== _driver_request_text ====================

def test_driver_text_includes_all_trip_fields():
    text = _driver_request_text(_booking(), _client())
    assert "08.07.2026 19:30" in text
    assert "Body massage" in text and "90 min" in text
    assert "Sara" in text and "971501234567" in text
    assert "Villa 20, Al Barsha" in text
    assert "maps.google.com/?q=25.1,55.2" in text


def test_driver_text_without_location_has_no_map():
    text = _driver_request_text(_booking(), _client(with_location=False))
    assert "maps.google.com" not in text
    assert "Body massage" in text  # still useful without a pin


# ==================== _notify_driver ====================

@pytest.mark.asyncio
async def test_notify_driver_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(webhook_app.config, "DRIVER_TELEGRAM_CHAT_ID", None)
    sender = AsyncMock()
    monkeypatch.setattr(webhook_app, "bot_instance", sender)

    status = await _notify_driver(_booking(), _client())
    assert status == "no_driver_configured"
    sender.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_notify_driver_sends_when_configured(monkeypatch):
    monkeypatch.setattr(webhook_app.config, "DRIVER_TELEGRAM_CHAT_ID", "-100999")
    sender = AsyncMock()
    monkeypatch.setattr(webhook_app, "bot_instance", sender)

    status = await _notify_driver(_booking(), _client())
    assert status == "sent"
    sender.send_message.assert_awaited_once()
    kwargs = sender.send_message.call_args.kwargs
    assert kwargs["chat_id"] == "-100999"
    assert kwargs["parse_mode"] == "HTML"
    assert "New transport request" in kwargs["text"]


@pytest.mark.asyncio
async def test_notify_driver_returns_error_on_send_failure(monkeypatch):
    monkeypatch.setattr(webhook_app.config, "DRIVER_TELEGRAM_CHAT_ID", "-100999")
    sender = AsyncMock()
    sender.send_message.side_effect = RuntimeError("telegram down")
    monkeypatch.setattr(webhook_app, "bot_instance", sender)

    status = await _notify_driver(_booking(), _client())
    assert status == "error"
