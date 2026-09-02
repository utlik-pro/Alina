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

    # Дата берётся будущая: раньше здесь стояло «24 August», и 25.08 тест
    # начал падать сам — парсер справедливо не признаёт прошедший день.
    from datetime import datetime as _d, timedelta as _td, timezone as _tz
    _soon = _d.now(_tz(_td(hours=4))) + _td(days=3)
    _when = f"{_soon.day} {_soon:%B}"

    assert "which day" in q("Our offer — 275 AED", {}).lower()
    assert "what time" in q(f"{_when} is possible dear 🌹", {}).lower()
    assert "what time" in q("Our offer — 275 AED",
                            {"date": _soon.strftime("%Y-%m-%d")}).lower()
    assert "book it" in q(f"{_when} at 6:00 PM is possible 🌹", {}).lower()


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


def test_summer_prefill_reply_always_carries_the_cleansing_offer():
    """Татьяна 2026-08-27: «Чистку вновь не распознал». Креатив, идущий
    сейчас с summer-префиллом, — видео про чистку (420 вместо 770, бесплатный
    массаж лица и рук до конца месяца), а мы видим только подставленный
    текст. Поэтому summer-ответ с ценами ОБЯЗАН нести чистку — раньше гейт
    довольствовался любым из четырёх офферов, и клиентка с рекламы чистки
    получила общий список.
    """
    from webhook_app import _enforce_summer_offers

    drifted = "Manicure is 200 AED and pedicure is 220 AED"
    out = _enforce_summer_offers(drifted, "summer")
    assert "420" in out and "275" in out
    assert drifted in out
    # Другие офферы есть, чистки нет — она добавляется первой строкой.
    body_only = "Body massage 60 min — 350 AED instead of 500"
    out2 = _enforce_summer_offers(body_only, "summer")
    assert "420" in out2 and out2.index("420") < out2.index("350")
    # Подарочная строка убрана 31.08 по поправке Татьяны («вот что он
    # включает, а не массаж рук и лица»).
    assert "FREE facial massage" not in out2
    # Чистка уже названа — не трогаем.
    with_cl = "Deep facial cleansing — 420 AED instead of 770\nWhich one dear?"
    assert _enforce_summer_offers(with_cl, "summer") == with_cl
    assert _enforce_summer_offers(drifted, "consult") == drifted
    assert _enforce_summer_offers("Which city dear?", "summer") == "Which city dear?"


def test_phone_is_not_asked_twice_in_one_reply():
    """Живой диалог 2026-08-27 04:53: модель попросила «Please send your
    WhatsApp number dear» (новый бриф), а гейт добавил своё «May I have your
    number?» следом — номер спрошен дважды подряд в одном ответе.
    """
    import types

    from webhook_app import PHONE_FIRST_LINE, _enforce_phone_first

    ctx = types.SimpleNamespace(booking_data={}, client_data={"area": "abu_dhabi"})
    reply = ("Our offers: 420 AED instead of 770\n"
             "---MESSAGE_SPLIT---\n"
             "Please send your WhatsApp number dear")
    out = _enforce_phone_first(reply, ctx, phone_known=False, is_ig=True)
    assert PHONE_FIRST_LINE not in out          # эха нет
    assert "morning or evening" in out          # а половину дня спросить надо
    # «villa number» в запросе адреса — не просьба дать телефон.
    addr = "Price is 420 AED\nPlease type your area, building and villa number"
    out2 = _enforce_phone_first(addr, ctx, phone_known=False, is_ig=True)
    assert PHONE_FIRST_LINE in out2


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


