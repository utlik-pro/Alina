"""Crystal Lab Bot — FastAPI webhook app for Render deployment.

Handles:
- Telegram Bot webhook (aiogram)
- ManyChat External Request webhook (future)
- Health check endpoint
"""

import asyncio
import re
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request, Response, BackgroundTasks
from loguru import logger

# Deduplication cache: message_id → timestamp (processed within last 5 min).
# OrderedDict so we can evict oldest entries when hitting the size cap —
# prevents unbounded memory growth and keeps TTL-cleanup O(log n) amortized.
_processed_message_ids: "OrderedDict[str, float]" = OrderedDict()
_DEDUP_TTL = 300  # 5 minutes
_DEDUP_MAX_ENTRIES = 5000


def _dedup_seen(message_id: str, now_ts: float) -> bool:
    """Return True if message_id was processed recently; otherwise record it.

    Evicts expired entries (oldest-first) and caps total size. Safe under
    asyncio single-thread assumptions — no locks needed.
    """
    if not message_id:
        return False
    # Evict expired from the oldest end.
    while _processed_message_ids:
        oldest_id, oldest_ts = next(iter(_processed_message_ids.items()))
        if now_ts - oldest_ts > _DEDUP_TTL:
            _processed_message_ids.popitem(last=False)
        else:
            break
    # Cap size.
    while len(_processed_message_ids) >= _DEDUP_MAX_ENTRIES:
        _processed_message_ids.popitem(last=False)
    if message_id in _processed_message_ids:
        # Refresh position so genuine repeats don't get evicted mid-storm.
        _processed_message_ids.move_to_end(message_id)
        return True
    _processed_message_ids[message_id] = now_ts
    return False

# Wappi message buffering: phone → {"messages": [text,...], "timer": Task, "sender_name": str}
# Per PRD 4.1 rule 6: wait 7s to collect multi-part messages before responding
_wappi_buffer: dict[str, dict] = {}
# ТЗ FR-1.4.1: wait 20s of silence after the client's LAST message, then
# process all collected messages together (Arab clients send 3-5 messages
# over 10-30s). Was hardcoded 7s — below spec. Env-tunable without a deploy.
import os as _os_buf
_WAPPI_BUFFER_DELAY = float(_os_buf.getenv("WAPPI_BUFFER_DELAY", "20"))  # seconds

# Per-phone processing locks. A turn can take up to ~30s (LLM + slots); if a
# new message arrives and flushes while the previous turn is still running,
# two _process_wappi_message coroutines would mutate the SAME in-memory
# dialog context and both send replies (duplicate / interleaved answers —
# the "сначала записал, глючит" report). The lock serialises turns per phone.
_wappi_locks: "dict[str, asyncio.Lock]" = {}

# In-flight buffer-flush tasks (named "wappi-flush:<phone>"). Render deploys
# SIGTERM the old instance while webhooks were already ACKed 200 to Wappi —
# Wappi never redelivers, so a turn that dies here dies SILENTLY (live-caught
# 2026-07-10 14:41: client sent two questions during a deploy, got dead air).
# The shutdown drain awaits these before the process exits.
_wappi_inflight: "set[asyncio.Task]" = set()

# Promo photos already sent to a phone (this process lifetime). get_promo_photo
# fires on every turn where the service/offer keywords match, so without this a
# client discussing "body massage" across several turns would receive the same
# image each time. Cleared on reset so re-testing sends the photo again.
_wappi_sent_promos: "dict[str, set[str]]" = {}

# Per-phone reset epoch. A /clear bumps it; a buffer flush that was scheduled
# before the reset (and already popped its fragments, so the reset's buffer-pop
# can't catch it) compares the epoch after taking the lock and DROPS itself,
# so a pre-reset fragment never processes against the freshly-wiped context.
_wappi_reset_epoch: "dict[str, int]" = {}


def _phone_lock(phone: str) -> "asyncio.Lock":
    lock = _wappi_locks.get(phone)
    if lock is None:
        lock = asyncio.Lock()
        _wappi_locks[phone] = lock
    return lock


IG_KEY_PREFIX = "ig:"

# ── Night log ────────────────────────────────────────────────────────
# Render's log stream needs a CLI token we no longer have, and the
# ig_turns.jsonl file lives inside an ephemeral container. Without an
# outside-readable trail a night shift can only be reconstructed by hand
# from the ManyChat inbox. This in-memory ring is served by
# /admin/night-log (auth: MANYCHAT_WEBHOOK_SECRET) so the night can be
# reviewed the next morning: every inbound DM, every outbound reply,
# every booking and every failure.
NIGHT_LOG: "deque" = None  # initialised below (deque import is local)


def _night_event(kind: str, **data) -> None:
    """Append one event to the night log; never let logging break a turn."""
    global NIGHT_LOG
    try:
        from collections import deque
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        if NIGHT_LOG is None:
            NIGHT_LOG = deque(maxlen=1000)
        # Abu Dhabi wall clock — the same reference the salon uses
        ts = _dt.now(_tz(_td(hours=4))).isoformat(timespec="seconds")
        for k, v in list(data.items()):
            if isinstance(v, str) and len(v) > 400:
                data[k] = v[:400] + "…"
        NIGHT_LOG.append({"ts": ts, "kind": kind, **data})
    except Exception:  # observability must never break the pipeline
        pass


def _is_ig_key(phone: str) -> bool:
    """True for synthetic Instagram identities ("ig:<ManyChat subscriber id>")."""
    return isinstance(phone, str) and phone.startswith(IG_KEY_PREFIX)


def _is_ig_test_subscriber(subscriber_id: str) -> bool:
    """Whitelisted testers run the full IG booking pipeline at any hour;
    their YClients records get the [TEST] prefix."""
    ids = {s.strip() for s in (config.IG_TEST_SUBSCRIBERS or "").split(",") if s.strip()}
    return str(subscriber_id).strip() in ids


def _ig_channel_brief(known_phone: str = "") -> str:
    """Instagram-channel system-prompt addendum (shared by prod and the sim).

    Tatyana's rules (2026-07-28): collect the phone before the final
    confirm, close with her verbatim template, no wa.me links — the whole
    booking happens inside Instagram Direct.
    """
    return (
        "\n\n📸 INSTAGRAM CHANNEL RULES:\n"
        "- This client writes from Instagram Direct — their phone number "
        "is NOT known automatically.\n"
        + (
            f"- Client's phone on file: {known_phone} (don't re-ask).\n"
            if known_phone
            else "- Before the FINAL confirmation, ask for their phone "
                 "number (WhatsApp number) — the booking cannot be "
                 "created without it. Pass it as client_phone in "
                 "book_appointment.\n"
        )
        + "- After the booking is created, close with EXACTLY this "
        "style: 'Your booking is confirmed ✔ [service, date, time]. "
        "Tomorrow our administrator will contact you to confirm the "
        "details 🌹'\n"
        "- Do NOT send wa.me links in this conversation — the whole "
        "booking happens right here in Instagram.\n"
        "- 📍 WORDING ONLY, NOT A NEW STEP — when you reach the address step "
        "(which comes AFTER the client has picked a time, never before), ask "
        "them to TYPE the address (area, building, apartment). Never say "
        "'share your location': a pin does not reach us from Instagram.\n"
        "- 🚫 OUT OF SERVICE AREA (Sharjah, Ajman, RAK, Fujairah, UAQ…): say "
        "once, warmly, that we only serve Abu Dhabi, Al Ain and Dubai — and "
        "then CLOSE the conversation gracefully. No 'what service are you "
        "interested in', no prices, no times after that; if they reply 'Okay', "
        "answer with a short goodbye ('If you are ever in Abu Dhabi, Al Ain "
        "or Dubai — we would be happy to pamper you 🙏'). Resume only if they "
        "say they can come to one of our cities.\n"
        "- 🎁 THE CUPPING COMBO is ONE fixed session of 45 MINUTES TOTAL — "
        "275 AED. If asked what it includes: lymphatic drainage body massage "
        "30 min + cupping 15 min + head massage 15 min, the whole procedure "
        "45 minutes (the salon's own wording — do not do the arithmetic out "
        "loud). When the client picks it ('special offer', 'cupping', '275'), "
        "NEVER ask '60 or 90 min?' — the length is already decided. Confirm "
        "the combo and go straight to the day/time. Its price is 275, not the "
        "350/460 massage prices, and in book_appointment pass "
        "service='lymphatic_cupping_combo', duration_minutes=45, "
        "base_price_aed=275.\n"
        "- 💵 WORDING ONLY, NOT A NEW STEP — payment is asked at its own step, "
        "AFTER the name and address are known. Do NOT put it next to a price "
        "quote and do NOT bring it up early. When you do reach it, the menu "
        "reads '💵 Cash (tax free)' / '🏦 Bank transfer (+5% VAT)', and from "
        "then on every price you quote keeps that footnote. Always quote the "
        "BASE price — never do the VAT arithmetic for them, and never let the "
        "number change between the recap and the confirmation.\n"
        "- ORDER IS FIXED, one question per message: service → body/face → "
        "duration → TIMES (offer them as soon as the duration is known — the "
        "client must see real times before anything else is asked) → address "
        "→ name → payment → phone → confirm.\n"
        "- PREGNANCY: if the client says she is pregnant — reassure her: "
        "our therapists have medical education, we offer prenatal "
        "massage (available after 4 months of pregnancy, 350 AED / "
        "60 min); earlier than month 4 — kindly explain prenatal starts "
        "from month 4. Do not refuse otherwise, continue to booking. "
        "All therapists are Russian certified FEMALE specialists.\n"
        "- 'Where is your studio?': the Abu Dhabi studio (Al Raha) is "
        "temporarily closed for maintenance — we come to the client's "
        "home, villa or hotel, transportation is free.\n"
        "- 'Can I pay by card?': yes — we have a card machine (on "
        "request); cash is tax free, bank transfer +5% VAT.\n"
        "- ⏰ NIGHT SHIFT — WHICH DAY YOU ARE BOOKING (all times = UAE, the "
        "salon's clock; the salon works 10:00 AM–9:00 PM):\n"
        "    · BEFORE midnight (you are answering between 10 PM and 11:59 "
        "PM): the working day is over, so you book for TOMORROW. Do NOT "
        "open with the closure — the admins never start with a 'no'. Just "
        "offer the next day as if it were the natural option: 'Tomorrow we "
        "have 10:00 AM, 3:00 PM or 5:30 PM 🌹 Which suits you?'. Mention "
        "that today is no longer possible ONLY if the client explicitly "
        "asked for today, and even then keep it warm and brief.\n"
        "    · AFTER midnight (00:00–09:00): the new day has begun and its "
        "working hours are STILL AHEAD, so 'today' means that day — offer "
        "it normally. A client writing at 2 AM wants an appointment later "
        "the same day; never push them a day further.\n"
        "  Either way: never promise a visit 'right now' or within the next "
        "couple of hours, and offer ONLY the times in the slot list — it is "
        "already filtered by the real clock.\n"
        "- ✂️ TALK LIKE THE ADMINS: SHORT, IN SEVERAL MESSAGES. Measured "
        "against 15 real admin replies — their median is 68 characters / 11 "
        "words / 2 lines, and after the opening line they go telegraphic "
        "('Yes dear\\nWhat time is preferable for you?', 'Yes, have card "
        "machine'). Match that: apart from the FIRST reply, keep each message "
        "to 1–2 short lines, ~15 words, and never re-introduce the service "
        "or repeat what the client already knows. A list of times is the "
        "only allowed exception.\n"
        "- Send 2–3 SEPARATE messages instead of one block when there is "
        "more than one thought — put ---MESSAGE_SPLIT--- between them, "
        "exactly how the admins fire short bubbles one after another. "
        "Example: 'Ok dear 🌹' ---MESSAGE_SPLIT--- 'Tomorrow 3:00 PM or "
        "5:30 PM — which suits you?'\n"
        "- ❓ ONE CLARIFYING QUESTION BEFORE ANY TIMES (owner decision "
        "2026-08-15). Never open with a schedule. Show times only once you "
        "know WHICH service — and for massage that means BOTH body-or-face "
        "AND 60-or-90 min, because each changes the price and which windows "
        "actually fit. If the client's words leave it open ('massage', "
        "'appointment', 'treatment', 'consult on a massage'), reply with a "
        "short warm line about the service (we come to your home, free "
        "transportation, Russian certified female specialists) and ask ONE "
        "question — e.g. 'Body massage or facial? 😊'. Ask the missing piece "
        "only: if they said 'facial', ask nothing about body, just the "
        "duration if it matters. If they already named it precisely ('body "
        "massage 60 min', 'lash lifting', 'deep cleansing'), skip the "
        "question and go straight to the times.\n"
        "- 🚫 NEVER NAME A THERAPIST in this channel (owner decision "
        "2026-08-15). Not when offering times, not in the recap, not in "
        "the final confirmation. Say 'our therapist' / 'our specialist' "
        "instead. The client picks a TIME, not a person.\n"
        "- OFFER TIMES, NOT A TIMETABLE: merge every free therapist's "
        "windows into ONE short list and offer 3–4 concrete times total "
        "— e.g. 'On Saturday we have 3:00 PM, 5:30 PM or 7:00 PM 🌹 "
        "Which suits you?'. Never list per-therapist lines, never dump "
        "a whole day. If none of them fit, offer the next few real "
        "times from the same day. This OVERRIDES the WhatsApp rule about "
        "showing every therapist — Instagram is a narrow, fast chat and "
        "a wall of slots kills the conversation."
    )


async def _send_to_client(phone: str, text: str) -> bool:
    """Channel-aware outbound: Wappi for real numbers, ManyChat for ig: keys.

    Every client-facing send in the booking turn goes through here, so the
    SAME pipeline (gates, cancel/reschedule, fallbacks) serves WhatsApp and
    Instagram identities. For WhatsApp numbers this is byte-for-byte the
    old behavior.
    """
    if _is_ig_key(phone):
        # HARD DAYTIME SILENCE (owner rule, reinforced 2026-08-15 after a
        # stale reply reached a client at 14:58). Every outbound path to an
        # Instagram client — booking turns, reminders, alerts, resets — goes
        # through here, so this single check makes a daytime send impossible
        # regardless of which code path produced the text.
        from agents.instagram_agent import ig_live_now

        if not ig_live_now():
            logger.warning(
                f"IG send BLOCKED (outside live window) for {phone}: {text[:80]!r}"
            )
            _night_event("send_blocked_daytime", who=phone, text=text)
            return False
        from services.instagram_client import manychat_send_text
        _ok = await manychat_send_text(phone[len(IG_KEY_PREFIX):], text)
        _night_event("sent" if _ok else "send_failed", who=phone, text=text)
        return _ok
    if wappi_client:
        return await wappi_client.send_message(phone, text)
    return False

# Reset/clear commands (WhatsApp + Telegram). The team kept typing "/clean"
# (not "/clear"); both + bare/RU variants are accepted.
_RESET_COMMANDS = frozenset({
    "/clear", "/clean", "/reset", "/start", "/new",
    "reset", "clear", "clean", "restart", "new chat",
    "очистить", "сброс", "сбросить", "очисти", "начать заново",
})


def _is_reset_command(text: str) -> bool:
    """True if a raw message is a reset command (tolerant of trailing !./space)."""
    if not text:
        return False
    return text.strip().lower().rstrip("!. ") in _RESET_COMMANDS


# Fresh-start reply after /clear — bypasses the LLM, so it must itself follow
# ТЗ §6 step 1 (greeting + the brief service menu). It used to be a bare
# "What services are you interested in?" with no menu — the owner's complaint.
_RESET_GREETING = (
    "✅ Memory cleared dear 🌹 Let's start fresh!\n\n"
    "Welcome to Crystal Lab home service 🙌\n"
    "Certified Russian therapists and free transportation to your home 🏠\n"
    "Abu Dhabi, Al Ain and Dubai 🌹\n\n"
    "- Body massage (different techniques)\n"
    "- Face massage\n"
    "- Deep facial cleansing\n"
    "- Manicure and pedicure\n"
    "- Eyelash extension and lifting\n\n"
    "What services are you interested in? We will give you all the details 🌹"
)


_NAILS_KW = ("manicure", "pedicure", "mani ", "mani+", "pedi", "nail", "gelish",
             "маникюр", "педикюр", "ногт")
_MASSAGE_KW = ("massage", "body", "lymphatic", "cupping", "deep tissue",
               "facial", "face", "prenatal", "postpartum", "массаж", "лицо")


def _detect_service_category(text: str) -> Optional[str]:
    """Rough service category from a message: 'nails' | 'massage' | None.

    Used to persist context.booking_data['service_type'] on the Wappi path so
    slot injection shows the RIGHT specialists (a manicure client was being
    shown massage-therapist availability because service_type was never set).
    """
    t = (text or "").lower()
    if any(k in t for k in _NAILS_KW):
        return "nails"
    if any(k in t for k in _MASSAGE_KW):
        return "massage"
    return None


# Service-first gate signal: has the client named ANY service yet? Broader than
# _detect_service_category (which only distinguishes massage vs nails for slot
# ROUTING) — it also recognises lashes / brows / facial cleansing, which the
# category detector deliberately doesn't route but which still mean "the client
# told us what they want". Keeps these OUT of _detect_service_category so slot
# routing is unchanged; used only to decide whether we may show slots at all.
_SERVICE_EXTRA_KW = (
    "lash", "eyelash", "brow", "eyebrow", "ресниц", "бров",
    "cleansing", "чистк", "лиц",  # facial deep cleansing / «чистка лица»
)


# High-precision group-booking phrases. Kept tight (no bare "couple"/"both"/
# "пара" which collide with "a couple of questions" / "both 60 min") so the
# code safety net doesn't spam the admin with false positives.
_GROUP_KW = (
    "me and my", "for me and", "and my mom", "and my mum", "and my mother",
    "and my sister", "and my friend", "and my husband", "and my wife",
    "and my daughter", "couple massage", "for two", "for both of us",
    "и мам", "и мою маму", "и подруг", "и сестр", "и мужа", "и жену",
    "для меня и", "вдвоём", "вдвоем", "на двоих", "нас двое", "нас двоих",
)


def _looks_like_group(text: str) -> bool:
    """True if the client clearly asked to book MORE THAN ONE person.

    Feeds the group safety net: the LLM often ignores the `guests` field and
    books only the main client (live-caught 2026-07-15 sim). If a group was
    requested but the booking has no guests, the admin is still alerted so the
    extra person never silently gets no appointment.
    """
    t = (text or "").lower()
    return any(k in t for k in _GROUP_KW)


# Roster resolution, tolerant of Russian case endings. Long/unambiguous forms are
# matched as a STEM (\bstem\w* — so "Наталье"/"Людмилу" resolve); ambiguous short
# forms ("Лена", "Катя", "Таня", "Люда", "Маша" — which collide with common words
# as prefixes) are matched only as WHOLE words in their declined forms.
_MASTER_STEMS = [
    ("Lyudmila", ["lyudmila", "людмил"]),
    ("Eliza", ["eliza", "элиз"]),
    ("Natalia", ["natalia", "наталь", "натали", "наташ"]),
    ("Masha", ["masha"]),
    ("Tatyana", ["tatyana", "татьян"]),
    ("Makhabat", ["makhabat", "махабат"]),
    ("Ekaterina", ["ekaterina", "екатерин"]),
    ("Elena", ["elena", "елен"]),
    ("Safina", ["safina", "сафин"]),
]
_MASTER_SHORT = {
    "люда": "Lyudmila", "люду": "Lyudmila", "люде": "Lyudmila", "люды": "Lyudmila",
    "маша": "Masha", "машу": "Masha", "маше": "Masha", "маши": "Masha",
    "таня": "Tatyana", "таню": "Tatyana", "тане": "Tatyana", "тани": "Tatyana", "tanya": "Tatyana",
    "катя": "Ekaterina", "катю": "Ekaterina", "кате": "Ekaterina", "кати": "Ekaterina", "katya": "Ekaterina",
    "лена": "Elena", "лену": "Elena", "лене": "Elena", "лены": "Elena",
}

# Negative-preference / replacement phrases ("don't send her again", "не понравилась").
_AVOID_KW = (
    "don't want", "dont want", "do not want", "don't send", "dont send",
    "not her", "someone else", "didn't like", "did not like", "not happy with",
    "no more", "never again", "не хочу", "не присылай", "не понрав", "не надо",
    "не её", "не ее", "больше не", "замен",
)
# Explicit LASTING positive preference ("only Elena", "always with Natalia").
_PREFER_KW = (
    "only ", "always ", "same as last", "same therapist", "i prefer",
    "book me with", "the usual", "только ", "как в прошлый", "тот же мастер",
    "как всегда", "мне нравится", "постоянн",
)


def _find_master_name(text: str):
    """Resolve a roster master mentioned in the text to its canonical name, else None."""
    t = (text or "").lower()
    # Ambiguous short forms — whole word only (declined forms enumerated).
    for w in re.findall(r"\b\w+\b", t):
        if w in _MASTER_SHORT:
            return _MASTER_SHORT[w]
    # Long/unambiguous forms — stem match tolerates Russian case endings.
    for canon, stems in _MASTER_STEMS:
        for st in stems:
            if re.search(r"\b" + re.escape(st) + r"\w*", t):
                return canon
    return None


def _detect_avoided_master(text: str):
    """A NAMED master the client asked NOT to be sent (negative phrase + a name).

    Unnamed 'give me another master' is handled conversationally, not persisted —
    we only store an avoid when we know WHO. High-precision on purpose.
    """
    t = (text or "").lower()
    if not any(k in t for k in _AVOID_KW):
        return None
    return _find_master_name(t)


def _detect_preferred_master(text: str):
    """A NAMED master the client states a LASTING preference for ('only Elena')."""
    t = (text or "").lower()
    if not any(k in t for k in _PREFER_KW):
        return None
    return _find_master_name(t)


def _service_named(text: str) -> bool:
    """True if the message names a concrete service (massage/nails/lashes/facial).

    The service-first gate uses this so we NEVER dump time slots at a client who
    only said "I want to book" without a service (live-caught 2026-07-15: client
    said just "записаться на завтра", agent showed massage slots, client actually
    wanted a manicure). Canonical flow is service → area → slot.
    """
    t = (text or "").lower()
    return _detect_service_category(t) is not None or any(k in t for k in _SERVICE_EXTRA_KW)


