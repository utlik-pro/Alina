"""Unit tests for YClients availability slot logic (get_real_available_slots).

Locks in the fix where native YClients book_times is the source of truth and
a 60-min travel buffer is applied around existing visits — covering the bugs
reported 27–28 April (no evening slots, Sunday "closed", hardcoded 10:00 grid).
"""

import pytest

from services.yclients_service import YClientsService


def _bt(*times):
    return [{"time": t} for t in times]


@pytest.fixture
def yc(monkeypatch):
    svc = YClientsService()
    return svc


@pytest.mark.asyncio
async def test_day_off_returns_empty(yc, monkeypatch):
    async def no_times(*a, **k):
        return []
    async def no_records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", no_times)
    monkeypatch.setattr(yc, "get_records", no_records)
    assert await yc.get_real_available_slots(1, "2030-01-06", 60) == []


@pytest.mark.asyncio
async def test_evening_slots_preserved(yc, monkeypatch):
    # Master with morning + evening availability, no bookings.
    async def times(*a, **k):
        return _bt("9:00", "10:00", "11:00", "12:00", "18:00", "19:00", "20:00")
    async def records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    slots = await yc.get_real_available_slots(1, "2030-01-06", 60)
    assert "18:00" in slots  # "после 6 всё свободно" must show
    assert "9:00" not in slots  # business rule: no bookings before 10:00
    assert "10:00" in slots


@pytest.mark.asyncio
async def test_travel_buffer_excludes_slots_near_booking(yc, monkeypatch):
    async def times(*a, **k):
        return _bt("9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00")
    async def records(*a, **k):
        # One existing visit at 13:00 for 60 min.
        return [{"datetime": "2030-01-06T13:00:00+03:00", "seance_length": 3600}]
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    slots = await yc.get_real_available_slots(1, "2030-01-06", 60)
    # 13:00 itself is booked; 12:00 and 14:00 violate the 60-min travel gap.
    assert "13:00" not in slots
    assert "12:00" not in slots
    assert "14:00" not in slots
    # Far-enough slots survive (10:00 floor applies — no 9:00).
    assert "9:00" not in slots
    assert "10:00" in slots
    assert "16:00" in slots


@pytest.mark.asyncio
async def test_no_thinning_keeps_adjacent_free_slots(yc, monkeypatch):
    """A client asking for a specific time (e.g. 16:30 then 17:00) must find it:
    we no longer thin the list, so adjacent 30-min free slots are all kept."""
    async def times(*a, **k):
        return _bt("10:00", "16:00", "16:30", "17:00", "17:30")
    async def records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    slots = await yc.get_real_available_slots(1, "2030-01-06", 60)
    # 17:00 must NOT be dropped just because 16:30 is also free (the "17:00 not
    # available" bug from live testing).
    assert "16:30" in slots and "17:00" in slots


@pytest.mark.asyncio
async def test_floor_excludes_before_10(yc, monkeypatch):
    async def times(*a, **k):
        return _bt(*[f"{h}:00" for h in range(9, 22)])  # 9:00–21:00 hourly
    async def records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    slots = await yc.get_real_available_slots(1, "2030-01-06", 60)
    assert slots[0] == "10:00"          # no 9:00
    last_hour = int(slots[-1].split(":")[0])
    assert last_hour >= 18              # full day range kept (no thinning)


@pytest.mark.asyncio
async def test_long_service_needs_bigger_gap(yc, monkeypatch):
    """A 90-min service must not be offered a slot that only has 60 min free
    before the next visit (the live '90-min → 15:00' bug)."""
    async def times(*a, **k):
        return _bt("11:00", "12:00", "13:00")
    async def records(*a, **k):
        # A visit at 14:00 for 60 min. With the 60-min travel buffer:
        #  - 60-min service at 13:00 ends 14:00 → 14:00-14:00 gap 0 < 60 → out.
        #  - 12:00 (ends 13:00) → 60 min to the 14:00 visit → 60-min OK, but a
        #    90-min service (ends 13:30) leaves only 30 min → must be dropped.
        return [{"datetime": "2030-01-06T14:00:00+03:00", "seance_length": 3600}]
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    slots60 = await yc.get_real_available_slots(1, "2030-01-06", 60)
    slots90 = await yc.get_real_available_slots(1, "2030-01-06", 90)
    assert "12:00" in slots60           # fits a 60-min session
    assert "12:00" not in slots90       # does NOT fit a 90-min session
    assert "11:00" in slots90           # far enough — still fits 90 min


