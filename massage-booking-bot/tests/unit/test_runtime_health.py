import pytest
from httpx import ASGITransport, AsyncClient
import webhook_app as wh

@pytest.mark.asyncio
async def test_runtime_health_exposes_revision_and_booking_model(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "test-revision")
    async with AsyncClient(transport=ASGITransport(app=wh.app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "v2"
    assert data["revision"] == "test-revision"
    assert data["booking_model"] == wh.config.OPENAI_MODEL