# The exact instruction injected when the area is known but the service is not.
# Kept as a module-level constant so scripts/sim_conversation.py injects the
# IDENTICAL text — the sim must never drift from prod (same rule as detect_area).
def _is_massage_service(name: str) -> bool:
    """True for services whose 60/90-min choice changes price AND fit."""
    n = (name or "").lower()
    if any(k in n for k in ("lash", "brow", "mani", "pedi", "nail", "cleansing", "permanent")):
        return False
    return any(k in n for k in ("massage", "масса", "body", "face", "facial"))


def _massage_kind_known(name: str) -> bool:
    """True when the client said WHICH massage — body or face.

    A bare "massage" is not enough: body and face differ in price, duration
    and even which therapist can take it, so asking the duration first (as
    the gate did on the first live night) skips a step and then repeats
    itself when the client answers "body massage".
    """
    n = (name or "").lower()
    return any(k in n for k in ("body", "face", "facial", "тел", "лиц", "спин"))


_OUT_OF_AREA_RE = re.compile(
    r"\b(sharjah|ajman|fujairah|fujeirah|umm al[- ]?quwain|"
    r"ras al[- ]?khaima?h|\brak\b|khor ?fakkan|dibba|"
    r"шардж|аджман|фуджейр|рас[- ]?(?:эль|аль)[- ]?хайм)\w*", re.I)


def _detect_out_of_area(text: str) -> Optional[str]:
    """An emirate/city we do NOT serve, or None. Sharjah ad-leads are common —
    the ads target the whole UAE while we only drive to Abu Dhabi, Al Ain and
    Dubai."""
    m = _OUT_OF_AREA_RE.search(text or "")
    return m.group(1) if m else None


_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _is_non_english_script(text: str) -> bool:
    """The message is written in a script the admins can't read — Arabic or
    any other non-Latin, non-Cyrillic writing (client rule 2026-08-16: «пусть
    переходят на англ… чтобы мы потом смогли с ними общаться»). Russian stays
    allowed, so Cyrillic does NOT count."""
    t = text or ""
    if _ARABIC_RE.search(t):
        return True
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 3:
        return False
    other = [c for c in letters
             if not _LATIN_RE.match(c) and not _CYRILLIC_RE.match(c)]
    return len(other) / len(letters) > 0.4


ENGLISH_PLEASE_MSG = "In English please 🙏\nWe reply in English dear 🌹"


def _enforce_english_reply(response_text: str, inbound_text: str) -> str:
    """The agent must never answer in Arabic (or another script the admins
    can't read) — the morning admins take over these chats and must be able
    to continue them. Live-caught 2026-08-16: an Arabic ad-reply question got
    a whole Arabic paragraph back. The prompt now forbids it; this is the
    binding version: if the model still emits such a reply, it is replaced by
    the polite English ask (better a lost nuance than an unreadable thread).
    Cyrillic passes — Russian is the allowed switch."""
    if not response_text or not _is_non_english_script(response_text):
        return response_text
    logger.warning(
        f"english-only gate: reply contained a non-English script "
        f"(inbound was {inbound_text[:40]!r}) — replaced")
    return ENGLISH_PLEASE_MSG


_COMBO_KEY = "lymphatic_cupping_combo"


def _detect_combo_choice(text: str) -> bool:
    """The client is choosing the advertised cupping combo (275 AED).

    Live-caught 2026-08-16, 02:48 UAE: a lead said "I like the special offer /
    Cupping" and the duration gate — which only knows 60-or-90 massages —
    asked "60 or 90 min dear?". The combo's length is FIXED (30+15+15 = 60),
    so the question reads as nonsense; the client answered "But it includes
    massage" and walked away. Choosing the combo must set the service AND its
    fixed duration in code so no gate ever asks about either again.
    """
    t = (text or "").lower()
    if "special offer" in t or "275" in t:
        return True
    if "cupping" in t or "банк" in t or "хиджам" in t or "hijama" in t:
        # The standalone cupping add-on exists (15 min / 100 AED), but in the
        # night IG funnel "cupping" is how clients name the advertised combo —
        # the admins themselves answer a cupping ask with the 275 offer.
        return True
    return False


def _massage_kind_from_text(text: str) -> Optional[str]:
    """'body' | 'face' | None — the kind the client just named.

    The category detector only yields the generic 'massage', so without this
    upgrade service_type stays kind-less forever and the body-or-face gate
    NEVER releases (found 2026-08-15: every Al Ain prefill run looped on the
    gate, slots were never injected, and the model invented times for an
    empty day). Face wins when both stems appear ('facial with body oils').
    """
    t = (text or "").lower()
    has_face = any(k in t for k in ("face", "facial", "лиц"))
    has_body = any(k in t for k in ("body", "тел", "спин", "back"))
    if has_face:
        return "face"
    if has_body:
        return "body"
    return None


def _kind_gate_msg() -> str:
    """Body-or-face gate, with the prices to hand.

    The first version only said "ask which one", so a client who answered a
    question with a question ("how much?") got the SAME question back — three
    times in a row in the 2026-08-15 prefill audit, without ever being told a
    price. A gate must say what to do when the client doesn't play along; the
    duration gate below already does, which is why it never loops.
    """
    from prices import get_price as _p, SERVICE_CATALOG as _cat
    body60 = int(_p("body_massage_60"))
    body90 = int(_p("body_massage_90"))
    face = int((_cat.get("face_massage") or {}).get("price") or 370)
    return (
        "\n\n⚠️ THE CLIENT SAID 'MASSAGE' BUT NOT WHICH ONE (body or face).\n"
        "🚨 Do NOT show times and do NOT ask about duration yet — body and face "
        "differ in price, length and available therapists.\n"
        "🚨 Ask ONE short question: 'Body massage or facial dear? 😊'\n"
        "🚨 BUT ANSWER THEM FIRST. If they asked about PRICE (or anything else) "
        "instead of choosing, give the answer and THEN ask, e.g.:\n"
        f"    'Body {body60} AED / 60 min, {body90} AED / 90 min\n"
        f"     Facial {face} AED / 50 min\n"
        "     Which one dear? 😊'\n"
        "🚨 NEVER send the same question twice in a row — repeating it while "
        "ignoring what they asked is how a lead walks away."
    )


MASSAGE_KIND_GATE_MSG = _kind_gate_msg()


DURATION_FIRST_GATE_MSG = (
    "\n\n⚠️ MASSAGE DURATION NOT CHOSEN YET (service and area are known).\n"
    "🚨 Do NOT show, list or invent ANY times / slots this turn — the free "
    "windows for 60 and 90 min are DIFFERENT (a 90-min session plus the "
    "travel buffer does not fit everywhere a 60-min one does), so any time "
    "offered now could be taken back a moment later.\n"
    "🚨 Give the two options with prices and ask which one, e.g.:\n"
    "    '60 min - 350 AED\\n90 min - 460 AED\\nWhich one would you like "
    "dear? 🌹'\n"
    "🚨 The system will provide the real slots for the chosen duration on "
    "the next turn.\n"
    "🚨 If you ALREADY asked this in a previous message, do NOT repeat the "
    "price list word-for-word — just nudge briefly: '60 or 90 min dear? 🌹'"
)


SERVICE_FIRST_GATE_MSG = (
    "\n\n⚠️ SERVICE NOT KNOWN YET (area is confirmed, service is not).\n"
    "🚨 Do NOT show, list or invent ANY times / slots / masters this turn.\n"
    "🚨 FIRST ask what service the client wants, warmly, e.g.:\n"
    "    'What would you like dear — massage, facial, manicure/pedicure, "
    "or lash extensions? 🌹'\n"
    "🚨 Only once the client names a service will the system provide real "
    "slots on the next turn. Never guess the service."
)


# Emirate keywords, kept in ONE place so the webhook slot-injection and the
# offline simulator detect area identically (they used to drift — the sim only
# knew "abu dhabi", so a Russian tester typing "Абу-Даби" was silently ignored
# in the sim while prod behaved differently). Abu Dhabi previously listed only
# "абу даби" (space) — the standard hyphenated "абу-даби" fell through, leaving
# area unknown and the agent re-asking "which area?" ("снова спрашивает откуда я").
_AREA_DUBAI_KW = (
    "dubai", "dxb", "dubai marina", "jbr", "deira", "bur dubai",
    "business bay", "palm jumeirah", "downtown dubai",
    # Russian nominative + inflected cases ("я в Дубае", "из Дубая", "по Дубаю").
    "дубай", "дубае", "дубая", "дубаи", "дубаем", "дубаю",
)
_AREA_ABU_DHABI_KW = (
    "abu dhabi", "abudhabi", "abu-dhabi", "abu-dabi", "abudabi",
    # Russian — hyphen AND space AND no-separator spellings (all indeclinable).
    "абу-даби", "абу даби", "абудаби", "абу-дабе", "абу дабе",
    # Abu Dhabi districts clients name instead of the emirate.
    "raha", "al raha", "khalifa", "al khalifa", "mussafah", "mbz",
    "mohammed bin zayed", "mohamed bin zayed", "yas", "yas island",
    "saadiyat", "al reem", "reem island", "corniche", "tourist club",
    "al bateen", "bateen", "shahama", "baniyas", "shamkha",
    "al wathba", "wathba",
)
# Typo-tolerant Al Ain: "al ain", "alain", "al-ain", "al aim" (autocorrect), etc.
_AL_AIN_TYPO_RE = re.compile(r"\ba[li][\s\-]*[aie]i[nm]\b", re.IGNORECASE)


def detect_area(text: str) -> Optional[str]:
    """Detect an EXPLICIT emirate mention in a client message.

    Returns 'al_ain' | 'dubai' | 'abu_dhabi' | None. Word-boundary matched so
    short tokens ("yas", "mbz") don't fire inside unrelated words ("always").
    Shared by webhook slot-injection AND scripts/sim_conversation.py so the two
    never diverge.
    """
    t = (text or "").lower()

    def _has(kw: str) -> bool:
        return re.search(r"\b" + re.escape(kw) + r"\b", t) is not None

    if _AL_AIN_TYPO_RE.search(t) or any(
        _has(k) for k in ("al ain", "alain", "al-ain", "аль айн", "аль-айн")
    ):
        return "al_ain"
    if any(_has(k) for k in _AREA_DUBAI_KW):
        return "dubai"
    if any(_has(k) for k in _AREA_ABU_DHABI_KW):
        return "abu_dhabi"
    return None


# Pull an explicit session length from a client message ("90 min", "90 минут",
# "1.5 hours", "полтора часа") so slot filtering can require the WHOLE session
# to fit, not a default 60 min. Requires a unit word so a bare "90" (price) or
# "17:00" (a time) is never mistaken for a duration. Returns minutes or None.
_DURATION_MIN_RE = re.compile(
    r"\b(\d{2,3})\s*(?:min\b|mins\b|minutes?|минут\w*|мин\b)", re.IGNORECASE
)
_DURATION_HR_RE = re.compile(
    r"\b(\d(?:[.,]\d)?)\s*(?:hours?\b|hrs?\b|час\w*)", re.IGNORECASE
)


def _detect_duration_minutes(text_lower: str) -> Optional[int]:
    m = _DURATION_MIN_RE.search(text_lower)
    if m:
        v = int(m.group(1))
        if 30 <= v <= 240:
            return v
    if "полтора час" in text_lower:
        return 90
    if "полчаса" in text_lower:
        return 30
    m = _DURATION_HR_RE.search(text_lower)
    if m:
        mins = int(round(float(m.group(1).replace(",", ".")) * 60))
        if 30 <= mins <= 240:
            return mins
    return None


def _booking_has_location_and_name(booking_call, client_data: dict) -> tuple:
    """(_has_location, _has_name) for a booking, checking dialog context + the
    tool's own address/name. Shared by the reply-wording override and the hard
    gate so they agree."""
    cd = client_data or {}
    has_loc = bool(
        cd.get("location")
        or (cd.get("location_details") or "").strip()
        or (getattr(booking_call, "address", None) or "").strip()
    )
    nm = (getattr(booking_call, "client_name", None) or cd.get("name") or "").strip()
    has_name = bool(nm) and nm.lower() not in ("client", "whatsapp client")
    return has_loc, has_name


_WEEKDAYS = {
    "monday": 0, "понедельник": 0, "tuesday": 1, "вторник": 1,
    "wednesday": 2, "среда": 2, "среду": 2, "thursday": 3, "четверг": 3,
    "friday": 4, "пятница": 4, "пятницу": 4, "saturday": 5, "суббота": 5,
    "субботу": 5, "sunday": 6, "воскресенье": 6,
}


_MONTHS_EN = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    "январ": 1, "янв": 1, "феврал": 2, "фев": 2, "март": 3, "мар": 3,
    "апрел": 4, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
    "август": 8, "авг": 8, "сентябр": 9, "сент": 9, "сен": 9,
    "октябр": 10, "окт": 10, "ноябр": 11, "ноя": 11, "декабр": 12, "дек": 12,
}


def _detect_explicit_date(text: str, now) -> Optional[str]:
    """Resolve a date the client spelled out: '20 August', 'Aug 20', '20/08',
    '20.08', 'the 20th'. Returns YYYY-MM-DD or None.

    Weekday names were handled, but a plain date was not: the agent answered
    "I don't have the schedule for 20 August yet" while the day was open
    (caught by the date-phrase battery 2026-08-15). Only future dates within
    the next ~6 months are accepted, so prices ("350 AED"), durations
    ("60 min") and flat numbers ("apt 1204") can't be mistaken for a day.
    """
    from datetime import timedelta as _td2

    t = (text or "").lower()
    day = month = None

    # "20 August", "20th August", "22nd of August", "20 го августа"
    # "20 August", "20th August", "22nd of August", "20 августа", "20AUG"
    m = re.search(r"\b([0-3]?\d)\s*(?:st|nd|rd|th|го)?\s*(?:of\s+)?([a-zа-яё]{3,9})\b", t)
    if m:
        for key, num in _MONTHS_EN.items():
            if m.group(2).startswith(key):
                day, month = int(m.group(1)), num
                break
    if day is None:
        m = re.search(r"\b([a-zа-я]{3,9})\s+([0-3]?\d)(?:st|nd|rd|th)?\b", t)
        if m:
            for key, num in _MONTHS_EN.items():
                if m.group(1).startswith(key):
                    day, month = int(m.group(2)), num
                    break
    if day is None:
        m = re.search(r"\b(20\d{2})-([01]?\d)-([0-3]?\d)\b", t)
        if m:
            day, month = int(m.group(3)), int(m.group(2))
    if day is None:
        m = re.search(r"\b([0-3]?\d)[./-]([01]?\d)(?![./-]?\d{2,})\b", t)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
    if day is None:
        # "on the 20th" — nearest future day-of-month. Never inside an
        # address: "Gate Tower, 21st floor" is where the client LIVES, not
        # when they want the visit (caught by the month-ahead sweep).
        m = re.search(
            r"\b(?:the\s+)?([0-3]?\d)(?:st|nd|rd|th)\b"
            r"(?!\s*(?:floor|fl\b|этаж|apartment|apt|room|tower|building|villa|street|road))",
            t,
        )
        if m:
            day, month = int(m.group(1)), now.month

    if not day or not month or not (1 <= day <= 31) or not (1 <= month <= 12):
        return None
    for year in (now.year, now.year + 1):
        try:
            cand = now.replace(year=year, month=month, day=day)
        except ValueError:
            continue
        if cand.date() >= now.date() and (cand - now) < _td2(days=190):
            return cand.strftime("%Y-%m-%d")
    return None


def _booking_day_mismatch(user_text: str, booking_call):
    """If the client's message says "tomorrow"/"today"/"next Saturday" but the
    booking's date is a different day, return (spoken_day, the_real_YYYY-MM-DD)
    so we can confirm the day instead of silently booking a wrong-day home
    visit. Else None."""
    if booking_call is None or not getattr(booking_call, "date", None):
        return None
    t = (user_text or "").lower()
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    now = _dt.now(_tz(_td(hours=4)))
    try:
        bd = _dt.strptime(booking_call.date, "%Y-%m-%d").date()
    except ValueError:
        return None
    tomorrow = (now + _td(days=1)).date()
    today = now.date()
    if ("tomorrow" in t or "завтра" in t) and bd != tomorrow:
        return ("tomorrow", tomorrow.isoformat())
    if (("today" in t or "сегодня" in t) and "tomorrow" not in t and "завтра" not in t) and bd != today:
        return ("today", today.isoformat())
    # Weekday names: "on Saturday" = the NEXT such day, strictly in the future;
    # "next Saturday" said ON a Saturday means +7 days, never today. Caught
    # live 2026-08-15: "next Saturday at 7 pm" was booked for the same evening.
    for word, idx in _WEEKDAYS.items():
        if not re.search(rf"\b{word}\b", t):
            continue
        delta = (idx - today.weekday()) % 7
        if delta == 0:  # the named day IS today
            delta = 7 if re.search(r"\bnext\b|\bследующ", t) else 0
        expected = today + _td(days=delta)
        if bd != expected:
            return (f"{'next ' if delta == 7 else ''}{word}", expected.isoformat())
        break
    return None


def _enforce_reply_wording(response_text: str, actions, booking_call, client_data: dict,
                           user_text: str = "", already_booked_sig=None,
                           group_requested: bool = False,
                           needs_phone: bool = False,
                           is_ig: bool = False) -> str:
    """Override the model's reply where its wording must be guaranteed:

    1) Reschedule — the move is applied by the team, not instantly. Never let
       the model tell the client it's "confirmed/done".
    2) A booking the model is about to attempt WITHOUT a location/name — the
       hard gate will block the record, so replace a false "confirmed" with the
       ask for the missing info (single client-facing reply).
    3) Group booking — the client asked for 2+ people but the model booked only
       the main client (no `guests` — happens often). Guarantee the client is
       told the extra spot(s) are still being arranged, so a group is never
       silently confirmed as "all set" for one person.
    Otherwise the model's reply is returned unchanged.
    """
    if actions is not None and getattr(actions, "reschedule_call", None) is not None:
        rc = actions.reschedule_call
        newt = _to_ampm(rc.new_time) if getattr(rc, "new_time", None) else "the new time"
        # NEUTRAL holding line only. The DEFINITIVE outcome — "passed to the team"
        # (slot free) OR "that time isn't free, here are alternatives" (occupied) —
        # is sent by _handle_reschedule AFTER it re-checks availability. Promising
        # "passed to the team" here produced a contradictory double-message when
        # the slot turned out occupied (live-caught 2026-07-15: "passed to 4:30 ✅"
        # immediately followed by "4:30 isn't free").
        return f"One moment dear 🌹 let me check {newt} for you 🙏"
    if booking_call is not None:
        # Duplicate: the model re-fires book_appointment when the client adds/
        # changes payment after it's already booked. Don't re-send "booked ✅".
        _sig = (getattr(booking_call, "service", None), getattr(booking_call, "date", None),
                getattr(booking_call, "time", None))
        if already_booked_sig is not None and _sig == already_booked_sig:
            return "Noted dear 🌹 all set — see you then!"
        _dm = _booking_day_mismatch(user_text, booking_call)
        if _dm:
            from datetime import datetime as _dt2
            try:
                _nice = _dt2.strptime(_dm[1], "%Y-%m-%d").strftime("%A %-d %b")
            except ValueError:
                _nice = _dm[1]
            return (f"Just to confirm dear 🌹 you'd like {_dm[0]} — {_nice}, right? "
                    f"I want to make sure the therapist comes on the correct day.")
        has_loc, has_name = _booking_has_location_and_name(booking_call, client_data)
        if not (has_loc and has_name):
            # Instagram can't hand us a shared location: an attachment never
            # reaches the bridge (ManyChat passes text), so inviting a 📍 pin
            # only earns the client a "please type it" nudge. Ask for the
            # address in words there; WhatsApp keeps the pin, which works.
            if not has_loc and not has_name:
                return ("Almost done dear 🌹 may I have your name, and please type your "
                        "address so the therapist can reach you?") if is_ig else (
                       "Almost done dear 🌹 may I have your name, and please share your "
                       "location 📍 so the therapist can reach you?")
            if not has_loc:
                return ("Almost done dear 🌹 please type your address (area, building, "
                        "apartment) so the therapist can reach you 🙏") if is_ig else (
                       "Almost done dear 🌹 please share your location 📍 (or type your "
                       "address) so the therapist can reach you 🙏")
            return "Almost done dear 🌹 may I have your name for the booking?"
        # Phone gate (Instagram channel): the YClients record needs a real
        # number and the admin confirms by phone in the morning (client's
        # rule) — never claim "booked" while the number is missing.
        if needs_phone:
            return ("Almost done dear 🌹 may I have your phone number please? "
                    "Our administrator will confirm your booking with you 🙏")
        # Explicit-confirm gate (ТЗ: …→ payment → explicit CONFIRM). The prompt
        # asks for a recap + "yes", but the model sometimes books straight off
        # the payment answer ("cash") — caught in the 2026-07-10 live test.
        # If the client's LAST message isn't a confirmation, replace the
        # premature "booked ✅" with the recap question; _maybe_create_booking
        # applies the same check so no record is created on this turn.
        if not _client_confirmed(user_text):
            return _booking_recap_question(booking_call)
        # Confirmed booking reaches here. Group honesty: if a group was asked
        # for but the model dropped the extra people (no guests in the call),
        # append the team-mediated line so the client isn't told "all set" for
        # one person. Skip if the model already said it.
        if group_requested and not getattr(booking_call, "guests", None):
            if not re.search(r"team|arrang|shortly|команд", response_text, re.I):
                response_text = response_text.rstrip() + (
                    "\n\nYour other guest's spot is being arranged by our team — "
                    "we'll confirm it very shortly 🌸"
                )
        # Instagram closing template — the client's (Tatyana's) verbatim rule
        # from 2026-07-28: every IG booking ends with the admin follow-up
        # promise. The model drops it about half the time, so append it here.
        if is_ig and not re.search(
            r"administrator|admin will|tomorrow.*(contact|confirm)", response_text, re.I
        ):
            response_text = response_text.rstrip() + (
                "\n\nTomorrow our administrator will contact you to confirm "
                "the details 🌹"
            )
    return response_text


