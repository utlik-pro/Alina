"""Regressions from live test T3 (2026-09-22, maincomby ↔ crystal_lab_ae), the
scenario behind Tatyana's F03 / F21 / F04.

D2 «Actually Thursday 1 October» was stored as the NEAREST Thursday (24.09):
   the weekday branch overwrote the explicit date parsed two seconds earlier.
D3 «what tame» with a chosen time got «what time would you like?» back.
D1 after «60 min» the reply offered «6:00 PM, 6:30 PM or 7:00 PM» and dropped
   the client's 5:30 PM, which was free.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import webhook_app as wh

UAE = timezone(timedelta(hours=4))
NOW = datetime(2026, 9, 22, 13, 50, tzinfo=UAE)   # Tuesday


# ── D2: an explicit date beats a weekday word in the same message ───────────

@pytest.mark.parametrize("text,expected,src", [
    ("actually thursday 1 october", "2026-10-01", "explicit"),
    ("no, thursday 1 october, not 24 september", "2026-10-01", "explicit"),
    ("wednesday 30 september", "2026-09-30", "explicit"),
    ("wednesday", "2026-09-23", "weekday"),           # from Tue 22.09 → tomorrow
    ("next tuesday", "2026-09-29", "weekday"),
    ("tuesday", "2026-09-22", "weekday"),          # today matches → today
    ("в четверг", "2026-09-24", "weekday"),
    ("i am not satisfied with money", None, "none"),   # 'sat'/'mon' inside words
    ("khalifa city, villa 5", None, "none"),
])
def test_named_date_resolution(text, expected, src):
    assert wh._resolve_named_date(text, NOW) == (expected, src)


# ── D3: a short «what time?» states the chosen time ─────────────────────────

def _ctx(**bd):
    return SimpleNamespace(booking_data=dict(bd), client_data={"area": "abu_dhabi"})


def test_what_tame_states_the_chosen_time_instead_of_asking_again():
    out = wh._enforce_time_ask_answered(
        "For Thursday 1 October, what time would you like dear?", "what tame",
        _ctx(time="17:30", date="2026-10-01", service_type="body_massage", service_duration=60))
    assert "5:30 PM" in out and "Thursday 1 October" in out
    assert "what time would you like" not in out.lower()


def test_what_time_without_a_chosen_time_keeps_the_old_behaviour():
    out = wh._enforce_time_ask_answered(
        "Body massage 60 min — 350 AED", "what tame",
        _ctx(service_type="body_massage", service_duration=60))
    assert "day suits you" in out          # the previous gate's day question


def test_a_long_question_about_another_day_is_not_answered_with_the_stored_time():
    reply = "Tomorrow we have 10:00 AM, 12:00 PM or 3:00 PM 🌹 Which suits you?"
    out = wh._enforce_time_ask_answered(
        reply, "what time do you have tomorrow", _ctx(time="17:30", date="2026-09-22"))
    assert out == reply


# ── D1: the chosen time is not silently replaced by a list ──────────────────

def _ctx_full(**bd):
    return SimpleNamespace(
        booking_data={"time": "17:30", "service_type": "body_massage", "service_duration": 60, **bd},
        client_data={"area": "abu_dhabi", "phone": "+971501112233"})


def test_stored_time_free_replaces_the_list_and_moves_on(monkeypatch):
    import bot
    monkeypatch.setattr(bot, "yclients_service", SimpleNamespace(is_slot_available=AsyncMock(return_value=True)))
    out = asyncio.run(wh._enforce_stored_time_kept(
        "Today we have 6:00 PM, 6:30 PM or 7:00 PM 🌹\nWhich time suits you?", "60 min", _ctx_full()))
    assert out.startswith("5:30 PM is available today 🌹")
    assert "address" in out                # next missing step: address
    assert "6:00 PM" not in out


def test_stored_time_busy_is_said_before_the_alternatives(monkeypatch):
    import bot
    monkeypatch.setattr(bot, "yclients_service", SimpleNamespace(is_slot_available=AsyncMock(return_value=False)))
    reply = "Today we have 6:00 PM, 6:30 PM or 7:00 PM 🌹\nWhich time suits you?"
    out = asyncio.run(wh._enforce_stored_time_kept(reply, "60 min", _ctx_full()))
    assert out.startswith("5:30 PM isn't free today for 60 min dear 🙏")
    assert reply in out


def test_stored_time_gate_stays_out_when_the_client_talks_about_time_or_the_list_has_it(monkeypatch):
    import bot
    monkeypatch.setattr(bot, "yclients_service", SimpleNamespace(is_slot_available=AsyncMock(return_value=True)))
    lst = "Today we have 5:30 PM, 6:00 PM or 7:00 PM 🌹"
    assert asyncio.run(wh._enforce_stored_time_kept(lst, "60 min", _ctx_full())) == lst
    other = "Today we have 6:00 PM or 7:00 PM 🌹"
    assert asyncio.run(wh._enforce_stored_time_kept(other, "7 pm please", _ctx_full())) == other
    assert asyncio.run(wh._enforce_stored_time_kept(other, "what time", _ctx_full())) == other
    single = "6:00 PM is available today 🌹"
    assert asyncio.run(wh._enforce_stored_time_kept(single, "60 min", _ctx_full())) == single


def test_stored_time_gate_uses_the_stored_date_and_availability_outage_leaves_reply(monkeypatch):
    import bot
    seen = {}
    async def avail(area, date, hhmm, duration=60, exclude_record_id=None):
        seen.update(area=area, date=date, hhmm=hhmm, duration=duration); return True
    monkeypatch.setattr(bot, "yclients_service", SimpleNamespace(is_slot_available=avail))
    out = asyncio.run(wh._enforce_stored_time_kept(
        "We have 6:00 PM or 7:00 PM 🌹", "60 min", _ctx_full(date="2026-10-01")))
    assert seen == {"area": "abu_dhabi", "date": "2026-10-01", "hhmm": "17:30", "duration": 60}
    assert "on Thursday 1 October" in out
    monkeypatch.setattr(bot, "yclients_service", SimpleNamespace(is_slot_available=AsyncMock(side_effect=RuntimeError("down"))))
    reply = "We have 6:00 PM or 7:00 PM 🌹"
    assert asyncio.run(wh._enforce_stored_time_kept(reply, "60 min", _ctx_full())) == reply


def test_next_step_question_walks_the_funnel():
    c = SimpleNamespace(booking_data={}, client_data={"area": "abu_dhabi"})
    assert c and wh._next_step_question(c) == wh.PHONE_FIRST_LINE
    c.client_data["phone"] = "+971501112233"
    assert "address in Abu Dhabi" in wh._next_step_question(c)
    c.client_data["location_details"] = "Khalifa City, villa 5"
    assert "name" in wh._next_step_question(c)
    c.client_data["name"] = "Dmitry Test"
    assert "pay" in wh._next_step_question(c)
    c.booking_data["payment_method"] = "cash"
    assert wh._next_step_question(c) == "Shall I confirm?"
