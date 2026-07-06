"""Unit tests for the stale-reply filter (must not drop slot-bearing turns)."""

import pytest

from agents.booking_agent import BookingAgent


@pytest.mark.parametrize("text", [
    "Sorry dear, I don't have Sunday schedule yet",
    "We don't have availability info",
    "Sunday is closed dear",
    "I do not have that info",
])
def test_pure_fallback_is_dropped(text):
    assert BookingAgent._is_stale_assistant_reply(text) is True


@pytest.mark.parametrize("text", [
    "Saturday we don't have, but Sunday 10:00 is available",
    "Al Ain we don't have, Eliza in Abu Dhabi 2pm free",
    "For Sunday: Natalia 9:00, 11:00",     # no stale phrase at all
    "Tomorrow Masha 14:30 or 16:00 dear",  # normal slot reply
])
def test_slot_bearing_reply_is_kept(text):
    # A reply that offers a concrete time must NOT be filtered out of history.
    assert BookingAgent._is_stale_assistant_reply(text) is False


def test_empty_is_not_stale():
    assert BookingAgent._is_stale_assistant_reply("") is False
