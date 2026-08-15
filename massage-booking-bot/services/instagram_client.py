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
  (recommended flavor: "Instagram API with Instagram Login" — free, no
  Facebook Page required; sends go via graph.instagram.com)
- INSTAGRAM_ACCESS_TOKEN (Instagram User token; or a Page token if using
  the Facebook-Login flavor — then set INSTAGRAM_GRAPH_BASE to
  https://graph.facebook.com/v23.0)
- INSTAGRAM_APP_SECRET (for payload signature verification)
- WHATSAPP_CTA_NUMBER (the WhatsApp number to funnel clients to)
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from config import config


def _graph_base() -> str:
    """Graph API base URL; host depends on the Meta login flavor in use."""
    return (config.INSTAGRAM_GRAPH_BASE or "https://graph.instagram.com/v23.0").rstrip("/")


def parse_instagram_events(payload: Dict[str, Any]) -> List[Dict[str, Optional[str]]]:
    """Extract inbound DM text events from a Meta webhook payload.

    Returns a list of {"sender_id", "text", "mid"} (mid may be None on
    exotic payloads — used for redelivery dedup). Ignores echoes,
    delivery/read receipts, and non-text messages.
    """
    events: List[Dict[str, Optional[str]]] = []
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
            mid = message.get("mid")
            events.append({
                "sender_id": str(sender),
                "text": str(text),
                "mid": str(mid) if mid else None,
            })
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


async def fetch_manychat_last_text(subscriber_id: str) -> str:
    """Pull the contact's last message text via the ManyChat API.

    Needed because ManyChat's External Request body template breaks on
    multiline/quoted client text ("Invalid payload json", live-caught on
    the first night 2026-08-12) — so the flow sends only ids and we fetch
    the text server-side. Returns "" when the key is missing or the call
    fails (the endpoint then 400s, same as before).
    """
    key = config.MANYCHAT_API_KEY
    if not key:
        return ""
    url = "https://api.manychat.com/fb/subscriber/getInfo"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params={"subscriber_id": subscriber_id},
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            ) as resp:
                if resp.status >= 400:
                    logger.error(f"ManyChat getInfo {resp.status} for {subscriber_id}")
                    return ""
                data = await resp.json()
                return str((data.get("data") or {}).get("last_input_text") or "").strip()
    except Exception as e:
        logger.error(f"ManyChat getInfo failed for {subscriber_id}: {e}")
        return ""


async def manychat_send_text(subscriber_id: str, text: str) -> bool:
    """Send an IG DM via the ManyChat Sending API (24h-window replies).

    This is the async delivery path for the booking flow: the External
    Request bridge ACKs instantly and the real reply goes out through this
    call, so long YClients/LLM turns can't hit ManyChat's request timeout.
    """
    # Second, lowest-level daytime guard. _send_to_client already checks the
    # window, but this is the single funnel every ManyChat delivery passes
    # through — so no future code path can accidentally break the silence
    # the client demanded (owner request 2026-08-15).
    from agents.instagram_agent import ig_live_now

    if not ig_live_now():
        logger.warning(
            f"ManyChat send BLOCKED (outside live window) to {subscriber_id}: "
            f"{text[:80]!r}"
        )
        return False
    key = config.MANYCHAT_API_KEY
    if not key:
        logger.info(f"[MC dev] would send to {subscriber_id}: {text[:120]}")
        return False
    url = "https://api.manychat.com/fb/sending/sendContent"
    payload = {
        "subscriber_id": int(subscriber_id) if str(subscriber_id).isdigit() else subscriber_id,
        "data": {
            "version": "v2",
            "content": {
                "type": "instagram",
                "messages": [{"type": "text", "text": text}],
            },
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            ) as resp:
                body = await resp.text()
                if resp.status >= 400 or '"status":"error"' in body.replace(" ", ""):
                    # 3031 = Meta's 24h messaging window is closed (the client
                    # hasn't written for over a day). Not a fault of ours — it
                    # must be distinguishable from a real breakage at 3am.
                    if '"code":3031' in body.replace(" ", ""):
                        logger.warning(
                            f"ManyChat 24h window CLOSED for {subscriber_id} — "
                            f"reply not delivered (client silent >24h)"
                        )
                    else:
                        logger.error(
                            f"ManyChat send failed {resp.status} for {subscriber_id}: {body[:300]}"
                        )
                    return False
                return True
    except Exception as e:
        logger.error(f"ManyChat send error for {subscriber_id}: {e}")
        return False


async def send_instagram_message(recipient_id: str, text: str) -> bool:
    """Send a DM via the Graph API. No-op (logs) if token absent."""
    token = config.INSTAGRAM_ACCESS_TOKEN
    if not token:
        logger.info(f"[IG dev] would reply to {recipient_id}: {text}")
        return False
    url = f"{_graph_base()}/me/messages"
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
