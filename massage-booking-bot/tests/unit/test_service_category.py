"""Unit tests for _detect_service_category (Wappi service-routing persistence)
and _service_named (the service-first slot gate)."""

import pytest

from webhook_app import _detect_service_category, _service_named


@pytest.mark.parametrize("text,expected", [
    ("I want a manicure", "nails"),
    ("russian pedicure please", "nails"),
    ("mani and pedi", "nails"),
    ("маникюр на завтра", "nails"),
    ("body massage 90 min", "massage"),
    ("lymphatic drainage", "massage"),
    ("face massage", "massage"),
    ("массаж спины", "massage"),
    ("prenatal", "massage"),
    ("Villa 23", None),
    ("cash", None),
    ("", None),
    ("tomorrow at 4pm", None),
])
def test_detect(text, expected):
    assert _detect_service_category(text) == expected


def test_nails_takes_priority_over_massage_words():
    # A combo phrase mentioning both should route to nails (more specific).
    assert _detect_service_category("manicure and a face massage") == "nails"


# --- service-first gate: _service_named -------------------------------------
# The slot injection must NOT show times until the client has named a service.
# _service_named is broader than _detect_service_category: it also recognises
# lashes / brows / facial cleansing (which the category detector does not route)
# so the gate never re-asks a client who already said what they want.

@pytest.mark.parametrize("text", [
    "I want a manicure",
    "body massage 90 min",
    "маникюр на завтра",
    "массаж спины",
    "I want eyelash extension",
    "хочу нарастить ресницы",
    "eyebrow lamination please",
    "Запишите мне на чистку лица",   # facial deep cleansing (Russian genitive)
    "deep facial cleansing",
])
def test_service_named_true(text):
    assert _service_named(text) is True


@pytest.mark.parametrize("text", [
    "Доброе утро! Я хочу записаться на завтра",  # the 2026-07-15 opener — no service
    "I want to book for tomorrow",
    "I'm in Abu Dhabi",
    "Я в Абу-Даби",
    "villa 15",
    "cash",
    "",
])
def test_service_named_false(text):
    # Area / greeting / booking-intent WITHOUT a named service must NOT unlock slots.
    assert _service_named(text) is False


def test_gate_replays_the_2026_07_15_bug():
    """Area given before service must ask the service, not dump slots."""
    named = False
    # Turn 1: "book for tomorrow" — no service, no area yet.
    assert _service_named("Я хочу записаться на завтра") is False
    # Turn 2: area only — still no service → gate must hold (this is the fix).
    assert _service_named("Я в Абу-Даби") is False
    named = named or _service_named("Я в Абу-Даби")
    assert named is False
    # Turn 3: client finally names the service → slots unlock.
    assert _service_named("Я хочу сделать маникюр") is True
