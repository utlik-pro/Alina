"""WhatsApp Cloud API Client for Crystal Lab Booking Bot"""

import httpx
from typing import Optional, Dict, Any, List
from loguru import logger


class WhatsAppClient:
    """Client for WhatsApp Business Cloud API v21.0"""

    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v21.0",
        verify_token: str = "",
    ):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.verify_token = verify_token
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def messages_url(self) -> str:
        return f"{self.BASE_URL}/{self.api_version}/{self.phone_number_id}/messages"

    @property
    def media_url_base(self) -> str:
        return f"{self.BASE_URL}/{self.api_version}"

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Webhook Verification ──────────────────────────────────────────

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verify webhook subscription from Meta.
        Returns challenge string if valid, None otherwise."""
        if mode == "subscribe" and token == self.verify_token:
            logger.info("Webhook verified successfully")
            return challenge
        logger.warning(f"Webhook verification failed: mode={mode}, token mismatch")
        return None

    # ── Send Messages ─────────────────────────────────────────────────

    async def send_text_message(self, to: str, text: str) -> Dict[str, Any]:
        """Send a text message to a WhatsApp number.
        `to` should be in international format without '+', e.g. '971551933662'
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return await self._send(payload)

    async def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str = "en",
        components: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Send a template message (required for starting conversations)."""
        template: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        return await self._send(payload)

    async def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Mark an incoming message as read (blue ticks)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return await self._send(payload)

    async def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send request to WhatsApp Cloud API."""
        client = await self._get_client()
        try:
            response = await client.post(
                self.messages_url,
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(f"WhatsApp API response: {data}")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"WhatsApp API error {e.response.status_code}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"WhatsApp API request failed: {e}")
            raise

    # ── Parse Incoming Webhook ────────────────────────────────────────

    @staticmethod
    def parse_webhook(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse incoming webhook payload and extract messages.

        Returns list of parsed messages, each with:
        - from_number: sender phone number
        - message_id: unique message ID
        - timestamp: Unix timestamp
        - type: text|location|image|contacts|interactive|button
        - body: message text (for text type)
        - location: {latitude, longitude, name, address} (for location type)
        - image: {id, mime_type, caption} (for image type)
        - contacts: list of contacts (for contacts type)
        - name: sender's WhatsApp profile name
        """
        messages = []

        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    # Extract contact info (profile names)
                    contacts_info = {}
                    for contact in value.get("contacts", []):
                        wa_id = contact.get("wa_id", "")
                        profile_name = contact.get("profile", {}).get("name", "")
                        contacts_info[wa_id] = profile_name

                    # Extract messages
                    for msg in value.get("messages", []):
                        parsed = {
                            "from_number": msg.get("from", ""),
                            "message_id": msg.get("id", ""),
                            "timestamp": msg.get("timestamp", ""),
                            "type": msg.get("type", ""),
                            "name": contacts_info.get(msg.get("from", ""), ""),
                        }

                        msg_type = msg.get("type", "")

                        if msg_type == "text":
                            parsed["body"] = msg.get("text", {}).get("body", "")

                        elif msg_type == "location":
                            loc = msg.get("location", {})
                            parsed["location"] = {
                                "latitude": loc.get("latitude"),
                                "longitude": loc.get("longitude"),
                                "name": loc.get("name", ""),
                                "address": loc.get("address", ""),
                            }

                        elif msg_type == "image":
                            img = msg.get("image", {})
                            parsed["image"] = {
                                "id": img.get("id", ""),
                                "mime_type": img.get("mime_type", ""),
                                "caption": img.get("caption", ""),
                            }

                        elif msg_type == "contacts":
                            parsed["contacts"] = msg.get("contacts", [])

                        elif msg_type == "interactive":
                            interactive = msg.get("interactive", {})
                            reply = interactive.get("button_reply") or interactive.get("list_reply", {})
                            parsed["body"] = reply.get("title", "")

                        elif msg_type == "button":
                            parsed["body"] = msg.get("button", {}).get("text", "")

                        messages.append(parsed)

                    # Extract status updates (delivered, read, etc.)
                    for status in value.get("statuses", []):
                        logger.debug(
                            f"Message status: {status.get('id')} -> {status.get('status')}"
                        )

        except Exception as e:
            logger.error(f"Error parsing webhook payload: {e}")

        return messages

    # ── Media Download ────────────────────────────────────────────────

    async def get_media_url(self, media_id: str) -> Optional[str]:
        """Get download URL for a media file by its ID."""
        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.media_url_base}/{media_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json().get("url")
        except Exception as e:
            logger.error(f"Failed to get media URL for {media_id}: {e}")
            return None
