"""Crystal Lab Bot — FastAPI webhook app for Render deployment.

Handles:
- Telegram Bot webhook (aiogram)
- ManyChat External Request webhook (future)
- Health check endpoint
"""

import asyncio
import time
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request, Response, BackgroundTasks
from loguru import logger

# Deduplication cache: message_id → timestamp (processed within last 5 min)
_processed_message_ids: dict[str, float] = {}
_DEDUP_TTL = 300  # 5 minutes

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
                if any(kw in _text_lower for kw in ["al ain", "alain", "al-ain", "аль айн"]):
                    _client_area = "al_ain"
                    dialog_manager.update_client_data(user_id, "area", "al_ain")
                elif any(kw in _text_lower for kw in [
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
                    for kw, weekday in _day_keywords.items():
                        if kw in _text_lower:
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

        response_text = await booking_agent.process_message(text, context)

        if not response_text or not response_text.strip():
            response_text = "Just a moment dear 🙏"

        await bot_module.message_service.save_message(telegram_id, "assistant", response_text)
        dialog_manager.add_bot_response(user_id, response_text)

        if wappi_client:
            parts = [p.strip() for p in response_text.split("---MESSAGE_SPLIT---") if p.strip()]
            for part in parts:
                await wappi_client.send_message(phone, part)

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

    # Dedup: skip if we've already processed this message_id
    now_ts = time.time()
    # Cleanup old entries
    expired = [k for k, ts in _processed_message_ids.items() if now_ts - ts > _DEDUP_TTL]
    for k in expired:
        _processed_message_ids.pop(k, None)

    if message_id and message_id in _processed_message_ids:
        logger.info(f"Wappi: duplicate message {message_id} ignored")
        return {"status": "duplicate"}

    if message_id:
        _processed_message_ids[message_id] = now_ts

    logger.info(f"Wappi [{phone}] {sender_name}: {text[:100]}")

    # Non-text messages — quick response, no AI
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
