"""Payment terms are a money-facing promise, so the code guarantees them
rather than trusting the prompt.

Live-caught in the 2026-08-15 Instagram booking test: the brevity rules
stripped "(tax free)" / "(+5% VAT)" off the payment menu, the model's own
recap quoted a bare "350 AED" for a BANK TRANSFER booking, and the
confirmation then announced "368 AED" — the client agreed to one number and
was told another at the finish line.
"""

import types

from webhook_app import (
    _detect_payment_method,
    _enforce_payment_terms,
    _enforce_reply_wording,
)


def test_bare_menu_lines_regain_their_labels():
    menu = "How would you like to pay?\n💵 Cash\n🏦 Bank transfer"
    out = _enforce_payment_terms(menu, None)
    assert "💵 Cash (tax free)" in out
    assert "🏦 Bank transfer (+5% VAT)" in out


def test_menu_repair_is_idempotent():
    menu = "💵 Cash (tax free)\n🏦 Bank transfer (+5% VAT)"
    assert _enforce_payment_terms(menu, None) == menu


def test_recap_price_carries_the_chosen_method():
    # The exact reply the agent sent on 2026-08-15 before the confirm question.
    recap = "So — 60 min body massage, Saturday 22 August at 7:00 PM, 350 AED"
    out = _enforce_payment_terms(recap, "bank_transfer")
    assert "350 AED (bank transfer +5% VAT)" in out
    assert "368" not in out  # the base price, never the VAT arithmetic


def test_cash_gets_the_tax_free_footnote():
    out = _enforce_payment_terms("Total 350 AED", "cash")
    assert "350 AED (cash — tax free)" in out


def test_prices_quoted_before_the_choice_stay_clean():
    # Consult phase: the client hasn't picked a method, so a price list must
    # not sprout payment footnotes on every line.
    quote = "60 min - 350 AED\n90 min - 460 AED"
    assert _enforce_payment_terms(quote, None) == quote


def test_footnote_is_not_doubled():
    already = "350 AED (bank transfer +5% VAT)"
    assert _enforce_payment_terms(already, "bank_transfer") == already


def test_detects_the_method_in_both_languages():
    assert _detect_payment_method("Bank transfer, +971501234567") == "bank_transfer"
    assert _detect_payment_method("перевод") == "bank_transfer"
    assert _detect_payment_method("cash please") == "cash"
    assert _detect_payment_method("наличными") == "cash"
    assert _detect_payment_method("Saturday 7 PM works") is None


def test_instagram_asks_for_a_typed_address_not_a_pin():
    # A shared pin never reaches us through ManyChat, so the 📍 invitation only
    # earns the client a "type it as text" nudge.
    bc = types.SimpleNamespace(address=None, client_name="Dmitry")
    actions = types.SimpleNamespace(reschedule_call=None, booking_call=bc)
    out = _enforce_reply_wording("Booked ✅", actions, bc, {"name": "Dmitry"}, is_ig=True)
    assert "📍" not in out
    assert "type your address" in out.lower()


def test_whatsapp_keeps_the_location_pin():
    bc = types.SimpleNamespace(address=None, client_name="Dmitry")
    actions = types.SimpleNamespace(reschedule_call=None, booking_call=bc)
    out = _enforce_reply_wording("Booked ✅", actions, bc, {"name": "Dmitry"}, is_ig=False)
    assert "📍" in out


def test_confirmation_quotes_the_price_the_client_agreed_to():
    from agents.booking_agent import BookingAgent

    bc = types.SimpleNamespace(
        service="body_massage", date="2026-08-22", time="19:00",
        master_name="", base_price_aed=350, payment_method="bank_transfer",
    )
    actions = types.SimpleNamespace(
        reschedule_call=None, cancel_call=None, booking_call=bc)
    out = BookingAgent._synthesize_tool_reply(actions)
    assert "350 AED" in out
    assert "368" not in out
    assert "+5% VAT" in out


