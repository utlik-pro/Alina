from unittest.mock import AsyncMock
import pytest
from httpx import ASGITransport, AsyncClient
import webhook_app as wh
import services.admin_reports as routes


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['/admin/funnel-report', '/admin/reconciliation'])
async def test_reports_deny_missing_auth_before_reading_data(monkeypatch, endpoint):
    reader = AsyncMock()
    monkeypatch.setattr(routes, 'load_funnel_report', reader)
    monkeypatch.setattr(routes, 'reconciliation_report', reader)
    monkeypatch.setattr(routes.config, 'WEBHOOK_SECRET', '')
    monkeypatch.setattr(routes.config, 'MANYCHAT_WEBHOOK_SECRET', '')
    async with AsyncClient(transport=ASGITransport(app=wh.app), base_url='http://test') as client:
        response = await client.get(endpoint)
    assert response.status_code == 403
    reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_report_outage_is_503_not_zero_sales(monkeypatch):
    monkeypatch.setattr(routes.config, 'MANYCHAT_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.setattr(routes, 'get_db', lambda: object())
    monkeypatch.setattr(routes, 'load_funnel_report', AsyncMock(side_effect=RuntimeError('down')))
    async with AsyncClient(transport=ASGITransport(app=wh.app), base_url='http://test') as client:
        response = await client.get('/admin/funnel-report', headers={'X-Manychat-Secret': 'test-secret'})
    assert response.status_code == 503
    assert 'summary' not in response.json()


@pytest.mark.asyncio
async def test_authenticated_report_has_no_store_and_bounds(monkeypatch):
    monkeypatch.setattr(routes.config, 'MANYCHAT_WEBHOOK_SECRET', 'test-secret')
    monkeypatch.setattr(routes, 'get_db', lambda: object())
    monkeypatch.setattr(routes, 'load_funnel_report', AsyncMock(return_value={'summary': {'inbound_contacts': 0}}))
    async with AsyncClient(transport=ASGITransport(app=wh.app), base_url='http://test') as client:
        response = await client.get('/admin/funnel-report', headers={'X-Manychat-Secret': 'test-secret'})
        bad = await client.get('/admin/funnel-report?hours=9999', headers={'X-Manychat-Secret': 'test-secret'})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert bad.status_code == 422
