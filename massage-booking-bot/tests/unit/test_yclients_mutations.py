"""YClients record mutations (owner decision 2026-07-10: the agent manages
the calendar itself — cancel deletes the record, reschedule moves it).

The HARD GUARD under test: a record is only ever mutated when its client
phone matches the WhatsApp client asking. Anything else refuses.
"""

import pytest

from services.yclients_service import YClientsService


@pytest.fixture
def svc():
    return YClientsService()


# ─── phone guard ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b,match", [
    ("971501234567", "+971 50 123 45 67", True),
    ("+375293726634", "375293726634", True),
    ("971501234567", "971509999999", False),
    ("", "971501234567", False),
    (None, None, False),
    ("123", "123", False),  # too short to trust
])
def test_phones_match(a, b, match):
    assert YClientsService._phones_match(a, b) is match


# ─── cancel_record ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_refuses_foreign_record(svc, monkeypatch):
    """A record belonging to ANOTHER client must never be deleted."""
    async def fake_get_record(rid):
        return {"id": rid, "client": {"phone": "971509999999"}}
    monkeypatch.setattr(svc, "get_record", fake_get_record)

    deleted = []
    async def boom(*a, **k):
        deleted.append(1)
    monkeypatch.setattr(svc, "_get_session", boom)

    assert await svc.cancel_record(111, "375293726634") is False
    assert not deleted  # never even opened a session


@pytest.mark.asyncio
async def test_cancel_refuses_marker_record(svc, monkeypatch):
    """Emirate marker records have no client — must never be touched."""
    async def fake_get_record(rid):
        return {"id": rid, "client": None, "comment": "Дубай"}
    monkeypatch.setattr(svc, "get_record", fake_get_record)
    assert await svc.cancel_record(222, "375293726634") is False


@pytest.mark.asyncio
async def test_cancel_refuses_on_api_failure(svc, monkeypatch):
    """Record unfetchable (outage / not found) → refuse, don't delete blind."""
    async def fake_get_record(rid):
        return None
    monkeypatch.setattr(svc, "get_record", fake_get_record)
    assert await svc.cancel_record(333, "375293726634") is False


@pytest.mark.asyncio
async def test_cancel_deletes_own_record(svc, monkeypatch):
    async def fake_get_record(rid):
        return {"id": rid, "client": {"phone": "+375 29 372-66-34"}}
    monkeypatch.setattr(svc, "get_record", fake_get_record)

    calls = {}

    class FakeResp:
        status = 204
        async def text(self):
            return ""
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def delete(self, url, headers=None):
            calls["url"] = url
            return FakeResp()

    async def fake_session():
        return FakeSession()
    monkeypatch.setattr(svc, "_get_session", fake_session)

    assert await svc.cancel_record(444, "375293726634") is True
    assert "/record/" in calls["url"] and calls["url"].endswith("/444")


# ─── reschedule_record ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reschedule_refuses_foreign_record(svc, monkeypatch):
    async def fake_get_record(rid):
        return {"id": rid, "client": {"phone": "971509999999"}}
    monkeypatch.setattr(svc, "get_record", fake_get_record)
    assert await svc.reschedule_record(1, "375293726634", "2026-07-12", "15:00") is False


@pytest.mark.asyncio
async def test_reschedule_moves_own_record_preserving_services(svc, monkeypatch):
    async def fake_get_record(rid):
        return {
            "id": rid,
            "date": "2026-07-11 12:00:00",
            "client": {"phone": "375293726634", "name": "Olga"},
            "staff": {"id": 12345, "name": "Екатерина"},
            "seance_length": 5400,
            "attendance": 0,
            "comment": "[TEST] bot booking #13",
            "services": [{"id": 777, "cost": 460, "first_cost": 460}],
        }
    monkeypatch.setattr(svc, "get_record", fake_get_record)

    sent = {}

    class FakeResp:
        status = 200
        async def json(self):
            return {"success": True, "data": {"id": 1}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def put(self, url, headers=None, json=None):
            sent["url"] = url
            sent["payload"] = json
            return FakeResp()

    async def fake_session():
        return FakeSession()
    monkeypatch.setattr(svc, "_get_session", fake_session)

    ok = await svc.reschedule_record(555, "375293726634", "2026-07-12", "15:00")
    assert ok is True
    p = sent["payload"]
    assert p["datetime"] == "2026-07-12T15:00:00+03:00"
    assert p["staff_id"] == 12345
    assert p["seance_length"] == 5400  # duration preserved when not overridden
    assert p["services"] == [{"id": 777, "cost": 460, "first_cost": 460}]
    assert p["save_if_busy"] is False
    assert "Перенесено агентом" in p["comment"]
    assert p["client"]["name"] == "Olga"


@pytest.mark.asyncio
async def test_reschedule_duration_override(svc, monkeypatch):
    async def fake_get_record(rid):
        return {
            "id": rid,
            "client": {"phone": "375293726634"},
            "staff": {"id": 1},
            "seance_length": 3600,
            "services": [],
        }
    monkeypatch.setattr(svc, "get_record", fake_get_record)

    sent = {}

    class FakeResp:
        status = 200
        async def json(self):
            return {"success": True}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def put(self, url, headers=None, json=None):
            sent["payload"] = json
            return FakeResp()

    async def fake_session():
        return FakeSession()
    monkeypatch.setattr(svc, "_get_session", fake_session)

    assert await svc.reschedule_record(1, "375293726634", "2026-07-12", "15:00",
                                       duration_minutes=90) is True
    assert sent["payload"]["seance_length"] == 90 * 60


# ─── find_record_by_phone ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_find_record_unique_match(svc, monkeypatch):
    async def fake_get(endpoint, params=None):
        return {"data": [
            {"id": 1, "deleted": False, "client": {"phone": "971509999999"}},
            {"id": 2, "deleted": False, "client": {"phone": "375293726634"}},
            {"id": 3, "deleted": True, "client": {"phone": "375293726634"}},
            {"id": 4, "deleted": False, "client": None},  # marker
        ]}
    monkeypatch.setattr(svc, "_get", fake_get)
    rec = await svc.find_record_by_phone("375293726634", "2026-07-11")
    assert rec and rec["id"] == 2


@pytest.mark.asyncio
async def test_find_record_ambiguous_returns_none(svc, monkeypatch):
    async def fake_get(endpoint, params=None):
        return {"data": [
            {"id": 1, "deleted": False, "client": {"phone": "375293726634"}},
            {"id": 2, "deleted": False, "client": {"phone": "375293726634"}},
        ]}
    monkeypatch.setattr(svc, "_get", fake_get)
    assert await svc.find_record_by_phone("375293726634", "2026-07-11") is None


@pytest.mark.asyncio
async def test_find_record_outage_returns_none(svc, monkeypatch):
    async def fake_get(endpoint, params=None):
        return None
    monkeypatch.setattr(svc, "_get", fake_get)
    assert await svc.find_record_by_phone("375293726634", "2026-07-11") is None