def test_courses_boilerplate_becomes_a_selling_line():
    """«Courses are arranged personally by our team» — ответ на незаданный вопрос.

    Строка появилась, чтобы не называть курсовые цены (модель выдумывала
    пакеты по 3 000 и 2 590). Задачу решает, но клиенту читается как
    отговорка: он спрашивал про скидку, а ему объясняют порядок формирования
    курсов. Владелец 2026-08-24: «фраза не оч корректная, можно просто, что
    с нами работают top Russian».
    """
    from webhook_app import TOP_RUSSIAN_LINE, _enforce_courses_wording

    # Все формулировки, реально встреченные в ночных логах.
    for said in ("Courses are arranged personally by our team 🙌",
                 "For massage packages, the courses are arranged personally by the team",
                 "For courses, our team arranges them personally 💎",
                 "Courses are arranged personally by the team dear 🌹"):
        out = _enforce_courses_wording(f"275 AED instead of 430\n{said}\n\nWhich day dear?")
        assert "arranged personally" not in out.lower()
        assert "arranges them personally" not in out.lower()
        assert TOP_RUSSIAN_LINE in out
        assert "275 AED instead of 430" in out      # цена не теряется
        assert "Which day dear?" in out             # следующий шаг тоже

    # Продающая строка не дублируется, если уже есть.
    already = f"{TOP_RUSSIAN_LINE}\nCourses are arranged personally by the team"
    assert _enforce_courses_wording(already).count("top Russian") == 1

    # Обычные ответы не трогаем.
    clean = "60 min - 350 AED\n90 min - 460 AED\n\nWhich one dear?"
    assert _enforce_courses_wording(clean) == clean


def test_agent_never_sends_a_client_to_an_invented_account():
    """Ночь 2026-08-23: клиентка трижды спросила «а можно посмотреть на
    специалистов», и агент трижды отправил её на «@crystallab.beauty» —
    ника, которого нет ни в одной строке наших данных.

    Это дороже неверной цены: рекламный лид уходит на чужой аккаунт и не
    возвращается. Проверять цены и слоты оказалось мало — запрет ставится на
    КЛАСС: любая ссылка, ник или домен вне белого списка вырезается вместе с
    подводкой к ним.
    """
    from webhook_app import NO_LINK_FALLBACK, _enforce_no_invented_links

    # Точный текст из живого диалога.
    for said in ("I can send you the Instagram page\n@crystallab.beauty",
                 "You can see our team on Instagram\n@crystallab.beauty",
                 "Visit crystallab.beauty for photos",
                 "Check https://example.com/team dear",
                 "Follow us at www.crystal-lab.ae"):
        out = _enforce_no_invented_links(said, who="t")
        assert "crystallab" not in out.lower()
        assert "example.com" not in out.lower()
        assert "@" not in out

    # Полезная часть ответа переживает вырезание.
    out = _enforce_no_invented_links(
        "You can see our team on Instagram\n@crystallab.beauty\n\n"
        "What time suits you dear?", who="t")
    assert out == "What time suits you dear?"

    # Если вырезать нечего — ответ не трогаем.
    clean = "60 min - 350 AED\n90 min - 460 AED"
    assert _enforce_no_invented_links(clean) == clean
    ok = "Yes dear, all our specialists are certified Russian female therapists 🌹"
    assert _enforce_no_invented_links(ok) == ok

    # Ответ, состоявший ТОЛЬКО из ссылки, не уходит пустым.
    assert _enforce_no_invented_links("@crystallab.beauty") == NO_LINK_FALLBACK


def test_configured_contacts_are_still_allowed(monkeypatch):
    """Белый список работает: вписанный ник и наш wa.me проходят."""
    import webhook_app as wh

    monkeypatch.setattr(wh.config, "IG_PUBLIC_HANDLE", "crystal_lab_ae")
    monkeypatch.setattr(wh.config, "WHATSAPP_CTA_NUMBER", "971501234567")
    good = "Our page is @crystal_lab_ae dear 🌹"
    assert wh._enforce_no_invented_links(good) == good
    wa = "Write us here https://wa.me/971501234567?text=Hi"
    assert wh._enforce_no_invented_links(wa) == wa
    # А чужой — всё равно вырезается.
    assert "other_salon" not in wh._enforce_no_invented_links("See @other_salon").lower()


