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
    # First live ad night (2026-08-18): three package leads were quoted
    # 1,550/1,650 and the cupping ad's own 275 offer never came up.
    from webhook_app import _enforce_package_offer_first

    bare = "Body massage package 5 sessions — 1,550 AED\nFace 5 — 1,650 AED"
    out = _enforce_package_offer_first(bare, "package")
    assert "275" in out and out.index("275") < out.index("1,550")
    # Already compliant / other campaigns / no package prices → untouched.
    good = "Our offer — 275 AED\n\nPackages: 1,550 AED"
    assert _enforce_package_offer_first(good, "package") == good
    assert _enforce_package_offer_first(bare, "consult") == bare
    assert _enforce_package_offer_first("60 min - 350 AED", "package") == "60 min - 350 AED"
