"""No time reaches a client unless YClients actually has it free.

Live-caught 2026-08-15 (prefill audit, Al Ain): the injected block for
20 August said "No slots available… do NOT invent times" and the model still
offered four times for that day. The gate judges the OUTGOING text against
the per-turn ground truth and rewrites an invented offer into the honest one.
"""

import types

from webhook_app import _enforce_slot_reality, _times_from_summary


def _ctx(truth, sticky_date=None):
    ctx = types.SimpleNamespace(booking_data={}, client_data={})
    ctx.slot_truth = truth
    if sticky_date:
        ctx.booking_data["date"] = sticky_date
    return ctx


def test_invented_times_for_an_empty_day_become_the_honest_answer():
    # The exact Al Ain shape: chosen day empty, another day genuinely open.
    ctx = _ctx({"2026-08-20": set(), "2026-08-21": {"13:30", "14:00"}},
               sticky_date="2026-08-20")
    out = _enforce_slot_reality(
        "For Thursday 20 August we have 10:00 AM, 12:00 PM, 3:00 PM or 5:00 PM",
        ctx, None)
    assert "10:00 AM" not in out.split("nearest")[0]
    assert "fully booked" in out
    assert "21 August" in out and "1:30 PM" in out  # the real alternative


def test_a_partly_invented_list_is_rewritten_to_the_real_times():
    ctx = _ctx({"2026-08-20": {"15:00", "19:00"}}, sticky_date="2026-08-20")
    out = _enforce_slot_reality(
        "We have 3:00 PM, 5:30 PM or 7:00 PM", ctx, None)
    assert "5:30 PM" not in out
    assert "3:00 PM" in out and "7:00 PM" in out


def test_a_truthful_offer_passes_untouched():
    ctx = _ctx({"2026-08-20": {"15:00", "17:30", "19:00"}},
               sticky_date="2026-08-20")
    text = "On Thursday we have 3:00 PM, 5:30 PM or 7:00 PM 🌹"
    assert _enforce_slot_reality(text, ctx, None) == text


def test_outage_judges_nothing():
    # "Temporarily unavailable" must never be read as "the day is empty".
    ctx = _ctx({"2026-08-20": None}, sticky_date="2026-08-20")
    text = "We have 3:00 PM or 5:30 PM"
    assert _enforce_slot_reality(text, ctx, None) == text
    assert _times_from_summary("SCHEDULE TEMPORARILY UNAVAILABLE (YClients…)") is None


def test_no_date_context_judges_against_the_union_of_days():
    ctx = _ctx({"2026-08-15": set(), "2026-08-16": {"10:00", "14:00"}})
    # 10:00 AM exists tomorrow — legitimate; 12:00 PM exists nowhere — ghost.
    out = _enforce_slot_reality("Today we have 10:00 AM or 12:00 PM", ctx, None)
    assert "12:00 PM" not in out
    ok = _enforce_slot_reality("Tomorrow we have 10:00 AM or 2:00 PM", ctx, None)
    assert ok == "Tomorrow we have 10:00 AM or 2:00 PM"


def test_reply_without_times_is_never_touched():
    ctx = _ctx({"2026-08-20": set()}, sticky_date="2026-08-20")
    text = "Please type your address dear 🌹"
    assert _enforce_slot_reality(text, ctx, None) == text


def test_booking_call_date_wins_over_sticky():
    bc = types.SimpleNamespace(date="2026-08-21")
    ctx = _ctx({"2026-08-20": set(), "2026-08-21": {"15:00"}},
               sticky_date="2026-08-20")
    text = "Confirmed for 3:00 PM 🌹"
    assert _enforce_slot_reality(text, ctx, bc) == text


def test_kind_upgrade_releases_the_gate_without_losing_duration():
    # The root cause of the eternal body-or-face gate: the category detector
    # only knows generic 'massage', so the client's own "body massage" answer
    # must upgrade the type (and must NOT reset the chosen duration — it is
    # the same category, not a switch).
    from webhook_app import _massage_kind_from_text, _massage_kind_known

    assert _massage_kind_from_text("body massage") == "body"
    assert _massage_kind_from_text("массаж тела") == "body"
    assert _massage_kind_from_text("facial please") == "face"
    assert _massage_kind_from_text("facial with body oils") == "face"  # face wins
    assert _massage_kind_from_text("massage") is None
    assert _massage_kind_known("body_massage") and _massage_kind_known("face_massage")
    assert not _massage_kind_known("massage")


def test_combo_choice_is_detected_and_fixes_the_duration():
    # Live-caught 2026-08-16 02:48: "I like the special offer / Cupping" was
    # answered with "60 or 90 min dear?" — a nonsense question for a fixed
    # 30+15+15 session — and the lead walked away.
    from webhook_app import _detect_combo_choice, _is_massage_service, _COMBO_KEY
    from prices import SPECIAL_OFFERS

    for phrase in ("I like the special offer", "Cupping", "and cupping",
                   "хочу банки", "the 275 one", "hijama"):
        assert _detect_combo_choice(phrase), phrase
    for phrase in ("body massage", "60 min", "facial please", "how much?"):
        assert not _detect_combo_choice(phrase), phrase
    # The combo key must slip past BOTH massage gates (kind and duration ask).
    assert not _is_massage_service(_COMBO_KEY)
    # 45 per Tatyana 2026-08-16: the parts are 30+15+15 but her total
    # is 45 and it wins (the ad creative says 45 too).
    assert SPECIAL_OFFERS[_COMBO_KEY]["duration"] == 45


