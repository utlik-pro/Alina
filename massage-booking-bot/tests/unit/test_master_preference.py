"""Master preference / replacement detection.

The agent must honour a client's therapist preference across sessions:
- positive ("only Elena", "same as last time") → preferred_therapist
- negative ("don't send Natalia", "не понравилась") → avoid_therapist (+ a hard
  booking guard so the avoided master is never booked even if the LLM ignores it)
"""

import pytest

from webhook_app import (
    _find_master_name, _detect_avoided_master, _detect_preferred_master,
)


@pytest.mark.parametrize("text,expected", [
    ("book me with Elena", "Elena"),
    ("хочу к Наталье", "Natalia"),
    ("Lyudmila please", "Lyudmila"),
    ("маша", "Masha"),
    ("Katya was great", "Ekaterina"),
    ("I want a massage", None),          # no master named
    ("Villa 12", None),
])
def test_find_master_name(text, expected):
    assert _find_master_name(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("I don't want Natalia again", "Natalia"),
    ("не понравилась Наталья, замените", "Natalia"),
    ("don't send Elena please", "Elena"),
    ("не хочу Люду больше", "Lyudmila"),
    ("please no more Masha", "Masha"),
])
def test_avoid_detected(text, expected):
    assert _detect_avoided_master(text) == expected


@pytest.mark.parametrize("text", [
    "I want another master",            # replacement WITHOUT a name → not persisted
    "give me someone else",
    "send me Elena please",             # positive, not an avoid
    "I want a massage",
])
def test_avoid_not_detected(text):
    assert _detect_avoided_master(text) is None


@pytest.mark.parametrize("text,expected", [
    ("only Elena please", "Elena"),
    ("always with Lyudmila", "Lyudmila"),
    ("book me with Masha as usual", "Masha"),
    ("мне нравится Сафина", "Safina"),
])
def test_preferred_detected(text, expected):
    assert _detect_preferred_master(text) == expected


@pytest.mark.parametrize("text", [
    "same as last time",                # no name here → uses the STORED preference
    "I want a massage",
    "tomorrow at 4pm",
])
def test_preferred_not_detected_without_name(text):
    assert _detect_preferred_master(text) is None
