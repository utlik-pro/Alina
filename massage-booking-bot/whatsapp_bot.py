"""Crystal Lab Booking Bot - WhatsApp Cloud API Integration

FastAPI webhook server that receives WhatsApp messages and processes them
using the same booking agent, database, and dialog context as the Telegram bot.
"""

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException
from loguru import logger

from config import config
from dialog_context import dialog_manager
from agents.booking_agent import BookingAgent
from database import init_db, ClientService, MessageService, BookingService, DialogSessionService
from services.notifications import NotificationService
from services.whatsapp_api import WhatsAppClient
from services.message_buffer import init_buffer, MessageBuffer

# ── Global Services ───────────────────────────────────────────────────

booking_agent = BookingAgent()
whatsapp_client: WhatsAppClient = None
notification_bot = None  # aiogram Bot for Telegram admin notifications

client_service: ClientService = None
message_service: MessageService = None
booking_service: BookingService = None
dialog_session_service: DialogSessionService = None
notification_service: NotificationService = None
wa_buffer: MessageBuffer = None


# ── App Lifecycle ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, clean up on shutdown."""
    global whatsapp_client, notification_bot
    global client_service, message_service, booking_service, dialog_session_service
    global notification_service, wa_buffer

    # Validate WhatsApp config
    if not config.WHATSAPP_ACCESS_TOKEN or not config.WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required!")
        raise RuntimeError("WhatsApp configuration missing")

    # Initialize WhatsApp client
    whatsapp_client = WhatsAppClient(
        access_token=config.WHATSAPP_ACCESS_TOKEN,
        phone_number_id=config.WHATSAPP_PHONE_NUMBER_ID,
        verify_token=config.WHATSAPP_VERIFY_TOKEN,
    )
    logger.info("WhatsApp client initialized")

    # Initialize database
    logger.info("Initializing database...")
    db = init_db(config.DATABASE_URL)
    await db.create_tables()

    client_service = ClientService(db)
    message_service = MessageService(db)
    booking_service = BookingService(db)
    dialog_session_service = DialogSessionService(db)
    logger.info("Database services initialized")

    # Initialize message buffer (Redis or in-memory fallback)
    wa_buffer = await init_buffer(config.REDIS_URL)

    # Initialize Telegram bot for admin notifications (if configured)
    if config.TELEGRAM_BOT_TOKEN and config.ADMIN_GROUP_CHAT_ID:
        from aiogram import Bot
        notification_bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        notification_service = NotificationService(notification_bot, config.ADMIN_GROUP_CHAT_ID)
        logger.info(f"Admin notifications enabled (Telegram group {config.ADMIN_GROUP_CHAT_ID})")

    logger.info("WhatsApp Bot ready!")
    logger.info(f"  Phone Number ID: {config.WHATSAPP_PHONE_NUMBER_ID}")
    logger.info(f"  AI Model: {config.OPENAI_MODEL}")

    yield

    # Cleanup
    if wa_buffer:
        await wa_buffer.close()
    await whatsapp_client.close()
    if notification_bot:
        await notification_bot.session.close()
    await db.close()
    logger.info("WhatsApp Bot shut down")


app = FastAPI(title="Crystal Lab WhatsApp Bot", lifespan=lifespan)


# ── Webhook Endpoints ─────────────────────────────────────────────────

@app.get("/webhook")
async def verify_webhook(request: Request):
    """WhatsApp webhook verification (GET).
    Meta sends: hub.mode, hub.verify_token, hub.challenge
    """
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    result = whatsapp_client.verify_webhook(mode, token, challenge)
    if result is not None:
        return Response(content=result, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request):
    """WhatsApp webhook handler (POST). Receives all incoming messages."""
    payload = await request.json()

    # Parse messages from webhook payload
    messages = WhatsAppClient.parse_webhook(payload)

    for msg in messages:
        phone = msg["from_number"]
        msg_type = msg["type"]
        msg_id = msg["message_id"]
        sender_name = msg.get("name", "")

        logger.info(f"WA message from {phone} ({sender_name}): type={msg_type}")

        # Mark as read
        asyncio.create_task(whatsapp_client.mark_as_read(msg_id))

        if msg_type == "text":
            await _buffer_text_message(phone, msg["body"], sender_name)

        elif msg_type == "location":
            await _handle_location(phone, msg["location"], sender_name)

        elif msg_type == "image":
            await _handle_image(phone, msg.get("image", {}), sender_name)

        elif msg_type == "contacts":
            await _handle_contacts(phone, msg.get("contacts", []), sender_name)

        elif msg_type in ("interactive", "button"):
            # Interactive replies (button clicks) treated as text
            body = msg.get("body", "")
            if body:
                await _buffer_text_message(phone, body, sender_name)

        else:
            logger.warning(f"Unsupported message type from {phone}: {msg_type}")

    # Always return 200 to acknowledge receipt
    return Response(status_code=200)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "crystal-lab-whatsapp-bot"}