def test_times_with_no_truth_and_no_area_become_the_city_question():
    # Cleansing prefill carries no emirate; the client answered "20 August"
    # to the city question and got four invented times for an empty day.
    ctx = types.SimpleNamespace(booking_data={}, client_data={})
    ctx.slot_truth = {}
    out = _enforce_slot_reality(
        "On Thursday 20 August we have 10:00 AM, 1:00 PM, 4:00 PM or 7:00 PM",
        ctx, None)
    assert "Abu Dhabi, Al Ain or Dubai" in out
    assert "10:00 AM" not in out
    # With a KNOWN area and empty truth the reply passes (other gates own it).
    ctx2 = types.SimpleNamespace(booking_data={}, client_data={"area": "dubai"})
    ctx2.slot_truth = {}
    text = "Tomorrow we have 3:00 PM 🌹"
    assert _enforce_slot_reality(text, ctx2, None) == text


def test_spaced_ordinal_dates_are_parsed():
    # «23 rd» с телефона — клиент так и написал (2026-08-18), а слитный
    # шаблон это пропускал: календарь нужного дня не загружался вовсе.
    from datetime import datetime
    from webhook_app import _detect_explicit_date

    now = datetime(2026, 8, 18, 12, 0)
    assert _detect_explicit_date("23 rd", now) == "2026-08-23"
    assert _detect_explicit_date("23rd", now) == "2026-08-23"
    assert _detect_explicit_date("sunday 23rd at 6:00 pm", now) == "2026-08-23"
    assert _detect_explicit_date("1 st of september", now) == "2026-09-01"
    # Адрес — не дата.
    assert _detect_explicit_date("gate tower, 21 st floor", now) is None


def test_busy_time_in_a_reply_is_rewritten(monkeypatch):
    # Живой провал: агент подтвердил «Sunday 23rd at 6:00 PM», когда у мастера
    # на 18:00 уже стоял 90-минутный визит.
    import asyncio
    import types as _t
    import webhook_app as wh

    class _YC:
        async def is_slot_available(self, area, date, hhmm, dur):
            return hhmm != "18:00"          # 18:00 занято, остальное свободно
        async def get_available_slots_summary(self, **kw):
            return "Available:\nEliza (Al Ain): 10:00 AM, 11:00 AM"

    import bot as bot_module
    monkeypatch.setattr(bot_module, "yclients_service", _YC(), raising=False)

    ctx = _t.SimpleNamespace(booking_data={"service_duration": 50}, client_data={})
    ctx.slot_truth = {}
    out = asyncio.run(wh._verify_reply_times_against_calendar(
        "Sunday 23rd at 6:00 PM is fine\n\nPlease type your address",
        ctx, "al_ain", who="test"))
    assert "6:00 PM" not in out
    assert "10:00 AM" in out                # предложены реальные окна


def test_typos_in_body_or_face_still_release_the_gate():
    # «Faicial» (живой клиент 2026-08-18) не распознавался, из-за чего слоты
    # не грузились вовсе и агент назвал занятые времена. Модель опечатку
    # понимает — код обязан тоже.
    from webhook_app import _massage_kind_from_text

    for w in ("Facial", "Faicial", "facal", "fasial", "фейшл"):
        assert _massage_kind_from_text(w) == "face", w
    for w in ("body", "bodu", "bosy", "массаж тела"):
        assert _massage_kind_from_text(w) == "body", w
    # Ложных срабатываний быть не должно.
    for w in ("booking", "buy", "package", "cleansing", "how much?"):
        assert _massage_kind_from_text(w) is None, w


def test_human_led_dialogue_detection(monkeypatch):
    """Правило владельца: главный — админ. Признак — хвост сообщений клиента
    после нашего последнего ответа, разнесённый по времени (мы отвечаем за
    ~25 сек и молчать между его репликами не можем)."""
    import asyncio
    import types as _t
    import webhook_app as wh

    class _Row:
        def __init__(self, kind, ts):
            self.kind, self.ts, self.who = kind, ts, "ig:777"

    def _db_with(rows):
        class _Res:
            def scalars(self):
                return _t.SimpleNamespace(all=lambda: rows)
        class _DB:
            async def execute(self, *a, **kw):
                return _Res()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
        return _t.SimpleNamespace(session=lambda: _DB())

    import database

    def _set(rows):
        monkeypatch.setattr(database, "get_db", lambda: _db_with(rows), raising=False)

    T = "2026-08-18T22:%02d:00+04:00"
    # Клиент написал дважды с разрывом 4 минуты, мы молчали -> ведёт человек.
    _set([_Row("inbound", T % 10), _Row("inbound", T % 6), _Row("sent", T % 1)])
    assert asyncio.run(wh._human_led_dialogue("777")) is True

    # Быстрая пара сообщений — это НЕ админ, агент ещё отвечает.
    _set([_Row("inbound", T % 10), _Row("inbound", T % 10), _Row("sent", T % 1)])
    assert asyncio.run(wh._human_led_dialogue("777")) is False

    # Мы ответили последними -> диалог наш.
    _set([_Row("sent", T % 12), _Row("inbound", T % 10), _Row("inbound", T % 5)])
    assert asyncio.run(wh._human_led_dialogue("777")) is False

    # Одно сообщение клиента — обычное начало, отвечаем.
    _set([_Row("inbound", T % 10)])
    assert asyncio.run(wh._human_led_dialogue("777")) is False

    # Наш сбой отправки — поломка, а не админ: хвост обрывается на нём.
    _set([_Row("inbound", T % 10), _Row("send_failed", T % 9), _Row("inbound", T % 5)])
    assert asyncio.run(wh._human_led_dialogue("777")) is False
