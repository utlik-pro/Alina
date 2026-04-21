"""Crystal Lab Bot — FastAPI webhook app for Render deployment.

Handles:
- Telegram Bot webhook (aiogram)
- ManyChat External Request webhook (future)
- Health check endpoint
"""

import asyncio
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
_WAPPI_BUFFER_DELAY = 7.0  # seconds

from config import config
from bot import router, booking_agent
from database import init_db, ClientService, MessageService, BookingService, DialogSessionService
from dialog_context import dialog_manager
from services.notifications import NotificationService
from services.follow_up import FollowUpService
from services.message_buffer import init_buffer, MessageBuffer
from services.yclients_service import YClientsService
from services.wappi_client import WappiClient, parse_incoming_message

# ── Global instances ─────────────────────────────────────────────────
bot_instance: Bot = None
dp: Dispatcher = None
wappi_client: WappiClient = None


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
    logger.info("✅ Database services initialized")

    # Notification service
    if config.ADMIN_GROUP_CHAT_ID:
        bot_module.notification_service = NotificationService(
            bot_instance, config.ADMIN_GROUP_CHAT_ID
        )
        logger.info(f"✅ Notifications enabled for group {config.ADMIN_GROUP_CHAT_ID}")

    # Follow-up service
    async def _send_follow_up(user_id: str, text: str):
        try:
            await bot_instance.send_message(chat_id=int(user_id), text=text)
        except Exception as e:
            logger.error(f"Failed to send follow-up to {user_id}: {e}")

    async def _send_photo(user_id: str, photo_path: str, caption: str):
        try:
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
            logger.info(f"✅ YClients connected: {len(staff)} staff members")
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

    yield

    # Shutdown — do NOT delete webhook, new instance will re-set it on startup
    logger.info("Shutting down...")
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
    """Health check for Render."""
    return {"status": "ok", "bot": "Crystal Lab", "mode": "webhook"}


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
            await _process_wappi_message(phone, combined, buf["sender_name"])
        except asyncio.CancelledError:
            pass  # new message arrived, will be handled by new timer
        except Exception as e:
            logger.error(f"Wappi buffer flush error: {e}", exc_info=True)

    entry["timer"] = asyncio.create_task(_flush())


