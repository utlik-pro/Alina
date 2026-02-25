"""Initialize database - create tables"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import init_db, Database
from config import config
from loguru import logger


async def init_database():
    """Initialize database and create all tables"""
    logger.info(f"Initializing database: {config.DATABASE_URL}")

    # Initialize database
    db = init_db(config.DATABASE_URL)

    # Create all tables
    await db.create_tables()

    logger.info("✅ Database initialized successfully!")
    logger.info("Tables created: clients, messages, bookings, dialog_sessions, packages")

    # Close connection
    await db.close()


if __name__ == "__main__":
    asyncio.run(init_database())
