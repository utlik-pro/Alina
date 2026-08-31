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

    routed = {}

    async def fake_buffer(phone, text, sender_name):
        routed["args"] = (phone, text, sender_name)

    daytime.setattr(webhook_app, "_buffer_and_process_wappi", fake_buffer)
    daytime.setattr(instagram_agent, "generate_ig_reply",
                    AsyncMock(return_value="would-be"))
    client = TestClient(webhook_app.app)
    r = client.post("/webhook/manychat",
                    json={"secret": "s3cret", "subscriber_id": "868311272",
                          "text": "book me today"})
    assert r.status_code == 200
    # Свой тестовый аккаунт работает и днём — иначе агента нельзя проверить
    # в рабочее время (2026-08-19). Для клиентов тишина осталась абсолютной,
    # это проверяет соседний тест.
    assert routed.get("args") is not None


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
    # Порог 1200: карточки админов (~450+ символов) обязаны попадать в лог
    # целиком — на 400 смоук считал правильный ответ провальным.
    webhook_app._night_event("ok", who="ig:1", text="y" * 800)
    assert not list(webhook_app.NIGHT_LOG)[-1]["text"].endswith("…")


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

    # abbreviated, joined, ISO and Russian month names — clients use them all
    assert wh._detect_explicit_date("20 Aug", now) == "2026-08-20"
    assert wh._detect_explicit_date("Sept 20", now) == "2026-09-20"
    assert wh._detect_explicit_date("20AUG", now) == "2026-08-20"
    assert wh._detect_explicit_date("2026-08-20", now) == "2026-08-20"
    assert wh._detect_explicit_date("20 августа", now) == "2026-08-20"
    assert wh._detect_explicit_date("3 сен", now) == "2026-09-03"
    # ambiguous US order stays unparsed rather than guessed
    assert wh._detect_explicit_date("8/20", now) is None

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


# 13 — no times until the massage duration is known (IG only)
def test_13_duration_gate_blocks_times_for_massage():
    """60- and 90-min windows differ, so offering times before the client
    picks a duration means taking them back (live-caught 2026-08-15)."""
    import webhook_app as wh

    assert wh._is_massage_service("body massage") is True
    assert wh._is_massage_service("facial massage") is True
    assert wh._is_massage_service("массаж 60") is True
    # services with a single fixed duration must NOT be gated
    for other in ("lash lifting", "eyebrow lamination", "manicure",
                  "pedicure", "deep cleansing", "permanent make up"):
        assert wh._is_massage_service(other) is False, other

    assert "Do NOT show" in wh.DURATION_FIRST_GATE_MSG
    assert "60" in wh.DURATION_FIRST_GATE_MSG and "90" in wh.DURATION_FIRST_GATE_MSG


# 14 — a bare "massage" asks body-or-face before duration
def test_14_ambiguous_massage_asks_kind_first():
    """Live first night: 'consult on a massage' jumped straight to the 60/90
    question, then repeated it verbatim when the client said 'body massage'."""
    import webhook_app as wh

    assert wh._massage_kind_known("massage") is False
    assert wh._massage_kind_known("массаж") is False
    for known in ("body massage", "facial massage", "face massage",
                  "массаж тела", "массаж лица"):
        assert wh._massage_kind_known(known) is True, known
    assert "Body massage or facial" in wh.MASSAGE_KIND_GATE_MSG
    assert "do NOT repeat" in wh.DURATION_FIRST_GATE_MSG


def test_daytime_silence_holds_for_clients_but_testers_can_work(monkeypatch):
    """Днём молчим для всех, КРОМЕ своих тестовых аккаунтов.

    Правило владельца о полной дневной тишине остаётся: реальный клиент днём
    не получает ничего. Но проверять агента можно только днём — правки мы
    делаем в рабочее время, а ждать 21:00 на каждую проверку нельзя.
    """
    import webhook_app as wh
    from config import config

    monkeypatch.setattr(config, "IG_TEST_SUBSCRIBERS", "868311272", raising=False)

    assert wh._is_ig_test_subscriber("868311272") is True
    assert wh._is_ig_test_subscriber("2012561461") is False   # реальный клиент
    assert wh._is_ig_test_subscriber("") is False

    # Пустой список = никаких исключений вообще.
    monkeypatch.setattr(config, "IG_TEST_SUBSCRIBERS", "", raising=False)
    assert wh._is_ig_test_subscriber("868311272") is False


