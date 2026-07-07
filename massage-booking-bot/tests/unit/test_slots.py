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
async def test_summary_passes_service_duration(yc, monkeypatch):
    """get_available_slots_summary must forward the requested duration to
    get_real_available_slots (default 60 when unset)."""
    seen = []

    async def staff(*a, **k):
        return [{"id": 1, "name": "Наталья", "specialization": "массажист"}]

    async def real_slots(staff_id, date, duration=60):
        seen.append(duration)
        return ["10:00"]

    monkeypatch.setattr(yc, "get_staff", staff)
    monkeypatch.setattr(yc, "get_real_available_slots", real_slots)

    await yc.get_available_slots_summary(date="2030-01-06", area="abu_dhabi", service_duration=90)
    assert seen == [90]
    seen.clear()
    await yc.get_available_slots_summary(date="2030-01-06", area="abu_dhabi")
    assert seen == [60]                 # default when unset
