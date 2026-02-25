"""Redis-backed message buffer for Crystal Lab Booking Bot

Replaces in-memory message_buffers/last_activity dicts with Redis.
Processing tasks (asyncio.Task) remain in memory since they can't be serialized.

Supports both Telegram (int user_id) and WhatsApp (phone string) as keys.
Falls back to in-memory storage if Redis is unavailable.
"""

import json
import time
import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger


class MessageBuffer:
    """Message buffer with Redis backend and in-memory fallback."""

    # Redis key prefixes
    BUFFER_PREFIX = "cl:buffer:"
    ACTIVITY_PREFIX = "cl:activity:"
    BUFFER_TTL = 300  # 5 min TTL for buffer keys (auto-cleanup)

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._redis = None
        self._use_redis = False

        # In-memory fallback (also used for asyncio.Tasks which can't go to Redis)
        self._memory_buffers: Dict[str, List[Any]] = {}
        self._memory_activity: Dict[str, float] = {}
        self.processing_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self):
        """Connect to Redis. Falls back to in-memory if unavailable."""
        if not self.redis_url:
            logger.info("No REDIS_URL configured, using in-memory buffer")
            return

        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            # Test connection
            await self._redis.ping()
            self._use_redis = True
            logger.info(f"Redis buffer connected: {self._mask_url(self.redis_url)}")
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}), using in-memory buffer")
            self._redis = None
            self._use_redis = False

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            logger.info("Redis buffer connection closed")

    @staticmethod
    def _mask_url(url: str) -> str:
        if "@" in url:
            parts = url.split("@")
            return f"redis://****@{parts[-1]}"
        return url

    def _key(self, prefix: str, user_key: str) -> str:
        return f"{prefix}{user_key}"

    # ── Buffer Operations ────────────────────────────────────────────

    async def add_message(self, user_key: str, message_data: dict) -> int:
        """Add a message to the user's buffer. Returns buffer size."""
        key = str(user_key)

        if self._use_redis:
            try:
                redis_key = self._key(self.BUFFER_PREFIX, key)
                await self._redis.rpush(redis_key, json.dumps(message_data, default=str))
                await self._redis.expire(redis_key, self.BUFFER_TTL)
                count = await self._redis.llen(redis_key)
                return count
            except Exception as e:
                logger.error(f"Redis add_message error: {e}")

        # Fallback to memory
        if key not in self._memory_buffers:
            self._memory_buffers[key] = []
        self._memory_buffers[key].append(message_data)
        return len(self._memory_buffers[key])

    async def get_messages(self, user_key: str) -> List[dict]:
        """Get all buffered messages for a user."""
        key = str(user_key)

        if self._use_redis:
            try:
                redis_key = self._key(self.BUFFER_PREFIX, key)
                raw_messages = await self._redis.lrange(redis_key, 0, -1)
                return [json.loads(m) for m in raw_messages]
            except Exception as e:
                logger.error(f"Redis get_messages error: {e}")

        return self._memory_buffers.get(key, [])

    async def clear_messages(self, user_key: str) -> None:
        """Clear the message buffer for a user."""
        key = str(user_key)

        if self._use_redis:
            try:
                await self._redis.delete(self._key(self.BUFFER_PREFIX, key))
            except Exception as e:
                logger.error(f"Redis clear_messages error: {e}")

        self._memory_buffers.pop(key, None)

    # ── Activity Tracking ────────────────────────────────────────────

    async def update_activity(self, user_key: str) -> None:
        """Record activity timestamp for a user."""
        key = str(user_key)
        now = time.time()

        if self._use_redis:
            try:
                redis_key = self._key(self.ACTIVITY_PREFIX, key)
                await self._redis.set(redis_key, str(now), ex=self.BUFFER_TTL)
                self._memory_activity[key] = now  # Keep local copy for fast reads
                return
            except Exception as e:
                logger.error(f"Redis update_activity error: {e}")

        self._memory_activity[key] = now

    async def get_last_activity(self, user_key: str) -> float:
        """Get last activity timestamp. Returns 0.0 if never active."""
        key = str(user_key)

        # Fast path: local copy
        if key in self._memory_activity:
            return self._memory_activity[key]

        if self._use_redis:
            try:
                redis_key = self._key(self.ACTIVITY_PREFIX, key)
                val = await self._redis.get(redis_key)
                if val:
                    ts = float(val)
                    self._memory_activity[key] = ts
                    return ts
            except Exception as e:
                logger.error(f"Redis get_last_activity error: {e}")

        return 0.0

    # ── Processing Task Management (always in-memory) ────────────────

    def get_processing_task(self, user_key: str) -> Optional[asyncio.Task]:
        """Get the active processing task for a user."""
        return self.processing_tasks.get(str(user_key))

    def set_processing_task(self, user_key: str, task: asyncio.Task) -> None:
        """Set the processing task for a user."""
        self.processing_tasks[str(user_key)] = task

    def clear_processing_task(self, user_key: str) -> None:
        """Remove the processing task reference."""
        self.processing_tasks.pop(str(user_key), None)

    def cancel_processing_task(self, user_key: str) -> bool:
        """Cancel existing processing task if running. Returns True if cancelled."""
        key = str(user_key)
        task = self.processing_tasks.get(key)
        if task and not task.done():
            task.cancel()
            logger.debug(f"Cancelled processing task for {key}")
            return True
        return False


# Global buffer instance
_buffer: Optional[MessageBuffer] = None


async def init_buffer(redis_url: Optional[str] = None) -> MessageBuffer:
    """Initialize global message buffer."""
    global _buffer
    _buffer = MessageBuffer(redis_url)
    await _buffer.connect()
    return _buffer


def get_buffer() -> MessageBuffer:
    """Get global buffer instance."""
    if _buffer is None:
        raise RuntimeError("Message buffer not initialized. Call init_buffer() first.")
    return _buffer