def test_requested_time_parser_ignores_numbers_that_are_not_times():
    from webhook_app import _detect_requested_time

    assert _detect_requested_time("22 August 19pm") == "19:00"
    assert _detect_requested_time("3pm") == "15:00"
    assert _detect_requested_time("5:30 PM") == "17:30"
    assert _detect_requested_time("19:00") == "19:00"
    assert _detect_requested_time("12am") == "00:00"
    # Not times: duration, price, a date, a phone number.
    assert _detect_requested_time("60 min") is None
    assert _detect_requested_time("350 AED") is None
    assert _detect_requested_time("22 August") is None
    assert _detect_requested_time("+971501234567") is None


def test_ad_prefill_is_recognised_per_creative():
    from webhook_app import _detect_ad_prefill

    assert _detect_ad_prefill(
        "Hello i would like to sign up for a massage package in Dubai at a discount"
    ) == "package"
    assert _detect_ad_prefill(
        "Hello i would like to sign up for the summer promotion in Al Ain"
    ) == "summer"
    assert _detect_ad_prefill(
        "I would like to consult on a massage and make an appointment in Abu Dhabi"
    ) == "consult"
    assert _detect_ad_prefill("hi, how much is a back massage?") is None


def test_unverified_package_prices_never_reach_the_prompt():
    # A real Instagram lead was quoted 3,000 / 2,590 on 2026-08-15 — figures no
    # admin has ever used and the client never confirmed.
    from prices import format_special_offers_for_prompt

    text = format_special_offers_for_prompt(include_packages=True)
    assert "1,550" in text and "1,650" in text      # the two the admins sell
    for banned in ("3,000", "2,590", "2,200"):
        assert banned not in text, f"{banned} must never reach the prompt"


def test_cleansing_prefill_is_recognised():
    # Tatyana 2026-08-16: this exact ad text is ALWAYS the deep-cleansing
    # creative — lead with 420/770 and keep the dialogue going.
    from webhook_app import _detect_ad_prefill

    assert _detect_ad_prefill(
        "Hello, I want to know the details about the promotion and get advice"
    ) == "cleansing"
    assert _detect_ad_prefill("what promotions do you have?") is None


def test_uae_phone_is_captured_in_any_format():
    # «0509952880» arrived mid-consult (live 2026-08-16) and the funnel
    # restarted instead of keeping it. Any UAE mobile spelling → +9715XXXXXXXX.
    from webhook_app import _detect_phone_in_text

    assert _detect_phone_in_text("0509952880") == "+971509952880"
    assert _detect_phone_in_text("+971 50 995 2880") == "+971509952880"
    assert _detect_phone_in_text("my number is 00971501234567") == "+971501234567"
    assert _detect_phone_in_text("Bank transfer, +971501234567") == "+971501234567"
    # Not phones: prices, durations, dates, short numbers.
    assert _detect_phone_in_text("350 AED") is None
    assert _detect_phone_in_text("60 min") is None
    assert _detect_phone_in_text("20 August") is None


def test_package_prefill_reply_always_carries_the_275_offer():
    # Ночь 2026-08-18: три баночных лида получили 1 550/1 650 без 275.
    # А владелица указала на вторую дыру: «он не видит банки, а предлагает
    # массаж за 350» — обычная цена тоже обязана тянуть за собой оффер.
    from webhook_app import _enforce_package_offer_first

    bare = "Body massage package 5 sessions — 1,550 AED\nFace 5 — 1,650 AED"
    out = _enforce_package_offer_first(bare, "package")
    assert "275" in out and out.index("275") < out.index("1,550")

    plain = "60 min - 350 AED\n90 min - 460 AED"
    assert "275" in _enforce_package_offer_first(plain, "package")
    # Прямой вопрос про банки — даже без префилла.
    assert "275" in _enforce_package_offer_first(
        plain, None, inbound_text="do you have cupping?")
    # Один раз за диалог, дальше не повторяем.
    assert _enforce_package_offer_first(
        plain, "package", already_shown=True) == plain
    # Уже содержит оффер / другая кампания / без цен — не трогаем.
    good = "Our offer — 275 AED\n\nPackages: 1,550 AED"
    assert _enforce_package_offer_first(good, "package") == good
    assert _enforce_package_offer_first(bare, "consult") == bare
    assert _enforce_package_offer_first("Body or facial dear?", "package") == "Body or facial dear?"