def test_phone_is_asked_right_after_the_price():
    """Татьяна 2026-08-25: «мы сразу просим номер, чтобы если они не ответят
    сразу — потом писали и писали им… берём номер и тут же спрашиваем какое
    время предпочтительно».

    Повод: 13 ночных заявок, из них утром админы не обработали ни одной —
    «но они не отвечали, увы». Номер делает молчащего лида возвратным.
    Раньше телефон спрашивали в самом конце, перед подтверждением.
    """
    import types

    from webhook_app import (PHONE_FIRST_LINE, TIME_PREF_LINE,
                             _enforce_phone_first)

    ctx = types.SimpleNamespace(booking_data={}, client_data={"area": "abu_dhabi"})
    priced = ("Lymphatic drainage + cupping + head massage — 275 AED instead of 430\n"
              "Today we have 10:00 AM, 2:30 PM or 7:00 PM")
    out = _enforce_phone_first(priced, ctx, phone_known=False, is_ig=True)
    assert PHONE_FIRST_LINE in out and TIME_PREF_LINE in out
    assert "275 AED" in out                     # цена остаётся
    assert "10:00 AM" not in out                # стена времён снимается:
    assert "7:00 PM" not in out                 # сначала половина дня

    # Половина дня уже известна — второй раз не спрашиваем, времена остаются.
    ctx2 = types.SimpleNamespace(
        booking_data={"time_preference": "evening"}, client_data={"area": "abu_dhabi"})
    out2 = _enforce_phone_first(priced, ctx2, phone_known=False, is_ig=True)
    assert PHONE_FIRST_LINE in out2 and TIME_PREF_LINE not in out2
    assert "7:00 PM" in out2

    # Гейт ЗАМЕНЯЕТ вопрос модели, а не добавляет свой: реплей 2026-08-25
    # показал, что два вопроса в одном сообщении клиент разруливает по
    # одному, и воронка встаёт.
    with_q = priced + "\n\nWhich day would you like dear? 😊"
    out_q = _enforce_phone_first(with_q, types.SimpleNamespace(
        booking_data={}, client_data={"area": "abu_dhabi"}), False, True)
    assert "which day" not in out_q.lower()
    assert PHONE_FIRST_LINE in out_q

    # Телефон уже есть, но половина дня ещё нет — спрашиваем только её.
    only_pref = types.SimpleNamespace(booking_data={}, client_data={"area": "dubai"})
    out3 = _enforce_phone_first(priced, only_pref, phone_known=True, is_ig=True)
    assert TIME_PREF_LINE in out3 and PHONE_FIRST_LINE not in out3

    # Оба уже спрошены, цены нет, не Instagram — молчим.
    done = types.SimpleNamespace(
        booking_data={"phone_asked": True, "pref_asked": True},
        client_data={"area": "abu_dhabi"})
    # Эмират неизвестен → только номер, без «утро или вечер?» (Татьяна
    # 01.09: после карточки идёт вопрос о городе, трёх вопросов не должно быть).
    no_area = types.SimpleNamespace(booking_data={}, client_data={})
    out_na = _enforce_phone_first(priced, no_area, phone_known=False, is_ig=True)
    assert PHONE_FIRST_LINE in out_na and TIME_PREF_LINE not in out_na
    assert _enforce_phone_first(priced, done, True, True) == priced
    assert _enforce_phone_first(priced, done, False, True) == priced
    no_price = "Body massage or facial dear? 😊"
    assert _enforce_phone_first(no_price, ctx, False, True) == no_price
    assert _enforce_phone_first(priced, ctx, False, False) == priced


def test_only_the_requested_half_of_the_day_is_offered():
    """Татьяна 2026-08-25: «Свободные окошки. Можете уточнить: утром/вечер?
    Какое время предпочтительно? Затем окошки и программы».

    Фильтруется ИНЪЕКЦИЯ, а не ответ — модель не может предложить того,
    чего не видит.
    """
    from webhook_app import (_detect_time_preference,
                            _filter_summary_by_preference)

    assert _detect_time_preference("morning please") == "morning"
    assert _detect_time_preference("вечером") == "evening"
    assert _detect_time_preference("утром удобнее") == "morning"
    # Конкретное время — это не половина дня, его разбирает другой детектор.
    assert _detect_time_preference("5 PM") is None
    assert _detect_time_preference("anytime") is None
    assert _detect_time_preference("morning or evening") is None

    summ = "Eliza (Al Ain): 10:00 AM, 11:30 AM, 1:00 PM, 6:30 PM, 8:00 PM"
    morning = _filter_summary_by_preference(summ, "morning")
    assert "10:00 AM" in morning and "8:00 PM" not in morning
    evening = _filter_summary_by_preference(summ, "evening")
    assert "6:30 PM" in evening and "10:00 AM" not in evening
    assert _filter_summary_by_preference(summ, None) == summ
    # Если в нужной половине пусто — честнее показать неудобное время,
    # чем сказать «мест нет».
    only_pm = "Eliza: 7:00 PM, 8:00 PM"
    assert _filter_summary_by_preference(only_pm, "morning") == only_pm