# ── Message Buffering ─────────────────────────────────────────────────

async def _buffer_text_message(phone: str, text: str, sender_name: str = "") -> None:
    """Add text message to buffer. Same 20-second debounce as Telegram bot."""

    count = await wa_buffer.add_message(phone, {
        "text": text,
        "type": "text",
        "sender_name": sender_name,
    })
    await wa_buffer.update_activity(phone)

    logger.debug(f"WA {phone}: buffered ({count} messages)")

    # Cancel previous processing task
    wa_buffer.cancel_processing_task(phone)

    # Start new processing task with 20-second delay
    task = asyncio.create_task(_process_buffered_messages(phone, delay_seconds=20))
    wa_buffer.set_processing_task(phone, task)


async def _process_buffered_messages(phone: str, delay_seconds: int = 20) -> None:
    """Process buffered messages after silence period.

    Same logic as Telegram bot.py:
    - Wait `delay_seconds` for silence
    - Combine all buffered messages
    - Process through AI agent
    - Send response via WhatsApp
    """
    await asyncio.sleep(delay_seconds)

    # Check no new messages arrived during sleep
    last_ts = await wa_buffer.get_last_activity(phone)
    if time.time() - last_ts < delay_seconds:
        logger.debug(f"WA {phone}: new messages arrived, buffer extended")
        return

    buffered = await wa_buffer.get_messages(phone)
    if not buffered:
        return

    logger.info(f"WA {phone}: processing {len(buffered)} buffered messages")

    try:
        # Use phone as user_id for dialog context (hash to int for compatibility)
        user_id = _phone_to_user_id(phone)
        telegram_id = phone  # We use phone number as the identifier

        # Get or create client
        client = await client_service.get_or_create_client(telegram_id)

        # Update client name from WhatsApp profile if not set
        sender_name = buffered[0].get("sender_name", "")
        if sender_name and not client.name:
            await client_service.update_client(telegram_id, name=sender_name)

        # Check if first interaction -> send new client notification
        if client.total_bookings == 0 and client.name is None and notification_service:
            # Refresh client after name update
            client = await client_service.get_or_create_client(telegram_id)
            await notification_service.send_new_client(client)

        # Get dialog context
        context = dialog_manager.get_or_create_context(user_id)

        # Update dialog session
        await dialog_session_service.get_or_create_session(telegram_id)
        await dialog_session_service.update_session_state(
            telegram_id=telegram_id,
            state=context.state,
            context_data=context.to_dict(),
        )

        # Combine text from all buffered messages
        combined_text = "\n".join(
            msg["text"] for msg in buffered if msg.get("text")
        )
        logger.info(f"WA {phone}: combined text: {combined_text}")

        # Save user messages to database
        for msg in buffered:
            if msg.get("text"):
                await message_service.save_message(telegram_id, "user", msg["text"])

        # Preprocess all messages (extract data before GPT)
        for msg in buffered:
            if msg.get("text"):
                await _preprocess_user_input(user_id, telegram_id, msg["text"], context, client)

        # Process with AI agent
        bot_response = await booking_agent.process_message(combined_text, context)

        # Send response via WhatsApp
        if "---MESSAGE_SPLIT---" in bot_response:
            for sub_msg in bot_response.split("---MESSAGE_SPLIT---"):
                sub_msg = sub_msg.strip()
                if sub_msg:
                    await whatsapp_client.send_text_message(phone, sub_msg)
                    await asyncio.sleep(0.5)
        else:
            await whatsapp_client.send_text_message(phone, bot_response)

        # Save bot response
        await message_service.save_message(telegram_id, "assistant", bot_response)

        # Post-process (extract booking data, detect medical notes, etc.)
        await _extract_and_save_data(user_id, telegram_id, combined_text, bot_response, context, client)

    except Exception as e:
        logger.error(f"Error processing WA messages from {phone}: {e}")
        try:
            await whatsapp_client.send_text_message(
                phone, "Sorry, a technical error occurred. Please try again."
            )
        except Exception:
            pass

    finally:
        await wa_buffer.clear_messages(phone)
        wa_buffer.clear_processing_task(phone)


