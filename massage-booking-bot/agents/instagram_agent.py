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

import json
import re
from collections import deque
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Deque, Dict, Optional
from zoneinfo import ZoneInfo

from loguru import logger
from openai import AsyncOpenAI

from config import config
from prices import format_price_list_for_prompt, format_special_offers_for_prompt
from services.instagram_client import build_handoff_reply, build_whatsapp_cta

MAX_TURNS = 12       # messages kept per sender (≈6 exchanges)
MAX_SENDERS = 500    # conversations kept in memory
IG_TEXT_LIMIT = 950  # Instagram DM hard cap is 1000 chars — stay under

# Shadow-mode marker for the ManyChat bridge. ManyChat's response mapper
# refuses EMPTY strings ("Invalid value type in json path", live-caught
# 2026-08-11), so shadow turns return this sentinel instead; the flow's
# Condition node (ai_reply is not [SHADOW]) stops it from reaching clients.
SHADOW_SENTINEL = "[SHADOW]"

# Turn log for prod QA (live AND shadow turns). NOTE: on Render the file is
# ephemeral (gone on redeploy) — the loguru [IG-SHADOW]/[IG-LIVE] lines in the
# Render log stream are the durable channel; this file is for local review.
IG_TURNS_LOG = Path(__file__).resolve().parent.parent / "logs" / "ig_turns.jsonl"


def _parse_hhmm(value: str, fallback: dtime) -> dtime:
    try:
        h, m = value.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return fallback


def ig_live_now(now: Optional[datetime] = None) -> bool:
    """True when the IG agent may actually SEND replies to clients.

    Owner rule (2026-08-09): live only from IG_ACTIVE_FROM to IG_ACTIVE_TO
    in IG_ACTIVE_TZ (default 21:00→09:00 Europe/Minsk — the night window
    while admins are offline). The window wraps midnight. Outside it the
    agent runs in SHADOW mode: replies are generated and logged, nothing
    is sent, so the system can be QA'd on real prod traffic.
    """
    tz = ZoneInfo(config.IG_ACTIVE_TZ)
    now = (now or datetime.now(tz)).astimezone(tz)
    start = _parse_hhmm(config.IG_ACTIVE_FROM, dtime(21, 0))
    end = _parse_hhmm(config.IG_ACTIVE_TO, dtime(9, 0))
    t = now.time()
    if start == end:
        return True  # degenerate config = always live
    if start < end:
        return start <= t < end
    return t >= start or t < end  # wraps midnight


def log_ig_turn(channel: str, sender_id: str, text: str, reply: str, live: bool) -> None:
    """Append one turn to the QA log; never let logging break the turn."""
    mode = "IG-LIVE" if live else "IG-SHADOW"
    logger.info(f"[{mode}] {channel}:{sender_id} | in: {text[:120]!r} | out: {reply[:200]!r}")
    try:
        IG_TURNS_LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channel": channel,
            "sender": sender_id,
            "live": live,
            "text": text,
            "reply": reply,
        }
        with IG_TURNS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"IG turn log failed: {e}")

_WA_LINK_RE = re.compile(r"https?://wa\.me/\S+")
_ASKS_FOR_LINK_RE = re.compile(r"link|whats\s?app|contact|number", re.IGNORECASE)