# Words that count as the client's explicit "yes" to the final recap. Checked
# against the LAST client message only — this is the second line of defence
# (the model shouldn't call book_appointment before a confirm at all).
_CONFIRM_WORDS_RE = re.compile(
    r"\b(?:yes|yep|yeah|yup|confirm(?:ed)?|sure|ok(?:ay)?|go ahead|book(?: it| me)?|"
    r"please book|sounds good|perfect|great|deal|agreed|yalla|"
    r"да|ага|конечно|подтверждаю|подтверди(?:те)?|давай(?:те)?|хорошо|ок|окей|"
    r"бронируй(?:те)?|записывай(?:те)?|запиши(?:те)?|пиши(?:те)?)\b",
    re.IGNORECASE,
)


def _client_confirmed(user_text: str) -> bool:
    """True if the client's message reads as an explicit go-ahead."""
    t = (user_text or "").strip()
    if not t:
        return False
    if "✅" in t or "👍" in t or t == "+":
        return True
    return _CONFIRM_WORDS_RE.search(t) is not None


def _match_booking_by_old_slot(bookings, old_date, old_time):
    """Pick the ONE booking matching the old date/time the client named.

    `bookings` are dicts with a datetime `booking_date`. Matching is tolerant:
    time alone ("17:30") is enough when it's unique; date alone likewise; both
    must agree when both are given. Returns the single match or None (caller
    then asks the client) — never a guess.
    """
    if not bookings:
        return None
    want_t = None
    if old_time:
        try:
            hh, mm = str(old_time).split(":")
            want_t = (int(hh), int(mm))
        except (ValueError, AttributeError):
            want_t = None
    want_d = (old_date or "").strip() or None

    matches = []
    for b in bookings:
        bd = b.get("booking_date")
        if bd is None:
            continue
        if want_t and (bd.hour, bd.minute) != want_t:
            continue
        if want_d and bd.strftime("%Y-%m-%d") != want_d:
            continue
        matches.append(b)
    if (want_t or want_d) and len(matches) == 1:
        return matches[0]
    return None


def _booking_recap_question(booking_call) -> str:
    """The final recap the agent must send BEFORE booking: one message with
    every agreed detail and a direct yes/no question."""
    svc = (getattr(booking_call, "service", "") or "appointment").replace("_", " ").strip()
    dur = getattr(booking_call, "duration_minutes", None)
    when = getattr(booking_call, "date", "") or ""
    try:
        from datetime import datetime as _dt3
        when = _dt3.strptime(when, "%Y-%m-%d").strftime("%A %-d %b")
    except ValueError:
        pass
    t = _to_ampm(getattr(booking_call, "time", "") or "")
    master = (getattr(booking_call, "master_name", None) or "").strip()
    pay = getattr(booking_call, "payment_method", "") or ""
    price = getattr(booking_call, "base_price_aed", None)
    bits = [f"{dur}-min {svc}" if dur else svc]
    if master:
        bits.append(f"with {master}")
    bits.append(f"{when} at {t}".strip())
    if price:
        bits.append(f"{int(price)} AED ({'cash — tax free' if pay == 'cash' else 'bank transfer +5% VAT'})")
    return f"So dear — {', '.join(bits)} 🌹 Shall I confirm?"


def _detect_ad_prefill(text: str) -> Optional[str]:
    """Which advertising creative sent this client, from the prefilled text
    Instagram puts in their first message. None when they wrote by themselves.

    The nine prefills are three templates × three emirates (see the crystal-lab
    SKILL). They matter because the creative decides which OFFER the client
    came for — the ad they tapped is invisible to us otherwise.
    """
    t = (text or "").lower()
    if "package" in t and ("discount" in t or "sign up" in t):
        return "package"
    if "summer promotion" in t:
        return "summer"
    if "consult" in t and "massage" in t:
        return "consult"
    # «Hello, I want to know the details about the promotion and get advice»
    # — Tatyana 2026-08-16: this text ALWAYS comes from the deep-cleansing
    # creative («этот текст на чистку — всегда… скидываем чистку и дальше
    # ведём диалог»). Note it carries NO emirate — ask it later as usual.
    if "details about the promotion" in t:
        return "cleansing"
    return None


_TIME_COLON_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?", re.I)
_TIME_MERIDIEM_RE = re.compile(r"\b(\d{1,2})\s*(am|pm)\b", re.I)


def _detect_requested_time(text: str) -> Optional[str]:
    """The concrete clock time the client just named ('7pm', '19:00',
    '5:30 PM'), as 24h 'HH:MM' — or None when they named no time.

    Deliberately narrow: a bare number is NOT a time ("60 min", "22 August",
    "350 AED", a phone number), so a match needs either a colon or an am/pm.
    """
    t = text or ""
    m = _TIME_COLON_RE.search(t)
    if m:
        hour, minute, mer = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    else:
        m = _TIME_MERIDIEM_RE.search(t)
        if not m:
            return None
        hour, minute, mer = int(m.group(1)), 0, m.group(2).lower()
    if mer == "pm" and hour < 12:
        hour += 12
    elif mer == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


_AMPM_TIMES_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)


def _ampm_times_set(text: str) -> set:
    """Every AM/PM clock time in `text`, as 24h 'HH:MM'."""
    out = set()
    for h, m, mer in _AMPM_TIMES_RE.findall(text or ""):
        hour, minute = int(h), int(m or 0)
        if mer.upper() == "PM" and hour < 12:
            hour += 12
        elif mer.upper() == "AM" and hour == 12:
            hour = 0
        out.add(f"{hour:02d}:{minute:02d}")
    return out


def _times_from_summary(summary) -> Optional[set]:
    """Free times promised by a slots summary. None = outage (judge nothing) —
    'temporarily unavailable' must never be read as 'the day is empty'."""
    if not summary or "TEMPORARILY UNAVAILABLE" in summary:
        return None
    return _ampm_times_set(summary)


def _enforce_slot_reality(response_text: str, context, booking_call,
                          _label=None) -> str:
    """No time reaches a client unless YClients actually has it free.

    Live-caught 2026-08-15 (prefill audit, Al Ain): the day's block said "No
    slots available… do NOT invent times" and the model still offered four
    times for it. An invented slot is a therapist who never arrives — so the
    promise is enforced on the OUTGOING text, not just requested in the
    prompt. If the reply names times that exist on none of the injected
    dates, it is replaced by the honest answer built from the ground truth:
    the chosen day's real times, or "fully booked" plus the nearest real day.
    A YClients outage (truth None) judges nothing — fail open, never block a
    reply because the backend hiccuped.
    """
    truth = getattr(context, "slot_truth", None) or {}
    if not response_text:
        return response_text
    said = _ampm_times_set(response_text)
    if not said:
        return response_text
    if not truth:
        # Times with NO ground truth at all: the injection never ran, which
        # (on the funnel paths) means the area is still unknown — any time in
        # the reply is invented by construction. Ask for the city instead
        # (live-caught 2026-08-16: the cleansing prefill has no emirate, the
        # client answered "20 August" to the city question, and four times
        # were offered for a day that is empty).
        if not (getattr(context, "client_data", None) or {}).get("area"):
            logger.warning(
                "slot-reality gate: times offered with no truth and no area "
                "— rewritten to the city question")
            return ("Happy to check the times for you dear 🌹\n"
                    "Which city are you in — Abu Dhabi, Al Ain or Dubai?")
        return response_text

    def _nice(d):
        from datetime import datetime as _dtg
        try:
            return _dtg.strptime(d, "%Y-%m-%d").strftime("%A %-d %B")
        except (ValueError, TypeError):
            return str(d)

    def _honest(target):
        real = truth.get(target)
        if real:
            shown = ", ".join(_to_ampm(t) for t in sorted(real)[:4])
            return (f"On {_nice(target)} we have {shown} 🌹\nWhich suits you?")
        days = sorted(d for d, v in truth.items() if v)
        head = (f"On {_nice(target)} we're fully booked dear 🙏"
                if target else "That time isn't available dear 🙏")
        if days:
            alt = days[0]
            shown = ", ".join(_to_ampm(t) for t in sorted(truth[alt])[:4])
            return f"{head}\nThe nearest we have is {_nice(alt)}: {shown}\nWhich suits you?"
        return f"{head}\nThe team will check further days for you 🌹"

    # A concrete chosen day (tool call or the sticky client-named date) is
    # judged strictly against THAT day's calendar.
    target = (getattr(booking_call, "date", None)
              or (context.booking_data or {}).get("date"))
    if target and target in truth:
        real = truth[target]
        if real is None:
            return response_text  # outage — never judge
        if said - real:
            logger.warning(
                f"slot-reality gate: reply offered {sorted(said - real)} for "
                f"{target}, real={sorted(real)} — rewritten")
            return _honest(target)
        return response_text

    # No chosen day: a time is legitimate if ANY injected day has it.
    if any(v is None for v in truth.values()):
        return response_text  # partial outage — fail open
    union = set()
    for v in truth.values():
        union |= v
    if said - union:
        logger.warning(
            f"slot-reality gate: reply offered {sorted(said - union)} not free "
            f"on any injected day — rewritten")
        return _honest(None)
    return response_text


_PAYMENT_MENU_RE = re.compile(
    r"^(\s*(?:[-•*]\s*)?(?:💵|🏦|💳)?\s*)(cash|bank transfer)\s*$", re.IGNORECASE)
_PRICE_RE = re.compile(r"\b(\d{2,5})\s*AED\b", re.IGNORECASE)


def _detect_payment_method(text: str) -> Optional[str]:
    """The payment method the client just named, or None if they didn't."""
    t = (text or "").lower()
    if re.search(r"bank transfer|transfer|перевод|банковск", t):
        return "bank_transfer"
    if re.search(r"\bcash\b|наличн", t):
        return "cash"
    return None


def _payment_label(payment_method: str) -> str:
    return "cash — tax free" if payment_method == "cash" else "bank transfer +5% VAT"


def _enforce_payment_terms(text: str, payment_method: Optional[str]) -> str:
    """Guarantee the client is never quoted a price whose payment terms are
    hidden — the rule is "base price + footnote", never VAT arithmetic.

    Live-caught 2026-08-15 (IG booking test): the brevity rules stripped the
    "(tax free)" / "(+5% VAT)" labels off the payment menu, and the model's own
    recap quoted a bare "350 AED" for a BANK TRANSFER booking — the client
    agreed to 350 and the confirmation then said 368. Prompt guidance is
    advisory; this is the binding version.

    Two repairs, both idempotent:
      1. a bare "💵 Cash" / "🏦 Bank transfer" menu line regains its label;
      2. once the client HAS chosen a method, the last price in the reply
         carries that method's footnote (prices quoted before the choice stay
         clean — that is the consult phase).
    """
    if not text:
        return text

    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = _PAYMENT_MENU_RE.match(line)
        if m:
            option = m.group(2).lower()
            label = "(tax free)" if option == "cash" else "(+5% VAT)"
            lines[i] = f"{m.group(1)}{m.group(2)} {label}".rstrip()
    text = "\n".join(lines)

    if payment_method and not re.search(r"VAT|tax free", text, re.I):
        matches = list(_PRICE_RE.finditer(text))
        if matches:
            last = matches[-1]
            text = (text[:last.end()]
                    + f" ({_payment_label(payment_method)})"
                    + text[last.end():])
    return text


def _detect_service_duration(text_lower: str) -> Optional[int]:
    """Default session length (minutes) for a recognised nail service, per the
    client's price list, used when the client hasn't stated an explicit
    duration. The length is a property of the service, so slots must fit it (a
    2h gel manicure must never be offered a 1h slot). None if not recognised.
    """
    t = text_lower
    _mani = "mani" in t or "маникюр" in t or "маник" in t
    _pedi = "pedi" in t or "педикюр" in t or "педик" in t
    _japan = "japan" in t or "япон" in t
    # Combos first (longest): both mani+pedi, or the word "combo".
    if "combo" in t or "комбо" in t or (_mani and _pedi):
        return 150 if _japan else 180
    # Nail extensions.
    if "наращ" in t or "extension" in t or "soft gel" in t or "hard gel" in t:
        return 180
    # Japanese single mani or pedi.
    if _japan and (_mani or _pedi):
        return 90
    # Basic russian (cleaning / classic) mani or pedi = 1h.
    if ("classic" in t or "cleaning" in t or "чистк" in t) and (_mani or _pedi):
        return 60
    # Russian GEL mani or pedi = 2h.
    if ("gelish" in t or "гель" in t or "гел " in t or (" gel" in t)) and (_mani or _pedi):
        return 120
    return None


from config import config
from bot import router, booking_agent
from database import (
    init_db, ClientService, MessageService, BookingService, DialogSessionService,
    PackageService, WaitingListService,
)
from dialog_context import dialog_manager
from services.notifications import NotificationService
from services.follow_up import FollowUpService
from services.scheduler import ReminderScheduler
from services.message_buffer import init_buffer, MessageBuffer
from services.yclients_service import YClientsService, _to_ampm
from services.wappi_client import WappiClient, parse_incoming_message
from agents.tools import BookingCall, CancelCall, RescheduleCall, AgentActions

# ── Global instances ─────────────────────────────────────────────────
bot_instance: Bot = None
dp: Dispatcher = None
wappi_client: WappiClient = None


KEEP_WARM_INTERVAL_SEC = 600  # 10 min — Render idles a service out at ~15


