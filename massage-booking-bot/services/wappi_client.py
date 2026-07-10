"""Wappi.pro WhatsApp API client.

Unofficial WhatsApp API via QR code binding. Used for:
- Receiving incoming WhatsApp messages via webhook
- Sending text messages back to clients
"""

import asyncio
import base64
import os

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

    @staticmethod
    def _normalize_recipient(recipient: str) -> str:
        """Reduce a recipient to bare digits Wappi expects.

        Strips @c.us/@g.us suffixes, '+', and any whitespace (incl. internal,
        e.g. "+971 50 123 4567" → "971501234567").
        """
        recipient = recipient.replace("@c.us", "").replace("@g.us", "").replace("+", "")
        return "".join(recipient.split())

    async def _post_with_retry(
        self,
        url: str,
        params: dict,
        payload: dict,
        log_label: str,
        timeout: float = 10,
    ) -> Optional[Dict[str, Any]]:
        """POST to Wappi with retry on 5xx/network errors (4xx is not retried).

        Shared by send_message / send_image so both get identical retry,
        backoff and error-classification behaviour.
        """
        session = await self._get_session()
        last_exc: Optional[Exception] = None
        last_data: Optional[Dict[str, Any]] = None
        for attempt in range(1, _SEND_MAX_ATTEMPTS + 1):
            try:
                async with session.post(
                    url, params=params, headers=self._headers, json=payload, timeout=timeout
                ) as resp:
                    data = await resp.json()
                    last_data = data
                    if resp.status == 200:
                        # HTTP 200 does NOT guarantee delivery — Wappi can return
                        # 200 with a body error (e.g. recipient not on WhatsApp).
                        # Surface that instead of logging a false "ok" (the
                        # "silently never replies" class of prod failure).
                        _bs = str((data or {}).get("status") or "").lower() if isinstance(data, dict) else ""
                        if _bs and _bs not in ("done", "success", "ok", "sent", "queued", "delivered", "processing"):
                            logger.error(
                                f"Wappi {log_label}: HTTP 200 but body status={_bs!r} — "
                                f"message likely NOT delivered: {data}"
                            )
                        else:
                            logger.info(f"Wappi: {log_label} ok")
                        return data
                    # 4xx (auth/invalid recipient) — no point retrying.
                    if 400 <= resp.status < 500:
                        logger.error(f"Wappi {log_label} failed ({resp.status}) — no retry: {data}")
                        return data
                    logger.warning(
                        f"Wappi {log_label} attempt {attempt}/{_SEND_MAX_ATTEMPTS} "
                        f"failed ({resp.status}): {data}"
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exc = e
                logger.warning(
                    f"Wappi {log_label} attempt {attempt}/{_SEND_MAX_ATTEMPTS} exception: {e}"
                )
            except Exception as e:
                # Unexpected — log full trace and don't retry.
                logger.error(f"Wappi {log_label} unexpected exception: {e}", exc_info=True)
                return None

            if attempt < _SEND_MAX_ATTEMPTS:
                await asyncio.sleep(_SEND_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))

        logger.error(
            f"Wappi {log_label} exhausted {_SEND_MAX_ATTEMPTS} attempts: "
            f"last_exc={last_exc}, last_data={last_data}"
        )
        return last_data

    async def send_message(self, recipient: str, body: str) -> Optional[Dict[str, Any]]:
        """Send a text message to a WhatsApp recipient.

        Args:
            recipient: Phone number in international format (e.g. "971501234567")
            body: Message text
        """
        if not self.token or not self.profile_id:
            logger.error("Wappi: token or profile_id not configured")
            return None

        recipient = self._normalize_recipient(recipient)
        url = f"{self.BASE_URL}/api/sync/message/send"
        params = {"profile_id": self.profile_id}
        payload = {"body": body, "recipient": recipient}

        return await self._post_with_retry(
            url, params, payload, log_label=f"send text to {recipient}: {body[:50]}"
        )

    async def send_image(
        self, recipient: str, image_path: str, caption: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Send an image to a WhatsApp recipient.

        The Wappi image endpoint takes the file as a raw base64 string
        (no ``data:`` prefix). See wappi.pro/api-documentation.

        Args:
            recipient: Phone number in international format (e.g. "971501234567")
            image_path: Local filesystem path to the image file
            caption: Optional caption shown under the image
        """
        if not self.token or not self.profile_id:
            logger.error("Wappi: token or profile_id not configured")
            return None

        if not os.path.exists(image_path):
            logger.error(f"Wappi send_image: file not found: {image_path}")
            return None

        try:
            with open(image_path, "rb") as f:
                b64_file = base64.b64encode(f.read()).decode("ascii")
        except OSError as e:
            logger.error(f"Wappi send_image: cannot read {image_path}: {e}")
            return None

        recipient = self._normalize_recipient(recipient)
        url = f"{self.BASE_URL}/api/sync/message/img/send"
        params = {"profile_id": self.profile_id}
        payload = {
            "recipient": recipient,
            "b64_file": b64_file,
            "file_name": os.path.basename(image_path),
        }
        if caption:
            payload["caption"] = caption

        # Base64 of a photo is ~100 KB — allow a longer timeout than text.
        return await self._post_with_retry(
            url, params, payload,
            log_label=f"send image {os.path.basename(image_path)} to {recipient}",
            timeout=20,
        )

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


def parse_incoming_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract relevant fields from Wappi incoming webhook payload.

    Wappi sends: {"messages": [{wh_type, body, from, senderName, type, time, ...}]}
    or sometimes: {"messages": {...}} (single object)

    Returns dict with:
        phone, text, sender_name, message_type, timestamp, message_id,
        latitude (float|None), longitude (float|None)
    or None if not a processable incoming message.

    For location messages (type="location") Wappi exposes coordinates in
    several shapes depending on WhatsApp client and SDK version:
        - top-level lat / lng (or latitude / longitude)
        - nested "location": {"lat", "lng"} or {"latitude", "longitude"}
        - sometimes body = "lat,lng" string fallback
    We probe all of them and return None-safe floats.
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

    latitude, longitude = _extract_coords(msg)

    return {
        "phone": phone,
        "text": msg.get("body", ""),
        "sender_name": msg.get("senderName", "") or msg.get("contact_name", ""),
        "message_type": msg.get("type", "chat"),
        "timestamp": msg.get("time", 0),
        "message_id": msg.get("id", ""),
        "latitude": latitude,
        "longitude": longitude,
    }


def _extract_coords(msg: Dict[str, Any]) -> tuple:
    """Best-effort extraction of (lat, lng) floats from a Wappi message.

    Returns (None, None) if no valid coordinates are found.
    """
    def _to_float(v: Any) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # 1) Top-level keys.
    lat = _to_float(msg.get("lat") or msg.get("latitude"))
    lng = _to_float(msg.get("lng") or msg.get("longitude"))
    if lat is not None and lng is not None:
        return lat, lng

    # 2) Nested "location" object.
    loc = msg.get("location")
    if isinstance(loc, dict):
        lat = _to_float(loc.get("lat") or loc.get("latitude"))
        lng = _to_float(loc.get("lng") or loc.get("longitude"))
        if lat is not None and lng is not None:
            return lat, lng

    # 3) Fallback: body = "lat,lng".
    body = msg.get("body", "")
    if isinstance(body, str) and "," in body and msg.get("type") == "location":
        parts = [p.strip() for p in body.split(",", 1)]
        if len(parts) == 2:
            lat = _to_float(parts[0])
            lng = _to_float(parts[1])
            if lat is not None and lng is not None:
                return lat, lng

    return None, None