def _dedupe_wa_link(answer: str, history, client_text: str) -> str:
    """Strip a repeated wa.me link from a consult reply.

    Live finding 2026-08-15 (jwrrrrrry dialogue): the model appended the
    link to all four replies in a row despite the once-per-conversation
    prompt rule. Prompt rules bend; this doesn't. The link stays when it's
    the first one in the conversation or the client explicitly asked for
    the link/contact again.
    """
    if not _WA_LINK_RE.search(answer):
        return answer
    sent_before = any(
        m["role"] == "assistant" and _WA_LINK_RE.search(m["content"])
        for m in history
    )
    if not sent_before or _ASKS_FOR_LINK_RE.search(client_text):
        return answer
    stripped = _WA_LINK_RE.sub("", answer)
    stripped = "\n".join(
        line.rstrip() for line in stripped.splitlines() if line.strip()
    )
    return stripped.strip() or answer


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
- {cta}
- The WhatsApp link is NOT for every message: send it only when the client wants to book / asks how to proceed, at most once per conversation (again only if they ask). When you do send it, put it ALONE on its own line, as the very last line.
- CONVERSATION OVER PRICE-DUMP — but ONLY when no price was asked: on a broad opener with NO price question ("consult on a massage and make an appointment", "hello") reply with a SHORT warm greeting, ONE selling line ("We come to your home — free transportation, top Russian therapists 🌹"), and ONE clarifying question (body massage or facial?) — no price list, no link yet.
- ANY PRICE QUESTION GETS A NUMBER IMMEDIATELY: if the client asks about cost in any form ("how much", "price?", "how much for one session"), NEVER answer with only a question. Give the anchor prices in the same message — body massage 60 min 350 AED, facial 50 min 370 AED, and the current offer 275 AED (lymphatic + cupping + head spa, 60 min) — then ask which one they want. The admins always answer a price question with a price; a bare counter-question loses the client.
- EVERY price answer carries ONE short value line with it ("we come to your home — free transportation, Russian certified female specialists 🌹"). A naked price list looks expensive; the same price next to the value reads as a deal.
- Lead with the RELEVANT CHEAPEST option: cupping questions → the 275 AED lymphatic+cupping+head spa offer FIRST (that IS the cupping ad); mention full body massage prices only if they ask. Never open with a bigger number when a fitting offer exists.
- CLOSE WITH A QUESTION, not a link: end consult replies with a light CTA — "Would you like to book? 😊" — and only when they say yes, send the WhatsApp link (or proceed to booking when booking is enabled). A message that ends with a question keeps the conversation alive; a bare link ends it.
- NEVER repeat the WhatsApp link once it already appears earlier in this conversation — after that, refer to it in words ("message us on WhatsApp above 😊") unless the client explicitly asks for the link again.
- Show prices as plain numbers: "350 AED". Never show VAT calculations in a price quote.
- If asked how to pay: cash — tax free; bank transfer +5% VAT; payment AFTER the service. Do not bring payment up yourself. If asked "can I pay by card?" — answer simply and positively: yes, we have a card machine (available on request).
- PREGNANCY: if the client says she is pregnant — reassure her: our therapists have medical education, we offer prenatal massage (available after 4 months of pregnancy), 350 AED for 60 min. If she is earlier than 4 months, kindly explain prenatal starts from month 4. Do not refuse otherwise, do not lecture about risks — reassure and continue toward booking (admin-team practice). Postpartum and after-surgery massage also exist.
- THERAPISTS ARE FEMALE: all our therapists are Russian certified female specialists — say so when the client asks who comes to their home.
- IF THEY ASK FOR THE PHONE NUMBER / "send me your WhatsApp": give the WhatsApp link (or the number) right away — never answer with just "message us on WhatsApp".
- REASSURE, DON'T ARGUE: on doubt ("are you sure I'll see results?") answer confidently and briefly — visible results after the first session, certified specialists — then move to booking.
- "WHERE IS YOUR STUDIO/SALON?": our Abu Dhabi studio (Al Raha) is temporarily closed for maintenance — we come to the client's home, villa or hotel, transportation is free. Never invent a walk-in address.
- Sessions start between 10:00 AM and 9:00 PM (12-hour times only).
- Service areas: Abu Dhabi, Al Ain and Dubai ONLY. Nails and lash extensions — Abu Dhabi only. If the client is outside these areas, say so honestly — never improvise coverage.
- LANGUAGE: reply in English by default — this is what the admins do and it works: an Arabic opener like "مرحبا، ممكن احجز جلسة" gets an English answer and the client keeps going in English. Do NOT switch on the client's FIRST message just because it is in another language. Switch only when they clearly can't follow English: they say so, ask for another language, or keep writing only in their own language after you replied in English.
- Style: warm and personal, short DM style (2–6 sentences), light emoji (🌹😊✨), no walls of text, no markdown, no bullet-list dumps of the whole catalog — answer what was asked.

{format_price_list_for_prompt()}

{format_special_offers_for_prompt(include_packages=False)}

AD TRAFFIC NOTE: clients often open the chat with a prefilled ad message —
"I would like to consult on a massage and make an appointment in [emirate]",
"Hello i would like to sign up for a massage package in [emirate] at a discount",
"Hello i would like to sign up for the summer promotion in [emirate]".
These refer to the CURRENT SPECIAL OFFERS above; the emirate in the message
is the client's area — do NOT re-ask which emirate they are in.
The "consult and make an appointment" prefill runs for BOTH body and face
ad campaigns — you cannot tell which ad they saw, so ASK what they're
interested in (body or facial) instead of listing everything.
PACKAGES (multi-session courses): you have NO package price list — NEVER
state or invent package/course prices. On the "massage package at a
discount" prefill: the ad they saw is the cupping combo offer (275 AED,
above) — present it, and add that multi-session courses are arranged
personally by the team with the administrator.
"""


async def generate_ig_reply(sender_id: str, text: str) -> str:
    """LLM consult reply for one inbound DM; static handoff on any failure."""
    fallback = build_handoff_reply()
    if not config.OPENAI_API_KEY:
        return fallback

    history = _history(sender_id)
    history.append({"role": "user", "content": text})
    # Static prefill only — embedding the client's question URL-encoded made
    # the link a monster in the IG bubble (owner feedback 2026-08-12).
    wa_link = build_whatsapp_cta()
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
    answer = _dedupe_wa_link(answer, history, text)
    if len(answer) > IG_TEXT_LIMIT:
        answer = answer[: IG_TEXT_LIMIT - 1].rstrip() + "…"
    history.append({"role": "assistant", "content": answer})
    return answer
