"""Client.area persistence — survives a restart so the agent doesn't re-ask
"which area?" ("снова спрашивает откуда я") after a Render deploy / a delayed
reply to the post-session survey.

Covers: the model column, ClientService.update_client(area=…) / reset_client,
and the lightweight auto-migration that ALTERs an already-deployed table (prod
picks up the column without a manual migration).
"""

import tempfile

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from database.db import Database
from database.services import ClientService


def _tmp_url():
    return "sqlite+aiosqlite:///" + tempfile.mktemp(suffix=".db")


@pytest.mark.asyncio
async def test_area_persists_and_resets():
    db = Database(_tmp_url())
    await db.create_tables()
    cs = ClientService(db)

    await cs.get_or_create_client("wappi_1")
    await cs.update_client("wappi_1", area="abu_dhabi")
    assert (await cs.get_or_create_client("wappi_1")).area == "abu_dhabi"

    # A later explicit mention switches the persisted area.
    await cs.update_client("wappi_1", area="dubai")
    assert (await cs.get_or_create_client("wappi_1")).area == "dubai"

    # /clear wipes it so a fresh conversation starts clean.
    await cs.reset_client("wappi_1")
    assert (await cs.get_or_create_client("wappi_1")).area is None
    await db.close()


@pytest.mark.asyncio
async def test_auto_migration_adds_area_to_existing_table():
    """An already-deployed DB whose `clients` table predates the area column
    must gain it on startup (create_tables → _ensure_columns), not error."""
    url = _tmp_url()
    eng = create_async_engine(url)
    async with eng.begin() as c:
        await c.execute(text(
            "CREATE TABLE clients (id INTEGER PRIMARY KEY, "
            "telegram_id VARCHAR(50), name VARCHAR(255))"
        ))
    async with eng.begin() as c:
        before = await c.run_sync(lambda sc: [col["name"] for col in inspect(sc).get_columns("clients")])
    assert "area" not in before
    await eng.dispose()

    await Database(url).create_tables()  # runs _ensure_columns

    eng2 = create_async_engine(url)
    async with eng2.begin() as c:
        after = await c.run_sync(lambda sc: [col["name"] for col in inspect(sc).get_columns("clients")])
    await eng2.dispose()
    assert "area" in after
