"""Wappi.pro WhatsApp API client.

Unofficial WhatsApp API via QR code binding. Used for:
- Receiving incoming WhatsApp messages via webhook
- Sending text messages back to clients
"""

import asyncio

import aiohttp
from typing import Optional, Dict, Any
from loguru import logger

from config import config

# Retry config for transient Wappi/network failures when sending messages.
# 5xx and network errors are retried; 4xx (auth, invalid recipient) are not.
_SEND_MAX_ATTEMPTS = 3
_SEND_BACKOFF_BASE_SEC = 0.5  # 0.5, 1.0, 2.0 s


class WappiClient:
    """Wappi WhatsApp API client."""

    BASE_URL = "https://wappi.pro"

    def __init__(self):
        self.token = config.WAPPI_TOKEN
        self.profile_id = config.WAPPI_PROFILE_ID
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    async def send_message(self, recipient: str, body: str) -> Optional[Dict[str, Any]]:
        """Send a text message to a WhatsApp recipient.

        Args:
            recipient: Phone number in international format (e.g. "971501234567")
            body: Message text
        """
        if not self.token or not self.profile_id:
            logger.error("Wappi: token or profile_id not configured")
            return None

        # Normalize recipient — strip @c.us suffix if present
        recipient = recipient.replace("@c.us", "").replace("+", "").strip()

        url = f"{self.BASE_URL}/api/sync/message/send"
        params = {"profile_id": self.profile_id}
        payload = {"body": body, "recipient": recipient}

        session = await self._get_session()
        last_exc: Optional[Exception] = None
        last_data: Optional[Dict[str, Any]] = None
        for attempt in range(1, _SEND_MAX_ATTEMPTS + 1):
            try:
                async with session.post(
                    url, params=params, headers=self._headers, json=payload, timeout=10
                ) as resp:
                    data = await resp.json()
                    last_data = data
                    if resp.status == 200:
                        logger.info(f"Wappi: sent to {recipient}: {body[:50]}...")
                        return data
                    # 4xx (auth/invalid recipient) — no point retrying.
                    if 400 <= resp.status < 500:
                        logger.error(f"Wappi send failed ({resp.status}) — no retry: {data}")
                        return data
                    logger.warning(
                        f"Wappi send attempt {attempt}/{_SEND_MAX_ATTEMPTS} "
                        f"failed ({resp.status}): {data}"
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exc = e
                logger.warning(
                    f"Wappi send attempt {attempt}/{_SEND_MAX_ATTEMPTS} exception: {e}"
                )
            except Exception as e:
                # Unexpected — log full trace and don't retry.
                logger.error(f"Wappi send unexpected exception: {e}", exc_info=True)
                return None

            if attempt < _SEND_MAX_ATTEMPTS:
                await asyncio.sleep(_SEND_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))

        logger.error(
            f"Wappi send exhausted {_SEND_MAX_ATTEMPTS} attempts "
            f"to {recipient}: last_exc={last_exc}, last_data={last_data}"
        )
        return last_data

    async def set_webhook(self, webhook_url: str, auth: str = "") -> bool:
        """Configure Wappi to send events to our webhook URL.

        Args:
            webhook_url: Public URL to receive webhooks
            auth: Optional secret for Authorization header on webhook requests
        """
        if not self.token or not self.profile_id:
            return False

        url = f"{self.BASE_URL}/api/webhook/url/set"
        params = {"profile_id": self.profile_id, "url": webhook_url}
        if auth:
            params["auth"] = auth

        session = await self._get_session()
        try:
            async with session.post(url, params=params, headers=self._headers, timeout=10) as resp:
                if resp.status == 200:
                    logger.info(f"Wappi: webhook set to {webhook_url}")
                    return True
                logger.error(f"Wappi set_webhook failed: {resp.status}")
                return False
        except Exception as e:
            logger.error(f"Wappi set_webhook exception: {e}")
            return False


def parse_incoming_message(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extract relevant fields from Wappi incoming webhook payload.

    Wappi sends: {"messages": [{wh_type, body, from, senderName, type, time, ...}]}
    or sometimes: {"messages": {...}} (single object)

    Returns dict with: {phone, text, sender_name, message_type, timestamp}
    or None if not a processable incoming message.
    """
    messages = payload.get("messages")
    if not messages:
        return None

    # Handle both list and object forms
    if isinstance(messages, dict):
        msg = messages
    elif isinstance(messages, list) and messages:
        msg = messages[0]
    else:
        return None

    # Only process incoming messages, not delivery status / outgoing
    wh_type = msg.get("wh_type")
    if wh_type != "incoming_message":
        return None

    # Skip messages sent by the bot owner (is_me=True)
    if msg.get("is_me"):
        return None

    phone = msg.get("from", "").replace("@c.us", "").replace("@g.us", "")
    if not phone:
        return None

    # Skip group messages for now (group IDs end in @g.us)
    if "@g.us" in msg.get("from", ""):
        return None

    return {
        "phone": phone,
        "text": msg.get("body", ""),
        "sender_name": msg.get("senderName", "") or msg.get("contact_name", ""),
        "message_type": msg.get("type", "chat"),
        "timestamp": msg.get("time", 0),
        "message_id": msg.get("id", ""),
    }