def test_package_prefill_never_asks_body_or_facial():
    # Живой тест 2026-08-19: на баночной рекламе агент спросил «Body massage or
    # facial dear?» — выбора нет, оффер 275 телесный, лицевых банок в каталоге
    # не существует. Клиент ответил датой и временем и получил тот же вопрос
    # второй раз: воронка встала.
    from webhook_app import _enforce_package_service_known

    reply = ("Lymphatic drainage + cupping + head massage — 275 AED, 45 min\n\n"
             "Body massage or facial dear? 😊")
    out = _enforce_package_service_known(reply, "package")
    assert "facial" not in out.lower()
    assert "275" in out                      # цена остаётся
    assert "which day" in out.lower()        # вместо выбора — следующий шаг
    # Второй ход: преамбула про выбор уходит целиком, не оставляя огрызка.
    stuck = ("24 Aug at 6:00 PM noted dear 🌹\n\n"
             "For massage, we just need to choose which one first 😊\n\n"
             "Body massage or facial dear?")
    out2 = _enforce_package_service_known(stuck, "package")
    assert "choose which one" not in out2.lower()
    assert "6:00 PM" in out2                 # уже названное время не теряем
    # ...и день переспрашивать нельзя: он назван. Слепая подстановка «which
    # day» гоняла клиента по кругу — реплей поймал это на ходах 2 и 3.
    assert "which day" not in out2.lower()
    assert "book it" in out2.lower()          # шаг вперёд, а не назад
    # Другая кампания и ответы без этого вопроса — не трогаем.
    assert _enforce_package_service_known(reply, "cleansing") == reply
    clean = "Which day would you like dear? 😊"
    assert _enforce_package_service_known(clean, "package") == clean


def test_package_next_step_follows_what_is_already_known():
    from webhook_app import _package_next_step_question as q

    assert "which day" in q("Our offer — 275 AED", {}).lower()
    assert "what time" in q("24 August is possible dear 🌹", {}).lower()
    assert "what time" in q("Our offer — 275 AED", {"date": "2026-08-24"}).lower()
    assert "book it" in q("24 August at 6:00 PM is possible 🌹", {}).lower()


def test_offer_275_always_carries_its_old_price():
    # Реклама обещает скидку; «275 AED» без «было 430» читается как обычный
    # прайс. Живой тест 2026-08-19: модель назвала оффер верно, но «было»
    # потеряла, и гейт 275 промолчал — цифра-то на месте.
    from webhook_app import _enforce_offer_was_price

    assert _enforce_offer_was_price("… — 275 AED, 45 min") == (
        "… — 275 AED instead of 430, 45 min")
    # Уже со старой ценой — не дублируем.
    good = "275 AED instead of 430, 45 min"
    assert _enforce_offer_was_price(good) == good
    # Подставляем один раз, даже если цена названа дважды.
    assert _enforce_offer_was_price("275 AED … total 275 AED").count("430") == 1
    # Оффера в ответе нет — молчим.
    assert _enforce_offer_was_price("60 min - 350 AED") == "60 min - 350 AED"


def test_cleansing_question_never_gets_the_facial_massage_price():
    # Живой случай 2026-08-18 03:50: «Deep Facial cleansing in Abu Dhabi?»
    # → «50 min - 370 AED» (цена лифтинг-массажа лица, другая услуга).
    from webhook_app import _enforce_cleansing_facts

    wrong = "50 min - 370 AED 🌹\n\nWhich day would you like dear?"
    out = _enforce_cleansing_facts(wrong, "Deep Facial cleansing in Abu Dhabi?")
    assert "420" in out and "120 min" in out
    assert "370" not in out
    # Уже верный ответ не трогаем.
    right = "Deep cleansing is 420 AED, 2 hours"
    assert _enforce_cleansing_facts(right, "cleansing?") == right
    # Вопрос не про чистку — не вмешиваемся.
    assert _enforce_cleansing_facts(wrong, "facial massage price?") == wrong
    # Русское «чистка» тоже ловится.
    assert "420" in _enforce_cleansing_facts(wrong, "сколько стоит чистка лица?")


