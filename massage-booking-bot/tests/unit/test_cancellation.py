"""Unit tests for cancellation & penalty logic (FR-5.1–5.3)."""

from datetime import datetime, timedelta

import pytest

from services.cancellation import (
    calculate_penalty,
    is_force_majeure,
    TRANSPORTATION_PENALTY_AED,
)


NOW = datetime(2026, 6, 2, 12, 0, 0)


def _in(hours):
    return NOW + timedelta(hours=hours)


class TestForceMajeure:
    @pytest.mark.parametrize("text", [
        "I'm in the hospital", "newborn baby arrived", "there was a death in family",
        "ambulance came", "капельница сегодня", "роды начались",
    ])
    def test_detects(self, text):
        assert is_force_majeure(text) is True

    @pytest.mark.parametrize("text", [
        "changed my mind", "too expensive", "busy at work", "",
    ])
    def test_ignores(self, text):
        assert is_force_majeure(text) is False


class TestPenalty:
    def test_more_than_24h_free(self):
        r = calculate_penalty(_in(48), is_package=False, now=NOW)
        assert r["free"] and r["charge_aed"] == 0

    def test_12_to_24h_free(self):
        r = calculate_penalty(_in(18), is_package=False, now=NOW)
        assert r["free"]

    def test_same_day_new_client_warns_with_charge(self):
        r = calculate_penalty(_in(6), is_package=False, now=NOW)
        assert r["warn_only"] and r["charge_aed"] == TRANSPORTATION_PENALTY_AED
        assert not r["free"]

    def test_same_day_package_warns_with_deduction(self):
        r = calculate_penalty(_in(6), is_package=True, now=NOW)
        assert r["warn_only"] and r["deduct_session"] is True

    def test_under_1h_new_client_charged(self):
        r = calculate_penalty(_in(0.5), is_package=False, now=NOW)
        assert r["charge_aed"] == TRANSPORTATION_PENALTY_AED and not r["warn_only"]

    def test_master_en_route_package_deducts(self):
        r = calculate_penalty(_in(5), is_package=True, master_en_route=True, now=NOW)
        assert r["deduct_session"] and not r["warn_only"]

    def test_force_majeure_overrides_same_day(self):
        r = calculate_penalty(_in(0.5), is_package=False, reason="hospital", now=NOW)
        assert r["free"] and r["force_majeure"] and r["charge_aed"] == 0