# ── Message Type Handlers ─────────────────────────────────────────────

async def _handle_location(phone: str, location: dict, sender_name: str = "") -> None:
    """Handle location message from WhatsApp client."""
    user_id = _phone_to_user_id(phone)
    telegram_id = phone

    lat = location.get("latitude")
    lng = location.get("longitude")
    logger.info(f"WA {phone}: location received: {lat}, {lng}")

    # Save to database
    await client_service.get_or_create_client(telegram_id)
    await client_service.update_client(
        telegram_id=telegram_id,
        location_latitude=lat,
        location_longitude=lng,
    )

    # Update dialog context
    dialog_manager.update_state(user_id, "location_received")
    context = dialog_manager.get_or_create_context(user_id)
    context.has_location = True
    context.client_data["location"] = f"{lat},{lng}"

    response = "Thank you! What is your villa or apartment number?"
    await whatsapp_client.send_text_message(phone, response)

    await message_service.save_message(telegram_id, "user", f"[Location: {lat},{lng}]")
    await message_service.save_message(telegram_id, "assistant", response)


async def _handle_image(phone: str, image: dict, sender_name: str = "") -> None:
    """Handle image message from WhatsApp client."""
    telegram_id = phone
    caption = image.get("caption", "")
    logger.info(f"WA {phone}: image received, caption: {caption}")

    response = "Thank you for the photo! I've saved it."
    await whatsapp_client.send_text_message(phone, response)

    msg_text = f"[Photo received]"
    if caption:
        msg_text += f" Caption: {caption}"
    await message_service.save_message(telegram_id, "user", msg_text)
    await message_service.save_message(telegram_id, "assistant", response)


async def _handle_contacts(phone: str, contacts: list, sender_name: str = "") -> None:
    """Handle shared contacts from WhatsApp."""
    telegram_id = phone
    logger.info(f"WA {phone}: contacts received: {len(contacts)} contacts")

    # Extract phone numbers from shared contacts
    for contact in contacts:
        name = contact.get("name", {}).get("formatted_name", "Unknown")
        phones = contact.get("phones", [])
        phone_str = phones[0].get("phone", "N/A") if phones else "N/A"
        logger.info(f"WA {phone}: shared contact: {name} ({phone_str})")

    response = "Thank you for sharing the contact!"
    await whatsapp_client.send_text_message(phone, response)
    await message_service.save_message(telegram_id, "user", f"[Contact shared: {len(contacts)} contacts]")
    await message_service.save_message(telegram_id, "assistant", response)


# ── Data Preprocessing & Extraction ──────────────────────────────────
# Mirror of bot.py logic adapted for WhatsApp (phone-based user IDs)

