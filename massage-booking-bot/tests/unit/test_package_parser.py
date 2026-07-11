"""Unit tests for the package-state parser (comment ledger reader)."""

import pytest

from services.package_parser import parse_comment, client_package_state


def test_bare_counter_is_body_track():
    st = parse_comment("3+")
    assert st.has_package and st.body_session == 3 and st.face_session is None
    assert st.confidence == 0.9


def test_body_and_face_counters():
    st = parse_comment("B3+ / F2+")
    assert st.body_session == 3 and st.face_session == 2


def test_cyrillic_body_letter():
    st = parse_comment("В5+")
    assert st.body_session == 5


def test_last_session():
    st = parse_comment("5+(последний сеанс по пакету)")
    assert st.body_session == 5 and st.is_last is True and st.has_package


def test_remaining_minutes():
    st = parse_comment("ост. на нач. дня 08.07- 210 мин")
    assert st.remaining_minutes == 210 and st.has_package


def test_remaining_minutes_with_track():
    st = parse_comment("B4+(ост. на нач. дня на тело 150 мин)")
    assert st.body_session == 4 and st.remaining_minutes == 150 and st.remaining_track == "body"


def test_keyword_only_low_confidence():
    st = parse_comment("Это старый абонемент, просит массаж для похудения")
    assert st.has_package and st.body_session is None and st.confidence == 0.4


def test_price_plus_is_not_a_counter():
    """'499+' / '130+' are money, not session numbers → must be rejected."""
    st = parse_comment("Оплатила 700 трансфер за офер 499+ бандаж 130+ педикюр 150")
    # no valid session counter; not package-related either → None or no counter
    assert st is None or (st.body_session is None and st.face_session is None)


def test_non_package_comment_returns_none():
    assert parse_comment("Уточнить локацию") is None
    assert parse_comment("Терминал") is None
    assert parse_comment("") is None


def test_client_state_picks_latest_record():
    records = [
        {"date": "2026-07-01 10:00:00", "comment": "2+", "deleted": False},
        {"date": "2026-07-08 10:00:00", "comment": "4+(последний)", "deleted": False},
        {"date": "2026-06-20 10:00:00", "comment": "1+", "deleted": False},
    ]
    st = client_package_state(records)
    assert st.body_session == 4 and st.is_last is True


def test_client_state_ignores_deleted_and_nonpackage():
    records = [
        {"date": "2026-07-08 10:00:00", "comment": "3+", "deleted": True},
        {"date": "2026-07-07 10:00:00", "comment": "Уточнить локацию", "deleted": False},
    ]
    assert client_package_state(records) is None
