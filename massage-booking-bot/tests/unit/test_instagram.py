"""Unit tests for the Instagram entry-point scaffold."""

from services.instagram_client import (
    parse_instagram_events,
    build_handoff_reply,
    build_whatsapp_cta,
)


def test_parse_basic_dm():
    payload = {"entry": [{"messaging": [
        {"sender": {"id": "u1"}, "message": {"text": "hi, massage?"}},
    ]}]}
    assert parse_instagram_events(payload) == [{"sender_id": "u1", "text": "hi, massage?"}]


def test_parse_ignores_echoes_and_receipts():
    payload = {"entry": [{"messaging": [
        {"sender": {"id": "u1"}, "message": {"text": "echo", "is_echo": True}},
        {"sender": {"id": "u2"}, "delivery": {"mids": ["x"]}},
        {"sender": {"id": "u3"}, "message": {"attachments": [{"type": "image"}]}},
        {"sender": {"id": "u4"}, "message": {"text": "real"}},
    ]}]}
    assert parse_instagram_events(payload) == [{"sender_id": "u4", "text": "real"}]


def test_handoff_reply_without_cta_number(monkeypatch):
    from services import instagram_client
    monkeypatch.setattr(instagram_client.config, "WHATSAPP_CTA_NUMBER", None)
    reply = build_handoff_reply("massage")
    assert "WhatsApp" in reply
    assert build_whatsapp_cta("x") is None


def test_handoff_reply_with_cta_number(monkeypatch):
    from services import instagram_client
    monkeypatch.setattr(instagram_client.config, "WHATSAPP_CTA_NUMBER", "+971 50 123 4567")
    link = build_whatsapp_cta("massage tomorrow")
    assert link.startswith("https://wa.me/971501234567?text=")
    assert "wa.me/971501234567" in build_handoff_reply("massage")
