"""Database connection and session management"""

from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from loguru import logger

from .models import Base


class Database:
    """Database manager with async support"""

    def __init__(self, database_url: str):
        """
        Initialize database connection

        Args:
            database_url: PostgreSQL connection string
                Example: "postgresql+asyncpg://user:password@localhost:5432/dbname"
        """
        self.database_url = database_url

        # Create async engine
        # Use NullPool for SQLite (no real pooling), connection pool for PostgreSQL
        engine_kwargs = {
            "echo": False,  # Set to True for SQL query logging
        }

        if "sqlite" in database_url:
            engine_kwargs["poolclass"] = NullPool
        else:
            # PostgreSQL: use connection pooling
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10

        self.engine = create_async_engine(database_url, **engine_kwargs)

        # Create async session factory
        self.async_session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info(f"Database initialized: {self._mask_url(database_url)}")

    @staticmethod
    def _mask_url(url: str) -> str:
        """Mask password in database URL for logging"""
        if "@" in url and ":" in url:
            parts = url.split("@")
            credentials = parts[0].split("//")[1]
            if ":" in credentials:
                user = credentials.split(":")[0]
                return url.replace(credentials, f"{user}:****")
        return url

    async def create_tables(self):
        """Create all tables in the database"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")
        await self._ensure_columns()

    async def _ensure_columns(self):
        """Lightweight auto-migration: add new columns to existing tables.

        SQLAlchemy's create_all() only creates *missing tables*, never new
        columns on existing ones. When we add a field to a model we must
        ALTER TABLE here so already-deployed databases (SQLite dev,
        Postgres prod) pick it up without a manual migration step.

        Only additive ADD COLUMN is supported — safe and idempotent.
        """
        from sqlalchemy import inspect as _sa_inspect, text as _sa_text

        # table -> {column: SQL type}. Keep types portable (SQLite + Postgres).
        wanted = {
            "clients": {
                "area": "VARCHAR(50)",
                "preferred_therapist": "VARCHAR(255)",
                "avoid_therapist": "VARCHAR(255)",
                "medical_notes": "TEXT",
            },
            "bookings": {
                "area": "VARCHAR(50)",
                "penalty_amount": "FLOAT",
                "penalty_reason": "VARCHAR(500)",
                "rescheduled_to": "INTEGER",
                "confirmation_sent_at": "TIMESTAMP",
                "survey_sent_at": "TIMESTAMP",
                "package_id": "INTEGER",
                "payment_status": "VARCHAR(30)",
            },
        }

        # 1) Read schema (one read-only transaction).
        async with self.engine.begin() as conn:
            existing_tables = await conn.run_sync(
                lambda sync_conn: _sa_inspect(sync_conn).get_table_names()
            )
            missing: list[tuple[str, str, str]] = []  # (table, col, type)
            for table, columns in wanted.items():
                if table not in existing_tables:
                    continue
                existing_cols = await conn.run_sync(
                    lambda sync_conn, t=table: {
                        c["name"] for c in _sa_inspect(sync_conn).get_columns(t)
                    }
                )
                for col, col_type in columns.items():
                    if col not in existing_cols:
                        missing.append((table, col, col_type))

        # 2) Apply each ALTER in ITS OWN transaction. On Postgres a failed
        #    statement poisons the whole transaction ("current transaction is
        #    aborted"), so a single bad ALTER must not skip the rest. Isolating
        #    each one keeps every other column migrating independently.
        for table, col, col_type in missing:
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(
                        _sa_text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    )
                logger.info(f"Auto-migration: added {table}.{col} ({col_type})")
            except Exception as e:
                logger.warning(f"Auto-migration skip {table}.{col}: {e}")

    async def drop_tables(self):
        """Drop all tables (use with caution!)"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.warning("All database tables dropped")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager for database sessions

        Usage:
            async with db.session() as session:
                result = await session.execute(query)
                await session.commit()
        """
        session: AsyncSession = self.async_session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()

    async def close(self):
        """Close database connection"""
        await self.engine.dispose()
        logger.info("Database connection closed")


# Global database instance
_db: Optional[Database] = None


def init_db(database_url: str) -> Database:
    """Initialize global database instance"""
    global _db
    _db = Database(database_url)
    return _db


def get_db() -> Database:
    """Get global database instance"""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db