async def _preprocess_user_input(
    user_id: int,
    telegram_id: str,
    user_message: str,
    context,
    client,
) -> None:
    """Preprocess user input BEFORE GPT call. Same logic as bot.py."""

    # Extract villa/apartment number in location_received state
    if context.state == "location_received":
        if not context.client_data.get("location_details"):
            await client_service.update_client(telegram_id, location_details=user_message.strip())
            dialog_manager.update_client_data(user_id, "location_details", user_message.strip())
            dialog_manager.update_state(user_id, "selecting_slot")
            logger.info(f"Location details saved: {user_message.strip()}")

    # Extract selected time
    time_patterns = ["a.m.", "p.m.", "am", "pm", "10:00", "12:00", "4:00", "7:30"]
    if context.state == "selecting_slot" and any(p in user_message.lower() for p in time_patterns):
        dialog_manager.update_booking_data(user_id, "time", user_message.strip())
        dialog_manager.update_state(user_id, "confirming")
        context.has_slot_proposal = True
        logger.info(f"Time selected: {user_message.strip()}")

    # Extract client name
    if context.state == "confirming" and not context.client_data.get("name"):
        potential_name = user_message.strip()
        if (len(potential_name) < 50 and
            not any(w in potential_name.lower() for w in [
                "massage", "want", "need", "a.m", "p.m", "min", "aed",
                "villa", "cash", "bank", "transfer", "pay"
            ])):
            await client_service.update_client(telegram_id, name=potential_name)
            dialog_manager.update_client_data(user_id, "name", potential_name)
            logger.info(f"Name saved: {potential_name}")

    # Extract payment method
    if context.client_data.get("name") and not context.booking_data.get("payment_method"):
        msg_lower = user_message.lower()
        if "cash" in msg_lower:
            dialog_manager.update_booking_data(user_id, "payment_method", "cash")
        elif "bank" in msg_lower or "transfer" in msg_lower:
            dialog_manager.update_booking_data(user_id, "payment_method", "transfer")

    # Extract duration
    if context.state == "consulting" and any(x in user_message.lower() for x in ["60", "90", "min", "minutes"]):
        if "90" in user_message.lower():
            dialog_manager.update_booking_data(user_id, "service_duration", 90)
            dialog_manager.update_booking_data(user_id, "price", 480.0)
        elif "60" in user_message.lower():
            dialog_manager.update_booking_data(user_id, "service_duration", 60)
            dialog_manager.update_booking_data(user_id, "price", 350.0)

    # Eyelash type selection
    if context.state == "consulting":
        msg_lower = user_message.lower()
        current_service = context.booking_data.get("service_type") or ""
        if current_service and "eyelash" in current_service.lower():
            if "russian" in msg_lower:
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension Russian volume")
                dialog_manager.update_booking_data(user_id, "price", 400.0)
            elif "2d" in msg_lower:
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension 2D volume")
                dialog_manager.update_booking_data(user_id, "price", 350.0)
            elif "volume" in msg_lower:
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension 2D volume")
                dialog_manager.update_booking_data(user_id, "price", 350.0)
            elif "classic" in msg_lower or "classical" in msg_lower:
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension classical volume")
                dialog_manager.update_booking_data(user_id, "price", 300.0)


