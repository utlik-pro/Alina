#!/usr/bin/env python3
"""Exercise the production app's imports, lifespan, async DB and health offline.

Uses only disposable data and dummy credentials. Telegram webhook registration
is the sole mocked startup call; Docker CI also disables network access.
"""
import asyncio
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_temporary_db = TemporaryDirectory(prefix='crystal-startup-')
os.environ.update(
    TELEGRAM_BOT_TOKEN='0:test', OPENAI_API_KEY='startup-check',
    DATABASE_URL=f'sqlite+aiosqlite:///{_temporary_db.name}/startup.db', REDIS_URL='',
    MOCK_YCLIENTS='true', MOCK_WHATSAPP='true', RENDER='false',
    ADMIN_GROUP_CHAT_ID='', WAPPI_TOKEN='', WAPPI_PROFILE_ID='',
    MANYCHAT_API_KEY='', INSTAGRAM_ACCESS_TOKEN='',
    RENDER_GIT_COMMIT='startup-check',
)


async def main():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    import bot
    import webhook_app as wh
    from database.db import get_db

    with patch.object(wh.Bot, 'set_webhook', new_callable=AsyncMock) as register:
        async with wh.app.router.lifespan_context(wh.app):
            register.assert_awaited_once()
            # Actually enter the async engine: importing SQLAlchemy alone missed
            # the greenlet dependency in the deployment that motivated this check.
            async with get_db().engine.connect() as connection:
                assert await connection.scalar(text('SELECT count(*) FROM bookings')) == 0
            assert bot.message_service is not None
            async with AsyncClient(transport=ASGITransport(app=wh.app), base_url='http://test') as client:
                response = await client.get('/')
                assert response.status_code == 200
                assert response.json()['revision'] == 'startup-check'
                assert response.json()['status'] == 'ok'
    print('Startup, async database, health and shutdown: OK')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        _temporary_db.cleanup()
