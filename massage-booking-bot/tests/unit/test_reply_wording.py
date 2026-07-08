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
    rc = types.SimpleNamespace(new_time="16:30")
    out = _enforce_reply_wording("Your booking is confirmed ✅", _actions(reschedule=rc), None, {})
    low = out.lower()
    assert "reschedule" in low
    assert "4:30 pm" in low                      # 24h → AM/PM
    assert "confirmed" not in low and "booked" not in low


def test_booking_without_location_is_replaced_with_ask():
    bc = _bc(address=None, client_name="Sara")   # name ok, no location
    out = _enforce_reply_wording("Your massage is booked ✅", _actions(), bc, {"name": "Sara"})
    assert "location" in out.lower()
    assert "booked" not in out.lower() and "confirmed" not in out.lower()


def test_booking_without_name_is_replaced_with_ask():
    bc = _bc(address="Khalifa City villa 3", client_name=None)  # location ok, no name
    out = _enforce_reply_wording("Booked ✅", _actions(), bc, {})
    assert "name" in out.lower()


def test_booking_with_location_and_name_is_left_unchanged():
    bc = _bc(address="Khalifa City villa 3", client_name="Sara")
    original = "Your body massage is booked on Tuesday at 5:00 PM ✅"
    out = _enforce_reply_wording(original, _actions(), bc, {})
    assert out == original


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