def test_bare_location_question_gets_the_home_service_answer():
    """Живая корректировка Татьяны 2026-08-26 21:36, первый вечер запуска.

    Клиент написал одно слово «Location» — вопрос «где вы находитесь», — а
    агент прочёл его как готовность диктовать адрес и спросил адрес клиента.
    Татьяна дописала руками: «Home service. Free transportation to your
    home». Полные формулировки модель понимает, голое слово — нет.
    """
    from webhook_app import HOME_SERVICE_LINE, _enforce_location_answer

    wrong = ("Please type your address dear\n"
             "Area, building and apartment number\n"
             "And your WhatsApp number please 🌹")
    # Точный текст клиента со скриншота.
    out = _enforce_location_answer(wrong, "Location")
    assert out.startswith(HOME_SERVICE_LINE)
    assert "type your address" in out          # воронка не теряется

    # Другие формы того же вопроса.
    for q in ("location?", "Where are you?", "where r u",
              "What's the location", "где вы находитесь?", "ваш адрес?"):
        assert _enforce_location_answer(wrong, q).startswith(HOME_SERVICE_LINE), q

    # Ответ, уже объясняющий формат, не трогаем (как дописала Татьяна).
    good = ("We come to your home, villa or hotel — free transportation 🌹\n"
            "Please type your address dear")
    assert _enforce_location_answer(good, "Location") == good

    # НЕ вопрос о локации: адрес клиента, время, обычные реплики.
    for msg in ("Khalifa City villa 3", "6 pm", "yes",
                "I am interested in the location near me"):
        assert _enforce_location_answer(wrong, msg) == wrong, msg


def test_first_contact_without_known_ad_asks_which_service():
    """Татьяна 2026-09-01 (скрин A❤️G, уточняет правило Алины от 30.08):
    «ИИ здесь совсем не знает что… надо спросить, как и было: лицо, тело или
    чистка. И дать ему оффер по тому, что он написал». На голое «Hi» — один
    вопрос; карточка — после выбора.
    """
    import types

    from webhook_app import _enforce_full_intro

    menu = ("Hi dear 🌹\nWelcome to Crystal Lab home service 🙌\n"
            "What services are you interested in? We will give you all the details 🌹")
    ctx = types.SimpleNamespace(booking_data={}, client_data={}, message_count=1)
    out = _enforce_full_intro(menu, ctx, "Hi")
    low = out.lower()
    assert "face massage" in low and "body massage" in low and "cleansing" in low
    assert "Abu Dhabi" in out and "Dubai" in out           # три эмирата
    assert "1650" not in out and "1550" not in out          # карточек ещё нет
    assert "What services are you interested in" not in out
    # Ход не важен; после отправки — не повторяем.
    late = types.SimpleNamespace(booking_data={}, client_data={}, message_count=5)
    assert "cleansing" in _enforce_full_intro(menu, late, "Hi").lower()
    sent = types.SimpleNamespace(booking_data={"cards_intro_sent": True},
                                 client_data={}, message_count=1)
    assert _enforce_full_intro(menu, sent, "Hi") == menu
    # Узнанная реклама, названная услуга, /clear — не трогаем.
    for bd, inbound in (({"ad_prefill": "package"}, "Hi"),
                        ({"service_type": "face_massage"}, "Hi"),
                        ({}, "/clear")):
        c = types.SimpleNamespace(booking_data=bd, client_data={}, message_count=1)
        assert _enforce_full_intro(menu, c, inbound) == menu, (bd, inbound)
    priced = "Face massage 50 min — 370 AED"
    assert _enforce_full_intro(priced, ctx, "Hi") == priced