async def _extract_and_save_data(
    user_id: int,
    telegram_id: str,
    user_message: str,
    bot_response: str,
    context,
    client,
) -> None:
    """Extract and save data AFTER GPT response. Same logic as bot.py."""

    # Medical notes detection
    medical_keywords = [
        "cesarean", "surgery", "operation", "birth", "pregnant",
        "pain", "bleeding", "medical", "doctor", "hospital",
    ]
    if any(kw in user_message.lower() for kw in medical_keywords):
        await client_service.update_client(telegram_id, medical_notes=user_message.strip())
        logger.warning(f"Medical note from WA {telegram_id}: {user_message.strip()}")
        if notification_service:
            await notification_service.send_medical_note_alert(client, user_message.strip())

    # Service detection from bot response
    if ("aed" in bot_response.lower() or "vat" in bot_response.lower()) and \
       context.state == "consulting" and not context.booking_data.get("service_selected"):

        service_name = "Body massage"
        duration = 60
        base_price = 350.0
        msg_lower = user_message.lower()

        if ("body" in msg_lower and "face" in msg_lower):
            service_name, duration, base_price = "Body + Face massage", 85, 650.0
        elif "body" in msg_lower and "massage" in msg_lower:
            if "90" in msg_lower:
                service_name, duration, base_price = "Body massage", 90, 480.0
            else:
                service_name, duration, base_price = "Body massage", 60, 350.0
        elif "neck" in msg_lower and ("shoulder" in msg_lower or "back" in msg_lower):
            service_name, duration, base_price = "Neck/shoulders/back massage", 30, 200.0
        elif "foot" in msg_lower or "reflexology" in msg_lower:
            service_name, duration, base_price = "Foot reflexology", 30, 175.0
        elif "face" in msg_lower and "massage" in msg_lower:
            service_name, duration, base_price = "Face massage", 50, 370.0
        elif "manicure" in msg_lower and "pedicure" in msg_lower:
            service_name, duration, base_price = "Combo mani + pedi", None, 380.0
        elif "manicure" in msg_lower or "mani" in msg_lower:
            service_name, duration, base_price = "Russian gelish manicure", None, 200.0
        elif "pedicure" in msg_lower or "pedi" in msg_lower:
            service_name, duration, base_price = "Russian gelish pedicure", None, 220.0
        elif "eyelash" in msg_lower or "lash" in msg_lower:
            if "extension" in msg_lower:
                if "russian" in msg_lower:
                    service_name, duration, base_price = "Eyelash extension Russian volume", None, 400.0
                elif "2d" in msg_lower or "volume" in msg_lower:
                    service_name, duration, base_price = "Eyelash extension 2D volume", None, 350.0
                else:
                    service_name, duration, base_price = "Eyelash extension classical volume", None, 300.0
            elif "lifting" in msg_lower:
                service_name, duration, base_price = "Eyelash lifting", None, 150.0
        elif "eyebrow" in msg_lower or "brow" in msg_lower:
            service_name, duration, base_price = "Eyebrow lamination", None, 200.0
        elif "permanent" in msg_lower or "pmu" in msg_lower:
            if "lip" in msg_lower:
                service_name, duration, base_price = "Permanent makeup lips", None, 1200.0
            elif "brow" in msg_lower:
                service_name, duration, base_price = "Permanent makeup eyebrows", None, 1000.0
            else:
                service_name, duration, base_price = "Permanent makeup", None, 1000.0
        elif "wax" in msg_lower:
            service_name, duration, base_price = "Face waxing", None, 100.0
        elif "cupping" in msg_lower or "hijama" in msg_lower:
            service_name, duration, base_price = "Cupping therapy", 60, 350.0
        elif "deep" in msg_lower and ("clean" in msg_lower or "facial" in msg_lower):
            service_name, duration, base_price = "Deep facial cleansing", 90, 420.0
        elif "carboxy" in msg_lower:
            service_name, duration, base_price = "Carboxy-therapy", 40, 300.0

        dialog_manager.update_booking_data(user_id, "service_type", service_name)
        dialog_manager.update_booking_data(user_id, "service_duration", duration)
        dialog_manager.update_booking_data(user_id, "price", base_price)
        context.booking_data["service_selected"] = True
        logger.info(f"WA service saved: {service_name}, {duration} min, {base_price} AED")

    # Booking confirmation detection
    if "booked" in bot_response.lower() and "\u2705" in bot_response:
        booking_data = context.booking_data
        service_name = booking_data.get("service_type", "Body massage")
        duration = booking_data.get("service_duration", 60)
        base_price = booking_data.get("price", 350.0)
        booking_time = booking_data.get("time", "TBD")
        payment_method = booking_data.get("payment_method", "cash")

        from datetime import datetime, timedelta
        import re
        booking_date = datetime.now() + timedelta(days=1)
        if booking_time and booking_time != "TBD":
            time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(a\.?m\.?|p\.?m\.?)', booking_time.lower())
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                am_pm = time_match.group(3).replace('.', '').replace(' ', '')
                if 'p' in am_pm and hour != 12:
                    hour += 12
                elif 'a' in am_pm and hour == 12:
                    hour = 0
                booking_date = booking_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

        booking = await booking_service.create_booking(
            telegram_id=telegram_id,
            service_name=service_name,
            duration=duration,
            base_price=base_price,
            booking_date=booking_date,
            payment_method=payment_method,
        )
        await booking_service.update_booking_status(booking.id, "confirmed")
        dialog_manager.update_state(user_id, "completed")
        logger.info(f"Booking {booking.id} created for WA {telegram_id}")

        if notification_service:
            fresh_client = await client_service.get_or_create_client(telegram_id)
            await notification_service.send_booking_confirmed(fresh_client, booking)


# ── Helpers ───────────────────────────────────────────────────────────

def _phone_to_user_id(phone: str) -> int:
    """Convert phone number string to integer user_id for dialog_manager compatibility.
    Uses hash to create a stable integer from the phone number.
    """
    return abs(hash(phone)) % (10**10)