@pytest.mark.asyncio
async def test_last_start_is_duration_aware(yc, monkeypatch):
    """A long service must start early enough to finish by the 23:00 close:
    last start = min(21:00, 23:00 - duration). A 3h combo can't start at 21:00."""
    async def times(*a, **k):
        return _bt(*[f"{h}:00" for h in range(10, 23)])  # 10:00–22:00 hourly
    async def records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    assert (await yc.get_real_available_slots(1, "2030-01-06", 60))[-1] == "21:00"
    assert (await yc.get_real_available_slots(1, "2030-01-06", 120))[-1] == "21:00"
    assert (await yc.get_real_available_slots(1, "2030-01-06", 180))[-1] == "20:00"  # 3h combo


@pytest.mark.asyncio
async def test_summary_passes_service_duration(yc, monkeypatch):
    """get_available_slots_summary must forward the requested duration to
    get_real_available_slots (default 60 when unset)."""
    seen = []

    async def staff(*a, **k):
        return [{"id": 1, "name": "Наталья", "specialization": "массажист"}]

    async def real_slots(staff_id, date, duration=60, records=None):
        seen.append(duration)
        return ["10:00"]

    async def no_records(staff_id, date):
        return []

    monkeypatch.setattr(yc, "get_staff", staff)
    monkeypatch.setattr(yc, "get_real_available_slots", real_slots)
    monkeypatch.setattr(yc, "get_records", no_records)

    await yc.get_available_slots_summary(date="2030-01-06", area="abu_dhabi", service_duration=90)
    assert seen == [90]
    seen.clear()
    await yc.get_available_slots_summary(date="2030-01-06", area="abu_dhabi")
    assert seen == [60]                 # default when unset


# ── nail-duration default (no explicit duration) ──────────────────────────
# Regression: a bare "manicure" (no "gel" keyword) resolved to duration=None
# and defaulted to a 60-min buffer, so slots were offered back-to-back for a
# service that really runs ≥2h (впритык). Nails now default to 120 min.

@pytest.mark.asyncio
async def test_nail_service_defaults_to_120_when_duration_unknown(monkeypatch):
    svc = YClientsService()
    captured = {}

    async def staff(*a, **k):
        return [{"id": 7, "name": "Елена", "specialization": "мастер маникюра"}]

    async def real_slots(staff_id, date, service_duration=60, records=None):
        captured["duration"] = service_duration
        return ["10:00", "14:00"]

    async def no_records(staff_id, date):
        return []

    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_real_available_slots", real_slots)
    monkeypatch.setattr(svc, "get_records", no_records)

    await svc.get_available_slots_summary(
        date="2030-01-06", service_name="manicure", area="abu_dhabi",
        service_duration=None,
    )
    assert captured["duration"] == 120  # nails default, NOT 60


@pytest.mark.asyncio
async def test_massage_still_defaults_to_60_when_duration_unknown(monkeypatch):
    svc = YClientsService()
    captured = {}

    async def staff(*a, **k):
        return [{"id": 8, "name": "Наталья", "specialization": "массажист"}]

    async def real_slots(staff_id, date, service_duration=60, records=None):
        captured["duration"] = service_duration
        return ["10:00"]

    async def no_records(staff_id, date):
        return []

    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_real_available_slots", real_slots)
    monkeypatch.setattr(svc, "get_records", no_records)

    await svc.get_available_slots_summary(
        date="2030-01-06", service_name="body massage", area="abu_dhabi",
        service_duration=None,
    )
    assert captured["duration"] == 60


def test_book_tool_duration_enum_covers_long_nail_services():
    from agents.tools import BOOK_APPOINTMENT_TOOL
    enum = BOOK_APPOINTMENT_TOOL["function"]["parameters"]["properties"]["duration_minutes"]["enum"]
    assert 150 in enum   # Japanese mani+pedi combo (2.5h)
    assert 180 in enum   # Russian mani+pedi combo (3h) / nail extension


@pytest.mark.asyncio
async def test_nails_outside_abu_dhabi_reports_area_limitation(monkeypatch):
    """A Dubai/Al Ain client asking for nails must be told nails are Abu Dhabi
    only — NOT the generic 'try another day' dead-end."""
    svc = YClientsService()

    async def staff(*a, **k):
        return [
            {"id": 7, "name": "Елена", "specialization": "мастер маникюра"},   # Abu Dhabi
            {"id": 9, "name": "Людмила Дубай", "specialization": "массажист"},
        ]

    async def no_records(staff_id, date):
        return []

    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_records", no_records)
    msg = await svc.get_available_slots_summary(
        date="2030-01-06", service_name="gel manicure", area="dubai",
        service_duration=None,
    )
    assert "NOT AVAILABLE" in msg
    assert "Abu Dhabi" in msg


# ── YClients OUTAGE vs real day-off (reliability) ─────────────────────────
# get_available_times returns None on API failure (auth/5xx/network) — this
# must NOT be shown to a client as "no availability" nor block a real booking.

