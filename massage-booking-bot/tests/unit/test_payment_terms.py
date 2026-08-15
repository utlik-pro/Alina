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
