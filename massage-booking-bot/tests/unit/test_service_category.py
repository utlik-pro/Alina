"""Unit tests for _detect_service_category (Wappi service-routing persistence)."""

import pytest

from webhook_app import _detect_service_category


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
