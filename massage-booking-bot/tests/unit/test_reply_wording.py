"""The LLM is not reliable about two client-facing wordings, so the code
guarantees them: never say a reschedule is "confirmed", and never leave a false
"confirmed" when a booking is attempted without a location/name."""

import types

from webhook_app import _enforce_reply_wording, _booking_has_location_and_name


def _bc(address=None, client_name=None):
    return types.SimpleNamespace(address=address, client_name=client_name)


def _actions(reschedule=None):
    return types.SimpleNamespace(reschedule_call=reschedule, booking_call=None)


def test_reschedule_never_says_confirmed():
    # The turn's reply is a NEUTRAL holding line — never "confirmed/booked", and
    # never a premature "passed to the team" (that definitive outcome is sent by
    # _handle_reschedule AFTER the availability re-check, so an occupied slot
    # can't get "passed ✅" contradicted by a later "not free" — 2026-07-15 bug).
    rc = types.SimpleNamespace(new_time="16:30")
    out = _enforce_reply_wording("Your booking is confirmed ✅", _actions(reschedule=rc), None, {})
    low = out.lower()
    assert "4:30 pm" in low                      # 24h → AM/PM, echoes the new time
    assert "confirmed" not in low and "booked" not in low
    assert "passed" not in low                   # no premature "passed to the team"
    assert "moment" in low or "check" in low     # neutral holding line


def test_booking_without_location_is_replaced_with_ask():
    bc = _bc(address=None, client_name="Sara")   # name ok, no location
    out = _enforce_reply_wording("Your massage is booked ✅", _actions(), bc, {"name": "Sara"})
    assert "location" in out.lower()
    assert "booked" not in out.lower() and "confirmed" not in out.lower()


def test_booking_without_name_is_replaced_with_ask():
    bc = _bc(address="Khalifa City villa 3", client_name=None)  # location ok, no name
    out = _enforce_reply_wording("Booked ✅", _actions(), bc, {})
    assert "name" in out.lower()


def test_booking_confirmed_by_client_is_left_unchanged():
    bc = _bc(address="Khalifa City villa 3", client_name="Sara")
    original = "Your body massage is booked on Tuesday at 5:00 PM ✅"
    # The client explicitly said yes → the model's confirmation passes through.
    out = _enforce_reply_wording(original, _actions(), bc, {}, user_text="yes please confirm")
    assert out == original


def test_booking_without_explicit_confirm_becomes_recap_question():
    """ТЗ: …→ payment → explicit CONFIRM. If the model books straight off the
    payment answer ("cash"), the reply must become the recap question instead
    of a premature "booked ✅" (live 2026-07-10 catch)."""
    bc = types.SimpleNamespace(
        address="Khalifa City villa 3", client_name="Sara",
        service="body_massage", duration_minutes=90, date="2030-01-06",
        time="10:00", payment_method="cash", base_price_aed=460,
        master_name="Natalia",
    )
    out = _enforce_reply_wording(
        "Your body massage is booked ✅", _actions(), bc, {}, user_text="cash")
    assert "Shall I confirm?" in out
    assert "booked" not in out.lower()
    # Recap carries the agreed details.
    assert "90-min" in out and "Natalia" in out and "460 AED" in out


def test_client_confirmed_detector():
    from webhook_app import _client_confirmed
    for yes in ("yes", "Yes, confirm", "ok", "давай", "подтверждаю", "book it",
                "👍", "+", "sure, go ahead", "да, записывайте"):
        assert _client_confirmed(yes), yes
    for no in ("cash", "bank transfer", "Sarah", "Al Reem Island villa 3",
               "10:00 AM", "what about tomorrow?", ""):
        assert not _client_confirmed(no), no


def test_gps_in_context_counts_as_location():
    bc = _bc(address=None, client_name="Sara")
    has_loc, has_name = _booking_has_location_and_name(bc, {"location": {"lat": 24.4, "lng": 54.3}, "name": "Sara"})
    assert has_loc and has_name


def test_placeholder_name_does_not_count():
    bc = _bc(address="villa 1", client_name="WhatsApp Client")
    _, has_name = _booking_has_location_and_name(bc, {})
    assert has_name is False


def test_no_action_returns_original():
    out = _enforce_reply_wording("hello dear 🌹", _actions(), None, {})
    assert out == "hello dear 🌹"


def test_recap_omits_placeholder_master_and_uses_friendly_name():
    import types
    from agents.booking_agent import BookingAgent
    bc = types.SimpleNamespace(service="combo_mani_pedi", duration_minutes=180,
                               date="2026-07-09", time="16:00", master_name="",
                               base_price_aed=380, payment_method="cash")
    out = BookingAgent._synthesize_tool_reply(
        types.SimpleNamespace(booking_call=bc, cancel_call=None, reschedule_call=None))
    assert "combo mani + pedi" in out          # friendly, not "180-min Nails"
    assert "your therapist" not in out.lower()  # no placeholder
    assert "booked ✅" in out


def test_dedupe_collapses_stutter():
    from agents.booking_agent import BookingAgent
    dup = "Tomorrow 5 PM with Makhabat 🌹\n\nTomorrow 5 PM with Makhabat 🌹"
    assert BookingAgent._dedupe_blocks(dup) == "Tomorrow 5 PM with Makhabat 🌹"


def test_wrong_day_mismatch_none_when_no_day_word():
    import types
    from webhook_app import _booking_day_mismatch
    bc = types.SimpleNamespace(date="2026-07-09", time="17:00")
    assert _booking_day_mismatch("book me at 5pm", bc) is None  # no tomorrow/today word


def test_match_booking_by_old_slot():
    """Reschedule/cancel selector: the client's named old slot must pick the
    right booking among several (the 'which one → loop' live catch)."""
    from datetime import datetime
    from webhook_app import _match_booking_by_old_slot

    b1 = {"booking_id": 1, "booking_date": datetime(2030, 1, 6, 10, 0)}
    b2 = {"booking_id": 2, "booking_date": datetime(2030, 1, 6, 17, 30)}
    b3 = {"booking_id": 3, "booking_date": datetime(2030, 1, 7, 17, 30)}

    # Unique time picks it.
    assert _match_booking_by_old_slot([b1, b2], None, "17:30")["booking_id"] == 2
    # Ambiguous time (two 17:30s) → None, ask the client.
    assert _match_booking_by_old_slot([b1, b2, b3], None, "17:30") is None
    # Date + time disambiguates.
    assert _match_booking_by_old_slot([b1, b2, b3], "2030-01-07", "17:30")["booking_id"] == 3
    # Date alone, unique.
    assert _match_booking_by_old_slot([b1, b3], "2030-01-07", None)["booking_id"] == 3
    # No selector at all → None (never guess).
    assert _match_booking_by_old_slot([b1, b2], None, None) is None
    # Garbage time → no crash, no guess.
    assert _match_booking_by_old_slot([b1, b2], None, "half past five") is None


def test_display_service_name_never_leaks_snake_case():
    """Reminders/surveys печатали сырой ключ ('deep_facial_cleansing') — live
    catch 2026-07-10. Client-facing name must come from the catalog."""
    from prices import display_service_name as d
    assert d("deep_facial_cleansing") == "Deep facial cleansing"
    assert "_" not in d("body_massage_90")
    assert d("") == "your appointment"
