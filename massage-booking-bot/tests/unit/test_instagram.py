"""Unit tests for the Instagram entry point (consult → WhatsApp funnel)."""

from unittest.mock import AsyncMock, MagicMock

from services.instagram_client import (
    parse_instagram_events,
    build_handoff_reply,
    build_whatsapp_cta,
    _graph_base,
)


def test_parse_basic_dm():
    payload = {"entry": [{"messaging": [
        {"sender": {"id": "u1"}, "message": {"text": "hi, massage?", "mid": "m.1"}},
    ]}]}
    assert parse_instagram_events(payload) == [
        {"sender_id": "u1", "text": "hi, massage?", "mid": "m.1"}
    ]


def test_parse_without_mid_still_works():
    payload = {"entry": [{"messaging": [
        {"sender": {"id": "u1"}, "message": {"text": "hello"}},
    ]}]}
    assert parse_instagram_events(payload) == [
        {"sender_id": "u1", "text": "hello", "mid": None}
    ]


def test_parse_ignores_echoes_and_receipts():
    payload = {"entry": [{"messaging": [
        {"sender": {"id": "u1"}, "message": {"text": "echo", "is_echo": True}},
        {"sender": {"id": "u2"}, "delivery": {"mids": ["x"]}},
        {"sender": {"id": "u3"}, "message": {"attachments": [{"type": "image"}]}},
        {"sender": {"id": "u4"}, "message": {"text": "real"}},
    ]}]}
    assert parse_instagram_events(payload) == [
        {"sender_id": "u4", "text": "real", "mid": None}
    ]


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


def test_graph_base_defaults_to_instagram_login_flavor(monkeypatch):
    """Recommended (free) flavor = Instagram Login → graph.instagram.com."""
    from services import instagram_client
    monkeypatch.setattr(
        instagram_client.config, "INSTAGRAM_GRAPH_BASE",
        "https://graph.instagram.com/v23.0",
    )
    assert _graph_base() == "https://graph.instagram.com/v23.0"
    # Trailing slash never doubles up in the URL join
    monkeypatch.setattr(
        instagram_client.config, "INSTAGRAM_GRAPH_BASE",
        "https://graph.facebook.com/v23.0/",
    )
    assert _graph_base() == "https://graph.facebook.com/v23.0"


# ── consult agent ────────────────────────────────────────────────────────


def test_duplicate_mid_detected_once():
    from agents import instagram_agent
    instagram_agent._seen_mids.clear()
    instagram_agent._seen_mids_set.clear()
    assert instagram_agent.is_duplicate("mid-1") is False
    assert instagram_agent.is_duplicate("mid-1") is True
    assert instagram_agent.is_duplicate("mid-2") is False
    # Missing mid never counts as a duplicate (would eat real messages)
    assert instagram_agent.is_duplicate(None) is False
    assert instagram_agent.is_duplicate(None) is False


def test_system_prompt_has_prices_cta_and_no_booking_rule():
    from agents.instagram_agent import build_system_prompt
    prompt = build_system_prompt("https://wa.me/971501234567?text=hi")
    assert "SERVICES & PRICES" in prompt          # catalog from prices.py
    assert "https://wa.me/971501234567" in prompt  # deep link passed through
    assert "CANNOT book" in prompt                 # no availability promises
    assert "Abu Dhabi only" in prompt              # nails/lashes area rule
    # No-link mode still points to WhatsApp
    assert "WhatsApp" in build_system_prompt(None)


async def test_generate_reply_falls_back_without_api_key(monkeypatch):
    from agents import instagram_agent
    monkeypatch.setattr(instagram_agent.config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(
        instagram_agent.config, "WHATSAPP_CTA_NUMBER", "+971501234567",
        raising=False,
    )
    reply = await instagram_agent.generate_ig_reply("u-fallback", "how much is massage?")
    assert "wa.me/971501234567" in reply  # static handoff with CTA


async def test_generate_reply_falls_back_when_llm_raises(monkeypatch):
    from agents import instagram_agent
    monkeypatch.setattr(instagram_agent.config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        instagram_agent.config, "WHATSAPP_CTA_NUMBER", "+971501234567",
        raising=False,
    )
    broken = MagicMock()
    broken.chat.completions.create = AsyncMock(side_effect=RuntimeError("api down"))
    monkeypatch.setattr(instagram_agent, "_openai", broken)
    reply = await instagram_agent.generate_ig_reply("u-err", "price?")
    assert "wa.me/971501234567" in reply


async def test_generate_reply_uses_llm_answer_and_keeps_history(monkeypatch):
    from agents import instagram_agent
    monkeypatch.setattr(instagram_agent.config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        instagram_agent.config, "WHATSAPP_CTA_NUMBER", "+971501234567",
        raising=False,
    )
    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = "Body massage 60 min is 350 AED 🌹"
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(instagram_agent, "_openai", fake)
    instagram_agent._histories.pop("u-ok", None)

    reply = await instagram_agent.generate_ig_reply("u-ok", "how much is massage?")
    assert reply == "Body massage 60 min is 350 AED 🌹"
    # History keeps the exchange for follow-up turns
    hist = list(instagram_agent._histories["u-ok"])
    assert hist[-2]["role"] == "user"
    assert hist[-1]["role"] == "assistant"
    # The system prompt went in with the catalog and the deep link
    call = fake.chat.completions.create.call_args.kwargs
    sent = call["messages"]
    assert sent[0]["role"] == "system"
    assert "SERVICES & PRICES" in sent[0]["content"]
    # IG path runs on its own model knob, not the WhatsApp agent's
    assert call["model"] == instagram_agent.config.IG_OPENAI_MODEL


async def test_generate_reply_trims_overlong_answer(monkeypatch):
    from agents import instagram_agent
    monkeypatch.setattr(instagram_agent.config, "OPENAI_API_KEY", "sk-test")
    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = "x" * 2000
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=fake_response)
    monkeypatch.setattr(instagram_agent, "_openai", fake)

    reply = await instagram_agent.generate_ig_reply("u-long", "everything please")
    assert len(reply) <= instagram_agent.IG_TEXT_LIMIT


