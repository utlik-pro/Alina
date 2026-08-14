"""Stage-1 unit tests: Instagram identities flowing through the booking core.

The IG channel reuses the WhatsApp pipeline with a synthetic "ig:<id>"
identity — these tests pin the channel-aware seams: the send router, the
phone gates, and the ManyChat bridge routing into the buffered pipeline.
"""

from unittest.mock import AsyncMock, MagicMock

import webhook_app
from webhook_app import (
    IG_KEY_PREFIX,
    _enforce_reply_wording,
    _is_ig_key,
    _send_to_client,
)


def test_is_ig_key():
    assert _is_ig_key("ig:868311272") is True
    assert _is_ig_key("971551933662") is False
    assert _is_ig_key("") is False


async def test_send_router_routes_ig_to_manychat(monkeypatch):
    sent = {}

    async def fake_mc(subscriber_id, text):
        sent["mc"] = (subscriber_id, text)
        return True

    from services import instagram_client
    monkeypatch.setattr(instagram_client, "manychat_send_text", fake_mc)
    ok = await _send_to_client("ig:555", "hello")
    assert ok is True
    assert sent["mc"] == ("555", "hello")  # prefix stripped


async def test_send_router_routes_numbers_to_wappi(monkeypatch):
    fake_wappi = MagicMock()
    fake_wappi.send_message = AsyncMock(return_value=True)
    monkeypatch.setattr(webhook_app, "wappi_client", fake_wappi)
    ok = await _send_to_client("971551933662", "hi")
    assert ok is True
    fake_wappi.send_message.assert_awaited_once_with("971551933662", "hi")


def _confirmed_booking_call():
    call = MagicMock()
    call.service = "Body massage"
    call.date = "2026-08-20"
    call.time = "18:00"
    call.address = "Villa 5, Al Reem"
    call.client_name = "Anna"
    call.guests = None
    call.master_name = None
    return call


def test_phone_gate_overrides_reply_for_ig(monkeypatch):
    """needs_phone → the 'booked ✅' reply becomes a phone question."""
    monkeypatch.setattr(webhook_app, "_booking_day_mismatch", lambda *a: None)
    client_data = {"name": "Anna", "location": "Al Reem", "location_details": "Villa 5"}
    reply = _enforce_reply_wording(
        "Your booking is confirmed ✔", None, _confirmed_booking_call(), client_data,
        user_text="yes, confirm",
        needs_phone=True,
    )
    assert "phone number" in reply
    # Without the flag the confirmed reply passes through untouched
    reply2 = _enforce_reply_wording(
        "Your booking is confirmed ✔", None, _confirmed_booking_call(), client_data,
        user_text="yes, confirm",
        needs_phone=False,
    )
    assert reply2 == "Your booking is confirmed ✔"


def test_manychat_bridge_routes_to_booking_pipeline(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from agents import instagram_agent

    monkeypatch.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(webhook_app.config, "IG_BOOKING_ENABLED", True)
    monkeypatch.setattr(webhook_app.config, "MANYCHAT_API_KEY", "mc-key", raising=False)
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: True)
    routed = {}

    async def fake_buffer(phone, text, sender_name):
        routed["args"] = (phone, text, sender_name)

    monkeypatch.setattr(webhook_app, "_buffer_and_process_wappi", fake_buffer)
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat",
                    json={"subscriber_id": "77", "text": "book me a massage",
                          "secret": "s3cret"})
    assert r.status_code == 200
    assert r.json()["queued"] is True
    assert routed["args"] == (f"{IG_KEY_PREFIX}77", "book me a massage", None)


def test_manychat_bridge_shadow_bypasses_booking(monkeypatch, tmp_path):
    """Outside the live window the booking path must NOT engage."""
    from fastapi.testclient import TestClient
    from agents import instagram_agent

    monkeypatch.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(webhook_app.config, "IG_BOOKING_ENABLED", True)
    monkeypatch.setattr(webhook_app.config, "IG_ASYNC_SEND", False)
    monkeypatch.setattr(webhook_app.config, "MANYCHAT_API_KEY", "mc-key", raising=False)
    monkeypatch.setattr(instagram_agent, "IG_TURNS_LOG", tmp_path / "t.jsonl")
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: False)

    async def fake_reply(sender_id, text):
        return "consult answer"

    monkeypatch.setattr(instagram_agent, "generate_ig_reply", fake_reply)
    called = {}

    async def fake_buffer(phone, text, sender_name):  # must NOT be hit
        called["hit"] = True

    monkeypatch.setattr(webhook_app, "_buffer_and_process_wappi", fake_buffer)
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat",
                    json={"subscriber_id": "77", "text": "hi", "secret": "s3cret"})
    assert r.status_code == 200
    assert r.json()["shadow"] is True
    assert "hit" not in called
