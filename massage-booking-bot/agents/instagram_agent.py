"""Instagram Direct consult agent — lightweight, consult-and-funnel only.

The Instagram entry point has exactly two jobs (owner request 2026-08-09):
1. Consult on services and prices (catalog from prices.py — single source).
2. Funnel the prospect to WhatsApp via a wa.me deep link — booking, slots
   and availability live ONLY in the WhatsApp agent.

Design constraints:
- No YClients access here, so the agent must never promise availability
  or time slots — that would be a lie it can't verify.
- Language: English by default, switch when the client can't follow it
  (same rule as the WhatsApp agent).
- Prices are shown as plain "350 AED" — no VAT math in client-facing text;
  payment terms only when asked (cash tax free / bank transfer +5% VAT,
  payment AFTER the service).
- Any LLM failure falls back to the static handoff reply so the prospect
  always gets an answer with a WhatsApp pointer.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional

from loguru import logger
from openai import AsyncOpenAI

from config import config
from prices import format_price_list_for_prompt
from services.instagram_client import build_handoff_reply, build_whatsapp_cta

MAX_TURNS = 12       # messages kept per sender (≈6 exchanges)
MAX_SENDERS = 500    # conversations kept in memory
IG_TEXT_LIMIT = 950  # Instagram DM hard cap is 1000 chars — stay under

_histories: Dict[str, Deque[dict]] = {}
_seen_mids: Deque[str] = deque(maxlen=500)
_seen_mids_set: set = set()
_openai: Optional[AsyncOpenAI] = None


def is_duplicate(mid: Optional[str]) -> bool:
    """True if this message id was already handled.

    Meta redelivers webhook events when the ACK is slow or the app was
    briefly down — without this, the prospect gets the same reply twice.
    Unknown/missing mids are never treated as duplicates.
    """
    if not mid:
        return False
    if mid in _seen_mids_set:
        return True
    if len(_seen_mids) == _seen_mids.maxlen:
        _seen_mids_set.discard(_seen_mids[0])
    _seen_mids.append(mid)
    _seen_mids_set.add(mid)
    return False


def _history(sender_id: str) -> Deque[dict]:
    h = _histories.get(sender_id)
    if h is None:
        if len(_histories) >= MAX_SENDERS:
            _histories.pop(next(iter(_histories)))
        h = deque(maxlen=MAX_TURNS)
        _histories[sender_id] = h
    return h


def _client() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _openai


def build_system_prompt(wa_link: Optional[str]) -> str:
    cta = (
        f"WHATSAPP LINK (paste EXACTLY as-is, never shorten or rewrite it): {wa_link}"
        if wa_link
        else "No deep link is configured — invite the client to message Crystal Lab on WhatsApp."
    )
    return f"""You are the Instagram Direct assistant (agent) of Crystal Lab — premium at-home beauty services in the UAE (Abu Dhabi, Al Ain, Dubai): massage, nails, lashes & brows, facials. Masters come to the client's home, villa or hotel.

YOUR ONLY TWO JOBS:
1. Briefly consult on services and prices (use the catalog below — prices are exact).
2. Move the conversation to WhatsApp — ALL booking happens there.

HARD RULES:
- You CANNOT book, check availability or promise time slots here. NEVER say a time, date or master is available. Anything about booking, dates, times, "who is free" → invite to WhatsApp.
- Every reply where the client shows interest (asks about a price, a service, or booking) must END with a short invitation to continue on WhatsApp + the link.
- {cta}
- Show prices as plain numbers: "350 AED". Never show VAT calculations in a price quote.
- If asked how to pay: cash — tax free; bank transfer +5% VAT; payment AFTER the service. Do not bring payment up yourself.
- Sessions start between 10:00 AM and 9:00 PM (12-hour times only).
- Service areas: Abu Dhabi, Al Ain and Dubai ONLY. Nails and lash extensions — Abu Dhabi only. If the client is outside these areas, say so honestly — never improvise coverage.
- LANGUAGE: reply in English by default. If the client clearly can't follow English (says so directly, asks for another language, or keeps writing only in their language) — switch to their language and continue in it. A single greeting like "Привет" is NOT a reason to switch.
- Style: warm and personal, short DM style (2–6 sentences), light emoji (🌹😊✨), no walls of text, no markdown, no bullet-list dumps of the whole catalog — answer what was asked.

{format_price_list_for_prompt()}
"""


async def generate_ig_reply(sender_id: str, text: str) -> str:
    """LLM consult reply for one inbound DM; static handoff on any failure."""
    fallback = build_handoff_reply(prefill_context=text[:120])
    if not config.OPENAI_API_KEY:
        return fallback

    history = _history(sender_id)
    history.append({"role": "user", "content": text})
    wa_link = build_whatsapp_cta(text[:100])
    messages = [
        {"role": "system", "content": build_system_prompt(wa_link)},
        *history,
    ]
    try:
        response = await _client().chat.completions.create(
            model=config.IG_OPENAI_MODEL,
            messages=messages,
        )
        answer = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"IG consult LLM failed for {sender_id}: {e}")
        return fallback
    if not answer:
        return fallback
    if len(answer) > IG_TEXT_LIMIT:
        answer = answer[: IG_TEXT_LIMIT - 1].rstrip() + "…"
    history.append({"role": "assistant", "content": answer})
    return answer