async def _keep_warm(base_url: str) -> None:
    """Ping our own health endpoint so Render never idles the instance out.

    Only meaningful on Render; a cold start costs ~30-60s, which is far more
    than ManyChat waits for its External Request.
    """
    import aiohttp

    while True:
        try:
            await asyncio.sleep(KEEP_WARM_INTERVAL_SEC)
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(f"{base_url}/") as resp:
                    if resp.status != 200:
                        logger.warning(f"keep-warm: health returned {resp.status}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"keep-warm ping failed: {e}")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown logic."""
    global bot_instance, dp

    # Validate config
    if not config.validate():
        raise RuntimeError("Invalid configuration")

    # Initialize bot and dispatcher
    bot_instance = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Initialize message buffer
    import bot as bot_module
    bot_module.msg_buffer = await init_buffer(config.REDIS_URL)

    # Initialize database
    logger.info("Initializing database...")
    db = init_db(config.DATABASE_URL)
    await db.create_tables()

    bot_module.client_service = ClientService(db)
    bot_module.message_service = MessageService(db)
    bot_module.booking_service = BookingService(db)
    bot_module.dialog_session_service = DialogSessionService(db)
    bot_module.package_service = PackageService(db)
    bot_module.waiting_list_service = WaitingListService(db)
    logger.info("✅ Database services initialized")

    # Notification service
    if config.ADMIN_GROUP_CHAT_ID:
        bot_module.notification_service = NotificationService(
            bot_instance, config.ADMIN_GROUP_CHAT_ID
        )
        logger.info(f"✅ Notifications enabled for group {config.ADMIN_GROUP_CHAT_ID}")

    # Follow-up service. Contexts are keyed "wappi_<phone>" for WhatsApp and
    # a numeric chat_id for Telegram — route each to the right channel.
    # (Previously every follow-up did int(user_id), which raised ValueError
    # on "wappi_..." and silently dropped ALL WhatsApp nudges → the client's
    # "offers tomorrow then goes silent" complaint.)
    async def _send_follow_up(user_id: str, text: str):
        try:
            if str(user_id).startswith("wappi_"):
                phone = str(user_id)[len("wappi_"):]
                if wappi_client:
                    await _send_to_client(phone, text)
                else:
                    logger.error(f"Follow-up: no wappi_client for {user_id}")
                return
            await bot_instance.send_message(chat_id=int(user_id), text=text)
        except Exception as e:
            logger.error(f"Failed to send follow-up to {user_id}: {e}")

    async def _send_photo(user_id: str, photo_path: str, caption: str):
        try:
            if str(user_id).startswith("wappi_"):
                # Wappi client sends text only — deliver the caption.
                await _send_follow_up(user_id, caption)
                return
            from aiogram.types import FSInputFile
            photo = FSInputFile(photo_path)
            await bot_instance.send_photo(chat_id=int(user_id), photo=photo, caption=caption)
        except Exception as e:
            logger.error(f"Failed to send photo to {user_id}: {e}")
            await _send_follow_up(user_id, caption)

    bot_module.follow_up_service = FollowUpService(
        send_message=_send_follow_up,
        notification_service=bot_module.notification_service,
        send_photo=_send_photo,
    )
    await bot_module.follow_up_service.start(check_interval=60)

    # YClients service
    if not config.MOCK_YCLIENTS and config.YCLIENTS_PARTNER_TOKEN and config.YCLIENTS_USER_TOKEN:
        bot_module.yclients_service = YClientsService()
        try:
            staff = await bot_module.yclients_service.get_staff()
            logger.info(f"✅ YClients connected: {len(staff or [])} staff members")
        except Exception as e:
            logger.error(f"❌ YClients connection failed: {e}")
            bot_module.yclients_service = None

    # Wappi WhatsApp client
    global wappi_client
    if config.WAPPI_TOKEN and config.WAPPI_PROFILE_ID:
        wappi_client = WappiClient()
        logger.info("✅ Wappi WhatsApp client initialized")
    else:
        logger.info("⚠️ Wappi not configured (WAPPI_TOKEN / WAPPI_PROFILE_ID missing)")

    # Reminder scheduler (FR-3.1 day-before confirmations, FR-4 post-session).
    # Sends WhatsApp via Wappi; falls back to Telegram if Wappi is absent.
    async def _scheduler_send(phone: str, text: str):
        if wappi_client:
            await _send_to_client(phone, text)
        else:
            # Telegram fallback (dev): phone is "wappi_<n>" stripped → not a
            # chat id, so only attempt when it's numeric.
            try:
                await bot_instance.send_message(chat_id=int(phone), text=text)
            except Exception as e:
                logger.warning(f"Scheduler Telegram fallback failed for {phone}: {e}")

    bot_module.reminder_scheduler = ReminderScheduler(
        booking_service=bot_module.booking_service,
        send_message=_scheduler_send,
        package_service=bot_module.package_service,
        notification_service=bot_module.notification_service,
        check_interval=900,
    )
    await bot_module.reminder_scheduler.start()

    # Set Telegram webhook
    import os
    base_url = config.RENDER_EXTERNAL_URL
    if not base_url:
        # Fallback: construct from RENDER_EXTERNAL_HOSTNAME or service name
        hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
        if hostname:
            base_url = f"https://{hostname}"
        else:
            base_url = "https://crystal-lab-bot.onrender.com"
    webhook_url = f"{base_url}/webhook/telegram"
    await bot_instance.set_webhook(
        url=webhook_url,
        secret_token=config.WEBHOOK_SECRET,
        drop_pending_updates=False,
    )
    logger.info(f"✅ Telegram webhook set: {webhook_url}")
    logger.info("🤖 Crystal Lab Bot started in WEBHOOK mode (Render)")

    # Keep-warm: Render puts an idle instance to sleep, and the next request
    # then waits ~30-60s for a cold start. ManyChat's External Request gives
    # up long before that, so a night DM would go unanswered (the flow now
    # correctly stays silent rather than sending a stale reply — but silence
    # loses the lead too). A light self-request every 10 minutes keeps the
    # instance awake through the quiet hours.
    keepalive_task = (
        asyncio.create_task(_keep_warm(base_url)) if config.RENDER else None
    )

    yield

    if keepalive_task is not None:
        keepalive_task.cancel()

    # Shutdown — do NOT delete webhook, new instance will re-set it on startup
    logger.info("Shutting down...")
    # FIRST: finish what clients are owed. Buffered/in-flight Wappi turns die
    # silently if we close the clients under them (deploy = SIGTERM here).
    try:
        await _drain_wappi_turns()
    except Exception:
        logger.error("Wappi shutdown drain failed", exc_info=True)
    if getattr(bot_module, "reminder_scheduler", None):
        await bot_module.reminder_scheduler.stop()
    if bot_module.follow_up_service:
        await bot_module.follow_up_service.stop()
    if bot_module.msg_buffer:
        await bot_module.msg_buffer.close()
    if wappi_client:
        await wappi_client.close()
    await bot_instance.session.close()
    await db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def health():
    """Health check for Render.

    Also exposes the Instagram track's runtime state (no secrets) — the
    flags live only in the Render env, so this is the only way to verify
    from outside which mode the night shift is actually in.
    """
    from agents.instagram_agent import ig_live_now

    return {
        "status": "ok",
        "bot": "Crystal Lab",
        "mode": "webhook",
        "ig": {
            "booking_enabled": config.IG_BOOKING_ENABLED,
            "live_now": ig_live_now(),
            "window": f"{config.IG_ACTIVE_FROM}-{config.IG_ACTIVE_TO} {config.IG_ACTIVE_TZ}",
            "model": config.IG_OPENAI_MODEL,
            "manychat": bool(config.MANYCHAT_API_KEY),
            "testers": len([t for t in config.IG_TEST_SUBSCRIBERS.split(",") if t.strip()]),
        },
        # Which Telegram group the lead alerts go to. Only the tail is shown —
        # enough to tell the configured group apart from a stale one without
        # publishing the id. The old group silently stopped existing and
        # nobody noticed until 2026-08-15.
        "leads_group_tail": (str(config.ADMIN_GROUP_CHAT_ID or "")[-5:] or "unset"),
        # WhatsApp transport — silently absent when WAPPI_* aren't in the
        # deploy env, which once made the whole WA channel go quiet unnoticed.
        "wappi": bool(config.WAPPI_TOKEN and config.WAPPI_PROFILE_ID),
    }


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook."""
    # Verify secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if config.WEBHOOK_SECRET and secret != config.WEBHOOK_SECRET:
        logger.warning("Invalid webhook secret token")
        return Response(status_code=403)

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot_instance})
    await dp.feed_update(bot=bot_instance, update=update)
    return Response(status_code=200)


async def _buffer_and_process_wappi(phone: str, text: str, sender_name: str):
    """Buffer incoming Wappi messages — wait 7s, then process combined.

    If a new message arrives within 7s, restart the timer (PRD 4.1 rule 6).
    """
    entry = _wappi_buffer.setdefault(phone, {"messages": [], "timer": None, "sender_name": sender_name})
    entry["messages"].append(text)
    # Stamp the reset epoch at buffer time so the flush can tell if a /clear
    # landed in between and this fragment is now stale.
    entry["epoch"] = _wappi_reset_epoch.get(phone, 0)
    if sender_name and not entry.get("sender_name"):
        entry["sender_name"] = sender_name

    # Cancel existing timer if any (reset 7s window)
    if entry.get("timer") and not entry["timer"].done():
        entry["timer"].cancel()

    async def _flush():
        try:
            await asyncio.sleep(_WAPPI_BUFFER_DELAY)
            buf = _wappi_buffer.pop(phone, None)
            if not buf:
                return
            combined = "\n".join(buf["messages"])
            logger.info(f"Wappi buffer [{phone}]: flushing {len(buf['messages'])} messages")
            # Serialise per phone: if the previous batch is still being
            # processed (LLM can take up to 30s), wait for it instead of
            # running a second processing concurrently on the same context.
            # The message-collection (buffer) above is UNCHANGED — this only
            # prevents overlapping processings from corrupting state / sending
            # duplicate replies.
            async with _phone_lock(phone):
                # A /clear may have fired after we popped the buffer but before
                # we got the lock — drop these now-stale fragments instead of
                # replying against the wiped context.
                if buf.get("epoch", 0) != _wappi_reset_epoch.get(phone, 0):
                    logger.info(f"Wappi buffer [{phone}]: dropped stale pre-reset fragments")
                    return
                await _process_wappi_message(phone, combined, buf["sender_name"])
        except asyncio.CancelledError:
            pass  # new message arrived, will be handled by new timer
        except Exception as e:
            logger.error(f"Wappi buffer flush error: {e}", exc_info=True)
            # Never leave the client on read: a crash here used to mean dead
            # air (the webhook already ACKed Wappi, nothing retries).
            try:
                if wappi_client:
                    await _send_to_client(
                        phone, "Sorry dear, one moment 🙏 Please repeat your message 🌹"
                    )
            except Exception:
                pass

    task = asyncio.create_task(_flush(), name=f"wappi-flush:{phone}")
    _wappi_inflight.add(task)
    task.add_done_callback(_wappi_inflight.discard)
    entry["timer"] = task


# Render sends SIGKILL ~30s after SIGTERM; leave headroom for the fallback
# sends + admin alert after the drain wait.
_WAPPI_DRAIN_TIMEOUT = float(_os_buf.getenv("WAPPI_DRAIN_TIMEOUT", "22"))


async def _drain_wappi_turns():
    """Flush buffered Wappi messages and wait out in-flight turns on shutdown.

    Without this, a deploy silently drops every message that is sitting in the
    20s collect window or mid-LLM: the webhook already returned 200, Wappi
    never redelivers, the client just gets read-and-ignored.
    """
    # Phones still in the buffer are waiting out the collect window — their
    # timer hasn't popped the buffer yet, so it is safe to cancel and process
    # the collected fragments immediately.
    drained: "list[asyncio.Task]" = []
    for phone, entry in list(_wappi_buffer.items()):
        _wappi_buffer.pop(phone, None)
        timer = entry.get("timer")
        if timer and not timer.done():
            timer.cancel()
        combined = "\n".join(entry["messages"])
        sender = entry.get("sender_name") or ""

        async def _run(p=phone, text=combined, name=sender):
            async with _phone_lock(p):
                await _process_wappi_message(p, text, name)

        drained.append(asyncio.create_task(_run(), name=f"wappi-flush:{phone}"))

    # Tasks already past their sleep are mid-turn (possibly mid-LLM) — never
    # cancel those, wait for them. Just-cancelled timers finish instantly.
    inflight = [t for t in _wappi_inflight if not t.done()]
    if not drained and not inflight:
        return
    logger.info(
        f"Shutdown: draining {len(drained)} buffered + {len(inflight)} in-flight Wappi turns"
    )
    _done, pending = await asyncio.wait(
        drained + inflight, timeout=_WAPPI_DRAIN_TIMEOUT
    )
    if not pending:
        return
    # About to be SIGKILLed with turns unfinished: ask the client to nudge us
    # instead of dead air, and tell the admin which dialogues were cut.
    cut_phones = []
    for t in pending:
        name = t.get_name()
        cut_phones.append(name.split(":", 1)[1] if ":" in name else name)
    logger.error(f"Shutdown drain timed out; turns cut for: {cut_phones}")
    for p in cut_phones:
        try:
            if wappi_client and p.isdigit():
                await asyncio.wait_for(
                    _send_to_client(
                        p, "Sorry dear, one moment 🙏 Please repeat your message 🌹"
                    ),
                    timeout=5,
                )
        except Exception:
            pass
    try:
        import bot as bot_module
        ns = getattr(bot_module, "notification_service", None)
        if ns and getattr(ns, "group_chat_id", None):
            await ns.bot.send_message(
                chat_id=ns.group_chat_id,
                text=(
                    "⚠️ Деплой оборвал обработку сообщений WhatsApp.\n"
                    "Клиенты: " + ", ".join(cut_phones)[:500] + "\n"
                    "Агент попросил их написать ещё раз — проверьте, что диалог продолжился."
                ),
            )
    except Exception:
        pass


async def _maybe_create_booking(
    user_id: str,
    telegram_id: str,
    phone: str,
    sender_name: str,
    context,
    response_text: str,
    booking_call: Optional[BookingCall] = None,
):
    """Create DB + YClients records from a structured BookingCall.

    Flow:
    - If booking_call is None but the bot sent a ✅ confirmation — that's
      a phantom confirmation (model forgot to call the tool). Alert the
      admin and DO NOT create anything.
    - If booking_call is None and there's no ✅ — nothing to do.
    - If booking_call is present — validate, persist locally, create in
      YClients, notify admin.

    All the old regex date/time parsing is gone; structured fields from
    the tool call are the only source of truth.
    """
    import re as _re
    import bot as bot_module
    from datetime import datetime, timedelta, timezone as _tz

    uae_tz = _tz(timedelta(hours=4))
    now_uae = datetime.now(uae_tz).replace(tzinfo=None)

    # Detect phantom confirmation: ✅ + a confirmation cue but no tool call.
    # Broadened beyond "booked" — the model also confirms with "all set",
    # "confirmed", "scheduled", "see you", which previously escaped both the
    # creation AND the admin alert (silent false confirmation to the client).
    text_low = response_text.lower()
    has_confirm_marker = (
        "✅" in response_text
        and _re.search(
            r"\b(?:booked|confirmed|all set|scheduled|see you|you'?re all set)\b",
            text_low,
        ) is not None
    )
    if has_confirm_marker:
        # Filter out negated forms ("not yet booked", "will be booked"…)
        negation_re = _re.compile(
            r"(?:not\s+yet|won'?t\s+be|will\s+be|going\s+to\s+be|"
            r"cannot\s+be|can'?t\s+be|is\s+not|isn'?t|aren'?t|"
            r"would\s+be|should\s+be|could\s+be|maybe|might)\s+booked",
            _re.IGNORECASE,
        )
        if negation_re.search(text_low):
            has_confirm_marker = False

    if booking_call is None:
        if has_confirm_marker:
            logger.error(
                f"Wappi: ✅ confirmation WITHOUT book_appointment tool call — "
                f"phantom booking ignored. response={response_text[:200]!r}"
            )
            if bot_module.notification_service:
                try:
                    await bot_module.notification_service.send_booking_failed(
                        telegram_id=telegram_id,
                        reason=(
                            "Bot sent ✅ confirmation but did NOT call "
                            "book_appointment tool. No record created. "
                            f"Bot said: {response_text[:200]}"
                        ),
                    )
                except Exception:
                    pass
        return

    # Anti-duplicate guard: suppress ONLY an EXACT repeat of the booking we
    # just created (the model re-calls the tool when the client writes
    # "thanks"/emoji). A DIFFERENT service/date/time is a legitimate SECOND
    # booking (another day, "book my sister too") and must go through — the
    # old guard blocked ALL bookings once state=='completed', so the client
    # was stuck until /clear ("booked once then glitches").
    _new_sig = (booking_call.service, booking_call.date, booking_call.time)
    if getattr(context, "last_booking_sig", None) == _new_sig:
        logger.warning(
            f"Wappi: suppressing exact-duplicate book_appointment {_new_sig}"
        )
        return

    # Card-terminal note is a HARD rule (1 terminal for 6 masters): if the
    # client asked to pay by card/terminal ANYWHERE in the conversation, the
    # YClients record MUST carry "нужен терминал" so a master brings it. The
    # prompt asks the model to set this note, but that's advisory — enforce it
    # in code so a forgotten note never drops a terminal request on the floor.
    _convo = " ".join(
        (m.get("content") or "") for m in getattr(context, "recent_messages", [])
    ).lower()
    _wants_terminal = any(
        kw in _convo for kw in ("terminal", "терминал", "card machine", "pos machine")
    )
    if _wants_terminal and "терминал" not in (booking_call.notes or "").lower():
        booking_call.notes = (
            (booking_call.notes + ". ") if booking_call.notes else ""
        ) + "нужен терминал"
        logger.info("terminal requested by client — forced 'нужен терминал' note")

    # Parse structured date/time into a datetime.
    try:
        booking_date = datetime.strptime(
            f"{booking_call.date} {booking_call.time}", "%Y-%m-%d %H:%M"
        )
    except ValueError as e:
        logger.error(
            f"Wappi: BookingCall has malformed date/time — "
            f"date={booking_call.date!r} time={booking_call.time!r} err={e}"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=(
                        f"book_appointment tool returned malformed "
                        f"date/time: {booking_call.date} {booking_call.time}"
                    ),
                )
            except Exception:
                pass
        return

    # Sanity window: not in the past (1h grace), not >60 days future.
    if booking_date < now_uae - timedelta(hours=1):
        logger.error(
            f"Wappi: BookingCall date in the past: {booking_date.isoformat()} "
            f"(now={now_uae.isoformat()})"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=f"Tool date is in the past: {booking_date.isoformat()}",
                )
            except Exception:
                pass
        return
    if booking_date > now_uae + timedelta(days=60):
        logger.error(
            f"Wappi: BookingCall date too far in future: {booking_date.isoformat()}"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=f"Tool date >60 days out: {booking_date.isoformat()}",
                )
            except Exception:
                pass
        return

    # ── HARD GATE: never create a booking without a location AND a name ─────
    # The prompt gathers these (STEP 4.5 location, STEP 5 name) but the LLM can
    # jump straight to book_appointment ("не подтвердил, локацию не запросил, в
    # программу записал"). Prompt guidance is advisory — this code gate is
    # binding. If either is missing, DON'T create the record; ask the client for
    # what's missing and alert the admin. (The confirmation reply was already
    # sent, so we send a corrective follow-up.)
    # Wrong-day guard: if the client's last message said tomorrow/today but the
    # booking date is a different day, do NOT create the record — a home visit on
    # the wrong day is the worst outcome. The wording override already asked the
    # client to confirm the day; here we just block + alert admin.
    _last_user = ""
    for _m in reversed(context.recent_messages or []):
        if _m.get("role") == "user":
            _last_user = _m.get("content") or ""
            break
    _dm = _booking_day_mismatch(_last_user, booking_call)
    if _dm:
        logger.error(
            f"Wappi: WRONG-DAY booking BLOCKED for {telegram_id} — client said "
            f"{_dm[0]!r} but tool date={booking_call.date}. No record created."
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=(f"Day mismatch: client said {_dm[0]} ({_dm[1]}) but tool "
                            f"date={booking_call.date}. Blocked — confirm the day."),
                )
            except Exception:
                pass
        return

    _has_location, _has_name = _booking_has_location_and_name(
        booking_call, context.client_data
    )
    if not (_has_location and _has_name):
        _missing = ([] if _has_name else ["name"]) + ([] if _has_location else ["location"])
        logger.warning(
            f"Wappi: booking BLOCKED for {telegram_id} — missing {_missing}. "
            f"No record created."
        )
        # NOTE: the client is asked for the missing info by the wording-override
        # in _process_wappi_message (single reply) — we don't send a duplicate
        # here. This gate is the binding RECORD block + admin alert.
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=(f"Agent tried to book WITHOUT {', '.join(_missing)} — "
                            f"asked the client, no record created. "
                            f"{booking_call.service} {booking_call.date} {booking_call.time}"),
                )
            except Exception:
                pass
        return

    # Explicit-confirm gate (ТЗ: …→ payment → explicit CONFIRM). The model
    # sometimes calls book_appointment straight off the payment answer ("cash")
    # without the final recap+yes — caught live 2026-07-10. If the client's
    # LAST message isn't a confirmation, don't create the record; the wording
    # override already replaced the reply with the recap question, so the
    # client's "yes" on the next turn re-fires the tool and passes this gate.
    if not _client_confirmed(_last_user):
        logger.info(
            f"Wappi: booking deferred for {telegram_id} — awaiting explicit "
            f"confirm (last msg: {_last_user[:60]!r}). Recap question sent."
        )
        return

    # Phone gate (Instagram channel, binding record block): the identity key
    # is not a number — without a real client phone the YClients record can't
    # be created and the morning admin couldn't call to confirm (client's
    # rule). The reply override already asked the client for the number.
    if _is_ig_key(phone):
        _real_phone = (getattr(booking_call, "client_phone", None) or "").strip()
        if not _real_phone:
            try:
                _db_client = await bot_module.client_service.get_or_create_client(telegram_id)
                _real_phone = (_db_client.phone or "").strip()
            except Exception:
                _real_phone = ""
        if len(re.sub(r"\D", "", _real_phone)) < 9:
            logger.info(f"IG booking deferred for {telegram_id} — no client phone yet")
            return

    # Avoid-master guard: the client asked NOT to be sent this therapist, but the
    # model picked them anyway (the injected prompt note is advisory — the LLM
    # skips it). Don't create the record — re-offer with a different master and
    # alert the admin. Code gate backs the advisory note (SKILL: no hard gate = bug).
    _avoid_book = (context.client_data or {}).get("avoid_therapist") if context else None
    if _avoid_book and booking_call.master_name and \
            booking_call.master_name.strip().lower() == _avoid_book.strip().lower():
        logger.info(f"Booking blocked: master {_avoid_book!r} is on the client's avoid list")
        await _admin_text(
            f"🙅 <b>Бронь с нежелательным мастером заблокирована</b>\n"
            f"Клиент {telegram_id} ({phone}) просил НЕ присылать {_avoid_book}, а агент "
            f"пытался записать именно к ней. Предложите другого мастера."
        )
        if wappi_client:
            try:
                await _send_to_client(
                    phone, "Let me find you another therapist dear 🌹 one moment 🙏")
            except Exception:
                pass
        return

    # Slot-reality gate: never create a record for a time that isn't genuinely
    # free (an invented/occupied slot). Authoritative check against live YClients
    # for the client's area + service duration. Prefer booking_call.area (the
    # authoritative area the record will be created for, always present in the
    # tool call) over the in-memory context area, which may be None on a fresh
    # context — the gate used to be silently skipped in that case.
    _area = booking_call.area or (context.client_data or {}).get("area")
    if _area and booking_call.time:
        try:
            _slot_ok = await bot_module.yclients_service.is_slot_available(
                _area, booking_call.date, booking_call.time,
                int(booking_call.duration_minutes or 60))
        except Exception as e:
            logger.warning(f"Wappi: slot-reality check failed ({e}) — allowing")
            _slot_ok = True
        if not _slot_ok:
            logger.error(
                f"Wappi: booking BLOCKED — {booking_call.time} on {booking_call.date} "
                f"({_area}) is NOT a real free slot. No record created."
            )
            if bot_module.notification_service:
                try:
                    await bot_module.notification_service.send_booking_failed(
                        telegram_id=telegram_id,
                        reason=(f"Agent tried to book {booking_call.time} {booking_call.date} "
                                f"({_area}) but it's not free/offered. Blocked."),
                    )
                except Exception:
                    pass
            if wappi_client:
                try:
                    await _send_to_client(
                        phone,
                        f"Sorry dear, {_to_ampm(booking_call.time)} isn't free 🙏 "
                        "let me offer you the real times — one moment 🌹")
                except Exception:
                    pass
            return

    # Save in local DB
    try:
        client = await bot_module.client_service.get_or_create_client(telegram_id)
        if not client.phone:
            # For IG identities the key is NOT a phone — store the real number
            # the client dictated (booking_call.client_phone), never the key.
            real_phone = booking_call.client_phone if _is_ig_key(phone) else phone
            if real_phone and not _is_ig_key(str(real_phone)):
                await bot_module.client_service.update_client(telegram_id, phone=real_phone)
        if booking_call.client_name and not client.name:
            await bot_module.client_service.update_client(
                telegram_id, name=booking_call.client_name
            )
        # Persist the text address so the driver / admin / reminder messages
        # show where to go (they read client.location_details).
        if booking_call.address and not (client.location_details or "").strip():
            await bot_module.client_service.update_client(
                telegram_id, location_details=booking_call.address
            )

        booking = await bot_module.booking_service.create_booking(
            telegram_id=telegram_id,
            service_name=booking_call.service,
            duration=booking_call.duration_minutes,
            base_price=booking_call.base_price_aed,
            booking_date=booking_date,
            payment_method=booking_call.payment_method,
        )
        await bot_module.booking_service.update_booking_status(booking.id, "confirmed")
        dialog_manager.update_state(user_id, "completed")
        # Remember who they booked with, so "same as last time" works next visit.
        if booking_call.master_name:
            try:
                await bot_module.client_service.update_client(
                    telegram_id, preferred_therapist=booking_call.master_name)
                if context:
                    context.client_data["preferred_therapist"] = booking_call.master_name
            except Exception as _e:
                logger.warning(f"couldn't persist preferred_therapist on booking: {_e}")
        logger.info(
            f"✅ Wappi booking {booking.id} saved "
            f"({booking_call.service} {booking_call.date} {booking_call.time} "
            f"{booking_call.area})"
        )
    except Exception as e:
        logger.error(f"Wappi DB booking error: {e}", exc_info=True)
        return

    # Did the appointment actually reach YClients? Stays True when there is no
    # YClients path (mock/dev). We only fingerprint the booking for de-dup AFTER
    # it is confirmed synced — so a FAILED sync can be retried by the model's
    # next identical tool call instead of being silently suppressed as a
    # duplicate (which previously left the appointment in local DB only).
    _yc_synced = True

    # Create in YClients
    if bot_module.yclients_service and not config.MOCK_YCLIENTS:
        _yc_synced = False
        try:
            import os as _os
            yc_service_id = await bot_module.yclients_service.find_service_id(
                booking_call.service,
                duration_minutes=booking_call.duration_minutes,
            )
            if yc_service_id is None:
                logger.error(
                    f"YClients: couldn't map service {booking_call.service!r} "
                    f"({booking_call.duration_minutes}min) to any catalog entry"
                )
                if bot_module.notification_service:
                    try:
                        await bot_module.notification_service.send_booking_failed(
                            telegram_id=telegram_id,
                            reason=(
                                f"Local booking created but YClients sync failed: "
                                f"service {booking_call.service!r} "
                                f"({booking_call.duration_minutes}min) not in catalog. "
                                f"Admin must add the YClients record manually."
                            ),
                        )
                    except Exception:
                        pass
            # Staff resolution priority:
            #   1. master_id from tool call — the model picked a concrete therapist
            #   2. master_name from tool call, filtered by area
            #   3. any non-admin staff in the client's area
            # Never falls back to an unfiltered default: sending an
            # Al-Ain therapist to an Abu-Dhabi client (or vice versa)
            # means a 90-minute misrouted drive and a missed appointment.
            yc_staff_id = booking_call.master_id
            # Never trust a master_id blindly: the model can hallucinate an
            # integer that happens to be a real therapist in ANOTHER emirate.
            # If the supplied id doesn't serve the client's area, drop it and
            # re-resolve within the area — a cross-emirate booking is a 90-min
            # wrong-city drive / missed appointment.
            if yc_staff_id and booking_call.area:
                # date-aware: a floating master (Lyudmila) validates by her
                # daily emirate marker, not her name tag — else she'd be dropped
                # and the client would get a DIFFERENT therapist than confirmed.
                _mid_area = await bot_module.yclients_service.staff_area_of(
                    yc_staff_id, date=booking_call.date)
                if _mid_area is not None and _mid_area != booking_call.area:
                    logger.warning(
                        f"book: master_id {yc_staff_id} serves {_mid_area!r}, not "
                        f"client area {booking_call.area!r} — re-resolving by area"
                    )
                    yc_staff_id = None
            if not yc_staff_id:
                yc_staff_id = await bot_module.yclients_service.find_staff_id(
                    name=booking_call.master_name,
                    area=booking_call.area,
                    date=booking_call.date,
                )
            if not yc_staff_id:
                logger.error(
                    f"YClients: no staff found for area={booking_call.area!r} "
                    f"master_name={booking_call.master_name!r}. "
                    f"Skipping YClients record creation."
                )
                if bot_module.notification_service:
                    try:
                        await bot_module.notification_service.send_booking_failed(
                            telegram_id=telegram_id,
                            reason=(
                                f"Couldn't find a therapist in {booking_call.area} "
                                f"for {booking_call.master_name or 'any'}. "
                                f"Local booking #{booking.id} saved but NOT "
                                f"synced to YClients. Admin must assign manually."
                            ),
                        )
                    except Exception:
                        pass

            fresh_client = await bot_module.client_service.get_or_create_client(telegram_id)
            client_name = (
                booking_call.client_name
                or fresh_client.name
                or sender_name
                or "WhatsApp Client"
            )
            # For IG identities the key must never leak into YClients as a
            # "phone" — the phone gate above guarantees a real number exists.
            client_phone = (
                booking_call.client_phone
                or fresh_client.phone
                or ("" if _is_ig_key(phone) else phone)
            )

            if yc_service_id and yc_staff_id:
                _is_test = _os.getenv("YCLIENTS_TEST_BOOKINGS", "false").lower() == "true"
                # Whitelisted IG testers always create [TEST]-prefixed records.
                if _is_ig_key(phone) and _is_ig_test_subscriber(phone[len(IG_KEY_PREFIX):]):
                    _is_test = True
                yc_result = await bot_module.yclients_service.create_booking(
                    staff_id=yc_staff_id,
                    service_ids=[yc_service_id],
                    date=booking_call.date,
                    time=booking_call.time,
                    client_name=client_name,
                    client_phone=client_phone,
                    comment=(
                        (
                            f"Instagram agent booking (night) #{booking.id}. "
                            f"Phone: {client_phone}. "
                            if _is_ig_key(phone)
                            else f"WhatsApp (Wappi) bot booking #{booking.id}. "
                        )
                        + f"Area: {booking_call.area}. "
                        # The admin calls this client in the morning to confirm
                        # (IG rule) — they must see how the client is paying, or
                        # they quote the wrong sum. Cash and transfer differ by 5%.
                        + (
                            f"Payment: {_payment_label(booking_call.payment_method)}. "
                            if getattr(booking_call, "payment_method", None)
                            else ""
                        )
                        + (f"Notes: {booking_call.notes}. " if booking_call.notes else "")
                        + (f"Address: {booking_call.address}." if booking_call.address else "")
                    ),
                    is_test=_is_test,
                    duration_minutes=booking_call.duration_minutes,
                )
                if yc_result:
                    _yc_synced = True
                    logger.info(
                        f"✅ YClients booking created from WhatsApp: "
                        f"#{yc_result.get('id', '?')}"
                    )
                    # Who is actually driving to the client. `staff_name` never
                    # existed on the tool call (the field is master_name), and
                    # IG replies deliberately never name a therapist — so the
                    # morning retro used to show an empty master on every IG
                    # booking. Resolve it from the id we just booked with.
                    _master_log = (getattr(booking_call, "master_name", "") or "").strip()
                    if not _master_log and yc_staff_id:
                        try:
                            _all_staff = await bot_module.yclients_service.get_staff()
                            _master_log = next(
                                (str(s.get("name", "")) for s in (_all_staff or [])
                                 if str(s.get("id")) == str(yc_staff_id)), "")
                        except Exception:
                            _master_log = ""
                    _night_event(
                        "booking_created", who=phone,
                        record=str(yc_result.get("id", "?")),
                        service=str(getattr(booking_call, "service", "")),
                        date=str(getattr(booking_call, "date", "")),
                        time=str(getattr(booking_call, "time", "")),
                        master=_master_log,
                    )
                    # Persist the record id — cancel/reschedule mutate YClients
                    # directly and target the record through this.
                    if yc_result.get("id"):
                        try:
                            await bot_module.booking_service.set_yclients_id(
                                booking.id, yc_result["id"]
                            )
                        except Exception as e:
                            logger.error(f"Couldn't persist YClients id: {e}")
                else:
                    # Create failed (4xx / slot conflict / save_if_busy). This
                    # used to be a bare log — the appointment silently never
                    # reached the calendar. Alert the admin so it's reconciled.
                    logger.warning("⚠️ YClients booking creation failed")
                    if bot_module.notification_service:
                        try:
                            await bot_module.notification_service.send_booking_failed(
                                telegram_id=telegram_id,
                                reason=(
                                    f"YClients did NOT accept booking #{booking.id} "
                                    f"({booking_call.service} {booking_call.date} "
                                    f"{booking_call.time}, {booking_call.area}). "
                                    f"Local record saved — admin must create the "
                                    f"YClients record manually."
                                ),
                            )
                        except Exception:
                            pass
            else:
                logger.warning(
                    f"⚠️ YClients: service_id={yc_service_id}, "
                    f"staff_id={yc_staff_id} — skipping"
                )
        except Exception as e:
            logger.error(f"❌ YClients booking error from WhatsApp: {e}")

    # Fingerprint for de-dup ONLY once the booking is confirmed synced (or there
    # was no YClients path at all). A failed sync leaves the sig unset so the
    # model's next identical book_appointment call retries instead of being
    # suppressed as a duplicate.
    if _yc_synced:
        context.last_booking_sig = _new_sig

    # Notify admin + auto-share the trip with the driver/logistics group.
    try:
        fresh_client = await bot_module.client_service.get_or_create_client(telegram_id)
    except Exception as e:
        logger.error(f"Wappi: couldn't load client for post-booking notifications: {e}")
        return

    if bot_module.notification_service:
        try:
            await bot_module.notification_service.send_booking_confirmed(fresh_client, booking)
        except Exception as e:
            logger.error(f"Wappi: failed to notify admin: {e}")

    # Terminal is a physical constraint (1 terminal for 6 masters). The note is
    # in the YClients comment, but the admin coordinates who carries it — surface
    # it in Telegram too so it isn't missed.
    if booking_call.notes and "терминал" in booking_call.notes.lower():
        await _admin_text(
            f"💳 <b>Клиент просит ТЕРМИНАЛ</b> — бронь #{booking.id} "
            f"({booking_call.service} {booking_call.date} {booking_call.time}, "
            f"{booking_call.area}). Мастеру нужно взять терминал."
        )

    # Group booking ("me and my mom" / couple): the primary person is booked
    # above, but each EXTRA guest needs their OWN therapist at the same time.
    # The agent can't safely auto-pick a 2nd free master live (2-master
    # availability + partial-failure rollback), so extra records are
    # TEAM-MEDIATED — same honest pattern as cancel/reschedule. Alert the admin
    # with the exact records to add. The silent bug this fixes: one record
    # created for two people (live-caught 2026-07-14, Annette «бронь только на
    # одного»). The client is told their group is being finalised by the team.
    _group_flag = bool((context.booking_data or {}).get("group_requested"))
    if booking_call.guests or _group_flag:
        _when = f"{booking_call.date} {_to_ampm(booking_call.time)}"
        if booking_call.guests:
            _body = "Каждому гостю нужен СВОЙ мастер в тот же слот:\n" + "\n".join(
                f"• {g.get('client_name')} — "
                f"{g.get('service') or booking_call.service} "
                f"({g.get('duration_minutes') or booking_call.duration_minutes} min)"
                for g in booking_call.guests
            )
        else:
            # Safety net: the client asked for a group but the model booked only
            # the main person (no guests in the tool call). Don't let the extra
            # person silently vanish — flag it for a human to add.
            _body = (
                "⚠️ Клиент упоминал запись НА НЕСКОЛЬКИХ человек, но агент создал "
                "только ОДНУ запись. Проверьте диалог и добавьте недостающие."
            )
        await _admin_text(
            f"👥 <b>ГРУППОВАЯ ЗАПИСЬ — проверьте/добавьте записи вручную</b>\n\n"
            f"Основная бронь #{booking.id}: {booking_call.client_name} — "
            f"{booking_call.service}, {_when}, {booking_call.area}.\n"
            f"{_body}\n\n"
            f"⚠️ Доп. люди НЕ бронируются автоматически (нужны разные мастера, "
            f"тот же адрес/время)."
        )

    # Auto-share with driver on booking creation (FR 5.2). No-op until
    # DRIVER_TELEGRAM_CHAT_ID is configured, so safe to always call.
    # Best-effort — a driver-send failure must never break the flow.
    try:
        driver_status = await _notify_driver(booking, fresh_client)
        if driver_status == "sent":
            logger.info(f"🚗 Driver auto-notified for booking {booking.id}")
    except Exception as e:
        logger.error(f"Wappi: driver auto-notify failed: {e}")


async def _admin_text(message: str):
    """Post a plain HTML message to the admin group; falls back to the DM
    (NotificationService._send_with_fallback) — alerts must never vanish just
    because the group id is dead (live catch 2026-07-10: getChat 400)."""
    import bot as bot_module
    ns = bot_module.notification_service
    if not ns or not ns.group_chat_id:
        return
    try:
        await ns._send_with_fallback(text=message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to post admin text (incl. fallback): {e}")


def _driver_request_text(booking, client) -> str:
    """Build the driver/logistics transport-request message for a booking."""
    when = booking.booking_date.strftime("%d.%m.%Y %H:%M") if booking.booking_date else "—"
    maps = ""
    if client.location_latitude and client.location_longitude:
        maps = f"\n🗺️ https://maps.google.com/?q={client.location_latitude},{client.location_longitude}"
    return (
        f"🚗 <b>New transport request</b>\n\n"
        f"📅 {when}\n"
        f"💆 {booking.service_name} ({booking.duration or '?'} min)\n"
        f"👤 {client.name or 'Client'} — {client.phone or '—'}\n"
        f"📍 {client.location_details or '—'}{maps}"
    )


async def _notify_driver(booking, client) -> str:
    """Send a transport request to the driver group (FR 5.2 'share with driver').

    Returns 'sent' | 'no_driver_configured' | 'error'. No-op when
    DRIVER_TELEGRAM_CHAT_ID is unset, so it's safe to call automatically on
    every booking before the driver group is provisioned.
    """
    if not config.DRIVER_TELEGRAM_CHAT_ID:
        return "no_driver_configured"
    try:
        await bot_instance.send_message(
            chat_id=config.DRIVER_TELEGRAM_CHAT_ID,
            text=_driver_request_text(booking, client),
            parse_mode="HTML",
        )
        return "sent"
    except Exception as e:
        logger.error(f"Driver notify failed: {e}")
        return "error"


async def _handle_cancellation(telegram_id: str, phone: str, call: "CancelCall", context=None):
    """Cancel the client's active booking: local status + penalty rules +
    DELETE the YClients record (owner decision 2026-07-10 — the agent manages
    the calendar itself). If the YClients delete fails, the admin is alerted
    to remove the record manually."""
    import bot as bot_module
    from services.cancellation import calculate_penalty
    from services.scheduler import now_uae

    # Two-phase guard: only cancel + apply penalty when the model explicitly
    # marked the client's intent as confirmed. A soft/ambiguous "maybe cancel"
    # must never charge money or free a slot.
    if not call.confirmed:
        logger.info(f"Cancel tool called WITHOUT confirmation for {telegram_id} — ignoring")
        return

    # Disambiguate: with >1 upcoming booking, a bare "cancel" would silently hit
    # the SOONEST one, which may not be the one the client means. Don't guess —
    # route to admin and let the client name which appointment. The tool's
    # old_date/old_time selector picks the booking when the client named it
    # ("cancel my 5:30 PM") — only an unresolvable ambiguity asks the client.
    actives = await bot_module.booking_service.get_active_bookings(telegram_id)
    b = None
    if len(actives) == 1:
        b = actives[0]
    elif len(actives) > 1:
        b = _match_booking_by_old_slot(actives, call.old_date, call.old_time)
        if b is None:
            logger.info(f"Cancel: {telegram_id} has multiple active bookings — not auto-cancelling")
            await _admin_text(
                f"❓ <b>Отмена — уточнить какую</b>\nКлиент <code>{telegram_id}</code> "
                f"({phone}) просит отмену, но у него НЕСКОЛЬКО активных броней. "
                f"Ничего не отменял — уточните у клиента и обработайте вручную."
            )
            if wappi_client:
                await _send_to_client(
                    phone,
                    "You have more than one upcoming appointment dear 🌹 "
                    "Which one would you like to cancel — please tell me its "
                    "time (e.g. 'the 5:30 PM one')?"
                )
            return

    if not b:
        logger.info(f"Cancel requested but no active booking for {telegram_id}")
        await _admin_text(
            f"❌ <b>Запрос на отмену</b>\nКлиент <code>{telegram_id}</code> "
            f"просит отмену, но активной брони в базе нет. Проверьте YClients."
        )
        return

    is_package = bool(b.get("package_id"))
    pen = calculate_penalty(
        b["booking_date"],
        is_package=is_package,
        master_en_route=call.master_en_route,
        reason=call.reason,
        now=now_uae(),
    )

    # Record cancellation locally
    await bot_module.booking_service.update_booking_status(
        b["booking_id"], "cancelled", notes=f"Cancelled: {call.reason}"[:500]
    )

    penalty_note = ""
    if pen["charge_aed"] > 0:
        await bot_module.booking_service.apply_penalty(
            b["booking_id"], pen["charge_aed"], pen["reason"]
        )
        penalty_note = f"\n💸 Штраф: {pen['charge_aed']:.0f} AED ({pen['reason']})"
    elif pen["deduct_session"] and is_package and bot_module.package_service:
        await bot_module.package_service.consume_session(b["package_id"])
        penalty_note = "\n💳 Списан 1 сеанс из пакета (отмена в день визита)"
    elif pen["force_majeure"]:
        penalty_note = "\n🤝 Форс-мажор — без штрафа"
    elif pen["free"]:
        penalty_note = "\n✅ Без штрафа (заблаговременная отмена)"

    # Cancel in YClients too (owner decision 2026-07-10: the agent manages the
    # calendar itself, no manual hand-off). Guarded: only a record whose client
    # phone matches this WhatsApp client can be deleted.
    yc_deleted = False
    yc_id = b.get("yclients_appointment_id")
    try:
        yc = bot_module.yclients_service
        if yc:
            if not yc_id and b.get("booking_date"):
                # Older bookings didn't persist the record id — find it by phone.
                found = await yc.find_record_by_phone(
                    phone, b["booking_date"].strftime("%Y-%m-%d")
                )
                yc_id = found and found.get("id")
            if yc_id:
                yc_deleted = await yc.cancel_record(yc_id, phone)
    except Exception as e:
        logger.error(f"Cancel: YClients sync error: {e}")

    when = b["booking_date"].strftime("%d.%m.%Y %H:%M") if b.get("booking_date") else "—"
    _area_lbl = {"abu_dhabi": "Abu Dhabi", "al_ain": "Al Ain", "dubai": "Dubai"}.get(
        b.get("area"), (b.get("area") or "").replace("_", " ").title())
    _master_line = f"💆 {b.get('therapist_name') or '—'}" + (f" · {_area_lbl}" if _area_lbl else "")
    # DELETE is API-walled (403) → removal from YClients is a MANUAL admin step.
    # Make it impossible to miss: a loud action header + WHOSE calendar to open,
    # else the record hangs in the app and the master drives to a cancelled visit
    # (live-caught 2026-07-14: «после отмены запись висит в приложении»).
    if yc_deleted:
        _header = "❌ <b>Отмена брони</b>"
        _yc_line = f"🗑️ Запись {yc_id} удалена из YClients автоматически ✅"
    else:
        _header = "‼️ <b>ОТМЕНА — УДАЛИТЕ ЗАПИСЬ ВРУЧНУЮ В YCLIENTS</b>"
        _yc_line = (
            f"⚠️ Запись (id {yc_id or 'не найдена'}) ОСТАЁТСЯ в YClients.\n"
            f"Удалите вручную, иначе мастер приедет на отменённый визит.\n"
            f"После удаления — предложите этот слот листу ожидания."
        )
    await _admin_text(
        f"{_header}\n\n"
        f"👤 {b.get('client_name') or telegram_id}\n"
        f"📞 {phone}\n"
        f"{_master_line}\n"
        f"🛎️ {b['service_name']} — {when}\n"
        f"💬 Причина: {call.reason or '—'}{penalty_note}\n"
        f"{_yc_line}"
    )

    # Waiting list: notify ONLY when the slot is GENUINELY free. On a failed
    # DELETE (403 — the current token can't delete) the record still occupies
    # the slot in YClients, so telling a waiting client "it's free" is a false
    # promise — they'd try to book a still-busy slot. The admin offers it after
    # the manual removal instead (see the alert above).
    if yc_deleted:
        await _notify_waiting_list(b.get("area"), b.get("booking_date"))
    else:
        logger.info(
            "Waiting list NOT notified — YClients delete didn't confirm, slot "
            "still occupied; admin will offer it after manual removal."
        )


async def _handle_reschedule(telegram_id: str, phone: str, call: "RescheduleCall", context=None):
    """Move the client's active booking to a new date/time: local records +
    move the YClients record itself (owner decision 2026-07-10). If the
    YClients move fails, the admin is alerted to move it manually."""
    import bot as bot_module
    from datetime import datetime as _dt, timedelta as _td

    # Pick WHICH booking to move. With >1 upcoming booking a bare "reschedule"
    # would hit the soonest one, maybe the wrong one. The tool now carries an
    # old_date/old_time selector (the client almost always names the original
    # slot — "move my 5:30 PM"); match on it. Only if the selector can't
    # single out one booking do we ask the client — this used to LOOP because
    # the clarifying answer had no way to reach the handler.
    actives = await bot_module.booking_service.get_active_bookings(telegram_id)
    b = None
    if len(actives) == 1:
        b = actives[0]
    elif len(actives) > 1:
        b = _match_booking_by_old_slot(actives, call.old_date, call.old_time)
        if b is None:
            logger.info(
                f"Reschedule: {telegram_id} has {len(actives)} active bookings, "
                f"selector old_date={call.old_date!r} old_time={call.old_time!r} "
                f"didn't single one out — asking the client"
            )
            await _admin_text(
                f"❓ <b>Перенос — уточнить какой</b>\nКлиент <code>{telegram_id}</code> "
                f"({phone}) просит перенос, но у него НЕСКОЛЬКО активных броней. "
                f"Ничего не переносил — уточните у клиента."
            )
            if wappi_client:
                await _send_to_client(
                    phone,
                    "You have more than one upcoming appointment dear 🌹 "
                    "Which one shall I move — please tell me its time "
                    "(e.g. 'the 5:30 PM one')?"
                )
            return

    if not b:
        await _admin_text(
            f"📅 <b>Запрос на перенос</b>\nКлиент <code>{telegram_id}</code> "
            f"просит перенос, но активной брони нет. Проверьте YClients."
        )
        return

    try:
        new_dt = _dt.strptime(f"{call.new_date} {call.new_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        # The client was already told "passed to the team, we'll confirm shortly"
        # — so a silent return would strand them. Alert the admin to follow up.
        logger.error(f"Reschedule: bad datetime {call.new_date} {call.new_time}")
        await _admin_text(
            f"⚠️ <b>Перенос — не разобрал дату/время</b>\nКлиент <code>{telegram_id}</code> "
            f"({phone}): агент прислал некорректные {call.new_date!r} {call.new_time!r}. "
            f"Клиенту сказали «передали команде» — уточните и перенесите вручную."
        )
        return

    # Sanity window — same guard as new bookings: not in the past (1h grace),
    # not more than 60 days out. Prevents a hallucinated/past slot becoming a
    # confirmed row the scheduler then messages about.
    now_uae = _dt.utcnow() + _td(hours=4)
    if new_dt < now_uae - _td(hours=1) or new_dt > now_uae + _td(days=60):
        logger.error(f"Reschedule: new date out of window: {new_dt.isoformat()}")
        await _admin_text(
            f"⚠️ <b>Перенос отклонён</b>\nКлиент <code>{telegram_id}</code>: "
            f"новая дата вне допустимого окна ({new_dt:%d.%m.%Y %H:%M}). "
            f"Обработайте вручную."
        )
        return

    # Re-validate availability with the SAME rigor as a new booking — otherwise
    # we'd confirm an occupied/off-day/travel-conflicting slot and the day-before
    # scheduler would message the client about a slot no master can serve. We can
    # only check when we know the client's area; skip the check if unknown.
    _area = context.client_data.get("area") if context else None
    if _area:
        _dur = int(b.get("duration") or 60)
        _hhmm = f"{new_dt.hour}:{new_dt.minute:02d}"
        try:
            # Exclude the record being moved so its OWN current slot doesn't
            # block the move (4:00 → 4:30 must not be blocked by the 4:00 record).
            _free = await bot_module.yclients_service.is_slot_available(
                _area, call.new_date, _hhmm, _dur,
                exclude_record_id=b.get("yclients_appointment_id"))
        except Exception as e:
            logger.warning(f"Reschedule availability check failed ({e}) — allowing")
            _free = True
        if not _free:
            logger.info(f"Reschedule: {new_dt.isoformat()} not free in {_area} — offering alternatives")
            await _admin_text(
                f"⚠️ <b>Перенос — слот занят</b>\nКлиент <code>{telegram_id}</code> "
                f"({phone}) просил перенос на {new_dt:%d.%m.%Y %H:%M} ({_area}), "
                f"но это время НЕ свободно. Ничего не переносил — предложите другое."
            )
            if wappi_client:
                await _send_to_client(
                    phone,
                    f"Sorry dear, {_to_ampm(_hhmm)} on that day isn't free 🙏 "
                    "Could you pick another time? I'll send you what's available 🌹"
                )
            return

    # Create the new booking (draft), chain the old one to it, THEN confirm the
    # new one. This order means a mid-way failure never leaves TWO 'confirmed'
    # rows (worst case: old='rescheduled' + new='draft', which the confirmation
    # scheduler ignores). Use base_price (pre-VAT) so calculate_total() doesn't
    # re-apply VAT on an already-inclusive total.
    new_booking = await bot_module.booking_service.create_booking(
        telegram_id=telegram_id,
        service_name=b["service_name"],
        duration=b.get("duration"),
        base_price=(b.get("base_price") if b.get("base_price") is not None else 0.0),
        booking_date=new_dt,
        payment_method=b.get("payment_method") or "cash",
    )
    await bot_module.booking_service.set_rescheduled(b["booking_id"], new_booking.id)
    await bot_module.booking_service.update_booking_status(new_booking.id, "confirmed")

    # Move the YClients record itself (owner decision 2026-07-10). Guarded:
    # only a record whose client phone matches this WhatsApp client.
    yc_moved = False
    yc_id = b.get("yclients_appointment_id")
    try:
        yc = bot_module.yclients_service
        if yc:
            if not yc_id and b.get("booking_date"):
                found = await yc.find_record_by_phone(
                    phone, b["booking_date"].strftime("%Y-%m-%d")
                )
                yc_id = found and found.get("id")
            if yc_id:
                yc_moved = await yc.reschedule_record(
                    yc_id, phone, call.new_date, call.new_time,
                    duration_minutes=b.get("duration"),
                )
                if yc_moved:
                    await bot_module.booking_service.set_yclients_id(
                        new_booking.id, yc_id
                    )
    except Exception as e:
        logger.error(f"Reschedule: YClients sync error: {e}")

    old_when = b["booking_date"].strftime("%d.%m.%Y %H:%M") if b.get("booking_date") else "—"
    new_when = new_dt.strftime("%d.%m.%Y %H:%M")
    _yc_line = (
        f"📌 Запись {yc_id} перенесена в YClients автоматически ✅"
        if yc_moved else
        f"⚠️ НЕ перенеслось в YClients (id {yc_id or 'не найден'}) — обновите вручную"
    )
    await _admin_text(
        f"📅 <b>Перенос брони</b>\n\n"
        f"👤 {b.get('client_name') or telegram_id}\n"
        f"📞 {phone}\n"
        f"🛎️ {b['service_name']}\n"
        f"⏮️ Было: {old_when}\n"
        f"⏭️ Стало: {new_when}\n"
        f"{_yc_line}"
    )
    # Definitive client message — sent HERE, after the availability re-check
    # passed, so the client never gets "passed to the team" contradicted by a
    # later "not free" (the turn's reply was only a neutral "checking…" line).
    # Honest team-mediated wording: the YClients move may or may not have synced;
    # the admin alert above carries the real status.
    if wappi_client:
        try:
            await _send_to_client(
                phone,
                f"Noted dear 🌹 I've passed your reschedule to {_to_ampm(call.new_time)} "
                f"to the team — we'll confirm it shortly 🙏"
            )
        except Exception:
            pass


async def _notify_waiting_list(area, freed_date):
    """When a slot frees up, ping the first matching waiting-list client."""
    import bot as bot_module
    wls = getattr(bot_module, "waiting_list_service", None)
    if not wls:
        return
    date_str = freed_date.strftime("%Y-%m-%d") if freed_date else None
    try:
        matches = await wls.get_matches(area=area, preferred_date=date_str)
    except Exception as e:
        logger.error(f"Waiting-list lookup failed: {e}")
        return
    if not matches:
        return
    first = matches[0]
    if first.get("phone") and wappi_client:
        try:
            await _send_to_client(
                first["phone"],
                "Good news dear 🌹 a slot just opened up for your preferred time! "
                "Would you like to book it? 😊",
            )
            await wls.mark_notified(first["id"])
            logger.info(f"Waiting-list: notified {first['phone']}")
        except Exception as e:
            logger.error(f"Waiting-list notify failed: {e}")


async def _reset_user(user_id: str, telegram_id: str):
    """Clear context, history, and client data for a user."""
    import bot as bot_module
    dialog_manager.clear_context(user_id)
    deleted = await bot_module.message_service.clear_history(telegram_id)
    await bot_module.client_service.reset_client(telegram_id)
    await bot_module.dialog_session_service.end_session(telegram_id)
    # Forget promo photos sent to this phone so a fresh session re-sends them.
    if str(user_id).startswith("wappi_"):
        _wappi_sent_promos.pop(str(user_id)[len("wappi_"):], None)
    logger.info(f"Reset user {user_id}: deleted {deleted} messages")
    return deleted


async def _process_wappi_message(phone: str, text: str, sender_name: str):
    """Background task: process WhatsApp message through AI agent."""
    try:
        import bot as bot_module

        # Channel-aware identity: Instagram turns arrive with an "ig:<id>"
        # key and must never look like a WhatsApp number downstream (the
        # wappi_ prefix is stripped back into a phone in scheduler paths).
        if _is_ig_key(phone):
            user_id = f"ig_{phone[len(IG_KEY_PREFIX):]}"
        else:
            user_id = f"wappi_{phone}"
        telegram_id = user_id

        # Check for reset commands (also handled pre-buffer in the webhook so a
        # reset sent right after another message still fires).
        if _is_reset_command(text):
            await _reset_user(user_id, telegram_id)
            # Route by channel, don't gate on the WhatsApp client: an
            # Instagram reset used to leave the client with no confirmation
            # at all when wappi wasn't configured (live-caught 2026-08-15).
            await _send_to_client(phone, _RESET_GREETING)
            return

        client = await bot_module.client_service.get_or_create_client(telegram_id)
        if sender_name and not client.name:
            await bot_module.client_service.update_client(telegram_id, name=sender_name)

        context = dialog_manager.get_or_create_context(user_id)

        if not context.recent_messages:
            db_history = await bot_module.message_service.get_conversation_history(telegram_id)
            if db_history:
                for msg in db_history[-20:]:
                    context.recent_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })
            # Area lives only in the in-memory context, so a Render restart /
            # deploy (frequent during this testing sprint) or a delayed reply to
            # the post-session survey lands on a FRESH context with area=None —
            # and the agent re-asks "which area?" ("снова спрашивает откуда я").
            # Restore it: (1) the persisted client.area column is authoritative;
            # (2) fall back to the newest area mention in the reloaded history.
            if not context.client_data.get("area"):
                if getattr(client, "area", None):
                    context.client_data["area"] = client.area
                    logger.info(f"area restored from DB: {client.area!r}")
                else:
                    for _m in reversed(context.recent_messages):
                        if _m.get("role") != "user":
                            continue
                        _recovered = detect_area(_m.get("content") or "")
                        if _recovered:
                            context.client_data["area"] = _recovered
                            logger.info(f"area recovered from history: {_recovered!r}")
                            # Backfill the column so next time it's a clean DB read.
                            try:
                                await bot_module.client_service.update_client(telegram_id, area=_recovered)
                            except Exception:
                                pass
                            break

            # Restore master preferences on a fresh context (survive a restart /
            # delayed reply) so "same as last time" and an avoided master hold
            # across sessions, not just within one in-memory context.
            if getattr(client, "preferred_therapist", None) and not context.client_data.get("preferred_therapist"):
                context.client_data["preferred_therapist"] = client.preferred_therapist
            if getattr(client, "avoid_therapist", None) and not context.client_data.get("avoid_therapist"):
                context.client_data["avoid_therapist"] = client.avoid_therapist

        await bot_module.message_service.save_message(telegram_id, "user", text)
        dialog_manager.add_user_message(user_id, text)

        # Client replied — reset the follow-up counter so nudges restart from
        # the beginning next time they go quiet (was Telegram-only before).
        if getattr(bot_module, "follow_up_service", None):
            bot_module.follow_up_service.reset_follow_up(user_id)

        # Persist the service category so slot injection routes to the right
        # specialists on THIS and later turns (nails clients were shown
        # massage therapists because service_type stayed None on the Wappi path).
        # Last mention wins, so a client who switches massage↔nails is re-routed.
        # Persist a sticky "service named" flag the moment the client names ANY
        # service — it drives the service-first gate below and must SURVIVE later
        # turns (client says "villa 15" / their name with no service word), or the
        # gate would re-ask "what service?" mid-flow. Covers lashes/facial that
        # service_type doesn't route.
        if _service_named(text) and not context.booking_data.get("service_named"):
            dialog_manager.update_booking_data(user_id, "service_named", True)

        # Sticky group-intent flag for the booking safety net below.
        if _looks_like_group(text) and not context.booking_data.get("group_requested"):
            dialog_manager.update_booking_data(user_id, "group_requested", True)

        # Which ad creative sent this client — STICKY, because the prefill
        # arrives in the very first message while the price question comes two
        # turns later. Live-caught 2026-08-15: a client from the cupping/package
        # creative was quoted the regular 350/460 per-session prices and never
        # saw the 275 offer he had actually tapped on.
        _ad_prefill = _detect_ad_prefill(text)
        if _ad_prefill and not context.booking_data.get("ad_prefill"):
            dialog_manager.update_booking_data(user_id, "ad_prefill", _ad_prefill)
            logger.info(f"ad prefill detected: {_ad_prefill}")

        # Master preference / replacement — persist to the client record so it
        # survives across sessions ("same as last time" works; an avoided master
        # is never offered again). Injected into the agent context below + a hard
        # booking guard backs it up.
        _avoid_m = _detect_avoided_master(text)
        if _avoid_m and _avoid_m != context.client_data.get("avoid_therapist"):
            context.client_data["avoid_therapist"] = _avoid_m
            try:
                await bot_module.client_service.update_client(telegram_id, avoid_therapist=_avoid_m)
            except Exception as _e:
                logger.warning(f"couldn't persist avoid_therapist: {_e}")
            await _admin_text(
                f"🙅 <b>Замена мастера</b>\n"
                f"Клиент {context.client_data.get('name') or telegram_id} ({phone}) "
                f"просит НЕ присылать <b>{_avoid_m}</b>. Записал в предпочтения — "
                f"агент больше не будет её предлагать."
            )
        _pref_m = _detect_preferred_master(text)
        if _pref_m and _pref_m != context.client_data.get("preferred_therapist"):
            context.client_data["preferred_therapist"] = _pref_m
            try:
                await bot_module.client_service.update_client(telegram_id, preferred_therapist=_pref_m)
            except Exception as _e:
                logger.warning(f"couldn't persist preferred_therapist: {_e}")

        _svc_cat = _detect_service_category(text)
        _cur_svc = context.booking_data.get("service_type") or None
        # Never DOWNGRADE a kind-specific type back to the generic one: the
        # detector only knows 'massage', so a later "massage tomorrow?" must
        # not erase the body/face answer already given (that re-arms the
        # body-or-face gate and re-asks a settled question).
        if (_svc_cat and _svc_cat != _cur_svc
                and not (_svc_cat == "massage"
                         and (_massage_kind_known(_cur_svc or "")
                              or _cur_svc == _COMBO_KEY))):
            dialog_manager.update_booking_data(user_id, "service_type", _svc_cat)
            # A category switch invalidates any previously-stated duration: a
            # 90-min massage length must not keep over-filtering slots for a
            # later manicure. Clear it — it re-defaults to 60 and is re-detected
            # from THIS/next message if the client names a new length.
            if context.booking_data.get("service_duration"):
                dialog_manager.update_booking_data(user_id, "service_duration", None)
        # Upgrade the generic 'massage' with the kind the client just named
        # ("body massage" → body_massage). Same category, so the duration is
        # NOT reset — this is the client answering the gate's own question,
        # and without the upgrade the gate never releases.
        _kind_now = _massage_kind_from_text(text)
        _svc_after = context.booking_data.get("service_type") or ""
        if (_kind_now and _is_massage_service(_svc_after)
                and not _massage_kind_known(_svc_after)):
            dialog_manager.update_booking_data(
                user_id, "service_type", f"{_kind_now}_massage")
            logger.info(f"massage kind upgraded from text → {_kind_now}_massage")

        # Out-of-area is STICKY: once the client says Sharjah (etc.), the
        # funnel stops — and it stays stopped on their "Okay" next turn, which
        # is exactly where the model used to resume selling (client complaint
        # 2026-08-16: «зачем спрашивать какой сервис… можно попрощаться
        # красиво и всё»). Naming one of OUR cities lifts the flag.
        _ooa_city = _detect_out_of_area(text)
        if _ooa_city:
            dialog_manager.update_booking_data(user_id, "out_of_area", _ooa_city)
            logger.info(f"out-of-area detected: {_ooa_city} — funnel stops")
        elif detect_area(text) and context.booking_data.get("out_of_area"):
            dialog_manager.update_booking_data(user_id, "out_of_area", None)
            logger.info("client named a served emirate — out-of-area lifted")

        # The advertised cupping combo has a FIXED length: choosing it settles
        # BOTH the service and the duration, so the 60-or-90 question is never
        # asked (it cost a hot lead on 2026-08-16 — see _detect_combo_choice).
        if (_is_ig_key(phone) and _detect_combo_choice(text)
                and context.booking_data.get("service_type") != _COMBO_KEY):
            from prices import SPECIAL_OFFERS as _SO
            dialog_manager.update_booking_data(user_id, "service_type", _COMBO_KEY)
            dialog_manager.update_booking_data(
                user_id, "service_duration", int(_SO[_COMBO_KEY]["duration"]))
            logger.info("combo choice detected → lymphatic_cupping_combo, 60 min fixed")

        # Reset the injected-slots block EVERY turn before rebuilding it. It is
        # per-turn ground truth (dated "TODAY — <date>"); if this turn's fetch is
        # skipped or fails, a leftover block from a previous turn would re-inject
        # STALE slots with an outdated date. Start clean.
        context.extra_system_info = ""
        context.slot_truth = {}  # reset with it — same staleness argument

        # Inject YClients slots if we know the area
        logger.info(
            f"slot_inject_check: yc_service={bot_module.yclients_service is not None} "
            f"mock={config.MOCK_YCLIENTS} text={text[:60]!r}"
        )
        if bot_module.yclients_service and not config.MOCK_YCLIENTS:
            _text_lower = text.lower()
            _client_area = context.client_data.get("area") or ""
            logger.info(
                f"slot_inject_entry: text_low={_text_lower!r} "
                f"area_cached={_client_area!r}"
            )
            # Detect an EXPLICIT area mention in THIS message. This runs even
            # when an area is already cached, so a client can CHANGE area
            # mid-session ("actually I'm in Abu Dhabi" must override a cached
            # al_ain — was stuck before, showing the wrong emirate's masters).
            # Detection lives in the shared detect_area() helper so the offline
            # simulator matches prod exactly.
            _explicit_area = detect_area(_text_lower)
            # Explicit mention wins over any cached value.
            if _explicit_area and _explicit_area != _client_area:
                logger.info(
                    f"area switch: {_client_area!r} → {_explicit_area!r} "
                    f"(explicit mention in message)"
                )
                _client_area = _explicit_area
                dialog_manager.update_client_data(user_id, "area", _explicit_area)
                # Persist so it survives a restart / delayed survey reply.
                try:
                    await bot_module.client_service.update_client(telegram_id, area=_explicit_area)
                except Exception as _e:
                    logger.warning(f"couldn't persist area to client record: {_e}")

            # Capture the session length on ANY message (even before area is
            # known) and persist it, so slots only offer times the WHOLE session
            # fits. An explicitly-stated length ("90 минут") wins; otherwise the
            # recognised service's own length (a gel manicure is 2h, a combo 3h).
            _dur_detected = _detect_duration_minutes(_text_lower) or _detect_service_duration(_text_lower)
            if _dur_detected and _dur_detected != context.booking_data.get("service_duration"):
                dialog_manager.update_booking_data(user_id, "service_duration", _dur_detected)
                logger.info(f"duration_detect: {_dur_detected} min (from message)")

            logger.info(f"slot_inject_post_detect: area_now={_client_area!r}")
            _service_known = bool(
                context.booking_data.get("service_named")
                or context.booking_data.get("service_type")
            )
            if _client_area and not _service_known:
                # SERVICE-FIRST GATE: area is confirmed but the client has NOT
                # named a service yet. Injecting slots here dumps massage times at
                # a client who may want nails/lashes/facial (live-caught
                # 2026-07-15: client said only "записаться на завтра", was shown
                # massage slots, actually wanted a manicure — "почему вы не
                # спросили какая услуга?"). Canonical flow is service → area →
                # slot; the prompt says so but the LLM skips it, so gate it in
                # CODE (crystal-lab SKILL: "no hard gate = bug"). Ask first.
                logger.info("service_first_gate: area known, service unknown → ask service")
                context.extra_system_info = SERVICE_FIRST_GATE_MSG
            elif (
                _is_ig_key(phone)
                and _is_massage_service(context.booking_data.get("service_type") or "")
                and not _massage_kind_known(context.booking_data.get("service_type") or "")
            ):
                logger.info("massage_kind_gate: 'massage' unspecified → ask body/face")
                context.extra_system_info = MASSAGE_KIND_GATE_MSG
            elif (
                _is_ig_key(phone)
                and not context.booking_data.get("service_duration")
                and _is_massage_service(context.booking_data.get("service_type") or "")
            ):
                # Same reasoning as the service gate, one step later: the LLM
                # happily pastes 60-min windows while the client hasn't said
                # whether they want 60 or 90 (live-caught 2026-08-15). Ask,
                # then show times that actually fit.
                logger.info("duration_first_gate: massage without duration → ask 60/90")
                context.extra_system_info = DURATION_FIRST_GATE_MSG
            elif _client_area:
                try:
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                    _uae = _tz(_td(hours=4))
                    _now = _dt.now(_uae)
                    today = _now.strftime("%Y-%m-%d")
                    tomorrow = (_now + _td(days=1)).strftime("%Y-%m-%d")

                    service_name = context.booking_data.get("service_type") or ""
                    _service_duration = context.booking_data.get("service_duration")
                    # Fetch today + tomorrow concurrently (was sequential).
                    slots_today, slots_tomorrow = await asyncio.gather(
                        bot_module.yclients_service.get_available_slots_summary(
                            date=today, service_name=service_name, area=_client_area,
                            service_duration=_service_duration),
                        bot_module.yclients_service.get_available_slots_summary(
                            date=tomorrow, service_name=service_name, area=_client_area,
                            service_duration=_service_duration),
                    )

                    # Detect specific date mentioned in message (e.g. "Sunday", "26 april", "sat")
                    extra_dates = []
                    # A client may spell the date out ("20 August", "22/08",
                    # "the 20th") instead of naming a weekday — without this
                    # the day's slots were never loaded and the agent said it
                    # had no schedule for a day that was wide open.
                    _explicit = _detect_explicit_date(_text_lower, _now)
                    if _explicit and _explicit not in (today, tomorrow):
                        extra_dates.append(_explicit)
                        dialog_manager.update_booking_data(user_id, "date", _explicit)
                    logger.info(
                        f"weekday_detect: text_low={_text_lower!r} "
                        f"today={today} tomorrow={tomorrow} "
                        f"current_wd={_now.weekday()}"
                    )
                    _day_keywords = {
                        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                        "friday": 4, "saturday": 5, "sunday": 6,
                        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
                        "понедел": 0, "вторник": 1, "сред": 2, "четверг": 3,
                        "пятниц": 4, "суббот": 5, "воскрес": 6,
                    }
                    import re as _re_day
                    for kw, weekday in _day_keywords.items():
                        # Word-boundary match: "sat" must not match "satellite",
                        # "mon" must not match "money", "fri" must not match
                        # "afraid". Russian prefixes (e.g. "понедел") anchor
                        # only at start — still match "понедельник".
                        if _re_day.search(r"\b" + kw, _text_lower):
                            # For English full/short forms also require \b at
                            # end. "понедел" is a prefix, leave trailing open.
                            if kw.isascii() and not _re_day.search(r"\b" + kw + r"\b", _text_lower):
                                continue
                            _current_wd = _now.weekday()
                            days_ahead = (weekday - _current_wd) % 7
                            # If today matches — today (not next week)
                            if days_ahead == 0 and "next" in _text_lower:
                                days_ahead = 7
                            target_date = (_now + _td(days=days_ahead)).strftime("%Y-%m-%d")
                            if target_date != today and target_date != tomorrow:
                                extra_dates.append(target_date)
                                # Persist the chosen day so a later turn with no
                                # weekday word (villa/name/GPS/"cash") keeps
                                # injecting THIS day's slots — fixes the
                                # "loses Sunday then says no schedule" dead-end.
                                dialog_manager.update_booking_data(
                                    user_id, "date", target_date
                                )
                            logger.info(
                                f"weekday_detect: matched kw={kw!r} → "
                                f"weekday={weekday} days_ahead={days_ahead} "
                                f"target={target_date} appended={target_date not in (today, tomorrow)}"
                            )
                            break
                    else:
                        logger.info("weekday_detect: no weekday keyword matched")

                    # Fetch slots for specific date if mentioned.
                    # We label each date with its weekday name so the LLM
                    # can map the client's "Wednesday" / "среда" to the
                    # actual ISO date — without that bridge it claims
                    # "I don't have availability info yet" even when the
                    # context lists "2026-04-29: <real slots>". (See bug
                    # report 2026-04-27: client asked for Wednesday and
                    # Thursday, bot fell back to "tomorrow" despite
                    # having the data.)
                    _weekday_names = [
                        "Monday", "Tuesday", "Wednesday", "Thursday",
                        "Friday", "Saturday", "Sunday",
                    ]

                    def _label(date_str: str) -> str:
                        try:
                            wd = _dt.strptime(date_str, "%Y-%m-%d").weekday()
                            return f"{_weekday_names[wd]} ({date_str})"
                        except Exception:
                            return date_str

                    # Always include the booking's chosen date if it's set —
                    # otherwise once the client has picked Sunday and the
                    # next message is just "Villa 23" / a GPS pin / their
                    # name (no weekday keyword), the slot block falls back
                    # to today+tomorrow only. The model then sees Sunday
                    # in chat history but no Sunday data in the context
                    # and emits "Sorry, we don't have Sunday schedule"
                    # AFTER it has already confirmed Sunday 12:00. Real
                    # bug from the 2026-04-27 16:09 UAE chat.
                    chosen_date = (context.booking_data or {}).get("date")
                    if chosen_date and chosen_date not in extra_dates \
                            and chosen_date != today and chosen_date != tomorrow:
                        extra_dates.insert(0, chosen_date)

                    # Ground truth for the outgoing-reply slot gate: date →
                    # set of genuinely free times (None = YClients outage,
                    # judge nothing). The model has been caught reading times
                    # off nowhere for a day whose block says "No slots
                    # available… do NOT invent times" (Al Ain, 2026-08-15).
                    _slot_truth = {
                        today: _times_from_summary(slots_today),
                        tomorrow: _times_from_summary(slots_tomorrow),
                    }
                    extra_slots_text = ""
                    for d in extra_dates[:2]:  # chosen date + at most 1 mentioned extra
                        try:
                            slots = await bot_module.yclients_service.get_available_slots_summary(
                                date=d, service_name=service_name, area=_client_area,
                                service_duration=_service_duration)
                            extra_slots_text += f"\n\n{_label(d)}:\n{slots}"
                            _slot_truth[d] = _times_from_summary(slots)
                        except Exception:
                            pass
                    context.slot_truth = _slot_truth

                    area_note = ""
                    if _client_area == "al_ain":
                        area_note = "\n🚨 Client in AL AIN. Show ONLY Al Ain therapists."
                    elif _client_area == "dubai":
                        area_note = "\n🚨 Client in DUBAI. Show ONLY Dubai therapists."
                    elif _client_area == "abu_dhabi":
                        area_note = "\n🚨 Client in ABU DHABI. Show ONLY Abu Dhabi therapists (no Al Ain / Dubai masters)."

                    # Master preference / replacement — surface stored prefs so the
                    # agent offers the preferred master first and NEVER offers the
                    # avoided one (a hard booking guard backs the avoid up).
                    _pref_note = ""
                    _pm = (context.client_data or {}).get("preferred_therapist")
                    _am = (context.client_data or {}).get("avoid_therapist")
                    if _pm:
                        _pref_note += (
                            f"\n💚 This client PREFERS {_pm} — offer {_pm}'s times first "
                            f"if available and honour 'same as last time'.")
                    if _am:
                        _pref_note += (
                            f"\n🚫 This client asked NOT to be sent {_am} — NEVER offer "
                            f"or book {_am} for them; pick another therapist.")

                    # Build a list of weekdays that ARE in this context so we
                    # can name them explicitly in the guard. The LLM keeps
                    # echoing its own previous "I don't have Sunday schedule
                    # yet" replies from chat history; naming the available
                    # weekdays inline forces it to compare against ground
                    # truth instead of pattern-matching on past responses.
                    _today_wd = _weekday_names[_dt.strptime(today, "%Y-%m-%d").weekday()]
                    _tom_wd = _weekday_names[_dt.strptime(tomorrow, "%Y-%m-%d").weekday()]
                    _extra_wd_list = []
                    for d in extra_dates[:1]:
                        try:
                            _extra_wd_list.append(
                                _weekday_names[_dt.strptime(d, "%Y-%m-%d").weekday()]
                            )
                        except Exception:
                            pass
                    _all_wd = ", ".join([_today_wd, _tom_wd] + _extra_wd_list)

                    context.extra_system_info = (
                        f"\n\nREAL AVAILABLE SLOTS (ground truth — overrides anything you said before):\n"
                        f"TODAY — {_label(today)}:\n{slots_today}\n\n"
                        f"TOMORROW — {_label(tomorrow)}:\n{slots_tomorrow}"
                        f"{extra_slots_text}\n\n"
                        f"🚨 The schedule above is the GROUND TRUTH. Available weekdays in "
                        f"this context: {_all_wd}.\n"
                        "🚨 If the client names ANY of those weekdays (in EN or RU: Wednesday / "
                        "среда / Thursday / четверг / Sunday / воскресенье …), MATCH it to the "
                        "labelled block above and quote those exact slots. NEVER reply 'I don't "
                        "have [weekday] schedule yet' / 'no availability info' for a weekday "
                        "that is IN this context — that's a hallucination from earlier in the "
                        "chat, ignore your past replies on this point.\n"
                        "🚨 PRESENTATION ORDER: when the client hasn't named a specific day, "
                        "offer TODAY's slots first. If the client doesn't want today, ask 'When "
                        "would suit you dear?' instead of jumping straight to tomorrow.\n"
                        "🚨 Use ONLY these real slots. Answer immediately — do NOT say 'checking'."
                        f"{area_note}{_pref_note}"
                    )

                    # The client named a CONCRETE time — check that exact time
                    # against the calendar and hand the model the verdict.
                    # Live-caught 2026-08-15: the Instagram rule "merge every
                    # therapist's windows into ONE list of 3–4 times" made the
                    # model read "not in my short list" as "not available", so
                    # it refused 7:00 PM on a day a therapist was free — a
                    # booking lost to a slot we actually had. The short list is
                    # a PRESENTATION choice; it must never become the truth
                    # about what exists.
                    _asked_time = _detect_requested_time(text)
                    _asked_date = ((context.booking_data or {}).get("date")
                                   or (extra_dates[0] if extra_dates else ""))
                    if _asked_time and _asked_date:
                        try:
                            _time_free = await bot_module.yclients_service.is_slot_available(
                                _client_area, _asked_date, _asked_time,
                                _service_duration or 60)
                        except Exception as _e:
                            logger.warning(f"requested-time check failed: {_e}")
                            _time_free = None
                        if _time_free is not None:
                            _pretty = _to_ampm(_asked_time)
                            logger.info(
                                f"requested_time_check: {_asked_date} {_asked_time} "
                                f"area={_client_area!r} free={_time_free}"
                            )
                            context.extra_system_info += (
                                f"\n\n🎯 THE CLIENT ASKED FOR {_pretty} on "
                                f"{_label(_asked_date)} — CHECKED AGAINST THE "
                                f"CALENDAR JUST NOW: "
                                + (
                                    f"that time IS FREE. Confirm {_pretty} and move "
                                    "to the next step. NEVER tell them it is "
                                    "unavailable — the short list you offer is a "
                                    "presentation choice, not the whole schedule."
                                    if _time_free else
                                    f"that time is NOT free. Say so honestly and "
                                    "offer the nearest real alternatives from the "
                                    "schedule above."
                                )
                            )
                except Exception as e:
                    logger.warning(f"Wappi: failed to fetch slots: {e}")
            else:
                # Area unknown but user might be asking about timing
                # ("when", "available", "tomorrow", "сегодня", etc.).
                # Without real slots the model happily invents times
                # like "2pm, 4pm, 6pm" — caught red-handed in a live
                # test. Inject a hard rule instead: never volunteer
                # times before we know the area.
                from datetime import datetime as _dt_au, timedelta as _td_au, timezone as _tz_au
                _asks_time = any(
                    kw in _text_lower for kw in (
                        "when", "time", "available", "slot", "schedule",
                        "today", "tomorrow", "morning", "afternoon", "evening",
                        "когда", "время", "свободн", "сегодня", "завтра",
                        "утро", "день", "вечер",
                    )
                # A concrete date or a clock time IS a timing ask too — the
                # cleansing prefill carries no emirate, and a client answering
                # "20 August" to the city question used to slip past this net
                # and get invented times (prefill audit, 2026-08-16).
                ) or bool(_detect_explicit_date(
                    _text_lower, _dt_au.now(_tz_au(_td_au(hours=4)))
                )) or bool(_detect_requested_time(_text_lower))
                if _asks_time:
                    context.extra_system_info = (
                        "\n\n⚠️ CLIENT AREA IS STILL UNKNOWN.\n"
                        "🚨 NEVER show or invent specific times (no '2pm', "
                        "'4pm', '10:00', etc.) before area is confirmed.\n"
                        "🚨 If the client asks about timing, reply first:\n"
                        "    'Are you in Abu Dhabi, Al Ain or Dubai dear? 🌹'\n"
                        "   Once they answer, the system will provide real "
                        "slots on the next turn.\n"
                        "🚨 Do NOT guess the area from ambiguous words. "
                        "Ask explicitly."
                    )

        # Instagram-channel brief for the SAME booking brain: the client came
        # from IG Direct (no phone in the identity), so the number must be
        # collected before the final confirm, and the closing line follows
        # Tatyana's verbatim template (2026-07-28 agreement).
        if _is_ig_key(phone):
            context.extra_system_info = (
                (getattr(context, "extra_system_info", "") or "")
                + _ig_channel_brief((client.phone or "").strip())
            )

        # LLM timeout — OpenAI hangs cost us background-task slots and
        # leave clients silent indefinitely. 30s is well above p99 for
        # GPT-4o-class models; anything longer is a hang, not a slow run.
        #
        # Uses the with_tools path: the agent may call book_appointment,
        # in which case we get a structured BookingCall alongside the
        # reply text and create the YClients record directly from those
        # fields — no regex parsing of the reply.
        # The creative the client tapped decides which offer they must hear
        # FIRST. "Massage package at a discount" belongs to the cupping ad, so
        # the honest answer is that combo — not the regular per-session prices,
        # and never a course price list (the client complained about exactly
        # that dump on 2026-08-15).
        # Out of our service area: the funnel is CLOSED. One warm goodbye,
        # no service questions, no prices, no times — however the client
        # keeps the chat going ("Okay", "thanks") — until they name a city
        # we actually serve.
        _ooa_now = (context.booking_data or {}).get("out_of_area")
        if _ooa_now:
            if _ooa_city:
                # They named the city THIS turn — the refusal itself hasn't
                # been said yet. Say it once, warmly, and close.
                context.extra_system_info += (
                    f"\n\n🚫 THE CLIENT IS OUTSIDE OUR SERVICE AREA (they "
                    f"named '{_ooa_now}'). Tell them warmly, ONCE: we don't "
                    "work there — we do home service in Abu Dhabi, Al Ain "
                    "and Dubai. Then CLOSE gracefully ('If you are ever in "
                    "Abu Dhabi, Al Ain or Dubai — we would be happy to "
                    "pamper you 🙏'). DO NOT ask what service they want, no "
                    "prices, no times."
                )
            else:
                context.extra_system_info += (
                    f"\n\n🚫 THE CLIENT IS OUTSIDE OUR SERVICE AREA "
                    f"('{_ooa_now}') and we have ALREADY told them so. The "
                    "funnel is closed: no 'what service are you interested "
                    "in', no prices, no times, no offers. Reply with ONE "
                    "short warm goodbye, e.g. 'Ok dear 🌹 If you are ever "
                    "in Abu Dhabi, Al Ain or Dubai — we would be happy to "
                    "pamper you 🙏'. Resume the normal flow ONLY if the "
                    "client says they can come to one of OUR cities."
                )

        # The client wrote in a script the admins can't read (Arabic etc.) —
        # instruct THIS turn explicitly: answer the substance in English and
        # ask to switch. Russian is exempt (the admins speak it).
        if _is_non_english_script(text):
            context.extra_system_info += (
                "\n\n🚫 THE CLIENT'S MESSAGE IS NOT IN ENGLISH (non-Latin, "
                "non-Russian script). Reply in ENGLISH ONLY — never mirror "
                "their language (client rule: the admins must be able to read "
                "and continue every chat). Understand what they meant, answer "
                "it in English, and politely add: 'In English please 🙏'."
            )

        _ad = (context.booking_data or {}).get("ad_prefill")
        if _ad == "cleansing":
            from prices import SPECIAL_OFFERS as _SOC
            _cl = _SOC["offer_deep_cleansing"]
            context.extra_system_info += (
                "\n\n🎯 THIS CLIENT CAME FROM THE DEEP-CLEANSING AD (the "
                "'details about the promotion and get advice' prefill — the "
                "client's rule: this text is ALWAYS the cleansing creative). "
                f"Lead with THAT offer and nothing else: {_cl['name']} — "
                f"{int(_cl['price'])} AED instead of {int(_cl['was'])}, "
                f"{int(_cl['duration'])} min, specialist with medical "
                "education. Do NOT list the other promotions. Then continue "
                "the NORMAL flow — this prefill has no emirate, so ask which "
                "city they are in when the time comes."
            )
        elif _ad == "summer":
            # There is no "summer promotion" price list — the client never sent
            # one. What DOES exist is the four discounts currently advertised,
            # so a client tapping that ad hears those instead of a narrowing
            # question. Before this, three turns went by without a single price
            # (prefill audit, 2026-08-15) and the lead simply left.
            from prices import format_ad_offers_for_prompt as _offers
            context.extra_system_info += (
                "\n\n🎯 THIS CLIENT CAME FROM THE SUMMER-PROMOTION AD. We have "
                "no separate 'summer' price list, so lead with the discounts "
                "that ARE running, briefly, was→now, and then ask which one "
                "they want. Do NOT answer with a bare question — they asked "
                "about an offer and must hear real numbers:\n"
                + _offers()
            )
        elif _ad == "package":
            from prices import SPECIAL_OFFERS as _OFFERS
            _combo = _OFFERS["lymphatic_cupping_combo"]
            context.extra_system_info += (
                f"\n\n🎯 THIS CLIENT CAME FROM THE PACKAGE/CUPPING AD "
                f"('massage package at a discount'). Lead with THAT offer: "
                f"{_combo['description']} — {int(_combo['price'])} AED "
                f"(was {int(_combo['was'])}), {_combo['duration']} min. "
                "Quote it as soon as they say what they want, BEFORE the plain "
                "per-session prices. NEVER quote course/abonement prices on "
                "this prefill — say courses are arranged personally by the "
                "team. The emirate is already in their message: never re-ask it."
            )

        response_text: str = ""
        actions = AgentActions()
        try:
            response_text, actions = await asyncio.wait_for(
                booking_agent.process_message_with_tools(text, context),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.error(f"Wappi [{phone}]: booking_agent timed out after 30s")
            response_text = "Sorry dear, one moment 🙏 Please repeat your message 🌹"
        booking_call: Optional[BookingCall] = actions.booking_call

        if not response_text or not response_text.strip():
            response_text = "Just a moment dear 🙏"

        # Post-hoc area detection from the BOT's reply. The model is
        # smarter at reading typos than our regex (e.g. user wrote
        # "Al aim" — user-side detector missed it, but the model still
        # replied "Al Ain noted 😊"). Trust the model's interpretation
        # and write area into client_data so the next turn gets slot
        # injection. Requires both a confirming verb AND the area
        # name to avoid false positives from free narration.
        if not context.client_data.get("area"):
            import re as _re_posthoc
            _resp_low = response_text.lower()
            # Count how many of the THREE served cities the reply names. The
            # bot's own disambiguation question ("Are you in Abu Dhabi, Al Ain
            # or Dubai dear?") lists ≥2 — locking any single area off it would
            # pick the wrong emirate before the client even answers.
            _city_mentions = sum([
                ("al ain" in _resp_low or "al-ain" in _resp_low),
                "abu dhabi" in _resp_low,
                "dubai" in _resp_low,
            ])
            # CRITICAL: skip area-lock when the reply names 2+ cities (it's an
            # options list, not a confirmation) or is itself a question.
            if _city_mentions >= 2 or "?" in response_text:
                _area_confirm = None
            else:
                # Only STRONG confirmation signals (dropped weak prepositions
                # in/for/to/with that matched free narration).
                _area_confirm = _re_posthoc.search(
                    r"\b(?:noted|confirmed|your area is|area:|you're in|you are in|great,?\s*)\s*"
                    r"(?:—\s*)?"
                    r"(al\s*ain|abu\s*dhabi|dubai)\b",
                    _resp_low,
                ) or _re_posthoc.search(
                    r"\b(al\s*ain|abu\s*dhabi|dubai)\s+(?:noted|confirmed|it is)\b", _resp_low
                )
            if _area_confirm:
                area_kw = _area_confirm.group(1).replace(" ", "_")
                if "al" in area_kw and "ain" in area_kw:
                    _detected = "al_ain"
                elif "abu" in area_kw and "dhabi" in area_kw:
                    _detected = "abu_dhabi"
                elif "dubai" in area_kw:
                    _detected = "dubai"
                else:
                    _detected = None
                if _detected:
                    logger.info(
                        f"Wappi [{phone}]: post-hoc area detection from bot "
                        f"reply → {_detected}"
                    )
                    dialog_manager.update_client_data(user_id, "area", _detected)
                    try:
                        await bot_module.client_service.update_client(telegram_id, area=_detected)
                    except Exception:
                        pass

        # Guarantee honest client-facing wording at the CODE level — the LLM is
        # not reliable about it (it says "confirmed" on a reschedule, or before
        # it has a location/name). See _enforce_reply_wording.
        # IG channel: a real phone must be collected before the record exists
        # (the identity key is not a number there).
        _needs_phone = False
        if _is_ig_key(phone) and booking_call is not None:
            _known_phone = (getattr(booking_call, "client_phone", None) or client.phone or "")
            _needs_phone = len(re.sub(r"\D", "", str(_known_phone))) < 9
        response_text = _enforce_reply_wording(
            response_text, actions, booking_call, context.client_data, user_text=text,
            group_requested=bool((context.booking_data or {}).get("group_requested")),
            already_booked_sig=getattr(context, "last_booking_sig", None),
            needs_phone=_needs_phone,
            is_ig=_is_ig_key(phone),
        )

        # No invented times reach the client — every offered time must exist
        # in the YClients truth captured this turn (see _enforce_slot_reality).
        response_text = _enforce_slot_reality(response_text, context, booking_call)

        # English-only guard: the admins must be able to read and continue
        # every chat, so a non-English-script reply never leaves the building.
        response_text = _enforce_english_reply(response_text, text)

        # Payment terms are a money-facing promise: a quoted price must always
        # carry its footnote once the client has picked how they pay. The chosen
        # method is sticky — the client names it once ("bank transfer") and every
        # later price (recap, confirmation) must still say +5% VAT.
        _pay_known = (context.booking_data or {}).get("payment_method")
        _pay_now = (getattr(booking_call, "payment_method", None)
                    or _detect_payment_method(text))
        if _pay_now and _pay_now != _pay_known:
            dialog_manager.update_booking_data(user_id, "payment_method", _pay_now)
        response_text = _enforce_payment_terms(response_text, _pay_now or _pay_known)

        await bot_module.message_service.save_message(telegram_id, "assistant", response_text)
        dialog_manager.add_bot_response(user_id, response_text)

        if wappi_client:
            parts = [p.strip() for p in response_text.split("---MESSAGE_SPLIT---") if p.strip()]
            # Guard against a reply that is only the separator/whitespace —
            # response_text.strip() is non-empty (so the earlier empty-fallback
            # was skipped) but parts is [], and the client would get nothing.
            if not parts:
                parts = ["Just a moment dear 🙏"]
            # Small delay between parts: Wappi + WhatsApp can reorder
            # near-simultaneous sends, which breaks narrative flow (parts
            # arriving out of order, or admin/marketing inserts falling
            # between them). 0.4s per part gives WhatsApp time to process
            # in the intended order and also feels more natural to the
            # recipient (simulates typing).
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(0.4)
                await _send_to_client(phone, part)

            # Promo photo: attach a relevant offer/service image (cupping,
            # manicure, body/face massage, book-a-friend). Sent once per phone
            # so a client discussing the same service over several turns isn't
            # spammed with the same picture. Best-effort — never block/break
            # the text reply if the image send fails.
            # Gated behind WAPPI_SEND_PROMO_PHOTOS (OFF on prod for now).
            try:
                from services.promo_photos import get_promo_photo
                photo_path = (
                    get_promo_photo(text, response_text)
                    if config.WAPPI_SEND_PROMO_PHOTOS and not _is_ig_key(phone) else None
                )
                if photo_path:
                    sent = _wappi_sent_promos.setdefault(phone, set())
                    if photo_path not in sent:
                        await asyncio.sleep(0.4)
                        await wappi_client.send_image(phone, photo_path)
                        sent.add(photo_path)
            except Exception as e:
                logger.warning(f"Wappi [{phone}]: promo photo send failed: {e}")
        elif not wappi_client:
            # No Wappi client at message time (creds missing/rotated) — the
            # client gets NO reply. Make the failure loud instead of silent.
            logger.error(
                f"Wappi [{phone}]: NO wappi_client — reply NOT delivered. "
                f"Check WAPPI_TOKEN/WAPPI_PROFILE_ID."
            )

        # Post-booking: create DB + YClients record if the agent called
        # the book_appointment tool. If it sent a ✅ confirmation WITHOUT
        # calling the tool, _maybe_create_booking alerts the admin and
        # doesn't create anything — no more guessing dates from text.
        await _maybe_create_booking(
            user_id, telegram_id, phone, sender_name, context,
            response_text, booking_call,
        )

        # Cancellation / reschedule actions (FR-5.1–5.3, 7.2).
        if actions.cancel_call is not None:
            await _handle_cancellation(telegram_id, phone, actions.cancel_call, context)
        if actions.reschedule_call is not None:
            await _handle_reschedule(telegram_id, phone, actions.reschedule_call, context)

        # Persist a structured turn log for future debugging / bug analysis.
        try:
            from services.turn_logger import log_turn
            _action = ("book_appointment" if booking_call else
                       "cancel" if actions.cancel_call else
                       "reschedule" if actions.reschedule_call else None)
            log_turn(
                phone, text,
                area=context.client_data.get("area"),
                service=context.booking_data.get("service_type"),
                had_slots=bool(getattr(context, "extra_system_info", "")),
                reply=response_text,
                action=_action,
            )
        except Exception:
            pass

    except Exception as e:
        logger.opt(exception=True).error(
            "Wappi background processing error: {}", str(e))
        try:
            from services.turn_logger import log_turn
            log_turn(phone, text, error=str(e)[:300])
        except Exception:
            pass
        if wappi_client:
            try:
                await _send_to_client(
                    phone,
                    "Sorry dear, technical issue 🙏 Please try again in a moment 🌹"
                )
            except Exception:
                pass


@app.post("/admin/reset/{phone}")
async def admin_reset(phone: str, request: Request):
    """Clear dialog history for a WhatsApp user by phone.

    Protected by WEBHOOK_SECRET header: X-Admin-Secret
    Usage: curl -X POST https://.../admin/reset/375447574000 -H "X-Admin-Secret: <secret>"
    """
    secret = request.headers.get("X-Admin-Secret", "")
    if not config.WEBHOOK_SECRET or secret != config.WEBHOOK_SECRET:
        return Response(status_code=403, content="forbidden")

    phone_clean = phone.replace("+", "").strip()
    user_id = f"wappi_{phone_clean}"
    deleted = await _reset_user(user_id, user_id)
    return {"status": "ok", "phone": phone_clean, "messages_deleted": deleted}


@app.get("/admin/health/yclients")
async def admin_yclients_health(request: Request):
    """Diagnostic: is the YClients user_token still valid?

    Runs get_records() for the first staff member on today's date.
    A 401 ("Не указан идентификатор пользователя") means the token
    on this deploy has expired — the bot will stop producing real
    slots until it's rotated.

    Protected by X-Admin-Secret header.
    Usage: curl https://.../admin/health/yclients -H "X-Admin-Secret: <secret>"
    """
    # Two accepted secrets: the admin one, and the ManyChat bridge secret —
    # whoever verifies the night shift has the latter but not the former,
    # and a dead YClients token is exactly what must be caught BEFORE 21:00.
    import hmac as _hmac

    secret = (
        request.headers.get("X-Admin-Secret", "")
        or request.query_params.get("secret", "")
    )
    _ok = (
        (config.WEBHOOK_SECRET and _hmac.compare_digest(secret, config.WEBHOOK_SECRET))
        or (config.MANYCHAT_WEBHOOK_SECRET
            and _hmac.compare_digest(secret, config.MANYCHAT_WEBHOOK_SECRET))
    )
    if not _ok:
        return Response(status_code=403, content="forbidden")

    import bot as bot_module
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    if not bot_module.yclients_service:
        return {
            "status": "not_configured",
            "detail": "yclients_service is None (MOCK_YCLIENTS or missing tokens)",
        }

    try:
        staff = await bot_module.yclients_service.get_staff()
    except Exception as e:
        return {"status": "error", "stage": "get_staff", "detail": str(e)}

    if not staff:
        return {"status": "partner_token_fail", "detail": "get_staff returned empty"}

    today = _dt.now(_tz(_td(hours=4))).strftime("%Y-%m-%d")
    tomorrow = (_dt.now(_tz(_td(hours=4))) + _td(days=1)).strftime("%Y-%m-%d")
    sample = staff[0]
    # Slots are what the night shift actually shows a client, and they are
    # computed from schedule+records — so probe the real summary, not just
    # the token. Verified from outside before the 21:00 launch.
    try:
        _slots = await bot_module.yclients_service.get_available_slots_summary(
            date=tomorrow, area="abu_dhabi", service_duration=60
        )
    except Exception as e:
        _slots = f"ERROR: {e}"
    recs = await bot_module.yclients_service.get_records(sample["id"], today)
    if recs is None:
        return {
            "status": "user_token_fail",
            "detail": (
                "records API returned None (likely 401 'Не указан "
                "идентификатор пользователя'). Rotate YCLIENTS_USER_TOKEN "
                "in the deploy env and redeploy."
            ),
            "staff_probed": {"id": sample["id"], "name": sample.get("name")},
            "date": today,
        }
    return {
        "status": "ok",
        "slots_tomorrow_abu_dhabi": str(_slots)[:600],
        "records_count": len(recs),
        "staff_probed": {"id": sample["id"], "name": sample.get("name")},
        "date": today,
    }


@app.post("/webhook/wappi")
async def wappi_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive WhatsApp messages via Wappi.pro webhook.

    Responds with 200 OK immediately, then processes in background.
    Prevents Wappi retries that cause duplicate responses.
    Deduplicates by message_id (5 min TTL).
    """
    # Verify optional auth secret
    if config.WAPPI_WEBHOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != config.WAPPI_WEBHOOK_SECRET:
            logger.warning("Wappi webhook: invalid auth")
            return Response(status_code=403)

    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Wappi webhook: invalid JSON: {e}")
        return {"status": "bad_json"}

    parsed = parse_incoming_message(data)
    if not parsed:
        return {"status": "ignored"}

    phone = parsed["phone"]
    text = parsed["text"]
    sender_name = parsed["sender_name"]
    msg_type = parsed["message_type"]
    message_id = parsed.get("message_id", "")
    latitude = parsed.get("latitude")
    longitude = parsed.get("longitude")

    # Dedup: skip if we've already processed this message_id.
    if _dedup_seen(message_id, time.time()):
        logger.info(f"Wappi: duplicate message {message_id} ignored")
        return {"status": "duplicate"}

    logger.info(f"Wappi [{phone}] {sender_name}: {text[:100]}")

    # Location message — synthesize a text representation so the agent
    # treats it like a client sharing their address. Also prime
    # context.client_data with coords + inferred area so the slot-injection
    # code path in _process_wappi_message picks the right therapists.
    if msg_type == "location" and latitude is not None and longitude is not None:
        user_id = f"wappi_{phone}"
        area = _area_from_coords(latitude, longitude)

        if area:
            # Valid UAE coordinates — store them, model may use in address.
            dialog_manager.update_client_data(
                user_id, "location", {"lat": latitude, "lng": longitude}
            )
            dialog_manager.update_client_data(user_id, "area", area)
            # Persist to the DB client record too — the driver notification and
            # admin/booking messages read client.location_latitude/longitude, so
            # without this the therapist gets NO map pin even though the client
            # shared GPS.
            try:
                import bot as _bot_gps
                await _bot_gps.client_service.update_client(
                    f"wappi_{phone}",
                    location_latitude=latitude,
                    location_longitude=longitude,
                    area=area,
                )
            except Exception as _e:
                logger.warning(f"Wappi: couldn't persist GPS to client record: {_e}")
            area_label = {
                "abu_dhabi": "Abu Dhabi",
                "al_ain": "Al Ain",
                "dubai": "Dubai",
            }.get(area, "UAE")
            synthetic_text = (
                f"[Client shared GPS location in {area_label} "
                f"(lat={latitude:.5f}, lng={longitude:.5f}). Use this as "
                f"their address field — you still need to ask for the "
                f"building / villa / apartment number if not obvious.]"
            )
        else:
            # Coordinates outside UAE — clients testing from abroad, or
            # an accidental pin. Do NOT store the coords as "location"
            # (model took them and stuffed them into tool-call address,
            # which confused admin seeing Minsk GPS in a UAE booking).
            # Tell the model to ask for a text address instead.
            synthetic_text = (
                f"[Client shared a GPS location OUTSIDE the UAE "
                f"(lat={latitude:.5f}, lng={longitude:.5f}). DO NOT use "
                f"these coordinates as their address. Ask the client to "
                f"type their Abu Dhabi / Al Ain / Dubai address in text (e.g. "
                f"'Khalifa City, Villa 42'). If area is still unknown, "
                f"ask 'Are you in Abu Dhabi, Al Ain or Dubai dear?' first.]"
            )
            logger.info(
                f"Wappi [{phone}] non-UAE location "
                f"({latitude:.3f}, {longitude:.3f}) — asking for text address"
            )

        logger.info(f"Wappi [{phone}] location → {area or 'non_uae'}")
        background_tasks.add_task(
            _buffer_and_process_wappi, phone, synthetic_text, sender_name
        )
        return {"status": "location_accepted", "area": area or "outside_uae"}

    # Other non-text messages (image, audio, video, document, sticker…) —
    # we can't read them yet. Acknowledge politely and ask for text.
    if msg_type != "chat" or not text:
        if wappi_client:
            background_tasks.add_task(
                wappi_client.send_message,
                phone,
                "Sorry dear, I can only read text messages right now 🙏 "
                "Please type your question in text 🌹"
            )
        return {"status": "non_text"}

    # Reset command — handle BEFORE buffering. Otherwise a "/clear" arriving
    # within 7s of a prior message gets joined ("book sunday\n/clear") and the
    # exact-match reset check never fires (reported "не очищает историю").
    if _is_reset_command(text):
        user_id = f"wappi_{phone}"
        # Drop any pending buffered fragments so they don't process post-reset,
        # and bump the reset epoch so a flush that ALREADY popped its fragments
        # (and is blocked on the lock) drops itself instead of running against
        # the wiped context.
        _wappi_buffer.pop(phone, None)
        _wappi_reset_epoch[phone] = _wappi_reset_epoch.get(phone, 0) + 1
        background_tasks.add_task(_reset_and_greet, phone, user_id)
        return {"status": "reset"}

    # Schedule buffered processing (7s wait to combine multi-part messages per PRD 4.1.6)
    background_tasks.add_task(_buffer_and_process_wappi, phone, text, sender_name)
    return {"status": "accepted"}


async def _reset_and_greet(phone: str, user_id: str):
    """Reset a user's state and send the fresh-start greeting (WhatsApp)."""
    try:
        # Serialise with any in-flight turn for this phone so the wipe can't
        # race a concurrent _process_wappi_message mutating the same context.
        async with _phone_lock(phone):
            await _reset_user(user_id, user_id)
        if wappi_client:
            await _send_to_client(phone, _RESET_GREETING)
    except Exception as e:
        logger.error(f"Reset-and-greet failed for {phone}: {e}")


# ── Coordinate → area classifier ─────────────────────────────────────
# Crystal Lab serves Abu Dhabi, Al Ain and Dubai. Classify a GPS pin to the
# nearest served city center, but only within that center's radius — anything
# farther (outside UAE, or an emirate we don't serve) returns None and the
# agent asks the client to confirm their area in text.
#
# Per-center radius matters: Abu Dhabi and Al Ain sit alone, so a generous
# 0.6° (~66 km) safely captures their outskirts. Dubai does NOT — it's fused
# into the northern-emirates cluster (Sharjah center is only ~0.21° away,
# Ajman ~0.27°), so a wide radius would silently swallow those UNSERVED
# emirates. Dubai therefore gets a tight 0.19° (~21 km): enough for urban
# Dubai (Marina ≈0.18°, JBR ≈0.18°, Deira ≈0.09°) but short of Sharjah/Ajman.
# A far-flung Dubai pin just falls to None and the client confirms in text.
_AREA_CENTERS = {
    "abu_dhabi": (24.47, 54.37, 0.6),    # Abu Dhabi city
    "al_ain":    (24.21, 55.75, 0.6),    # Al Ain city
    "dubai":     (25.20, 55.27, 0.19),   # Dubai city (tight — excludes Sharjah/Ajman)
}


def _area_from_coords(lat: float, lng: float) -> Optional[str]:
    """Return 'abu_dhabi' | 'al_ain' | 'dubai' | None for a GPS coordinate.

    None means "unknown / outside service area" — the agent should ask
    the client to confirm their area in text rather than assume.
    """
    best_area: Optional[str] = None
    best_d2: Optional[float] = None
    for area, (clat, clng, radius) in _AREA_CENTERS.items():
        # Squared Euclidean distance in degrees. Good enough at UAE latitudes
        # for this classifier — no need for haversine. Each center only claims
        # a pin within its own radius; nearest wins if several would.
        d2 = (lat - clat) ** 2 + (lng - clng) ** 2
        if d2 <= radius * radius and (best_d2 is None or d2 < best_d2):
            best_d2 = d2
            best_area = area
    return best_area


@app.get("/webhook/instagram")
async def instagram_verify(request: Request):
    """Meta webhook verification handshake (GET hub.challenge)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == config.INSTAGRAM_VERIFY_TOKEN:
        logger.info("Instagram webhook verified")
        return Response(content=challenge or "", media_type="text/plain")
    logger.warning("Instagram webhook verification failed")
    return Response(content="forbidden", status_code=403)


async def _instagram_consult_task(sender_id: str, text: str) -> None:
    """One IG turn: LLM consult (prices + WhatsApp CTA), then send the DM.

    Runs as a background task so the webhook ACKs Meta fast; any LLM
    failure inside generate_ig_reply falls back to the static handoff.
    Outside the live window (owner: from 21:00 Minsk) the turn is SHADOW:
    generated + logged, not sent.
    """
    from agents.instagram_agent import generate_ig_reply, ig_live_now, log_ig_turn
    from services.instagram_client import send_instagram_message
    reply = await generate_ig_reply(sender_id, text)
    live = ig_live_now()
    log_ig_turn("instagram", sender_id, text, reply, live)
    if live:
        await send_instagram_message(sender_id, reply)


@app.post("/webhook/instagram")
async def instagram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Instagram DMs, consult on services/prices, funnel to WhatsApp."""
    import hashlib
    import hmac
    import json as _json
    from agents.instagram_agent import is_duplicate
    from services.instagram_client import parse_instagram_events

    raw = await request.body()

    # Verify Meta's X-Hub-Signature-256 (HMAC-SHA256 of the raw body) when an
    # app secret is configured. Reject forgeries before doing any work.
    if config.INSTAGRAM_APP_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            config.INSTAGRAM_APP_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("Instagram webhook: bad signature")
            return Response(content="forbidden", status_code=403)

    try:
        payload = _json.loads(raw or b"{}")
    except ValueError:
        return Response(content="bad request", status_code=400)
    events = parse_instagram_events(payload)
    logger.info(f"Instagram webhook: {len(events)} event(s)")

    for ev in events:
        if is_duplicate(ev.get("mid")):
            logger.info(f"Instagram webhook: duplicate mid {ev.get('mid')}, skipped")
            continue
        background_tasks.add_task(_instagram_consult_task, ev["sender_id"], ev["text"])

    return {"status": "ok", "events": len(events)}


# Client saw a photo/voice/sticker we can't read (or the text fetch failed).
# Friendly nudge instead of silence — sent only in the live window.
IG_MEDIA_FALLBACK = (
    "Sorry dear, I couldn't view that message 🌹 "
    "Could you type it as text, please?"
)


async def _manychat_shadow_log(subscriber_id: str, text: str) -> None:
    """Generate the would-be reply for QA AFTER the webhook has answered.

    Shadow turns must never make ManyChat wait: a slow response there means
    no field mapping, which means the flow falls through to whatever
    ai_reply still held — a stale reply from the previous night.
    """
    from agents.instagram_agent import generate_ig_reply, log_ig_turn

    try:
        reply = await generate_ig_reply(f"mc:{subscriber_id}", text)
        log_ig_turn("manychat", subscriber_id, text, reply, False)
    except Exception as e:
        logger.error(f"IG shadow log failed for {subscriber_id}: {e}")


async def _manychat_async_turn(subscriber_id: str, text: str) -> None:
    """Full IG turn in the background: generate → (live?) send via ManyChat API.

    Used when IG_ASYNC_SEND is on so the webhook ACKs ManyChat instantly —
    long LLM/YClients turns can't hit their External Request timeout.
    """
    from agents.instagram_agent import generate_ig_reply, ig_live_now, log_ig_turn
    from services.instagram_client import manychat_send_text
    reply = await generate_ig_reply(f"mc:{subscriber_id}", text)
    live = ig_live_now()
    log_ig_turn("manychat", subscriber_id, text, reply, live)
    if live:
        await manychat_send_text(subscriber_id, reply)


@app.post("/webhook/manychat")
async def manychat_webhook(request: Request, background_tasks: BackgroundTasks):
    """ManyChat External Request bridge — same consult brain, ManyChat front.

    When Instagram is connected through ManyChat, ManyChat owns the Meta
    webhook; its flow calls this endpoint with the subscriber's message and
    delivers whatever we return. Contract:
      POST {"subscriber_id": "...", "text": "..."}
      header X-Manychat-Secret = MANYCHAT_WEBHOOK_SECRET
    The response carries a flat {"reply": ...} (for External Request field
    mapping) plus the ManyChat v2 dynamic-block format so a flow can render
    the messages directly without mapping.
    """
    import hmac as _hmac
    from agents.instagram_agent import generate_ig_reply, ig_live_now, log_ig_turn

    try:
        payload = await request.json()
    except Exception:
        return Response(content="bad request", status_code=400)

    # Deny by default: never open when the secret is unset (admin-endpoint rule).
    # Header is canonical; body "secret" and ?secret= are equal fallbacks
    # because the ManyChat UI silently drops saved header VALUES and even
    # hand-typed body edits (live-caught 2026-08-11: Settings→Logs
    # "Forbidden" — the header arrived empty). The request URL field is the
    # one input ManyChat persists reliably, so the query param is the one
    # that actually carries auth in prod.
    secret = (
        request.headers.get("X-Manychat-Secret", "")
        or str(payload.get("secret") or "")
        or request.query_params.get("secret", "")
    )
    if not config.MANYCHAT_WEBHOOK_SECRET or not _hmac.compare_digest(
        secret, config.MANYCHAT_WEBHOOK_SECRET
    ):
        return Response(content="forbidden", status_code=403)
    subscriber_id = str(payload.get("subscriber_id") or "").strip()
    # Accept both our contract field ("text") and ManyChat's system-field
    # naming ("last_input_text") so either flow mapping works.
    text = str(payload.get("text") or payload.get("last_input_text") or "").strip()
    if subscriber_id and not text:
        # No text in the payload → the flow sends only ids (raw client text
        # in the body template breaks on newlines/quotes — "Invalid payload
        # json", live-caught 2026-08-12). Fetch it via the ManyChat API.
        from services.instagram_client import fetch_manychat_last_text
        text = await fetch_manychat_last_text(subscriber_id)
    if not subscriber_id:
        return Response(content="bad request", status_code=400)
    if not text:
        # Still nothing → the client sent media (photo/voice/sticker) we
        # can't read. Nudge politely in the live window, stay silent in shadow.
        from agents.instagram_agent import ig_live_now, log_ig_turn, SHADOW_SENTINEL
        live = ig_live_now()
        log_ig_turn("manychat", subscriber_id, "[media/unreadable]", IG_MEDIA_FALLBACK, live)
        if not live:
            return {"reply": SHADOW_SENTINEL, "shadow": True}
        return {"reply": IG_MEDIA_FALLBACK}

    # "mc:" prefix keeps ManyChat histories separate from direct-IG senders.
    from agents.instagram_agent import SHADOW_SENTINEL, ig_live_now
    # The live window is now MANDATORY for everyone, testers included: the
    # tester bypass existed to rehearse booking before the flag was on, and
    # its only remaining effect was answering during the day (owner request
    # 2026-08-15 — the client must see complete daytime silence).
    _night_event("inbound", who=subscriber_id, text=text, live=ig_live_now())
    if config.MANYCHAT_API_KEY and ig_live_now() and (
        config.IG_BOOKING_ENABLED or _is_ig_test_subscriber(subscriber_id)
    ):
        # Variant A (full IG booking): live-window DMs run through the SAME
        # booking pipeline as WhatsApp — buffering, gates, YClients record —
        # under an ig:<subscriber> identity; replies return via the Sending
        # API through _send_to_client. ACK instantly with the sentinel so
        # the ManyChat flow itself stays silent.
        background_tasks.add_task(
            _buffer_and_process_wappi, f"{IG_KEY_PREFIX}{subscriber_id}", text, None
        )
        _night_event("routed_to_booking", who=subscriber_id)
        return {"reply": SHADOW_SENTINEL, "queued": True}
    if config.IG_ASYNC_SEND and config.MANYCHAT_API_KEY:
        # Stage-0 async path: ACK instantly, deliver via the Sending API.
        # The sentinel keeps the flow's Condition from sending anything.
        background_tasks.add_task(_manychat_async_turn, subscriber_id, text)
        return {"reply": SHADOW_SENTINEL, "queued": True}
    live = ig_live_now()
    if not live:
        # Outside the window: ACK INSTANTLY. Waiting for the LLM here used to
        # blow ManyChat's External Request timeout — the mapping then never
        # ran, ai_reply kept LAST NIGHT's answer, and the flow's Condition
        # happily sent that stale text to a daytime client (live incident
        # 2026-08-15, Anum ishtiaq got a 15h-old reply at 14:58). The QA
        # generation now happens in the background, after the response.
        background_tasks.add_task(_manychat_shadow_log, subscriber_id, text)
        return {"reply": SHADOW_SENTINEL, "shadow": True}
    reply = await generate_ig_reply(f"mc:{subscriber_id}", text)
    log_ig_turn("manychat", subscriber_id, text, reply, live)
    # Mapping-only contract: the flow maps $.reply → ai_reply and a Condition
    # node drops the shadow sentinel (ManyChat's mapper rejects empty strings,
    # and returning v2 dynamic content could double-send if ManyChat renders
    # it — so the response carries ONLY the reply field).
    return {"reply": reply}


@app.get("/admin/night-log")
async def admin_night_log(request: Request, limit: int = 200, kind: str = ""):
    """Read the night's trail from outside the container.

    Auth uses MANYCHAT_WEBHOOK_SECRET (the one secret shared with the
    bridge) because the Render log stream and WEBHOOK_SECRET aren't
    available to whoever reviews the shift in the morning.
    """
    import hmac as _hmac

    secret = (
        request.headers.get("X-Manychat-Secret", "")
        or request.query_params.get("secret", "")
    )
    if not config.MANYCHAT_WEBHOOK_SECRET or not _hmac.compare_digest(
        secret, config.MANYCHAT_WEBHOOK_SECRET
    ):
        return Response(content="forbidden", status_code=403)

    events = list(NIGHT_LOG or [])
    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        events = [e for e in events if e.get("kind") in wanted]
    summary: dict = {}
    for e in events:
        summary[e["kind"]] = summary.get(e["kind"], 0) + 1
    clients = {e.get("who") for e in events if e.get("who")}
    return {
        "summary": summary,
        "unique_contacts": len(clients),
        "bookings": [e for e in events if e["kind"] == "booking_created"],
        "total_kept": len(NIGHT_LOG or []),
        "events": events[-limit:],
    }


@app.post("/admin/share-with-driver/{booking_id}")
async def admin_share_with_driver(booking_id: int, request: Request):
    """(Re)send a logistics notification to the driver group for a booking
    (FR 5.2 'share with driver').

    This also fires automatically when a booking is created; the endpoint
    lets an admin resend or push a booking made outside the agent.
    """
    import bot as bot_module
    # Deny by default: an admin mutation endpoint must NOT be open when
    # WEBHOOK_SECRET is unset (was `if config.WEBHOOK_SECRET:` → skipped the
    # check entirely on a misconfigured deploy, leaving these endpoints public).
    secret = request.headers.get("X-Admin-Secret", "")
    if not config.WEBHOOK_SECRET or secret != config.WEBHOOK_SECRET:
        return Response(content="forbidden", status_code=403)

    if not config.DRIVER_TELEGRAM_CHAT_ID:
        return {"status": "no_driver_configured"}

    # Find the booking + client
    from sqlalchemy import select
    from database.models import Booking, Client
    async with bot_module.booking_service.db.session() as session:
        row = (await session.execute(
            select(Booking, Client).join(Client, Booking.client_id == Client.id)
            .where(Booking.id == booking_id)
        )).first()
    if not row:
        return {"status": "booking_not_found"}
    b, c = row

    status = await _notify_driver(b, c)
    return {"status": status, "booking_id": booking_id}


@app.post("/admin/payment/{booking_id}/paid")
async def admin_mark_paid(booking_id: int, request: Request):
    """Mark a booking as paid (admin reconciles a bank transfer)."""
    import bot as bot_module
    # Deny by default: an admin mutation endpoint must NOT be open when
    # WEBHOOK_SECRET is unset (was `if config.WEBHOOK_SECRET:` → skipped the
    # check entirely on a misconfigured deploy, leaving these endpoints public).
    secret = request.headers.get("X-Admin-Secret", "")
    if not config.WEBHOOK_SECRET or secret != config.WEBHOOK_SECRET:
        return Response(content="forbidden", status_code=403)
    from services.payment import PaymentService
    try:
        await PaymentService(bot_module.booking_service).mark_paid(booking_id)
        return {"status": "paid", "booking_id": booking_id}
    except Exception as e:
        logger.error(f"mark_paid failed: {e}")
        return {"status": "error", "detail": str(e)}


@app.get("/admin/logs")
async def admin_logs(request: Request):
    """Return recent structured turn logs (for debugging / bug analysis)."""
    # Deny by default: an admin mutation endpoint must NOT be open when
    # WEBHOOK_SECRET is unset (was `if config.WEBHOOK_SECRET:` → skipped the
    # check entirely on a misconfigured deploy, leaving these endpoints public).
    secret = request.headers.get("X-Admin-Secret", "")
    if not config.WEBHOOK_SECRET or secret != config.WEBHOOK_SECRET:
        return Response(content="forbidden", status_code=403)
    from services.turn_logger import read_recent, LOG_PATH
    try:
        n = int(request.query_params.get("n", "50"))
    except ValueError:
        n = 50
    return {"path": LOG_PATH, "count": None, "logs": read_recent(min(max(n, 1), 500))}


# (The old canned-reply ManyChat stub from Task #14 lived here — replaced by
# the authenticated consult bridge above; one route, one handler.)
