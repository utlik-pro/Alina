"""Unit tests for the deterministic pipeline auditor (v1)."""

import pytest

from services.pipeline_audit.episodes import Episode, segment_episodes
from services.pipeline_audit.parsing import parse_date, parse_time
from services.pipeline_audit.findings import FAIL, WARN, OK, FLAG_HUMAN
from services.pipeline_audit.checks import booking_integrity, cancel_reschedule, manual_override
from services.pipeline_audit.gap_report import classify_comments


# Realistic epoch (~2026-07-11 09:00 UTC) so year inference in parsing lands in
# 2026, not 1970 (tiny fake timestamps would break the date parser).
BASE_TS = 1783760400


def _ep(phone, msgs):
    """msgs = list of (from_me, body, t)."""
    return Episode(
        phone=phone, start_t=msgs[0][2], end_t=msgs[-1][2],
        messages=[{"from_me": fm, "body": b, "t": t, "type": "chat"} for fm, b, t in msgs],
    )


# ── parsing ──────────────────────────────────────────────────────────────

def test_parse_date_dm_and_md():
    from datetime import date
    ref = date(2026, 7, 11)
    assert parse_date("Sat 11 Jul 12:00 PM", ref) == "2026-07-11"
    assert parse_date("Saturday, July 11", ref) == "2026-07-11"


def test_parse_time_ampm_and_24h():
    assert parse_time("12:00 PM") == "12:0" or parse_time("12:00 PM") == "12:00"
    assert parse_time("5:30 PM") == "17:30"
    assert parse_time("moved to 17:00") == "17:0" or parse_time("moved to 17:00") == "17:00"


# ── episode segmentation ────────────────────────────────────────────────

def test_segment_splits_on_clear():
    msgs = [
        {"from_me": False, "body": "Hi", "t": 1, "type": "chat"},
        {"from_me": True, "body": "Hello dear", "t": 2, "type": "chat"},
        {"from_me": False, "body": "/clear", "t": 3, "type": "chat"},
        {"from_me": False, "body": "Body massage", "t": 4, "type": "chat"},
    ]
    eps = segment_episodes("971500", msgs)
    assert len(eps) == 2
    assert eps[0].messages[0]["body"] == "Hi"
    assert eps[1].messages[0]["body"] == "Body massage"
    # the /clear control message is dropped
    assert all("/clear" not in m["body"] for e in eps for m in e.messages)


# ── #1 say-do booking integrity ─────────────────────────────────────────

def test_booking_integrity_ok_when_record_matches():
    ep = _ep("375293726634", [
        (False, "book me", BASE_TS),
        (True, "Your body massage is booked ✅ Ekaterina — Sat 11 Jul 12:00 PM — 460 AED", BASE_TS+1),
    ])
    recs = {"293726634": [{"id": 1, "date": "2026-07-11 12:00:00", "deleted": False,
                           "client": {"phone": "375293726634"}}]}
    out = booking_integrity.check(ep, recs, window=("2026-07-11", "2026-07-11"))
    assert len(out) == 1 and out[0].severity == OK


def test_booking_integrity_fail_phantom():
    ep = _ep("375293726634", [
        (True, "Your body massage is booked ✅ Ekaterina — Sat 11 Jul 12:00 PM — 460 AED", BASE_TS+1),
    ])
    recs = {"293726634": []}  # no record
    out = booking_integrity.check(ep, recs, window=("2026-07-11", "2026-07-11"))
    assert len(out) == 1 and out[0].severity == FAIL
    assert "PHANTOM" in out[0].summary


def test_booking_integrity_split_confirmation():
    """Recap in one message, 'it's booked ✅' in the next — still verified."""
    ep = _ep("375293726634", [
        (True, "So dear — 90-min body massage, Ekaterina, Sat 11 Jul at 12:00 PM. Shall I confirm?", BASE_TS),
        (False, "Yes", BASE_TS+1),
        (True, "Yes dear 🌹 it's booked ✅", BASE_TS+2),
    ])
    recs = {"293726634": [{"id": 9, "date": "2026-07-11 12:00:00", "deleted": False,
                           "client": {"phone": "375293726634"}}]}
    out = booking_integrity.check(ep, recs, window=("2026-07-11", "2026-07-11"))
    assert out[0].severity == OK


def test_booking_integrity_fully_booked_is_not_a_claim():
    """'we are fully booked' must NOT be read as a booking confirmation."""
    ep = _ep("971528843929", [
        (True, "Sorry dear, today we are fully booked 🙏", BASE_TS),
    ])
    assert booking_integrity.check(ep, {"528843929": []}, window=("2026-07-11", "2026-07-11")) == []


