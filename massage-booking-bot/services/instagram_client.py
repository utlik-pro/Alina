"""Instagram entry-point client (FR / AI_AGENT_REQUIREMENTS §1).

Flow: a prospect DMs the Instagram account → we qualify briefly and hand
off to WhatsApp with a wa.me deep link carrying the context.

This is intentionally a thin scaffold:
- Webhook verification + event parsing are complete and testable.
- Outbound sending uses the Meta Graph API and only runs when
  INSTAGRAM_ACCESS_TOKEN is configured. Without it we log the intended
  reply (dev / not-yet-provisioned mode).

To go live you need (from the user):
- A Meta app with Instagram messaging permissions
- INSTAGRAM_ACCESS_TOKEN (page/IG access token)
- INSTAGRAM_APP_SECRET (for payload signature verification)
- WHATSAPP_CTA_NUMBER (the WhatsApp number to funnel clients to)
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from config import config

GRAPH_API = "https://graph.facebook.com/v19.0"


def parse_instagram_events(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract inbound DM text events from a Meta webhook payload.

    Returns a list of {"sender_id": str, "text": str}. Ignores echoes,
    delivery/read receipts, and non-text messages.
    """
    events: List[Dict[str, str]] = []
    for entry in payload.get("entry", []):
        for msg in entry.get("messaging", []):
            sender = (msg.get("sender") or {}).get("id")
            message = msg.get("message") or {}
            if not sender or not message:
                continue
            if message.get("is_echo"):
                continue
            text = message.get("text")
            if not text:
                continue
            events.append({"sender_id": str(sender), "text": str(text)})
    return events


def build_whatsapp_cta(prefill_context: str = "") -> Optional[str]:
    """Build a wa.me deep link to the funnel WhatsApp number.

    Returns None if WHATSAPP_CTA_NUMBER isn't configured.
    """
    number = config.WHATSAPP_CTA_NUMBER
    if not number:
        return None
    digits = "".join(ch for ch in number if ch.isdigit())
    base_text = "Hi! I'm coming from Instagram 🌹"
    if prefill_context:
        base_text += f" {prefill_context}"
    return f"https://wa.me/{digits}?text={urllib.parse.quote(base_text)}"


def build_handoff_reply(prefill_context: str = "") -> str:
    """Client-facing reply that hands off to WhatsApp."""
    link = build_whatsapp_cta(prefill_context)
    if link:
        return (
            "Hi dear 🌹 Thank you for reaching out! To book and share your "
            f"location easily, let's continue on WhatsApp 👉 {link}"
        )
    # No CTA number configured yet — still respond gracefully.
    return (
        "Hi dear 🌹 Thank you for reaching out! Please message us on WhatsApp "
        "to book and share your location 😊"
    )


async def send_instagram_message(recipient_id: str, text: str) -> bool:
    """Send a DM via the Graph API. No-op (logs) if token absent."""
    token = config.INSTAGRAM_ACCESS_TOKEN
    if not token:
        logger.info(f"[IG dev] would reply to {recipient_id}: {text}")
        return False
    url = f"{GRAPH_API}/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    params = {"access_token": token}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params, json=payload, timeout=15) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error(f"IG send failed {resp.status}: {body}")
                    return False
                return True
    except Exception as e:
        logger.error(f"IG send error: {e}")
        return False
