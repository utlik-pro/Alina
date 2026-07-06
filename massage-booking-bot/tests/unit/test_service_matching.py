"""Unit tests for YClients service-name matching (find_service_id).

Locks in the fixes for the client-reported gaps: combos, classical lashes,
prenatal/postpartum, and the "pedicure → Men's/combo" mis-match.
"""

import pytest

from services.yclients_service import YClientsService

# Representative slice of the real Crystal Lab catalog.
CATALOG = [
    {"id": 21706335, "title": "Lymphatic drainage 60 min (new)"},
    {"id": 21706704, "title": "Face + body 110 min (new)"},
    {"id": 16435841, "title": "Classical volume"},
    {"id": 16435836, "title": "2d volume"},
    {"id": 16435830, "title": "Russian volume"},
    {"id": 21706467, "title": "Prenatal after 4 months (new)"},
    {"id": 21706416, "title": "Postpartum 60 min (new)"},
    {"id": 16432334, "title": "Gellish Russian pedicure with machine (smart disc)"},
    {"id": 16709148, "title": "Men's pedicure"},
    {"id": 23828859, "title": "Russian gellish manicure+pedicure"},
    {"id": 18510263, "title": "Combo Russian gellish mani + pedi"},
    {"id": 16432353, "title": "Russian gelish manicure (with machine)"},
    {"id": 18510280, "title": "Japanese pedicure"},
]


@pytest.fixture
def yc(monkeypatch):
    svc = YClientsService()
    async def catalog(*a, **k):
        return CATALOG
    monkeypatch.setattr(svc, "get_services", catalog)
    return svc


@pytest.mark.asyncio
@pytest.mark.parametrize("token,expected_id", [
    ("body_face_combo", 21706704),
    ("classic_eyelash_extension", 16435841),
    ("prenatal_massage", 21706467),
    ("postpartum_massage", 21706416),
    ("russian_manicure", 16432353),
])
async def test_matches(yc, token, expected_id):
    assert await yc.find_service_id(token) == expected_id


@pytest.mark.asyncio
async def test_bare_pedicure_is_womens_standalone_not_mens_or_combo(yc):
    # Must be the standalone women's Russian pedicure, never "Men's pedicure"
    # (won on shortness) or the manicure+pedicure combo (substring match).
    assert await yc.find_service_id("pedicure") == 16432334


@pytest.mark.asyncio
async def test_combo_query_still_returns_combo(yc):
    # When the client explicitly wants a combo, the penalty must not apply.
    assert await yc.find_service_id("combo_mani_pedi") == 18510263


@pytest.mark.asyncio
async def test_unknown_service_returns_none(yc):
    assert await yc.find_service_id("hot_stone") is None