def test_bare_day_corrects_the_known_month():
    """Живой случай M.a 2026-08-30: «Not in 10 omg», «I till you in 12» —
    агент проигнорировал поправку и дословно повторил ответ про 10-е.
    Число в конце короткой реплики при известном месяце — день ТОГО месяца.
    """
    from datetime import date

    from webhook_app import _bare_day_correction as bd

    today = date(2026, 8, 30)
    assert bd("I till you in 12", "2026-09-10", today) == "2026-09-12"
    assert bd("on the 12th", "2026-09-10", today) == "2026-09-12"
    assert bd("12", "2026-09-10", today) == "2026-09-12"
    # Прошедший день известного месяца перекатывается вперёд.
    assert bd("2", "2026-08-28", today) == "2026-09-02"
    # НЕ поправки: адреса, длительности, без известного месяца, длинные фразы.
    assert bd("villa 12 street 5", "2026-09-10", today) is None
    assert bd("Khalifa city 12", "2026-09-10", today) is None
    assert bd("in 12 minutes", "2026-09-10", today) is None
    assert bd("60", "2026-09-10", today) is None
    assert bd("12", None, today) is None


def test_new_face_prefills_resolve_service_and_area():
    """Татьяна 2026-08-30: новые связки на лицо. «Но думаю он и без
    настройки должен понять, что это лицо 370» — понимает, и закрепляем.
    """
    from webhook_app import _detect_ad_prefill, _massage_kind_from_text, detect_area

    for txt, area in (
            ("Hello, I would like to consult you about a facial massage in Al Ain",
             "al_ain"),
            ("Hello, I would like to consult you about a facial massage in Abu Dhabi",
             "abu_dhabi")):
        assert _detect_ad_prefill(txt) == "consult"
        assert detect_area(txt) == area
        assert _massage_kind_from_text(txt) == "face"


def test_no_times_ever_leave_without_a_known_emirate():
    """Алина 2026-08-30: «Мы не можем предлагать время не зная эмират».
    Правило уже стояло — закрепляем: пустая правда без области переписывает
    времена в вопрос о городе.
    """
    import types

    from webhook_app import _enforce_slot_reality

    ctx = types.SimpleNamespace(slot_truth={}, booking_data={}, client_data={})
    out = _enforce_slot_reality(
        "Tomorrow we have 2:00 PM, 4:30 PM or 6:00 PM 🌹", ctx, None)
    assert "2:00 PM" not in out
    assert "Abu Dhabi" in out and "Dubai" in out


def test_home_service_line_always_names_all_three_emirates():
    """Татьяна 2026-08-30, скрин ночного диалога: «иногда кликают Абу Даби,
    а в итоге хотят Дубай — и эта фраза может слить». Строка о зоне
    обслуживания обязана называть все три города; эмират из рекламы остаётся
    рабочим предположением для слотов, вопрос города не задаётся.
    """
    from webhook_app import ALL_EMIRATES, _enforce_all_emirates_line as g

    # Точная фраза из живого диалога 30.08 21:16.
    live = ("Yes dear 🌹 We do home service in Al Ain with certified "
            "Russian female specialists and free transportation")
    out = g(live)
    assert ALL_EMIRATES in out and "in Al Ain with" not in out

    for single in ("We do home service in Abu Dhabi 🌹",
                   "home service in Dubai with free transportation"):
        assert ALL_EMIRATES in g(single), single

    # НЕ трогаем: полное перечисление, адрес в известном эмирате, «к вам домой
    # в …» после того, как клиент сам назвал город.
    for keep in (f"We do home service in {ALL_EMIRATES} 🌹",
                 "Please type your address in Abu Dhabi\nArea, building or villa",
                 "We come to your home, hotel or villa in Dubai dear 🌹"):
        assert g(keep) == keep, keep