def test_booking_integrity_moved_after_confirm_is_warn_not_phantom():
    """Record landed on the right day but was moved to another time → WARN, not FAIL."""
    ep = _ep("375293726634", [
        (True, "Your body massage is booked ✅ Ekaterina — Sat 11 Jul 12:00 PM — 460 AED", BASE_TS+1),
    ])
    recs = {"293726634": [{
        "id": 1834685628, "date": "2026-07-11 13:30:00", "deleted": False,
        "client": {"phone": "375293726634"},
        "comment": "[TEST] WhatsApp (Wappi) bot booking #13. Area: abu_dhabi.",
    }]}
    out = booking_integrity.check(ep, recs, window=("2026-07-11", "2026-07-11"))
    assert len(out) == 1 and out[0].severity == WARN
    assert "moved after confirmation" in out[0].summary


def test_booking_integrity_out_of_window_flags():
    ep = _ep("375293726634", [
        (True, "booked ✅ Natalia — Sat 11 Jul 10:00 AM — 460 AED", BASE_TS+1),
    ])
    out = booking_integrity.check(ep, {"293726634": []}, window=("2026-06-01", "2026-06-02"))
    assert out[0].severity == FLAG_HUMAN


# ── #7 cancel / reschedule ──────────────────────────────────────────────

def test_cancel_ignores_team_mediated_wording():
    ep = _ep("375", [(True, "Ok dear, I've passed your cancellation to the team — shortly 🌹", 1)])
    assert cancel_reschedule.check(ep, {"375": [{"id": 1, "deleted": False}]}) == []


def test_cancel_fail_when_record_still_live():
    ep = _ep("375293726634", [(True, "Your appointment is cancelled ✅", BASE_TS)])
    recs = {"293726634": [{"id": 1, "deleted": False, "date": "2026-07-11 12:00:00"}]}
    out = cancel_reschedule.check(ep, recs)
    assert out[0].severity == FAIL


def test_cancel_ok_when_no_live_record():
    ep = _ep("375293726634", [(True, "Your appointment is cancelled ✅", BASE_TS)])
    recs = {"293726634": [{"id": 1, "deleted": True, "date": "2026-07-11 12:00:00"}]}
    out = cancel_reschedule.check(ep, recs)
    assert out[0].severity == OK


def test_move_ok_when_record_at_new_time():
    ep = _ep("375293726634", [(True, "Done dear 🌹 Your appointment is moved to 5:00 PM ✅", BASE_TS)])
    recs = {"293726634": [{"id": 1, "deleted": False, "date": "2026-07-12 17:00:00"}]}
    out = cancel_reschedule.check(ep, recs)
    assert out[0].severity == OK


def test_move_fail_when_no_record_at_new_time():
    ep = _ep("375293726634", [(True, "Your appointment is moved to 5:00 PM ✅", BASE_TS)])
    recs = {"293726634": [{"id": 1, "deleted": False, "date": "2026-07-12 12:00:00"}]}
    out = cancel_reschedule.check(ep, recs)
    assert out[0].severity == FAIL


# ── #6 manual override ──────────────────────────────────────────────────

def test_manual_override_flags_admin_edit():
    recs = [{
        "id": 1, "date": "2026-07-11 12:00:00",
        "comment": "[TEST] WhatsApp (Wappi) bot booking #13. Area: abu_dhabi.",
        "staff": {"name": "АДМИНИСТРАТОРЫ"},
        "client": {"phone": "375293726634"},
        "create_date": "2026-07-10T16:40:20+0300",
        "last_change_date": "2026-07-10T17:00:09+0300",
    }]
    out = manual_override.check_records(recs)
    assert len(out) == 1 and out[0].severity == FLAG_HUMAN
    assert "admin edited" in out[0].summary or "parked" in out[0].summary


def test_manual_override_ok_untouched():
    recs = [{
        "id": 2, "date": "2026-07-11 12:00:00",
        "comment": "WhatsApp (Wappi) bot booking #20. Area: abu_dhabi.",
        "staff": {"name": "Наталья"},
        "client": {"phone": "971500"},
        "create_date": "2026-07-10T16:40:20+0300",
        "last_change_date": "2026-07-10T16:40:30+0300",
    }]
    out = manual_override.check_records(recs)
    assert out[0].severity == OK


def test_manual_override_ignores_non_agent_records():
    recs = [{"id": 3, "comment": "3+", "staff": {"name": "Наталья"},
             "client": {"phone": "971"}, "create_date": None, "last_change_date": None}]
    assert manual_override.check_records(recs) == []


# ── gap report ──────────────────────────────────────────────────────────

def test_gap_report_packages_dominate_and_uncovered():
    comments = ["5+(последний сеанс по пакету)", "3+", "B3+", "Терминал",
                "Только Мария", "[TEST] WhatsApp (Wappi) bot booking #1"]
    g = classify_comments(comments)
    rows = {r["responsibility"]: r for r in g["rows"]}
    assert rows["Packages / session counter"]["count"] == 3
    assert rows["Packages / session counter"]["coverage"] == "none"
    assert rows["Terminal (card) payment"]["coverage"] == "full"
    assert g["bot_records"] == 1  # test stamp excluded from human workload
    assert 0.0 <= g["admin_coverage_score"] <= 1.0