# 12 — ночная смена агента: только лиды с рекламы (правило владельца
# 2026-08-19 «агент отвечает только новым по рекламе после 21-00»).
def test_12_night_agent_answers_only_ad_leads(nighttime):
    nighttime.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    nighttime.setattr(webhook_app.config, "MANYCHAT_API_KEY", "key")
    nighttime.setattr(webhook_app.config, "IG_BOOKING_ENABLED", True)
    nighttime.setattr(webhook_app.config, "IG_TEST_SUBSCRIBERS", "868311272")
    nighttime.setattr(webhook_app.config, "IG_ASYNC_SEND", False)
    # Правило выключено по умолчанию (см. IG_AD_LEADS_ONLY) — здесь включаем
    # явно, чтобы проверить саму механику, если её когда-нибудь вернут.
    nighttime.setattr(webhook_app.config, "IG_AD_LEADS_ONLY", True)
    nighttime.setattr(webhook_app, "_human_led_dialogue", AsyncMock(return_value=False))
    # База пуста → судим только по тексту текущего сообщения.
    nighttime.setattr(webhook_app, "_ad_originated_dialogue",
                      lambda sid, txt: _origin(sid, txt))

    async def _origin(sid, txt):
        return bool(webhook_app._detect_ad_prefill(txt))

    routed = []
    async def fake_buffer(phone, text, sender_name):
        routed.append(phone)
    nighttime.setattr(webhook_app, "_buffer_and_process_wappi", fake_buffer)

    client = TestClient(webhook_app.app)

    def post(sid, text):
        return client.post("/webhook/manychat", json={
            "secret": "s3cret", "subscriber_id": sid, "text": text}).json()

    # Лид с рекламы — агент работает.
    ad = post("111", "Hello i would like to sign up for a massage package "
                     "in Abu Dhabi at a discount")
    assert ad.get("not_ad") is None and "111" in str(routed)

    # Органика ночью — молчим, в пайплайн не уходит.
    org = post("222", "Hi, how much for a massage?")
    assert org["reply"] == instagram_agent.SHADOW_SENTINEL
    assert org.get("not_ad") is True
    assert "222" not in str(routed)

    # Мусор ночью — тоже молчим.
    assert post("333", "Can i see girl pic")["reply"] == instagram_agent.SHADOW_SENTINEL

    # Свой тестовый аккаунт проверяет агента без рекламного текста.
    tester = post("868311272", "hi")
    assert tester.get("not_ad") is None
    assert "868311272" in str(routed)


# 13 — недоступная база не должна глушить рекламного лида
def test_13_db_outage_does_not_silence_a_lead():
    async def _boom(*a, **kw):
        raise RuntimeError("db down")

    with patch("database.get_db", _boom):
        ok = asyncio.run(webhook_app._ad_originated_dialogue("999", "hi there"))
    assert ok is True, "при сбое БД открываемся, а не теряем лида"


# 14 — рекламный текст распознаётся без обращения к базе вообще
def test_14_ad_prefill_needs_no_database():
    import database

    with patch.object(database, "get_db") as get_db:
        ok = asyncio.run(webhook_app._ad_originated_dialogue(
            "999", "Hello i would like to sign up for the summer promotion in Dubai"))
    assert ok is True
    assert not get_db.called, "рекламный префилл виден по тексту, запрос лишний"


# 15 — по умолчанию ночью агент отвечает ЛЮБОМУ новому, а не только рекламе
def test_15_night_answers_everyone_by_default(nighttime):
    """Ночь 19→20 августа: правило «только реклама» заглушило 7 из 9.

    Происхождение определялось по ТЕКСТУ префилла, а Instagram помечает
    «Ad Inquiry» и тех, кто стёр подставленный текст и написал своими
    словами. Среди заглушённых были «Price», «U charges» и женщина с
    фиброзом после липосакции, приславшая телефон. Пока нет настоящего
    признака рекламы, правило выключено — и это проверяется здесь.
    """
    assert webhook_app.config.IG_AD_LEADS_ONLY is False

    nighttime.setattr(webhook_app.config, "MANYCHAT_WEBHOOK_SECRET", "s3cret")
    nighttime.setattr(webhook_app.config, "MANYCHAT_API_KEY", "key")
    nighttime.setattr(webhook_app.config, "IG_BOOKING_ENABLED", True)
    nighttime.setattr(webhook_app.config, "IG_TEST_SUBSCRIBERS", "")
    nighttime.setattr(webhook_app.config, "IG_ASYNC_SEND", False)
    nighttime.setattr(webhook_app, "_human_led_dialogue", AsyncMock(return_value=False))

    routed = []

    async def fake_buffer(phone, text, sender_name):
        routed.append(phone)

    nighttime.setattr(webhook_app, "_buffer_and_process_wappi", fake_buffer)
    client = TestClient(webhook_app.app)
    body = client.post("/webhook/manychat", json={
        "secret": "s3cret", "subscriber_id": "887696381", "text": "Price"}).json()
    assert body.get("not_ad") is None, "лид с «Price» больше не глушится"
    assert "887696381" in str(routed)