def test_misspelled_time_question_is_not_answered_with_prices():
    """Um Nasser, 2026-08-30 23:18: «what tame» — арабки пишут по-английски
    неидеально (Татьяна), а агент трижды повторил прайс вместо ответа о
    времени. Опечатки слова time ловятся по схожести, и вопрос «когда?»
    не может быть отвечен прайсом.
    """
    import types

    from webhook_app import _asks_about_time, _enforce_time_ask_answered

    for q in ("what tame", "what tiem", "what time", "when?", "когда можно?"):
        assert _asks_about_time(q), q
    for other in ("yes", "cash", "body massage", "Khalifa City villa 3"):
        assert not _asks_about_time(other), other

    prices = "Body 350 AED / 60 min, 460 AED / 90 min\nFacial 370 AED / 50 min"
    # Услуга не выбрана → честно: времена зависят от услуги.
    ctx = types.SimpleNamespace(booking_data={"service_type": "massage"},
                                client_data={"area": "abu_dhabi"})
    out = _enforce_time_ask_answered(prices, "what tame", ctx)
    assert "AED" not in out and "Body massage or facial" in out
    # Эмират неизвестен → вопрос города.
    ctx2 = types.SimpleNamespace(booking_data={}, client_data={})
    out2 = _enforce_time_ask_answered(prices, "what tame", ctx2)
    assert "Abu Dhabi" in out2 and "AED" not in out2
    # Всё известно → прайс не режем, дописываем вопрос про день.
    ctx3 = types.SimpleNamespace(booking_data={"service_type": "body_massage"},
                                 client_data={"area": "abu_dhabi"})
    out3 = _enforce_time_ask_answered(prices, "what tame", ctx3)
    assert "Which day suits you" in out3 and "350 AED" in out3
    # Ответ уже о времени — не трогаем.
    timed = "Tomorrow we have 2:00 PM or 5:30 PM 🌹"
    assert _enforce_time_ask_answered(timed, "what tame", ctx) == timed
    # Вопрос не о времени — не трогаем.
    assert _enforce_time_ask_answered(prices, "how much", ctx) == prices


def test_chosen_service_gets_its_full_admin_card():
    """Татьяна 2026-09-01: «дать ему оффер по тому, что он написал, тем
    ответом, который тут уже есть». Карточка — по ВЫБРАННОЙ услуге, включая
    чистку. Ответ-сравнение «лицо или тело?» не трогается (ночь 01.09 22:25:
    гейт заменил сравнение на карточку лица и потерял тело).
    """
    import types

    from webhook_app import _enforce_admin_service_card as g

    # Клиент сказал «face» → карточка лица + вопрос об эмирате (он неизвестен).
    ctx = types.SimpleNamespace(booking_data={}, client_data={})
    out = g("Facial massage 🌹 50 min - 370 AED", ctx, "face")
    assert "1650" in out and "buccal" in out.lower()
    assert "Which emirate" in out
    assert g("Facial massage 370 AED", ctx, "face") == "Facial massage 370 AED"  # один раз

    # «body» → карточка тела; эмират известен → без вопроса о городе.
    body = types.SimpleNamespace(booking_data={"service_type": "body_massage"},
                                 client_data={"area": "abu_dhabi"})
    out2 = g("Body 350 AED / 60 min", body, "body")
    assert "1550" in out2 and "Guasha" in out2 and "Which emirate" not in out2

    # «cleansing» → карточка чистки с восемью этапами.
    cl = types.SimpleNamespace(booking_data={}, client_data={"area": "dubai"})
    out3 = g("Deep facial cleansing 120 min — 420 AED", cl, "deep cleansing")
    assert "Deep manual cleansing" in out3 and "770" in out3

    # Сравнение двух услуг без выбора — НЕ трогаем.
    cmp_ctx = types.SimpleNamespace(booking_data={"service_type": "massage"},
                                    client_data={"area": "al_ain"})
    cmp = "Body 350 AED / 60 min\nFacial 370 AED / 50 min\n\nBody massage or facial dear?"
    assert g(cmp, cmp_ctx, "Hello") == cmp

    # Баночный префилл и комбо — не трогаем.
    pkg = types.SimpleNamespace(booking_data={"ad_prefill": "package"}, client_data={})
    assert g("Facial massage 370 AED", pkg, "face") == "Facial massage 370 AED"