@pytest.mark.asyncio
async def test_outage_returns_none_not_empty(yc, monkeypatch):
    async def outage(*a, **k):
        return None  # API failure
    async def no_records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", outage)
    monkeypatch.setattr(yc, "get_records", no_records)
    assert await yc.get_real_available_slots(1, "2030-01-06", 60) is None  # NOT []


@pytest.mark.asyncio
async def test_summary_says_temporarily_unavailable_on_outage(monkeypatch):
    svc = YClientsService()
    async def staff(*a, **k):
        return [{"id": 1, "name": "Наталья", "specialization": "массажист"}]
    async def outage(*a, **k):
        return None
    async def no_records(*a, **k):
        return []
    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_available_times", outage)
    monkeypatch.setattr(svc, "get_records", no_records)
    msg = await svc.get_available_slots_summary(date="2030-01-06", service_name="body massage", area="abu_dhabi", service_duration=60)
    assert "TEMPORARILY UNAVAILABLE" in msg           # outage, not a lie
    assert "no availability" not in msg.lower()


@pytest.mark.asyncio
async def test_is_slot_available_fails_open_on_outage(monkeypatch):
    svc = YClientsService()
    async def staff(*a, **k):
        return [{"id": 1, "name": "Наталья", "specialization": "массажист"}]
    async def outage(*a, **k):
        return None
    async def no_records(*a, **k):
        return []
    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_available_times", outage)
    monkeypatch.setattr(svc, "get_records", no_records)
    # Can't verify during an outage → must NOT block a client-confirmed slot.
    assert await svc.is_slot_available("abu_dhabi", "2030-01-06", "14:00", 60) is True


# ── book_appointment tool schema hardening ────────────────────────────────

def test_base_price_is_required_and_short_durations_present():
    from agents.tools import BOOK_APPOINTMENT_TOOL
    fn = BOOK_APPOINTMENT_TOOL["function"]["parameters"]
    assert "base_price_aed" in fn["required"]      # a price omission must not slip through
    enum = fn["properties"]["duration_minutes"]["enum"]
    for d in (25, 40, 50, 60, 90, 120, 150, 180):  # face 50, combos 150/180, etc.
        assert d in enum


def test_booking_call_tolerates_missing_price():
    """A missing base_price must degrade to 0, not raise KeyError and drop the
    whole booking mid-turn."""
    from agents.tools import BookingCall
    bc = BookingCall.from_tool_args({
        "service": "body_massage", "duration_minutes": 60, "date": "2030-01-06",
        "time": "14:00", "area": "abu_dhabi", "payment_method": "cash",
        "client_name": "Sara",
        # base_price_aed intentionally omitted
    })
    assert bc.base_price_aed == 0


@pytest.mark.asyncio
async def test_is_slot_available_excludes_moved_record(yc, monkeypatch):
    """Reschedule must not be blocked by the record being moved: is_slot_available
    drops exclude_record_id from every master's schedule before computing free
    slots (2026-07-15 "время есть, но не переносит" — a 4:00 booking couldn't
    move to 4:30 because its OWN 4:00 record occupied 4:30)."""
    seen = {}

    async def staff(*a, **k):
        return [{"id": 1, "name": "Natalia"}]  # untagged → Abu Dhabi

    async def records(staff_id, date, *a, **k):
        return [{"id": 999, "datetime": f"{date} 16:00:00"},
                {"id": 111, "datetime": f"{date} 12:00:00"}]

    async def real_slots(staff_id, date, dur, records=None):
        seen["records"] = records or []
        return ["16:30"]

    monkeypatch.setattr(yc, "get_staff", staff)
    monkeypatch.setattr(yc, "get_records", records)
    monkeypatch.setattr(yc, "get_real_available_slots", real_slots)

    ok = await yc.is_slot_available("abu_dhabi", "2030-01-06", "16:30", 50,
                                    exclude_record_id=999)
    assert ok is True
    ids = [str(r.get("id")) for r in seen["records"]]
    assert "999" not in ids       # the record being moved is filtered out
    assert "111" in ids           # other bookings still count


@pytest.mark.asyncio
async def test_is_slot_available_without_exclude_keeps_all_records(yc, monkeypatch):
    """Default (no exclude) leaves the schedule untouched — a normal booking gate
    must still see every existing record."""
    seen = {}

    async def staff(*a, **k):
        return [{"id": 1, "name": "Natalia"}]

    async def records(staff_id, date, *a, **k):
        return [{"id": 999}, {"id": 111}]

    async def real_slots(staff_id, date, dur, records=None):
        seen["records"] = records or []
        return ["16:30"]

    monkeypatch.setattr(yc, "get_staff", staff)
    monkeypatch.setattr(yc, "get_records", records)
    monkeypatch.setattr(yc, "get_real_available_slots", real_slots)

    await yc.is_slot_available("abu_dhabi", "2030-01-06", "16:30", 50)
    ids = [str(r.get("id")) for r in seen["records"]]
    assert ids == ["999", "111"]