def test_banned_price_never_reaches_a_client():
    # 3 000 / 2 590 / 2 200 — легаси-пакеты, которых нет в продаже; именно их
    # получил живой лид 2026-08-15.
    from webhook_app import _enforce_price_sanity

    bad = "Body massage package 10 x 60 min — 3,000 AED"
    out = _enforce_price_sanity(bad)
    assert "3,000" not in out and "3000" not in out
    assert "team will confirm" in out.lower()
    good = "60 min - 350 AED\n90 min - 460 AED"
    assert _enforce_price_sanity(good) == good
    # Сумма двух услуг незнакома каталогу, но это не ошибка — не режем.
    total = "Body + facial together — 720 AED"
    assert _enforce_price_sanity(total) == total


def test_summer_prefill_reply_always_carries_an_ad_offer():
    from webhook_app import _enforce_summer_offers

    drifted = "Manicure is 200 AED and pedicure is 220 AED"
    out = _enforce_summer_offers(drifted, "summer")
    assert "420" in out and "275" in out
    assert drifted in out
    ok = "Body massage 60 min — 350 AED instead of 500"
    assert _enforce_summer_offers(ok, "summer") == ok
    assert _enforce_summer_offers(drifted, "consult") == drifted
    assert _enforce_summer_offers("Which city dear?", "summer") == "Which city dear?"


def test_new_booking_keys_are_actually_saved():
    """Ключи, добавленные после первой версии словаря, обязаны сохраняться.

    update_booking_data игнорировал новые ключи (`if key in booking_data`),
    поэтому ad_prefill/offer_275_shown/payment_method не доживали до гейтов:
    ночью 2026-08-19 три баночных лида получили обычный прайс вместо оффера
    275, хотя юнит-тесты были зелёными — они зовут гейт напрямую и эту
    строку не проходят.
    """
    from dialog_context import DialogManager

    dm = DialogManager()
    uid = 4242
    for key, value in (("ad_prefill", "package"),
                       ("offer_275_shown", True),
                       ("payment_method", "bank_transfer"),
                       ("out_of_area", "sharjah")):
        dm.update_booking_data(uid, key, value)
        assert dm.get_or_create_context(uid).booking_data[key] == value, key
    # Существующие ключи по-прежнему обновляются.
    dm.update_booking_data(uid, "service_duration", 90)
    assert dm.get_or_create_context(uid).booking_data["service_duration"] == 90


def test_cupping_ad_client_may_still_switch_to_facial():
    """Автоподстановка комбо не должна запирать клиента на теле.

    Баночный префилл ставит service_type = комбо (иначе агент спрашивал
    «тело или лицо?» там, где выбора нет). Но клиент вправе передумать, а
    штатные детекторы этого не ловят: категория для «facial please» — общее
    «massage», а _is_massage_service комбо не признаёт. Без явного правила
    лицевой массаж считался бы по 275 AED за 45 минут вместо 370 за 50.
    """
    import webhook_app as wh

    # Предпосылки, из-за которых оба штатных апгрейда молчат.
    assert wh._is_massage_service(wh._COMBO_KEY) is False
    assert wh._detect_service_category("facial please") == "massage"
    assert wh._massage_kind_from_text("facial please") == "face"
    assert wh._massage_kind_from_text("body please") == "body"


def test_momentum_does_not_repeat_availability_the_model_already_offered():
    """Живой тест 2026-08-19: «We have available slots tomorrow in Dubai …
    We have free slots tomorrow 🌹» — одно и то же в одном сообщении.

    Гейт воронки умел молчать, когда названы времена или спрошен день, но не
    замечал, что модель уже пообещала доступность своими словами.
    """
    from webhook_app import _OFFERS_AVAILABILITY_RE as R

    for said in ("We have available slots tomorrow in Dubai",
                 "We have free slots today and tomorrow 🌹",
                 "Slots available tomorrow dear",
                 "We have availability for tomorrow",
                 "У нас есть свободные окна завтра"):
        assert R.search(said), said
    # Не путаем с обычным текстом, где доступности не обещали.
    for neutral in ("Facial massage is 370 AED dear 🌹",
                    "Which day would you like dear? 😊",
                    "Our discount offer is 275 AED instead of 430"):
        assert not R.search(neutral), neutral