def test_cleansing_description_is_the_admins_eight_steps():
    """Татьяна 2026-08-31: «вот что он включает, а не массаж рук и лица».
    Канон — восемь этапов; строка про бесплатные массажи из креатива убрана;
    шаг 5 (deep MANUAL cleansing) отвечает на вопрос про механическую чистку.
    """
    from prices import ADMIN_CARD_CLEANSING, SPECIAL_OFFERS

    desc = SPECIAL_OFFERS["offer_deep_cleansing"]["description"]
    assert "MANUAL" in desc and "ultrasonic" in desc
    assert "FREE" not in desc                      # подарки убраны
    assert "Deep manual cleansing" in ADMIN_CARD_CLEANSING
    assert "770" in ADMIN_CARD_CLEANSING and "420" in ADMIN_CARD_CLEANSING
    assert "free facial massage" not in ADMIN_CARD_CLEANSING.lower()


def test_first_mentioned_massage_kind_wins_and_card_keeps_the_funnel():
    """Ajmsrrk 2026-09-02 22:20 (владелец: «номер она дала уже, а мы "hello"
    опять»): на «Body massage, if I like it I will do facial too» ушла
    карточка ЛИЦА с приветствием «Hello 👋» посреди диалога — старое правило
    «лицо всегда побеждает» + карточка, стирающая следующий шаг воронки.
    """
    import types

    from webhook_app import _enforce_admin_service_card as g
    from webhook_app import _massage_kind_from_text as kind

    assert kind("Body massage if I like it I will do facial too") == "body"
    assert kind("facial with body oils") == "face"
    assert kind("facial please") == "face"
    assert kind("body") == "body"

    mid = types.SimpleNamespace(
        booking_data={}, client_data={"area": "abu_dhabi"},
        recent_messages=[{"role": "assistant", "content": "Got it dear 🌹"}])
    out = g("Body massage 60 min — 350 AED\nMay I have your address dear?",
            mid, "Body massage if I like it I will do facial too")
    assert "1550" in out and "1650" not in out          # карточка ТЕЛА
    assert not out.lstrip().startswith("Hello")         # без повторного привета
    assert "address" in out.lower()                     # шаг воронки сохранён

    # Первый ход — приветствие в карточке остаётся (оно есть только у
    # карточки лица: у Алины так написано).
    first = types.SimpleNamespace(booking_data={}, client_data={"area": "dubai"},
                                  recent_messages=[])
    assert g("Facial 370 AED", first, "face").lstrip().startswith("Hello")


def test_nearest_day_offer_pins_the_dialogue_date():
    """Amoon 2026-09-02 22:21 (Аль-Айн): агент предложил пятницу («The
    nearest we have is Friday 4 Sep: 10:00 AM, 5:30 PM or 9:00 PM»), она
    выбрала «5:30» — а рекап сказал «tomorrow at 5:30 PM»: четверг, выходной
    Элизы. Предложенный день обязан лечь в booking_data.date.
    """
    import asyncio
    import types

    import bot as bot_module
    import webhook_app as wh

    class _YC:
        async def get_available_slots_summary(self, date=None, **kw):
            if date.endswith("-04"):
                return "Eliza (Al Ain): 10:00 AM, 5:30 PM, 9:00 PM"
            return "No slots available for this date from the schedule."

    saved = getattr(bot_module, "yclients_service", None)
    bot_module.yclients_service = _YC()
    try:
        ctx = types.SimpleNamespace(booking_data={"service_type": "face_massage"},
                                    client_data={"area": "al_ain"})
        out = asyncio.run(wh._offer_nearest_day_when_empty(
            "Today and tomorrow are fully booked 🙏\nWhich day would suit you?",
            ctx, "al_ain"))
    finally:
        bot_module.yclients_service = saved
    assert "5:30 PM" in out
    assert ctx.booking_data.get("date", "").endswith("-04"), \
        "день из предложения обязан стать датой диалога"