# 16 — дневное молчание не должно выглядеть как «диалог ведёт админ»
def test_16_human_led_counts_only_inside_the_night_window():
    """К вечеру 20.08 набралось 47 контактов с висящим хвостом: днём агент
    молчит ПО ПРАВИЛУ, и это молчание гейт читал как работу живого админа.
    Их следующее ночное сообщение агент бы не увидел — включая рекламных
    лидов того же дня.

    Считать надо только внутри текущего окна, и сравнивать даты с зоной:
    NightEvent пишется по Абу-Даби (UTC+4), окно живёт по Минску (UTC+3).
    """
    from datetime import datetime, timedelta, timezone

    from agents.instagram_agent import ig_window_start

    minsk = timezone(timedelta(hours=3))
    uae = timezone(timedelta(hours=4))

    # Внутри окна (23:30 по Минску) старт — сегодняшние 21:00.
    ws = ig_window_start(datetime(2026, 8, 20, 23, 30, tzinfo=minsk))
    assert ws is not None and (ws.hour, ws.minute) == (21, 0)
    assert ws.day == 20

    # Под утро (06:00) мы всё ещё во ВЧЕРАШНЕМ окне.
    ws2 = ig_window_start(datetime(2026, 8, 21, 6, 0, tzinfo=minsk))
    assert ws2 is not None and ws2.day == 20 and ws2.hour == 21

    # Днём окна нет вовсе.
    assert ig_window_start(datetime(2026, 8, 20, 14, 0, tzinfo=minsk)) is None

    # Дневное сообщение (17:51 Минск = 18:51 Абу-Даби) осталось ЗА границей,
    # ночное (22:10 Минск = 23:10 Абу-Даби) — внутри. Разница зон в час не
    # должна путать сравнение.
    day_msg = datetime(2026, 8, 20, 18, 51, tzinfo=uae)
    night_msg = datetime(2026, 8, 20, 23, 10, tzinfo=uae)
    assert day_msg < ws, "дневное сообщение обязано отсекаться"
    assert night_msg >= ws, "ночное сообщение обязано учитываться"


# 17 — напоминание для Instagram: одно, через 5 минут, и НЕ днём
def test_17_instagram_nudge_routes_and_respects_the_window(daytime):
    """Татьяна 2026-08-25: «Напоминание тоже давайте пробовать делать. Если
    не отвечает — ещё раз спрашивать: интересуются ли они услугой и что есть
    свободные окошки», «давайте попробуем через 5 минут», «а потом я ещё раз
    по ним пройдусь».

    Это ОТМЕНЯЕТ прежнее «напоминания не делать» — но только внутри окна:
    днём тишина остаётся абсолютной, и напоминание тоже под неё попадает.
    """
    from services.follow_up import FOLLOW_UP_DELAYS
    from services.lost_client_messages import get_ig_nudge

    # Первое напоминание — ровно через 5 минут, как она попросила.
    assert FOLLOW_UP_DELAYS[0].total_seconds() == 300

    # Текст спрашивает про интерес и сообщает о свободных окнах.
    nudge = get_ig_nudge()
    assert "interested" in nudge.lower()
    assert "free slots" in nudge.lower()

    # Днём напоминание в Instagram НЕ уходит: маршрут идёт через
    # _send_to_client, а тот отказывает вне окна.
    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)) as send:
        ok = asyncio.run(webhook_app._send_to_client("ig:555", nudge))
    assert ok is False
    assert not send.called, "днём напоминание клиенту уходить не должно"


# 18 — ночью то же напоминание доставляется
def test_18_instagram_nudge_is_delivered_at_night(nighttime):
    from services.lost_client_messages import get_ig_nudge

    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)) as send:
        ok = asyncio.run(webhook_app._send_to_client("ig:555", get_ig_nudge()))
    assert ok is True
    assert send.called


