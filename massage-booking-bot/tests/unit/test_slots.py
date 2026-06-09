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
    assert "9:00" in slots


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
    # Far-enough slots survive.
    assert "9:00" in slots
    assert "16:00" in slots


@pytest.mark.asyncio
async def test_spread_not_clustered(yc, monkeypatch):
    async def times(*a, **k):
        return _bt(*[f"{h}:00" for h in range(9, 22)])  # 9:00–21:00 hourly
    async def records(*a, **k):
        return []
    monkeypatch.setattr(yc, "get_available_times", times)
    monkeypatch.setattr(yc, "get_records", records)
    slots = await yc.get_real_available_slots(1, "2030-01-06", 60)
    # With a 60-min spread we keep the hourly grid; the last slot must reach
    # into the evening (not clustered in the morning).
    assert slots[0] == "9:00"
    last_hour = int(slots[-1].split(":")[0])
    assert last_hour >= 18
