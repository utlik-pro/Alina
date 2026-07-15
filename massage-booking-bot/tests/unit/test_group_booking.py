"""Group booking: intent detector (_looks_like_group) + guest parser (_opt_guests).

Background: the LLM often ignores the `guests` field and books only the main
client (live sim 2026-07-15). The code safety net keys off _looks_like_group so
the admin is always alerted when a group was requested — the extra person can
never silently get no appointment.
"""

import pytest

from webhook_app import _looks_like_group, _enforce_reply_wording
from agents.tools import BookingCall


def _confirmed_call(guests=None):
    return BookingCall.from_tool_args({
        "service": "body_massage", "duration_minutes": 60, "date": "2026-07-16",
        "time": "13:00", "area": "abu_dhabi", "payment_method": "cash",
        "client_name": "Sara", "base_price_aed": 350, "address": "Villa 12",
        **({"guests": guests} if guests is not None else {}),
    })


_BOOKED = "Your body massage is booked ✅ Thu 16 Jul 1:00 PM 🌹"


@pytest.mark.parametrize("text", [
    "Hi, I want to book massage for me and my mom tomorrow",
    "book for me and my sister",
    "couple massage please",
    "can you do it for two of us",
    "для меня и мамы",
    "хочу записаться на двоих",
    "нас двое",
    "запишите меня и мужа",
])
def test_group_detected(text):
    assert _looks_like_group(text) is True


@pytest.mark.parametrize("text", [
    "both 60 min body massage",          # "both" alone is NOT a group signal
    "a couple of questions first",       # "couple of" ≠ couple massage
    "I want a massage",
    "manicure tomorrow please",
    "Villa 12, Al Raha",
    "",
])
def test_group_not_detected(text):
    assert _looks_like_group(text) is False


def test_guests_parsed_and_normalised():
    bc = BookingCall.from_tool_args({
        "service": "body_massage", "duration_minutes": 60, "date": "2026-07-16",
        "time": "13:00", "area": "abu_dhabi", "payment_method": "cash",
        "client_name": "Sara", "base_price_aed": 350,
        "guests": [
            {"client_name": "Olga", "service": "body_massage",
             "duration_minutes": 60, "base_price_aed": 350},
            {"client_name": "", "service": "x", "duration_minutes": 60,
             "base_price_aed": 1},          # unnamed → dropped
        ],
    })
    assert bc.guests is not None
    assert len(bc.guests) == 1
    assert bc.guests[0]["client_name"] == "Olga"
    assert bc.guests[0]["base_price_aed"] == 350.0


def test_single_booking_has_no_guests():
    bc = BookingCall.from_tool_args({
        "service": "body_massage", "duration_minutes": 60, "date": "2026-07-16",
        "time": "13:00", "area": "abu_dhabi", "payment_method": "cash",
        "client_name": "Sara", "base_price_aed": 350,
    })
    assert bc.guests is None


def test_guests_empty_list_is_none():
    bc = BookingCall.from_tool_args({
        "service": "body_massage", "duration_minutes": 60, "date": "2026-07-16",
        "time": "13:00", "area": "abu_dhabi", "payment_method": "cash",
        "client_name": "Sara", "base_price_aed": 350, "guests": [],
    })
    assert bc.guests is None


# --- client-message honesty net (_enforce_reply_wording) --------------------

def test_group_no_guests_appends_honest_line():
    """Model dropped the extra person → guarantee the client is told it's pending."""
    out = _enforce_reply_wording(
        _BOOKED, None, _confirmed_call(guests=None), {}, user_text="yes confirm",
        group_requested=True)
    assert "arranged by our team" in out
    assert _BOOKED in out  # original confirmation kept, line appended


def test_group_with_guests_no_double_line():
    """Model DID include guests → don't append (avoids duplicate messaging)."""
    out = _enforce_reply_wording(
        _BOOKED, None, _confirmed_call(guests=[{
            "client_name": "Olga", "service": "body_massage",
            "duration_minutes": 60, "base_price_aed": 350}]),
        {}, user_text="yes confirm", group_requested=True)
    assert "arranged by our team" not in out


def test_single_booking_untouched():
    out = _enforce_reply_wording(
        _BOOKED, None, _confirmed_call(guests=None), {}, user_text="yes confirm",
        group_requested=False)
    assert out == _BOOKED


def test_group_line_not_doubled_when_model_already_said_it():
    already = "You're booked ✅ Your mom's spot is being arranged by our team shortly 🌸"
    out = _enforce_reply_wording(
        already, None, _confirmed_call(guests=None), {}, user_text="yes confirm",
        group_requested=True)
    assert out.count("arranged by our team") == 1