async def _maybe_create_booking(user_id: str, telegram_id: str, phone: str,
                                 sender_name: str, context, response_text: str):
    """If bot response contains confirmation marker, create booking in DB + YClients.

    We trigger ONLY on a strong confirmation marker: word-boundary "booked"
    AND a ✅ checkmark in the same message, AND no negation/future-tense
    phrase right before "booked" ("not yet booked", "will be booked",
    "cannot be booked", etc). Previously any occurrence of the substring
    "booked" (e.g. "not yet booked") would create a real YClients record.
    """
    import re as _re
    text_low = response_text.lower()
    if "✅" not in response_text:
        return
    # Require standalone word "booked"
    if not _re.search(r"\bbooked\b", text_low):
        return
    # Reject if "booked" is negated / future-tense / conditional
    negation_re = _re.compile(
        r"(?:not\s+yet|won'?t\s+be|will\s+be|going\s+to\s+be|"
        r"cannot\s+be|can'?t\s+be|is\s+not|isn'?t|aren'?t|"
        r"would\s+be|should\s+be|could\s+be|maybe|might)\s+booked",
        _re.IGNORECASE,
    )
    if negation_re.search(text_low):
        logger.info("Booking trigger skipped — negated 'booked' in response")
        return

    import bot as bot_module
    from datetime import datetime, timedelta, timezone as _tz
    import re

    booking_data = context.booking_data

    service_name = booking_data.get("service_type")
    base_price = booking_data.get("price")
    if not service_name or base_price is None:
        logger.error(
            f"Wappi: booking not created — missing service/price. "
            f"service={service_name} price={base_price} response={response_text[:200]}"
        )
        if bot_module.notification_service:
            try:
                await bot_module.notification_service.send_booking_failed(
                    telegram_id=telegram_id,
                    reason=f"Service/price not extracted. Bot said: {response_text[:200]}"
                )
            except Exception:
                pass
        return

    duration = booking_data.get("service_duration") or 60
    booking_time = booking_data.get("time") or "TBD"
    payment_method = booking_data.get("payment_method") or "cash"

    # Parse time from response if missing.
    # Supports both 12h ("at 4pm", "at 4:30 pm") and 24h ("at 16:00", "at 19:30").
    # YClients returns slots in 24h format and the agent's system prompt now
    # echoes that format back, so the 24h branch is hit most often.
    if booking_time == "TBD":
        m = re.search(
            r'at\s+('
            r'\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)'  # 4pm / 4:30 pm
            r'|'
            r'\d{1,2}:\d{2}'                                 # 16:00 / 19:30
            r')',
            response_text.lower(),
        )
        if m:
            booking_time = m.group(1)

    # Parse date from response
    uae_tz = _tz(timedelta(hours=4))
    now_uae = datetime.now(uae_tz).replace(tzinfo=None)
    booking_date_str = (booking_data.get("date") or "").lower()
    booking_date = None

    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}
    month_map = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
                 "june": 6, "july": 7, "august": 8, "september": 9,
                 "october": 10, "november": 11, "december": 12}

    dow_match = re.search(
        r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(\w+)',
        response_text.lower()
    )
    if dow_match:
        try:
            day_num = int(dow_match.group(2))
            month_name = dow_match.group(3).lower()
            if month_name in month_map:
                month_num = month_map[month_name]
                year = now_uae.year
                if month_num < now_uae.month or (month_num == now_uae.month and day_num < now_uae.day):
                    year += 1
                booking_date = datetime(year, month_num, day_num)
        except Exception:
            pass

    if booking_date is None:
        # booking_data["date"] is authoritative when present — it was set
        # by the agent's own state extraction and isn't polluted by
        # off-topic mentions in the reply text.
        chosen_weekday = None
        resp_low = response_text.lower()

        for day_kw, weekday in day_map.items():
            if day_kw in booking_date_str:
                chosen_weekday = (day_kw, weekday)
                break

        # Otherwise scan response_text but pick the day whose position
        # is closest to "booked" (or to ✅ as a fallback anchor). This
        # avoids picking up off-topic mentions like:
        #     "Booked on Friday ✅. Monday is fully booked already."
        # where the old code would take Monday simply because it came
        # first in the dict iteration.
        if chosen_weekday is None:
            anchor = resp_low.find("booked")
            if anchor == -1:
                anchor = response_text.find("✅")
            if anchor == -1:
                anchor = 0

            best_dist = None
            for day_kw, weekday in day_map.items():
                # Find the occurrence of this day closest to the anchor.
                start = 0
                while True:
                    idx = resp_low.find(day_kw, start)
                    if idx == -1:
                        break
                    dist = abs(idx - anchor)
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        chosen_weekday = (day_kw, weekday)
                    start = idx + len(day_kw)

        if chosen_weekday is not None:
            _, weekday = chosen_weekday
            days_ahead = (weekday - now_uae.weekday()) % 7
            if days_ahead == 0 and "next" in resp_low:
                days_ahead = 7
            booking_date = now_uae + timedelta(days=days_ahead)

    if booking_date is None:
        if "today" in booking_date_str or "сегодня" in booking_date_str:
            booking_date = now_uae
        elif "tomorrow" in booking_date_str or "завтра" in booking_date_str:
            booking_date = now_uae + timedelta(days=1)
        else:
            booking_date = now_uae + timedelta(days=1)
            logger.warning(f"Wappi: defaulting to tomorrow. response='{response_text[:150]}'")

    # Parse HH:MM from booking_time — handle 12h (with am/pm) and 24h.
    if booking_time and booking_time != "TBD":
        bt = booking_time.lower().strip()
        # Try 12h first: "4pm", "4:30 pm", "12 a.m."
        tm = re.search(r'(\d{1,2}):?(\d{2})?\s*(a\.?m\.?|p\.?m\.?|am|pm)', bt)
        if tm:
            hour = int(tm.group(1))
            minute = int(tm.group(2)) if tm.group(2) else 0
            ampm = tm.group(3).replace('.', '').replace(' ', '')
            if 'p' in ampm and hour != 12:
                hour += 12
            elif 'a' in ampm and hour == 12:
                hour = 0
            booking_date = booking_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            # 24h fallback: "16:00", "19:30". Require colon to avoid treating
            # bare day numbers ("26") as an hour.
            tm24 = re.search(r'\b(\d{1,2}):(\d{2})\b', bt)
            if tm24:
                hour = int(tm24.group(1))
                minute = int(tm24.group(2))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    booking_date = booking_date.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )

    # Save in local DB
    try:
        # Ensure phone is set in client record
        client = await bot_module.client_service.get_or_create_client(telegram_id)
        if not client.phone:
            await bot_module.client_service.update_client(telegram_id, phone=phone)

        booking = await bot_module.booking_service.create_booking(
            telegram_id=telegram_id,
            service_name=service_name,
            duration=duration,
            base_price=base_price,
            booking_date=booking_date,
            payment_method=payment_method,
        )
        await bot_module.booking_service.update_booking_status(booking.id, "confirmed")
        dialog_manager.update_state(user_id, "completed")
        logger.info(f"✅ Wappi booking {booking.id} saved in DB for {telegram_id}")
    except Exception as e:
        logger.error(f"Wappi DB booking error: {e}", exc_info=True)
        return

    # Create in YClients
    if bot_module.yclients_service and not config.MOCK_YCLIENTS:
        try:
            import os as _os
            yc_service_id = await bot_module.yclients_service.find_service_id(service_name)
            yc_staff_id = await bot_module.yclients_service.find_staff_id()
            yc_date = booking_date.strftime("%Y-%m-%d")
            yc_time = booking_date.strftime("%H:%M")

            fresh_client = await bot_module.client_service.get_or_create_client(telegram_id)
            client_name = fresh_client.name or sender_name or "WhatsApp Client"
            client_phone = fresh_client.phone or phone

            if yc_service_id and yc_staff_id:
                _is_test = _os.getenv("YCLIENTS_TEST_BOOKINGS", "false").lower() == "true"
                yc_result = await bot_module.yclients_service.create_booking(
                    staff_id=yc_staff_id,
                    service_ids=[yc_service_id],
                    date=yc_date,
                    time=yc_time,
                    client_name=client_name,
                    client_phone=client_phone,
                    comment=f"WhatsApp (Wappi) bot booking #{booking.id}",
                    is_test=_is_test,
                )
                if yc_result:
                    logger.info(f"✅ YClients booking created from WhatsApp: #{yc_result.get('id', '?')}")
                else:
                    logger.warning("⚠️ YClients booking creation failed")
            else:
                logger.warning(f"⚠️ YClients: service_id={yc_service_id}, staff_id={yc_staff_id} — skipping")
        except Exception as e:
            logger.error(f"❌ YClients booking error from WhatsApp: {e}")

    # Notify admin
    if bot_module.notification_service:
        try:
            fresh_client = await bot_module.client_service.get_or_create_client(telegram_id)
            await bot_module.notification_service.send_booking_confirmed(fresh_client, booking)
        except Exception as e:
            logger.error(f"Wappi: failed to notify admin: {e}")


