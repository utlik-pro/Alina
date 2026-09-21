"""Regressions from the live failures of 20–21 Sep 2026 (Maryam Alzaabi,
Khalifa City) and the week before (Anwar 11.09, «ladies only» 13.09).

The night of 20.09: a fully qualified client confirmed «Tuesday 1:30 PM».
The model named no master, find_staff_id returned the FIRST of the roster
(Махабат, busy all day with Al Ain clients), YClients refused, the client
got «One moment…» — twice — and no record existed while three masters were
free at 13:30. Every step of that chain is pinned here.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.yclients_service import YClientsService

UAE = timezone(timedelta(hours=4))

_ROSTER = [
    {"id": 1, "name": "Махабат", "specialization": "массажист"},
    {"id": 2, "name": "Маша", "specialization": "массажист"},
    {"id": 3, "name": "Нина", "specialization": "массажист"},
    {"id": 9, "name": "Лана/Бота", "specialization": "мастер лэшмейкер"},
    {"id": 99, "name": "АДМИНИСТРАТОРЫ", "specialization": "ЛИСТ ОЖИДАНИЯ"},
]


def _svc(monkeypatch, free_by_id):
    svc = YClientsService()

    async def staff(*a, **k):
        return list(_ROSTER)

    async def slots(staff_id, date, duration=60, records=None):
        return free_by_id.get(staff_id, [])

    async def records(staff_id, date):
        return []

    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_real_available_slots", slots)
    monkeypatch.setattr(svc, "get_records", records)
    return svc


# ── 1. the master must be FREE at the confirmed time ─────────────────────────

@pytest.mark.asyncio
async def test_unnamed_master_is_the_first_FREE_one_not_the_first_in_roster(monkeypatch):
    svc = _svc(monkeypatch, {1: ["12:00"], 2: ["13:00", "13:30"], 3: ["13:30"], 9: ["13:30"]})
    picked = await svc.find_staff_id(
        area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=45, service_name="lymphatic_cupping_combo")
    assert picked == 2          # Маша — free; not Махабат (busy), not the lash maker


@pytest.mark.asyncio
async def test_named_but_busy_master_is_swapped_for_a_free_one(monkeypatch):
    svc = _svc(monkeypatch, {1: ["12:00"], 2: ["13:30"], 3: ["13:30"]})
    assert await svc.find_staff_id(
        name="Makhabat", area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=60, service_name="body_massage") == 2
    # A named master who IS free keeps the booking.
    assert await svc.find_staff_id(
        name="Nina", area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=60, service_name="body_massage") == 3


@pytest.mark.asyncio
async def test_nobody_free_returns_none_instead_of_a_busy_master(monkeypatch):
    svc = _svc(monkeypatch, {1: ["12:00"], 2: ["12:00"], 3: []})
    assert await svc.find_staff_id(
        area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=60, service_name="body_massage") is None


@pytest.mark.asyncio
async def test_slot_format_mismatch_does_not_hide_a_free_master(monkeypatch):
    # book_times says '9:30', the tool call says '09:30'.
    svc = _svc(monkeypatch, {1: ["9:30"], 2: []})
    assert await svc.find_staff_id(
        area="abu_dhabi", date="2026-09-22", time="09:30",
        duration_minutes=60, service_name="body_massage") == 1


@pytest.mark.asyncio
async def test_api_outage_for_one_master_ranks_after_known_free(monkeypatch):
    svc = _svc(monkeypatch, {2: ["13:30"], 3: ["13:30"]})

    async def slots(staff_id, date, duration=60, records=None):
        return None if staff_id == 1 else ({2: ["13:30"], 3: ["13:30"]}).get(staff_id, [])
    monkeypatch.setattr(svc, "get_real_available_slots", slots)
    assert await svc.find_staff_id(
        area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=60, service_name="body_massage") == 2


@pytest.mark.asyncio
async def test_lash_maker_is_never_booked_for_a_massage_and_vice_versa(monkeypatch):
    svc = _svc(monkeypatch, {1: [], 2: [], 3: [], 9: ["13:30"]})
    assert await svc.find_staff_id(
        area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=60, service_name="body_massage") is None
    assert await svc.find_staff_id(
        area="abu_dhabi", date="2026-09-22", time="13:30",
        duration_minutes=90, service_name="eyelash extension") == 9


@pytest.mark.asyncio
async def test_without_a_time_the_legacy_roster_order_is_kept(monkeypatch):
    svc = _svc(monkeypatch, {})
    assert await svc.find_staff_id(area="abu_dhabi", date="2026-09-22") == 1


def test_create_booking_refusal_is_definitive_and_carries_the_free_list():
    svc = YClientsService()
    with patch.object(svc, "get_real_available_slots",
                      AsyncMock(return_value=["12:00", "12:30"])), \
         patch.object(svc, "_get_session", AsyncMock()) as sess:
        out = asyncio.run(svc.create_booking(
            staff_id=1, service_ids=[1], date="2026-09-22", time="13:30",
            client_name="Maryam", client_phone="0504241434", duration_minutes=45))
    assert out == {"refused": "busy", "staff_id": 1, "free": ["12:00", "12:30"]}
    assert not sess.called


# ── 2. a definitive refusal releases the attempt; uncertainty still blocks ───

@pytest.mark.asyncio
async def test_failed_calendar_attempt_can_be_reclaimed_but_pending_and_accepted_cannot(tmp_path):
    from database.db import Database
    from database.models import Base, BookingAttempt
    from database.services import BookingService

    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'attempts.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    svc = BookingService(db)
    try:
        assert await svc.claim_calendar_attempt("maryam-22-09")
        assert not await svc.claim_calendar_attempt("maryam-22-09")       # pending blocks
        await svc.fail_calendar_attempt("maryam-22-09")                    # YClients said no
        assert await svc.claim_calendar_attempt("maryam-22-09")           # → retry allowed
        async with db.session() as session:
            assert (await session.get(BookingAttempt, "maryam-22-09")).status == "pending"
        await svc.complete_calendar_attempt("maryam-22-09", 777)
        await svc.fail_calendar_attempt("maryam-22-09")                    # must not touch accepted
        async with db.session() as session:
            assert (await session.get(BookingAttempt, "maryam-22-09")).status == "accepted"
        assert not await svc.claim_calendar_attempt("maryam-22-09")
    finally:
        await db.engine.dispose()


# ── 3. «One moment» is never repeated verbatim ────────────────────────────────

def test_pending_line_is_not_sent_twice_verbatim():
    import webhook_app as wh
    ctx = SimpleNamespace(booking_data={})
    assert wh._pending_line(ctx) == wh.BOOKING_PENDING_LINE
    second = wh._pending_line(ctx)
    assert second == wh.BOOKING_PENDING_AGAIN_LINE and second != wh.BOOKING_PENDING_LINE
    assert "administrator" in second
    # A context without booking_data degrades to the first line, never crashes.
    assert wh._pending_line(SimpleNamespace()) == wh.BOOKING_PENDING_LINE


# ── 4. phantom gate: only at a booking stage, only about THE CLIENT ──────────

def test_ladies_only_policy_answer_is_not_a_phantom_booking():
    import webhook_app as wh
    live = ("Yes dear, our home services are for ladies only 🌹\n\n"
            "Exception if husband is booked by wife, or for couples massage.\n\n"
            "What service would you like?")
    assert not wh._CLAIMS_BOOKED_RE.search(live)
    for phantom in ("Your face massage is booked ✅",
                    "Your facial massage is booked for tomorrow, Wednesday 9th September at 10:00 AM ✅",
                    "Your lymphatic cupping combo is booked ✅",
                    "You're booked for tomorrow dear 🌹",
                    "You are all booked dear",
                    "Your booking is confirmed ✅",
                    "Your appointment has been confirmed"):
        assert wh._CLAIMS_BOOKED_RE.search(phantom), phantom
    assert not wh._booking_stage_reached(SimpleNamespace(booking_data={"service_type": "face_massage"}))
    assert wh._booking_stage_reached(SimpleNamespace(booking_data={"date": "2026-09-22"}))
    assert wh._booking_stage_reached(SimpleNamespace(booking_data={"time": "13:30"}))


# ── 5. a bare 1:30–8:59 is the afternoon (the salon opens at 10:00) ──────────

def test_bare_small_hours_are_read_as_afternoon():
    from webhook_app import _detect_requested_time as d
    assert d("Tuesday between 1:30 to 5") == "13:30"
    assert d("8:30") == "20:30"
    assert d("morning at 8:00") == "08:00"     # explicit morning wins
    assert d("1:30 am") == "01:30"             # explicit am wins
    assert d("9:00") == "09:00"                # unchanged behaviour
    assert d("10:00") == "10:00"
    assert d("12:30") == "12:30"


# ── 6. a same-day booking never promises «Tomorrow our administrator…» ───────

def test_same_day_booking_gets_shortly_not_tomorrow():
    import webhook_app as wh
    from agents.tools import BookingCall

    def call(date):
        return BookingCall.from_tool_args({
            "service": "face_massage", "duration_minutes": 50, "date": date,
            "time": "10:00", "area": "abu_dhabi", "payment_method": "cash",
            "client_name": "Anwar", "base_price_aed": 370,
            "address": "Villa 13, Almawqi street, Yas", "client_phone": "+971501944487"})

    _CD = {"name": "Anwar", "location_details": "Villa 13, Almawqi street, Yas",
           "phone": "+971501944487"}
    today = datetime.now(UAE).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(UAE) + timedelta(days=1)).strftime("%Y-%m-%d")
    out = wh._enforce_reply_wording(
        "Your face massage is booked ✅\nTomorrow our administrator will contact "
        "you to confirm the details 🌹", None, call(today), _CD, user_text="yes", is_ig=True)
    assert "tomorrow" not in out.lower() and "shortly" in out
    out2 = wh._enforce_reply_wording(
        "Your face massage is booked ✅", None, call(today), _CD, user_text="yes", is_ig=True)
    assert "Our administrator will contact you shortly" in out2 and "Tomorrow" not in out2
    out3 = wh._enforce_reply_wording(
        "Your face massage is booked ✅", None, call(tomorrow), _CD, user_text="yes", is_ig=True)
    assert "Tomorrow our administrator will contact you" in out3


# ── 7. the master named to the client is the master on the record ───────────

def test_master_name_comes_from_the_record_not_the_models_guess(monkeypatch):
    import bot
    import webhook_app as wh
    monkeypatch.setattr(bot, "yclients_service", SimpleNamespace(
        get_staff=AsyncMock(return_value=[{"id": 5837520, "name": "Нина"},
                                          {"id": 5469396, "name": "Махабат"}])))
    assert asyncio.run(wh._resolve_master_name(5837520, "Makhabat")) == "Нина"
    assert asyncio.run(wh._resolve_master_name("5469396", "")) == "Махабат"
    # Only when no record id exists does the model's word count.
    assert asyncio.run(wh._resolve_master_name(None, "Makhabat")) == "Makhabat"
