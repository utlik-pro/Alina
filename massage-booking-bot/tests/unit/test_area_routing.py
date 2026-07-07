"""Unit tests for area routing across Abu Dhabi / Al Ain / Dubai.

The salon runs three separate emirates. Each master serves exactly one,
tagged in their YClients display name ("Элиза Al Ain", "Людмила Дубай";
untagged = Abu Dhabi). A client must only ever see / be booked with masters
from their own area — no cross-emirate drives.

Covers the live-tester feedback (7 Jul): a Dubai client was wrongly told
"we don't work in Dubai", and an Abu Dhabi master (Tatyana) was hidden.
"""

import pytest

from services.yclients_service import YClientsService, _staff_area


# Roster mirrors the real YClients staff list (names carry the area tag).
_ROSTER = [
    {"id": 3712102, "name": "Элиза Al Ain", "specialization": "массажист"},
    {"id": 5305116, "name": "Людмила Дубай", "specialization": "массажист"},
    {"id": 3853586, "name": "Наталья", "specialization": "массажист"},
    {"id": 3698466, "name": "Татьяна", "specialization": "массажист"},
    {"id": 3726110, "name": "Маша", "specialization": "массажист"},
    {"id": 3713319, "name": "АДМИНИСТРАТОРЫ", "specialization": "ЛИСТ ОЖИДАНИЯ"},
]


@pytest.fixture
def yc(monkeypatch):
    svc = YClientsService()

    async def staff(*a, **k):
        return list(_ROSTER)

    # Every real master has the same generous free day so the area filter is
    # the ONLY thing that changes which names appear.
    async def slots(staff_id, date, duration=60):
        return ["10:00", "12:00", "14:00"]

    monkeypatch.setattr(svc, "get_staff", staff)
    monkeypatch.setattr(svc, "get_real_available_slots", slots)
    return svc


# ── _staff_area classification ────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Элиза Al Ain", "al_ain"),
    ("Фарида Al-Ain", "al_ain"),
    ("Людмила Дубай", "dubai"),
    ("Sveta Dubai", "dubai"),
    ("Наталья", "abu_dhabi"),
    ("Татьяна", "abu_dhabi"),
    ("", "abu_dhabi"),
])
def test_staff_area_classification(raw, expected):
    assert _staff_area(raw) == expected


# ── summary respects the client's area ────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_dubai_shows_only_dubai_master(yc):
    s = await yc.get_available_slots_summary(date="2030-01-06", area="dubai")
    assert "Lyudmila (Dubai)" in s
    assert "Natalia" not in s and "Tatyana" not in s and "Eliza" not in s


@pytest.mark.asyncio
async def test_summary_abu_dhabi_excludes_dubai_and_al_ain(yc):
    s = await yc.get_available_slots_summary(date="2030-01-06", area="abu_dhabi")
    # Tatyana (the hidden-master bug) MUST be present.
    assert "Tatyana" in s and "Natalia" in s and "Masha" in s
    # Dubai + Al Ain masters must NOT leak in.
    assert "Lyudmila" not in s
    assert "Eliza" not in s


@pytest.mark.asyncio
async def test_summary_al_ain_shows_only_al_ain_master(yc):
    s = await yc.get_available_slots_summary(date="2030-01-06", area="al_ain")
    assert "Eliza (Al Ain)" in s
    assert "Lyudmila" not in s and "Tatyana" not in s


# ── booking path (find_staff_id) routes to the client's area ──────────────

@pytest.mark.asyncio
async def test_find_staff_dubai_routes_to_dubai_master(yc):
    assert await yc.find_staff_id(area="dubai") == 5305116
    assert await yc.find_staff_id(name="Lyudmila", area="dubai") == 5305116


@pytest.mark.asyncio
async def test_find_staff_abu_dhabi_never_returns_dubai_master(yc):
    # Lyudmila is a Dubai master — she must NOT be bookable for Abu Dhabi.
    assert await yc.find_staff_id(name="Lyudmila", area="abu_dhabi") is None
    # A real Abu Dhabi name still resolves.
    assert await yc.find_staff_id(name="Tatyana", area="abu_dhabi") == 3698466


@pytest.mark.asyncio
async def test_find_staff_admin_never_returned(yc):
    # The waiting-list / admin pseudo-staff must never be booked.
    for area in ("abu_dhabi", "al_ain", "dubai"):
        assert await yc.find_staff_id(area=area) != 3713319


# ── GPS coordinate → area (Dubai must not swallow unserved neighbours) ─────

@pytest.mark.parametrize("label,lat,lng,expected", [
    ("Dubai Downtown", 25.197, 55.274, "dubai"),
    ("Dubai Marina", 25.08, 55.14, "dubai"),
    ("JBR", 25.078, 55.134, "dubai"),
    ("Deira", 25.27, 55.32, "dubai"),
    # Unserved neighbouring emirates must NOT be auto-classified as Dubai —
    # they stay None so the agent asks the client to confirm in text.
    ("Sharjah", 25.346, 55.421, None),
    ("Ajman", 25.405, 55.513, None),
    # Existing centres unchanged.
    ("Abu Dhabi", 24.47, 54.37, "abu_dhabi"),
    ("Al Ain", 24.21, 55.75, "al_ain"),
    ("Minsk (abroad)", 53.9, 27.5, None),
])
def test_gps_area_classifier(label, lat, lng, expected):
    from webhook_app import _area_from_coords
    assert _area_from_coords(lat, lng) == expected, label


# ── Duration parser (client-stated session length) ────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("массаж тела 90 минут", 90),
    ("body massage 90 min", 90),
    ("1.5 hours please", 90),
    ("полтора часа", 90),
    ("2 hour massage", 120),
    ("60min", 60),
    ("полчаса", 30),
    # Must NOT mistake a price or a clock time for a duration.
    ("90 aed cash", None),
    ("запись на 17:00", None),
    ("маникюр", None),
])
def test_detect_duration_minutes(text, expected):
    from webhook_app import _detect_duration_minutes
    assert _detect_duration_minutes(text.lower()) == expected