async def _reset_user(user_id: str, telegram_id: str):
    """Clear context, history, and client data for a user."""
    import bot as bot_module
    dialog_manager.clear_context(user_id)
    deleted = await bot_module.message_service.clear_history(telegram_id)
    await bot_module.client_service.reset_client(telegram_id)
    await bot_module.dialog_session_service.end_session(telegram_id)
    logger.info(f"Reset user {user_id}: deleted {deleted} messages")
    return deleted


async def _process_wappi_message(phone: str, text: str, sender_name: str):
    """Background task: process WhatsApp message through AI agent."""
    try:
        import bot as bot_module

        user_id = f"wappi_{phone}"
        telegram_id = user_id

        # Check for reset commands
        _cmd = text.strip().lower()
        if _cmd in ("/clear", "/reset", "/start", "reset", "очистить", "сброс", "clear"):
            await _reset_user(user_id, telegram_id)
            if wappi_client:
                await wappi_client.send_message(
                    phone,
                    "✅ Memory cleared dear 🌹 Let's start fresh! What services are you interested in?"
                )
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

        await bot_module.message_service.save_message(telegram_id, "user", text)
        dialog_manager.add_user_message(user_id, text)

        # Inject YClients slots if we know the area
        if bot_module.yclients_service and not config.MOCK_YCLIENTS:
            _text_lower = text.lower()
            _client_area = context.client_data.get("area") or ""
            if not _client_area:
                import re as _re_area
                # Short tokens like "raha", "yas", "mbz" match inside unrelated
                # words if we just check substring containment (e.g. "raha"
                # inside "Sarah", "yas" inside "always"). Require word
                # boundaries. Multi-word tokens like "abu dhabi" still work.
                def _has_kw(kw: str) -> bool:
                    return _re_area.search(r"\b" + _re_area.escape(kw) + r"\b", _text_lower) is not None

                if any(_has_kw(kw) for kw in ["al ain", "alain", "al-ain", "аль айн"]):
                    _client_area = "al_ain"
                    dialog_manager.update_client_data(user_id, "area", "al_ain")
                elif any(_has_kw(kw) for kw in [
                    "abu dhabi", "abudhabi", "абу даби",
                    "raha", "al raha", "khalifa", "al khalifa",
                    "mussafah", "mbz", "mohammed bin zayed", "mohamed bin zayed",
                    "yas", "yas island", "saadiyat", "al reem", "reem island",
                    "corniche", "tourist club", "al bateen", "bateen",
                    "shahama", "baniyas", "shamkha", "al wathba", "wathba",
                ]):
                    _client_area = "abu_dhabi"
                    dialog_manager.update_client_data(user_id, "area", "abu_dhabi")

            if _client_area:
                try:
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                    _uae = _tz(_td(hours=4))
                    _now = _dt.now(_uae)
                    today = _now.strftime("%Y-%m-%d")
                    tomorrow = (_now + _td(days=1)).strftime("%Y-%m-%d")

                    service_name = context.booking_data.get("service_type") or ""
                    slots_today = await bot_module.yclients_service.get_available_slots_summary(
                        date=today, service_name=service_name)
                    slots_tomorrow = await bot_module.yclients_service.get_available_slots_summary(
                        date=tomorrow, service_name=service_name)

                    # Detect specific date mentioned in message (e.g. "Sunday", "26 april", "sat")
                    extra_dates = []
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
                            break

                    # Fetch slots for specific date if mentioned
                    extra_slots_text = ""
                    for d in extra_dates[:1]:  # limit to 1 extra
                        try:
                            slots = await bot_module.yclients_service.get_available_slots_summary(
                                date=d, service_name=service_name)
                            extra_slots_text += f"\n\n{d}:\n{slots}"
                        except Exception:
                            pass

                    area_note = ""
                    if _client_area == "al_ain":
                        area_note = "\n🚨 Client in AL AIN. Show ONLY Al Ain therapists."
                    elif _client_area == "abu_dhabi":
                        area_note = "\n🚨 Client in ABU DHABI. Do NOT show Al Ain therapists."

                    context.extra_system_info = (
                        f"\n\nREAL AVAILABLE SLOTS:\nTODAY ({today}):\n{slots_today}\n\n"
                        f"TOMORROW ({tomorrow}):\n{slots_tomorrow}"
                        f"{extra_slots_text}\n\n"
                        "🚨 Use ONLY these real slots. Answer immediately — do NOT say 'checking'."
                        f"{area_note}"
                    )
                except Exception as e:
                    logger.warning(f"Wappi: failed to fetch slots: {e}")

        # LLM timeout — OpenAI hangs cost us background-task slots and
        # leave clients silent indefinitely. 30s is well above p99 for
        # GPT-4o-class models; anything longer is a hang, not a slow run.
        try:
            response_text = await asyncio.wait_for(
                booking_agent.process_message(text, context),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.error(f"Wappi [{phone}]: booking_agent timed out after 30s")
            response_text = "Sorry dear, one moment 🙏 Please repeat your message 🌹"

        if not response_text or not response_text.strip():
            response_text = "Just a moment dear 🙏"

        await bot_module.message_service.save_message(telegram_id, "assistant", response_text)
        dialog_manager.add_bot_response(user_id, response_text)

        if wappi_client:
            parts = [p.strip() for p in response_text.split("---MESSAGE_SPLIT---") if p.strip()]
            # Small delay between parts: Wappi + WhatsApp can reorder
            # near-simultaneous sends, which breaks narrative flow (parts
            # arriving out of order, or admin/marketing inserts falling
            # between them). 0.4s per part gives WhatsApp time to process
            # in the intended order and also feels more natural to the
            # recipient (simulates typing).
            for i, part in enumerate(parts):
                if i > 0:
                    await asyncio.sleep(0.4)
                await wappi_client.send_message(phone, part)

        # Post-booking: create in YClients + notify admin
        await _maybe_create_booking(user_id, telegram_id, phone, sender_name, context, response_text)

    except Exception as e:
        logger.error(f"Wappi background processing error: {e}", exc_info=True)
        if wappi_client:
            try:
                await wappi_client.send_message(
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
        dialog_manager.update_client_data(
            user_id, "location", {"lat": latitude, "lng": longitude}
        )
        if area:
            dialog_manager.update_client_data(user_id, "area", area)

        area_label = {
            "abu_dhabi": "Abu Dhabi",
            "al_ain": "Al Ain",
        }.get(area, "unknown area")
        synthetic_text = (
            f"[Client shared GPS location: lat={latitude:.5f}, "
            f"lng={longitude:.5f} — detected {area_label}]"
        )
        logger.info(f"Wappi [{phone}] location → {area_label}")
        background_tasks.add_task(
            _buffer_and_process_wappi, phone, synthetic_text, sender_name
        )
        return {"status": "location_accepted", "area": area or "unknown"}

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

    # Schedule buffered processing (7s wait to combine multi-part messages per PRD 4.1.6)
    background_tasks.add_task(_buffer_and_process_wappi, phone, text, sender_name)
    return {"status": "accepted"}


# ── Coordinate → area classifier ─────────────────────────────────────
# Crystal Lab serves Abu Dhabi + Al Ain only. Pick the nearer of the two
# city centers, but only if within ~0.6° (~66 km). Anything farther
# (Dubai, Sharjah, outside UAE) returns None — the agent will ask the
# client to confirm the area in text.
_AREA_CENTERS = {
    "abu_dhabi": (24.47, 54.37),   # Abu Dhabi city
    "al_ain":    (24.21, 55.75),   # Al Ain city
}
_AREA_RADIUS_DEG = 0.6  # ~66 km; covers outskirts, excludes Dubai


def _area_from_coords(lat: float, lng: float) -> Optional[str]:
    """Return 'abu_dhabi' | 'al_ain' | None for a GPS coordinate.

    None means "unknown / outside service area" — the agent should ask
    the client to confirm their area in text rather than assume.
    """
    best_area: Optional[str] = None
    best_d2 = _AREA_RADIUS_DEG * _AREA_RADIUS_DEG
    for area, (clat, clng) in _AREA_CENTERS.items():
        # Squared Euclidean distance in degrees. Good enough at UAE
        # latitudes for a binary classifier with a 0.6° threshold —
        # no need for haversine.
        d2 = (lat - clat) ** 2 + (lng - clng) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_area = area
    return best_area


@app.post("/webhook/manychat")
async def manychat_webhook(request: Request):
    """Receive ManyChat External Request.

    ManyChat sends subscriber data + message, we process through AI agent
    and return v2 Dynamic Content JSON.
    """
    data = await request.json()
    logger.info(f"ManyChat webhook: {data}")

    # TODO: implement full ManyChat processing (Task #14)
    # For now, return a simple acknowledgement
    subscriber_id = data.get("subscriber_id", "unknown")
    message_text = data.get("last_input_text", "")
    channel = data.get("channel", "unknown")

    logger.info(f"ManyChat [{channel}] from {subscriber_id}: {message_text}")

    return {
        "version": "v2",
        "content": {
            "messages": [
                {
                    "type": "text",
                    "text": "Thank you for your message! Our team will get back to you shortly. 💎"
                }
            ],
            "actions": [
                {
                    "action": "add_tag",
                    "tag_name": "bot_responded"
                }
            ]
        }
    }