def test_no_slots_reply_must_name_the_nearest_ones():
    """Живой тест 2026-08-19, 20:30: лид с платной рекламы в Аль-Айне получил
    «Today and tomorrow we don't have free slots 🙏 When would suit you dear?»

    Факт верный — у единственного мастера действительно два дня заняты, — но
    следующий шаг переложили на клиента. Ближайшее окно было в пятницу с
    13:30, и достать его — пять секунд.
    """
    import asyncio, types
    import webhook_app as wh

    # Распознаём заявление о занятости на обоих языках и в разных формах.
    for said in ("Today and tomorrow we don't have free slots in Al Ain 🙏",
                 # Апостроф у модели типографский — на нём гейт промахнулся.
                 "Today and tomorrow we don’t have free slots in Al Ain 🙏",
                 "We have no availability tomorrow",
                 "That day is fully booked dear",
                 "Сегодня нет свободных окон"):
        assert wh._CLAIMS_NO_SLOTS_RE.search(said), said
    # Живая проверка 20:40: модель сказала это третьим способом. Ловить
    # формулировки бесполезно — их бесконечно много, поэтому основной вход
    # у гейта структурный (открытый вопрос про день без конкретных времён),
    # а список фраз лишь дополняет его.
    assert wh._CLAIMS_NO_SLOTS_RE.search(
        "Today and tomorrow are already full in Al Ain 🙏")
    for neutral in ("Tomorrow we have 10:00 AM or 3:00 PM",
                    "Facial massage is 370 AED dear"):
        assert not wh._CLAIMS_NO_SLOTS_RE.search(neutral), neutral
    # Ответ, уже обещающий места, гейт не трогает — это работа momentum.
    assert wh._OFFERS_AVAILABILITY_RE.search("We have free slots tomorrow 🌹")
    # ...но ОТРИЦАНИЕ переворачивает смысл: «we don’t have free slots» тоже
    # содержит «free slots», и проверка, стоявшая раньше жалобы, глушила
    # гейт на ровном месте (третий провал живой проверки, 20:49).
    denial = "Today and tomorrow we don’t have free slots in Al Ain 🙏"
    assert wh._OFFERS_AVAILABILITY_RE.search(denial)
    assert wh._CLAIMS_NO_SLOTS_RE.search(denial), (
        "жалоба обязана распознаваться раньше, чем «места обещаны»")

    # Времена берутся с разбросом по дню, а не первые три подряд.
    summary = ("Eliza (Al Ain): 1:30 PM, 2:00 PM, 6:30 PM, 7:00 PM, "
               "7:30 PM, 8:00 PM, 8:30 PM, 9:00 PM")
    picked = wh._display_times_from_summary(summary)
    assert picked[0] == "1:30 PM" and picked[-1] == "9:00 PM"
    assert len(picked) == 3

    # Календарь недоступен → ответ не трогаем, ничего не выдумываем.
    ctx = types.SimpleNamespace(booking_data={}, client_data={})
    text = "We don't have free slots today dear 🙏"
    import bot as bot_module
    saved = getattr(bot_module, "yclients_service", None)

    class _Dead:
        async def get_available_slots_summary(self, **kw):
            raise RuntimeError("yclients down")

    bot_module.yclients_service = _Dead()
    try:
        out = asyncio.run(wh._offer_nearest_day_when_empty(text, ctx, "al_ain"))
    finally:
        bot_module.yclients_service = saved
    assert out == text

    # Конкретика уже названа — второй раз не дописываем.
    named = "Tomorrow is fully booked, but we have 5:00 PM on Friday"
    assert asyncio.run(
        wh._offer_nearest_day_when_empty(named, ctx, "al_ain")) == named