# ── ManyChat bridge ──────────────────────────────────────────────────────


def test_manychat_endpoint_denies_without_secret(monkeypatch):
    from fastapi.testclient import TestClient
    import webhook_app
    # Deny by default: secret unset → closed, even with no header at all
    monkeypatch.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "")
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat", json={"subscriber_id": "1", "text": "hi"})
    assert r.status_code == 403


def test_manychat_endpoint_replies_and_validates(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import webhook_app
    from agents import instagram_agent

    monkeypatch.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(instagram_agent, "IG_TURNS_LOG", tmp_path / "t.jsonl")
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: True)
    seen = {}

    async def fake_reply(sender_id, text):
        seen["sender"] = sender_id
        return "Body massage 60 min — 350 AED 🌹"

    monkeypatch.setattr(instagram_agent, "generate_ig_reply", fake_reply)
    client = TestClient(webhook_app.app)

    r = client.post("/webhook/manychat", json={"subscriber_id": "42", "text": "price?"},
                    headers={"X-Manychat-Secret": "wrong"})
    assert r.status_code == 403

    r = client.post("/webhook/manychat", json={"subscriber_id": "42", "text": "price?"},
                    headers={"X-Manychat-Secret": "s3cret"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"].startswith("Body massage")
    assert body["content"]["messages"][0]["text"] == body["reply"]
    assert seen["sender"] == "mc:42"  # ManyChat histories are namespaced

    r = client.post("/webhook/manychat", json={"text": "no id"},
                    headers={"X-Manychat-Secret": "s3cret"})
    assert r.status_code == 400

    # ManyChat's UI drops saved header values — body secret is an equal path
    r = client.post("/webhook/manychat",
                    json={"subscriber_id": "42", "text": "price?", "secret": "s3cret"})
    assert r.status_code == 200

    # ...and so is ?secret= (the URL field is what ManyChat persists reliably)
    r = client.post("/webhook/manychat?secret=s3cret",
                    json={"subscriber_id": "42", "text": "price?"})
    assert r.status_code == 200

    r = client.post("/webhook/manychat?secret=wrong",
                    json={"subscriber_id": "42", "text": "price?", "secret": "also-wrong"})
    assert r.status_code == 403


# ── live window (owner: live from 21:00 Minsk, shadow otherwise) ─────────


def test_live_window_wraps_midnight_minsk():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from agents.instagram_agent import ig_live_now
    minsk = ZoneInfo("Europe/Minsk")
    assert ig_live_now(datetime(2026, 8, 9, 21, 0, tzinfo=minsk)) is True
    assert ig_live_now(datetime(2026, 8, 9, 23, 30, tzinfo=minsk)) is True
    assert ig_live_now(datetime(2026, 8, 10, 3, 0, tzinfo=minsk)) is True
    assert ig_live_now(datetime(2026, 8, 9, 20, 59, tzinfo=minsk)) is False
    assert ig_live_now(datetime(2026, 8, 9, 9, 0, tzinfo=minsk)) is False
    assert ig_live_now(datetime(2026, 8, 9, 14, 0, tzinfo=minsk)) is False
    # tz conversion: 18:05 UTC = 21:05 Minsk (UTC+3) → live
    assert ig_live_now(datetime(2026, 8, 9, 18, 5, tzinfo=ZoneInfo("UTC"))) is True


def test_log_ig_turn_writes_jsonl(tmp_path, monkeypatch):
    import json as _json
    from agents import instagram_agent
    log_file = tmp_path / "ig_turns.jsonl"
    monkeypatch.setattr(instagram_agent, "IG_TURNS_LOG", log_file)
    instagram_agent.log_ig_turn("manychat", "42", "price?", "350 AED", live=False)
    rec = _json.loads(log_file.read_text().strip())
    assert rec["live"] is False
    assert rec["channel"] == "manychat"
    assert rec["reply"] == "350 AED"


def test_manychat_endpoint_shadow_outside_window(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import webhook_app
    from agents import instagram_agent

    monkeypatch.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(instagram_agent, "IG_TURNS_LOG", tmp_path / "t.jsonl")
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: False)

    async def fake_reply(sender_id, text):
        return "would-be answer"

    monkeypatch.setattr(instagram_agent, "generate_ig_reply", fake_reply)
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat", json={"subscriber_id": "7", "text": "hi"},
                    headers={"X-Manychat-Secret": "s3cret"})
    assert r.status_code == 200
    body = r.json()
    assert body["shadow"] is True
    assert body["reply"] == ""
    assert body["content"]["messages"] == []
    # The would-be reply is still logged for QA
    assert "would-be answer" in (tmp_path / "t.jsonl").read_text()
