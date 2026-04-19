"""Crystal Lab Bot — FastAPI webhook app for Render deployment.

Handles:
- Telegram Bot webhook (aiogram)
- ManyChat External Request webhook (future)
- Health check endpoint
"""

import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request, Response
from loguru import logger

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


@app.post("/webhook/wappi")
async def wappi_webhook(request: Request):
    """Receive WhatsApp messages via Wappi.pro webhook.

    Wappi sends all selected event types (incoming_message, delivery_status, etc).
    We process only incoming_message events and respond via Wappi API.
    """
    # Verify optional auth secret
    if config.WAPPI_WEBHOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != config.WAPPI_WEBHOOK_SECRET:
            logger.warning("Wappi webhook: invalid auth")
            return Response(status_code=403)

    data = await request.json()
    parsed = parse_incoming_message(data)
    if not parsed:
        # Not an incoming message (e.g. delivery_status) — acknowledge and ignore
        return {"status": "ignored"}

    phone = parsed["phone"]
    text = parsed["text"]
    sender_name = parsed["sender_name"]
    msg_type = parsed["message_type"]

    logger.info(f"Wappi [{phone}] {sender_name}: {text[:100]}")

    # Only process text messages for now
    if msg_type != "chat" or not text:
        if wappi_client:
            await wappi_client.send_message(
                phone,
                "Sorry dear, I can only read text messages right now 🙏 "
                "Please type your question in text 🌹"
            )
        return {"status": "non_text"}

    # Process via AI agent — reuse channel-agnostic logic
    try:
        import bot as bot_module

        # Use phone as unique user identifier
        user_id = f"wappi_{phone}"
        telegram_id = user_id

        # Create/get client in DB (using phone-based telegram_id)
        client = await bot_module.client_service.get_or_create_client(telegram_id)
        if sender_name and not client.name:
            await bot_module.client_service.update_client(telegram_id, name=sender_name)

        # Dialog context
        context = dialog_manager.get_or_create_context(user_id)

        # Load DB history into context if empty
        if not context.recent_messages:
            db_history = await bot_module.message_service.get_conversation_history(telegram_id)
            if db_history:
                for msg in db_history[-20:]:
                    context.recent_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })

        # Save incoming message
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
                elif any(kw in _text_lower for kw in ["abu dhabi", "abudhabi", "абу даби", "raha"]):
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

                    area_note = ""
                    if _client_area == "al_ain":
                        area_note = "\n🚨 Client in AL AIN. Show ONLY Al Ain therapists."
                    elif _client_area == "abu_dhabi":
                        area_note = "\n🚨 Client in ABU DHABI. Do NOT show Al Ain therapists."

                    context.extra_system_info = (
                        f"\n\nREAL AVAILABLE SLOTS:\nTODAY ({today}):\n{slots_today}\n\n"
                        f"TOMORROW ({tomorrow}):\n{slots_tomorrow}\n\n"
                        "🚨 Use ONLY these real slots."
                        f"{area_note}"
                    )
                except Exception as e:
                    logger.warning(f"Wappi: failed to fetch slots: {e}")

        # Generate response via AI agent (pass context object directly — it has .get())
        response_text = await booking_agent.process_message(text, context)

        if not response_text or not response_text.strip():
            response_text = "Just a moment dear 🙏"

        # Save bot response
        await bot_module.message_service.save_message(telegram_id, "assistant", response_text)
        dialog_manager.add_bot_response(user_id, response_text)

        # Send via Wappi — split on ---MESSAGE_SPLIT--- if present
        if wappi_client:
            parts = [p.strip() for p in response_text.split("---MESSAGE_SPLIT---") if p.strip()]
            for part in parts:
                await wappi_client.send_message(phone, part)

        return {"status": "processed"}

    except Exception as e:
        logger.error(f"Wappi webhook processing error: {e}", exc_info=True)
        if wappi_client:
            await wappi_client.send_message(
                phone,
                "Sorry dear, technical issue 🙏 Please try again in a moment 🌹"
            )
        return {"status": "error"}


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