# 19 — сквозной прогон напоминания: 5 минут, один раз, и не сжигается днём
def test_19_ig_nudge_fires_at_5_minutes_end_to_end(monkeypatch):
    """Аудит 2026-08-26 поймал три дефекта, которые юниты пропускали, потому
    что проверяли константы, а не живой цикл: (1) ворота «потеряшек» пускали
    IG-лида не раньше ЧАСА тишины — 5-минутная задержка Татьяны была мёртвым
    кодом; (2) лид с 1–2 сообщениями не проходил фильтр message_count>2
    вообще; (3) дневная попытка записывала count=1 и сжигала единственное
    напоминание без доставки. Этот тест гоняет НАСТОЯЩИЙ
    _check_inactive_clients с настоящим dialog_manager.
    """
    import asyncio
    from datetime import datetime, timedelta

    from dialog_context import dialog_manager
    from services.follow_up import FollowUpService

    uid = "ig_909090"
    dialog_manager.contexts.pop(uid, None)
    dialog_manager.add_user_message(uid, "Price")          # одно сообщение
    ctx = dialog_manager.get_or_create_context(uid)
    ctx.last_activity = datetime.now() - timedelta(minutes=6)

    sent = []

    async def recorder(user_id, text):
        sent.append((user_id, text))

    svc = FollowUpService(send_message=recorder)

    # Днём: не отправляем И НЕ СЖИГАЕМ — счётчик остаётся нулевым.
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: False)
    asyncio.run(svc._check_inactive_clients())
    assert sent == []
    assert svc.follow_up_state.get(uid, {}).get("count", 0) == 0, \
        "дневная попытка не имеет права сжечь единственное напоминание"

    # Ночью: одно напоминание через 5 минут, с текстом Татьяны.
    monkeypatch.setattr(instagram_agent, "ig_live_now", lambda now=None: True)
    asyncio.run(svc._check_inactive_clients())
    assert len(sent) == 1 and sent[0][0] == uid
    assert "interested" in sent[0][1].lower()
    assert svc.follow_up_state[uid]["count"] == 1

    # Второй цикл: повтора нет — ровно ОДНО («потом я ещё раз по ним пройдусь»).
    asyncio.run(svc._check_inactive_clients())
    assert len(sent) == 1

    dialog_manager.contexts.pop(uid, None)


# 20 — «I am interested» не значит «утром»
def test_20_i_am_is_not_a_morning_preference():
    """Аудит 2026-08-26: голое \\bam\\b в детекторе половины дня ловило
    английский глагол — «I am interested» молча ставило «утро», резало все
    вечерние окна из инъекции и навсегда снимало вопрос «morning or
    evening?». Клиент, начавший фразу с «I am…», больше никогда не видел
    вечерних времён.
    """
    from webhook_app import _detect_time_preference as d

    for phrase in ("I am interested in the offer", "Yes I am",
                   "Am I able to book tomorrow?", "I am at Villa 23",
                   "внутренний район города"):
        assert d(phrase) is None, phrase
    # Настоящие предпочтения работают по-прежнему.
    assert d("morning please") == "morning"
    assert d("evening") == "evening"
    assert d("утром удобнее") == "morning"
    assert d("вечером") == "evening"


# 21 — прод-тестировщик: тихий режим 770099xxx
def test_21_smoke_ids_run_the_pipeline_but_never_reach_manychat(nighttime):
    """Смоук-ID (770099xxx) проходят весь конвейер как тестеры, но их
    исходящие не уходят в ManyChat — только в ночной лог, откуда их читает
    scripts/prod_smoke.py. Неделя ручных проб кончалась send_failed-шумом
    на каждом прогоне.
    """
    from webhook_app import _is_ig_test_subscriber, _is_smoke_id

    assert _is_smoke_id("770099001") and _is_ig_test_subscriber("770099001")
    # Не смоук: реальные клиенты, короткие, длинные, нечисловые.
    for sid in ("868311272", "77009900", "7700990011", "77009900a", "997733588"):
        assert not _is_smoke_id(sid), sid

    # Отправка смоуку: событие «sent» есть, HTTP-вызова в ManyChat нет.
    webhook_app.NIGHT_LOG = None
    with patch("services.instagram_client.manychat_send_text",
               AsyncMock(return_value=True)) as send:
        ok = asyncio.run(webhook_app._send_to_client("ig:770099001", "smoke hello"))
    assert ok is True
    assert not send.called, "в ManyChat смоук-отправка уходить не должна"
    events = list(webhook_app.NIGHT_LOG or [])
    assert events and events[-1]["kind"] == "sent"
    assert events[-1]["text"] == "smoke hello"


# 22 — сброс не буферизуется и не склеивается со следующим сообщением
def test_22_reset_bypasses_the_buffer(monkeypatch):
    """Смоук 2026-08-30 (дважды): «/clear» и «Hi» слились в один ход
    «/clear\\nHi» — сброс не распознан, контекст не чищен, гейт карточек
    промолчал. Сброс обязан выполняться немедленно отдельным ходом, а
    фрагменты, накопленные до него, — выбрасываться.
    """
    processed = []

    async def recorder(phone, text, sender_name):
        processed.append(text)

    monkeypatch.setattr(webhook_app, "_process_wappi_message", recorder)

    async def run():
        # обычный фрагмент попадает в буфер (обработки сразу нет)
        await webhook_app._buffer_and_process_wappi("ig:770099099", "hello", None)
        assert processed == []
        # сброс: немедленно, отдельным ходом, буфер с «hello» выброшен
        await webhook_app._buffer_and_process_wappi("ig:770099099", "/clear", None)
        assert processed == ["/clear"]
        assert "ig:770099099" not in webhook_app._wappi_buffer

    asyncio.run(run())
