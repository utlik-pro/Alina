"""Daytime silence: NOTHING may reach an Instagram client outside the window.

The client (salon owner) demanded complete silence during the day after a
stale reply reached a lead at 14:58 on 2026-08-15. These tests walk every
outbound path that can end at an Instagram DM and assert it is blocked.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import webhook_app
from agents import instagram_agent


@pytest.fixture
def daytime(monkeypatch):
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: False)
    return monkeypatch


@pytest.fixture
def nighttime(monkeypatch):
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: True)
    return monkeypatch


# 1 — the shared router used by booking turns, reminders, alerts, resets
def test_1_send_to_client_blocked_in_daytime(daytime):
    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)) as send:
        ok = asyncio.run(webhook_app._send_to_client("ig:868311272", "hello"))
    assert ok is False
    assert not send.called


# 2 — the same router must still work at night
def test_2_send_to_client_allowed_at_night(nighttime):
    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)) as send:
        ok = asyncio.run(webhook_app._send_to_client("ig:868311272", "hello"))
    assert ok is True
    assert send.called


# 3 — WhatsApp clients are never affected by the IG window
def test_3_whatsapp_send_unaffected_by_window(daytime):
    fake = SimpleNamespace(send_message=AsyncMock(return_value=True))
    with patch.object(webhook_app, "wappi_client", fake):
        ok = asyncio.run(webhook_app._send_to_client("971501234567", "hi"))
    assert ok is True
    assert fake.send_message.called


# 4 — lowest-level funnel blocks even if a caller forgets the window
def test_4_manychat_send_text_blocks_itself_in_daytime(daytime):
    from services.instagram_client import manychat_send_text

    with patch("aiohttp.ClientSession") as session:
        ok = asyncio.run(manychat_send_text("868311272", "hello"))
    assert ok is False
    assert not session.called, "no HTTP call may leave during the day"


# 5 — a tester (whitelist) gets NO booking pipeline during the day
def test_5_tester_gets_no_daytime_booking(daytime):
    daytime.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    daytime.setattr(webhook_app.config, "MANYCHAT_API_KEY", "key")
    daytime.setattr(webhook_app.config, "IG_BOOKING_ENABLED", True)
    daytime.setattr(webhook_app.config, "IG_TEST_SUBSCRIBERS", "868311272")
    daytime.setattr(webhook_app.config, "IG_ASYNC_SEND", False)

    async def never(*a, **kw):
        raise AssertionError("booking pipeline must not run during the day")

    daytime.setattr(webhook_app, "_buffer_and_process_wappi", never)
    daytime.setattr(instagram_agent, "generate_ig_reply",
                    AsyncMock(return_value="would-be"))
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat",
                    json={"secret": "s3cret", "subscriber_id": "868311272",
                          "text": "book me today"})
    assert r.status_code == 200
    assert r.json()["reply"] == instagram_agent.SHADOW_SENTINEL
    assert r.json().get("shadow") is True


# 6 — a normal client during the day: instant sentinel, no generation awaited
def test_6_regular_client_daytime_is_instant_sentinel(daytime):
    daytime.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    daytime.setattr(webhook_app.config, "MANYCHAT_API_KEY", "key")
    daytime.setattr(webhook_app.config, "IG_BOOKING_ENABLED", True)
    daytime.setattr(webhook_app.config, "IG_TEST_SUBSCRIBERS", "")
    daytime.setattr(webhook_app.config, "IG_ASYNC_SEND", False)

    slow = AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(5))
    daytime.setattr(instagram_agent, "generate_ig_reply", slow)
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat",
                    json={"secret": "s3cret", "subscriber_id": "555", "text": "price?"})
    assert r.json()["reply"] == instagram_agent.SHADOW_SENTINEL
    assert r.json()["shadow"] is True


# 7 — unreadable media during the day must not trigger the nudge
def test_7_media_nudge_silent_in_daytime(daytime, tmp_path):
    daytime.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    daytime.setattr(instagram_agent, "IG_TURNS_LOG", tmp_path / "t.jsonl")
    daytime.setattr("services.instagram_client.fetch_manychat_last_text",
                    AsyncMock(return_value=""))
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat",
                    json={"secret": "s3cret", "subscriber_id": "777", "text": ""})
    body = r.json()
    assert body["reply"] == instagram_agent.SHADOW_SENTINEL
    assert body.get("shadow") is True
    assert webhook_app.IG_MEDIA_FALLBACK not in str(body)


# 8 — a reminder for an IG client is blocked too (scheduler path)
def test_8_reminder_to_ig_client_blocked_in_daytime(daytime):
    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)) as send:
        ok = asyncio.run(webhook_app._send_to_client(
            "ig:99", "Reminder: your massage is tomorrow at 5 PM"))
    assert ok is False
    assert not send.called


# 9 — the night log records the trail and is protected by the secret
def test_9_night_log_records_and_requires_secret(daytime):
    daytime.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    webhook_app.NIGHT_LOG = None  # start clean

    # a blocked daytime send must leave a trace
    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)):
        asyncio.run(webhook_app._send_to_client("ig:4242", "hello"))

    client = TestClient(webhook_app.app)
    assert client.get("/admin/night-log").status_code == 403
    assert client.get("/admin/night-log?secret=wrong").status_code == 403

    r = client.get("/admin/night-log?secret=s3cret")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"].get("send_blocked_daytime") == 1
    assert body["unique_contacts"] == 1
    assert body["events"][-1]["who"] == "ig:4242"


# 10 — logging must never break a turn, even on bad input
def test_10_night_log_never_raises():
    webhook_app.NIGHT_LOG = None
    webhook_app._night_event("weird", who=None, text=object())  # unserialisable
    webhook_app._night_event("ok", who="ig:1", text="x" * 5000)
    events = list(webhook_app.NIGHT_LOG)
    assert len(events) == 2
    assert events[-1]["text"].endswith("…"), "long text must be truncated"


# 11 — a lash-maker must never be offered for a massage (and vice versa)
def test_11_specialist_role_must_match_the_service():
    """Live defect 2026-08-15: 'Бота' (мастер лэшмейкер) was offered for body
    massage, so a lash specialist would have arrived for a massage booking.
    Anything that wasn't a nail tech used to count as a massage therapist.
    """
    from unittest.mock import AsyncMock, patch as _patch

    from services.yclients_service import YClientsService

    staff = [
        {"id": 1, "name": "Екатерина", "specialization": "массажист",
         "position": {"title": "Массажист"}},
        {"id": 2, "name": "Бота", "specialization": "мастер лэшмейкер",
         "position": {"title": "Лэшмейкер"}},
        {"id": 3, "name": "Елена", "specialization": "маникюр",
         "position": {"title": "Мастер маникюра"}},
        {"id": 4, "name": "АДМИНИСТРАТОРЫ", "specialization": "ЛИСТ ОЖИДАНИЯ",
         "position": {"title": "ЛИСТ ОЖИДАНИЯ"}},
    ]
    svc = YClientsService()

    def run(service_name):
        with _patch.object(svc, "get_staff", AsyncMock(return_value=staff)), \
             _patch.object(svc, "get_records", AsyncMock(return_value=[])), \
             _patch.object(svc, "get_real_available_slots",
                           AsyncMock(return_value=["10:00", "10:30"])):
            return asyncio.run(svc.get_available_slots_summary(
                date="2026-08-22", service_name=service_name,
                area="abu_dhabi", service_duration=60))

    massage = run("body massage")
    assert "Ekaterina" in massage
    assert "Bota" not in massage, "a lash-maker must not take massage bookings"
    assert "Elena" not in massage and "Елена" not in massage

    lashes = run("lash lifting")
    assert "Bota" in lashes
    assert "Ekaterina" not in lashes

    # the waiting-list service record is never a bookable master
    for out in (massage, lashes, run("manicure")):
        assert "АДМИНИСТРАТОР" not in out.upper()


# 12 — a client may spell the date out instead of naming a weekday
def test_12_explicit_date_is_understood():
    """'20 August' / '22/08' / 'the 20th' must resolve to a real date.

    Before this the agent replied "I don't have the schedule for 20 August
    yet" while that day was wide open (date-phrase battery, 2026-08-15).
    """
    import datetime as _dt

    import webhook_app as wh

    now = _dt.datetime(2026, 8, 15, 18, 0)  # Saturday
    assert wh._detect_explicit_date("on 20 August", now) == "2026-08-20"
    assert wh._detect_explicit_date("August 20 please", now) == "2026-08-20"
    assert wh._detect_explicit_date("book 22 aug at 7pm", now) == "2026-08-22"
    assert wh._detect_explicit_date("20/08", now) == "2026-08-20"
    assert wh._detect_explicit_date("on the 20th", now) == "2026-08-20"

    # ordinals with "of", and Russian-style "3 сентября"
    assert wh._detect_explicit_date("book me 22nd of August", now) == "2026-08-22"
    assert wh._detect_explicit_date("on 3rd of September", now) == "2026-09-03"
    assert wh._detect_explicit_date("1st of September", now) == "2026-09-01"

    # must NOT mistake prices, durations, flat numbers, times — or an
    # ADDRESS — for a date. "Gate Tower, 21st floor" is where the client
    # lives, not when they want the visit (month-ahead sweep, 2026-08-15).
    for noise in ("60 min massage 350 AED", "apt 1204", "5 pm works",
                  "0501234567", "90 min", "room 21st floor",
                  "Gate Tower 2, 21st floor apt 1801", "Marina, 3rd floor"):
        assert wh._detect_explicit_date(noise, now) is None, noise

    # a date that already passed is never resolved into the past …
    assert wh._detect_explicit_date("14 August", now) is None
    # … and anything beyond the ~6-month booking horizon is ignored too,
    # so "3 March" (200 days out) is not treated as a booking date
    assert wh._detect_explicit_date("3 March", now) is None
    # a date later this year inside the horizon still resolves
    assert wh._detect_explicit_date("2 October", now) == "2026-10-02"
