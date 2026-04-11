"""Crystal Lab Booking Bot - Telegram MVP with Database Integration"""

import asyncio
import os
import time
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BotCommand, Location
from aiogram.filters import CommandStart, Command
from loguru import logger

from config import config
from dialog_context import dialog_manager
from agents.booking_agent import BookingAgent
from prices import get_price, get_service, SERVICE_CATALOG as PRICE_CATALOG
from database import init_db, get_db, ClientService, MessageService, BookingService, DialogSessionService
from services.notifications import NotificationService
from services.follow_up import FollowUpService
from services.message_buffer import init_buffer, get_buffer, MessageBuffer
from services.promo_photos import get_promo_photo
from services.yclients_service import YClientsService

# Инициализация роутера
router = Router()

# Инициализация агента
booking_agent = BookingAgent()

# Global services (will be initialized in main())
client_service: ClientService = None
message_service: MessageService = None
booking_service: BookingService = None
dialog_session_service: DialogSessionService = None
notification_service: NotificationService = None
follow_up_service: FollowUpService = None
yclients_service: YClientsService = None
msg_buffer: MessageBuffer = None


@router.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """Обработчик команды /start"""

    user_id = message.from_user.id
    telegram_id = str(user_id)
    logger.info(f"Команда /start от пользователя {user_id}")

    # Create or get client in database
    client = await client_service.get_or_create_client(telegram_id)

    # Notify group about new client (if first time)
    if client.total_bookings == 0 and notification_service:
        await notification_service.send_new_client(client)

    # Update dialog context
    context = dialog_manager.get_or_create_context(user_id)
    dialog_manager.update_state(user_id, "consulting")

    # Create dialog session in DB
    await dialog_session_service.get_or_create_session(telegram_id)

    # Приветственное сообщение
    greeting = """Welcome to Crystal Lab home service🙌

Certified Russian technicians and free transportation to your home 🏠
Abu Dhabi and Al Ain

We can offer you a lot of beauty services on offer price 🌹

- Body massage (different techniques)
- Face massage & Deep facial cleansing
- Manicure and pedicure (Russian gelish & Japanese)
- Eyelash extensions & lifting
- Eyebrow lamination
- Permanent makeup (lips, eyebrows, eyeliner)
- Hair and makeup
- Face waxing
- Cupping therapy

What services are you interested in? We will give you all the details 🌹"""

    await message.answer(greeting)

    # Save messages to database
    await message_service.save_message(
        telegram_id=telegram_id,
        role="assistant",
        content=greeting,
    )


@router.message(Command("status"))
async def command_status_handler(message: Message) -> None:
    """Показать текущий статус бронирования из БД"""

    user_id = message.from_user.id
    telegram_id = str(user_id)

    try:
        # Get client from database
        client = await client_service.get_or_create_client(telegram_id)

        # Get dialog context
        context = dialog_manager.get_context(user_id)
        if not context:
            await message.answer("У вас пока нет активного диалога. Напишите /start")
            return

        # Format client info
        name = client.name if client.name else "не указано"
        location = f"{client.location_latitude},{client.location_longitude}" if client.location_latitude else "не указана"
        if client.location_details:
            location += f" ({client.location_details})"

        # Get booking data from context
        booking_data = context.get("booking_data", {})
        service = booking_data.get("service", "не выбрана")
        date_time = booking_data.get("date", "не выбрано")
        if booking_data.get("time"):
            date_time = f"{date_time} {booking_data.get('time')}"

        status_message = f"""📊 Статус вашего бронирования:

Состояние: {context.get("state", "unknown")}
Имя: {name}
Локация: {location}
Услуга: {service}
Дата/время: {date_time}
Статус брони: {booking_data.get("status", "draft")}"""

        # Add medical notes if any
        if client.medical_notes:
            status_message += f"\n\n⚕️ Медицинские заметки:\n{client.medical_notes}"

        await message.answer(status_message)

    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await message.answer("Произошла ошибка при получении статуса")


@router.message(Command("clear"))
async def command_clear_handler(message: Message) -> None:
    """Сброс контекста диалога и истории сообщений"""

    user_id = message.from_user.id
    telegram_id = str(user_id)
    logger.info(f"Команда /clear от пользователя {user_id}")

    # Clear in-memory context
    dialog_manager.clear_context(user_id)

    # Clear message history from database
    deleted_count = await message_service.clear_history(telegram_id)
    logger.info(f"Удалено {deleted_count} сообщений из БД для {user_id}")

    # Reset client data (name, location)
    await client_service.reset_client(telegram_id)

    # End session in database
    await dialog_session_service.end_session(telegram_id)

    await message.answer(
        "✅ История, имя и локация полностью очищены. Начните заново с /start"
    )


@router.message(F.location)
async def handle_location(message: Message) -> None:
    """Обработка геолокации"""

    user_id = message.from_user.id
    telegram_id = str(user_id)
    location: Location = message.location

    logger.info(f"Получена локация от {user_id}: {location.latitude}, {location.longitude}")

    # Update client in database
    await client_service.update_client(
        telegram_id=telegram_id,
        location_latitude=location.latitude,
        location_longitude=location.longitude,
    )

    # Update dialog context
    dialog_manager.update_state(user_id, "location_received")

    # ВАЖНО: Установить флаг что локация получена
    context = dialog_manager.get_or_create_context(user_id)
    context.has_location = True
    context.client_data["location"] = f"{location.latitude},{location.longitude}"

    # Ask for villa/apartment number
    response = "Thank you! What is your villa or apartment number?"
    await message.answer(response)

    # Save to database
    await message_service.save_message(telegram_id, "user", f"[Location: {location.latitude},{location.longitude}]")
    await message_service.save_message(telegram_id, "assistant", response)


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Обработка фото"""

    user_id = message.from_user.id
    telegram_id = str(user_id)

    logger.info(f"Получено фото от {user_id}")

    response = "Thank you for the photo! I've saved it."
    await message.answer(response)

    # Save to database
    await message_service.save_message(telegram_id, "user", "[Photo received]")
    await message_service.save_message(telegram_id, "assistant", response)


async def _process_buffered_messages(user_id: int, telegram_id: str, delay_seconds: int = 20) -> None:
    """
    Обработка накопленных сообщений после паузы.

    КРИТИЧНО: Реальные клиенты (особенно арабы) отправляют 3-5 сообщений за 10-30 секунд:
    - "Maybe 19th feb dear" + "Aroun 11" + "Its 1 hr rite?" (38 сек)
    - GPS + "Villa 20" + [Photo] (1 сек)
    - "Body" → "Both" (меняют решение за 4 сек)

    ОБНОВЛЕНО 22.11.2025: Увеличена задержка с 7 до 20 секунд на основе встречи с клиентом.
    """
    await asyncio.sleep(delay_seconds)

    # Проверяем что нет новых сообщений последние N секунд
    last_ts = await msg_buffer.get_last_activity(str(user_id))
    if time.time() - last_ts < delay_seconds:
        logger.debug(f"User {user_id}: новые сообщения поступили, буфер продлен")
        return

    # Получаем все накопленные сообщения (stored as dicts with "text" and "message" keys)
    buffered = await msg_buffer.get_messages(str(user_id))
    if not buffered:
        logger.debug(f"User {user_id}: буфер пуст")
        return

    logger.info(f"User {user_id}: обработка {len(buffered)} накопленных сообщений")

    # We need the original Message objects for .answer() — stored separately
    _msg_objects = getattr(msg_buffer, '_message_objects', {})
    original_messages = _msg_objects.get(str(user_id), [])

    try:
        # Get or create client
        client = await client_service.get_or_create_client(telegram_id)

        # Get dialog context (и загрузить историю из БД если контекст новый)
        context = dialog_manager.get_or_create_context(user_id)

        if not context.recent_messages:
            # Контекст пустой — загружаем историю из базы данных
            db_history = await message_service.get_conversation_history(telegram_id)
            if db_history:
                for msg in db_history[-20:]:  # Последние 20 сообщений
                    context.recent_messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })
                logger.info(f"User {user_id}: загружено {len(context.recent_messages)} сообщений из БД")

            # Загружаем имя и локацию клиента из БД
            if client.name and not context.client_data.get("name"):
                context.client_data["name"] = client.name
            if client.location_details and not context.client_data.get("location_details"):
                context.client_data["location_details"] = client.location_details

        # Update session activity
        await dialog_session_service.update_session_state(
            telegram_id=telegram_id,
            state=context.state,
            context_data=context.to_dict(),
        )

        # Комбинируем все тексты сообщений в один контекст
        combined_text = "\n".join(m.get("text", "") for m in buffered if m.get("text"))
        logger.info(f"User {user_id}: комбинированный текст: {combined_text}")

        # Save all user messages to database AND dialog history
        for m in buffered:
            if m.get("text"):
                await message_service.save_message(telegram_id, "user", m["text"])

        # Добавляем комбинированное сообщение в историю диалога (для GPT)
        dialog_manager.add_user_message(user_id, combined_text)

        # ВАЖНО: Извлекаем данные ДО вызова GPT из ВСЕХ сообщений
        for m in buffered:
            if m.get("text"):
                await _preprocess_user_input(user_id, telegram_id, m["text"], context, client)

        # Inject real YClients available slots into context (if not in mock mode)
        # Only fetch slots when we know enough to show relevant ones
        if yclients_service and not config.MOCK_YCLIENTS:
            try:
                _text_lower = combined_text.lower()

                # Detect if client mentioned their area
                _client_area = context.client_data.get("area") or ""
                if not _client_area:
                    if any(kw in _text_lower for kw in ["al ain", "alain", "al-ain", "аль айн"]):
                        _client_area = "al_ain"
                        dialog_manager.update_client_data(user_id, "area", "al_ain")
                    elif any(kw in _text_lower for kw in ["abu dhabi", "abudhabi", "абу даби", "raha", "khalifa", "mussafah", "mbz"]):
                        _client_area = "abu_dhabi"
                        dialog_manager.update_client_data(user_id, "area", "abu_dhabi")
                    elif context.has_location:
                        _client_area = "known"  # Location shared via GPS

                # Check if client is asking for times/slots or we already have area
                _wants_slots = (
                    _client_area  # We know the area
                    or any(kw in _text_lower for kw in ["time", "when", "available", "slot", "book", "tomorrow", "today",
                                                         "время", "когда", "свободн", "запис", "завтра", "сегодня"])
                    or context.booking_data.get("service_type")  # Service already chosen, might need slots next
                )

                # Only inject slots if we have enough context
                if _wants_slots and (not context.booking_data.get("time") or "today" in _text_lower or "сегодня" in _text_lower):
                    from datetime import datetime as _dt, timedelta as _td

                    # Detect which service for filtering
                    service_name = context.booking_data.get("service_type") or ""
                    if not service_name:
                        if any(kw in _text_lower for kw in ["mani", "pedi", "nail", "маникюр", "педикюр", "ногти", "гель"]):
                            service_name = "Russian gelish manicure"
                        elif any(kw in _text_lower for kw in ["lash", "eyelash", "ресниц", "наращивание"]):
                            service_name = "eyelash extension"
                        elif any(kw in _text_lower for kw in ["brow", "ламинация бров", "брови"]):
                            service_name = "eyebrow lamination"

                    # Fetch both today and tomorrow (UAE timezone UTC+4)
                    from datetime import timezone as _tz
                    _uae = _tz(_td(hours=4))
                    _now_uae = _dt.now(_uae)
                    today = _now_uae.strftime("%Y-%m-%d")
                    tomorrow = (_now_uae + _td(days=1)).strftime("%Y-%m-%d")

                    slots_today = await yclients_service.get_available_slots_summary(
                        date=today, service_name=service_name)
                    slots_tomorrow = await yclients_service.get_available_slots_summary(
                        date=tomorrow, service_name=service_name)

                    # Filter by area if known
                    area_note = ""
                    if _client_area == "al_ain":
                        area_note = "\n🚨 Client is in AL AIN. Show ONLY Al Ain therapists (marked 'Al Ain')."
                    elif _client_area == "abu_dhabi":
                        area_note = "\n🚨 Client is in ABU DHABI. Do NOT show Al Ain therapists."

                    slots_text = f"TODAY ({today}):\n{slots_today}\n\nTOMORROW ({tomorrow}):\n{slots_tomorrow}"
                    context.extra_system_info = (
                        f"\n\nREAL AVAILABLE SLOTS FROM SCHEDULE:\n{slots_text}\n\n"
                        "🚨 Use ONLY these real slots. NEVER invent times or therapists. "
                        "If a therapist is NOT listed — she has a day off. "
                        "Only offer times that appear above."
                        f"{area_note}"
                    )
                elif not _client_area and not context.booking_data.get("time"):
                    # No area known, no slots — GPT will ask for area per system prompt
                    context.extra_system_info = (
                        "\n\n⚠️ CLIENT'S AREA IS NOT KNOWN YET. "
                        "Ask: 'Are you in Abu Dhabi or Al Ain dear?' BEFORE showing any time slots. "
                        "Do NOT show slots until you know the area."
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch YClients slots: {e}")

        # Process combined message with AI
        bot_response = await booking_agent.process_message(combined_text, context)

        # Send response через последний оригинальный Message object
        last_msg_obj = original_messages[-1] if original_messages else None
        logger.info(f"User {user_id}: last_msg_obj={'YES' if last_msg_obj else 'NONE'}, response_len={len(bot_response) if bot_response else 0}, response_empty={not (bot_response and bot_response.strip())}")

        if last_msg_obj and bot_response and bot_response.strip():
            if "---MESSAGE_SPLIT---" in bot_response:
                sub_messages = bot_response.split("---MESSAGE_SPLIT---")
                for i, sub_msg in enumerate(sub_messages):
                    sub_msg = sub_msg.strip()
                    if sub_msg:
                        await last_msg_obj.answer(sub_msg)
                        if i < len(sub_messages) - 1:
                            await asyncio.sleep(0.5)
            else:
                await last_msg_obj.answer(bot_response.strip())

            # Send promo photo if relevant
            try:
                promo_path = get_promo_photo(combined_text, bot_response)
                if promo_path:
                    from aiogram.types import FSInputFile
                    photo = FSInputFile(promo_path)
                    await last_msg_obj.answer_photo(photo=photo)
                    logger.info(f"User {user_id}: sent promo photo {os.path.basename(promo_path)}")
            except Exception as e:
                logger.warning(f"Failed to send promo photo: {e}")

        # Save bot response to database AND dialog history
        if bot_response:
            await message_service.save_message(telegram_id, "assistant", bot_response)
            dialog_manager.add_bot_response(user_id, bot_response)

            # Extract and save data from combined text
            await _extract_and_save_data(user_id, telegram_id, combined_text, bot_response, context, client, last_msg_obj)
        else:
            logger.warning(f"User {user_id}: GPT вернул пустой ответ")

    except Exception as e:
        logger.error(f"Ошибка при обработке буферизованных сообщений от {user_id}: {e}")
        if original_messages:
            await original_messages[-1].answer("Sorry, there was a technical issue. Please try again 🙏")

    finally:
        await msg_buffer.clear_messages(str(user_id))
        if hasattr(msg_buffer, '_message_objects'):
            msg_buffer._message_objects.pop(str(user_id), None)
        msg_buffer.clear_processing_task(str(user_id))


@router.message(F.text)
async def handle_message(message: Message) -> None:
    """
    Обработка текстовых сообщений с буферизацией.

    КРИТИЧНО: Клиенты отправляют множественные сообщения подряд.
    Бот ждет 20 секунд после получения сообщения перед обработкой,
    чтобы собрать все сообщения клиента вместе.
    (Обновлено 22.11.2025: увеличено с 7 до 20 секунд)
    """

    user_id = message.from_user.id
    telegram_id = str(user_id)
    user_message = message.text

    logger.info(f"Сообщение от {user_id}: {user_message}")

    # Reset follow-up counter (client is active)
    if follow_up_service:
        follow_up_service.reset_follow_up(user_id)

    # Добавляем сообщение в буфер (Redis-backed)
    user_key = str(user_id)
    count = await msg_buffer.add_message(user_key, {"text": user_message})
    # Store original Message object separately (for .answer())
    if not hasattr(msg_buffer, '_message_objects'):
        msg_buffer._message_objects = {}
    if user_key not in msg_buffer._message_objects:
        msg_buffer._message_objects[user_key] = []
    msg_buffer._message_objects[user_key].append(message)
    await msg_buffer.update_activity(user_key)

    logger.debug(f"User {user_id}: добавлено в буфер ({count} сообщений)")

    # Отменяем предыдущую задачу обработки (если есть)
    msg_buffer.cancel_processing_task(user_key)

    # Запускаем новую задачу обработки с задержкой 20 секунд (обновлено 22.11.2025)
    task = asyncio.create_task(_process_buffered_messages(user_id, telegram_id, delay_seconds=20))
    msg_buffer.set_processing_task(user_key, task)


async def _preprocess_user_input(
    user_id: int,
    telegram_id: str,
    user_message: str,
    context,  # DialogContext object
    client,
) -> None:
    """Предобработка пользовательского ввода ДО вызова GPT"""

    import re as _re
    msg_lower = user_message.lower().strip()

    # ── 1. Извлекаем локацию (текстовую или после GPS) ──
    location_keywords = ["villa", "apartment", "apt", "tower", "building", "floor", "flat", "house", "studio", "room"]
    is_location_text = any(kw in msg_lower for kw in location_keywords)

    if context.state == "location_received" and not context.client_data.get("location_details"):
        # GPS уже был — это номер виллы
        await client_service.update_client(telegram_id, location_details=user_message.strip())
        dialog_manager.update_client_data(user_id, "location_details", user_message.strip())
        dialog_manager.update_state(user_id, "selecting_slot")
        logger.info(f"Сохранены детали локации (после GPS): {user_message.strip()}")
    elif is_location_text and not context.client_data.get("location_details"):
        # Текстовая локация — сохраняем и переводим в selecting_slot
        await client_service.update_client(telegram_id, location_details=user_message.strip())
        dialog_manager.update_client_data(user_id, "location_details", user_message.strip())
        context.has_location = True
        if context.state in ("consulting", "location_received"):
            dialog_manager.update_state(user_id, "selecting_slot")
        logger.info(f"Сохранена текстовая локация: {user_message.strip()}")

    # ── 2. Извлекаем время (без жёсткой привязки к state) ──
    time_match = _re.search(r'\b(\d{1,2})\s*(a\.?m\.?|p\.?m\.?|am|pm)\b', msg_lower)
    time_match2 = _re.search(r'\b(\d{1,2}):(\d{2})\b', msg_lower)
    has_day_word = any(w in msg_lower for w in ["today", "tomorrow", "tomor", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])

    if (time_match or time_match2) and not context.booking_data.get("time"):
        # Сохраняем время если ещё не сохранено
        dialog_manager.update_booking_data(user_id, "time", user_message.strip())
        if context.state in ("consulting", "selecting_slot"):
            dialog_manager.update_state(user_id, "confirming")
        context.has_slot_proposal = True
        logger.info(f"Выбрано время: {user_message.strip()}")
    elif has_day_word and not time_match and not context.booking_data.get("date"):
        # Только день без времени (напр. "tomorrow")
        dialog_manager.update_booking_data(user_id, "date", user_message.strip())
        logger.info(f"Выбран день: {user_message.strip()}")

    # ── 3. Извлекаем способ оплаты (в любой момент) ──
    if not context.booking_data.get("payment_method"):
        if "cash" in msg_lower:
            dialog_manager.update_booking_data(user_id, "payment_method", "cash")
            logger.info(f"Выбран способ оплаты: cash")
        elif "bank" in msg_lower or "transfer" in msg_lower:
            dialog_manager.update_booking_data(user_id, "payment_method", "transfer")
            logger.info(f"Выбран способ оплаты: transfer")

    # ── 4. Извлекаем имя клиента ──
    # Имя определяем если: ещё не сохранено, время уже есть (бот спрашивает имя после времени),
    # короткое сообщение без ключевых слов
    if not context.client_data.get("name") and context.booking_data.get("time"):
        potential_name = user_message.strip()
        skip_words = ["massage", "want", "need", "a.m", "p.m", "min", "aed", "villa",
                       "cash", "bank", "transfer", "pay", "yes", "no", "ok", "hi",
                       "hello", "apartment", "tower", "today", "tomorrow", "tomor"]
        if (len(potential_name) < 50 and
            not any(word in potential_name.lower() for word in skip_words) and
            not _re.search(r'\d', potential_name)):  # Имя обычно не содержит цифр
            await client_service.update_client(telegram_id, name=potential_name)
            dialog_manager.update_client_data(user_id, "name", potential_name)
            if context.state != "confirming":
                dialog_manager.update_state(user_id, "confirming")
            logger.info(f"Сохранено имя: {potential_name}")

    # Извлекаем длительность если клиент выбирает (60 min, 90 min)
    if context.state == "consulting" and any(x in user_message.lower() for x in ["60", "90", "min", "minutes"]):
        if "90" in user_message.lower():
            _price_90 = get_price("body_massage_90")
            dialog_manager.update_booking_data(user_id, "service_duration", 90)
            dialog_manager.update_booking_data(user_id, "price", _price_90)
            logger.info(f"Обновлена длительность ДО GPT: 90 мин, {_price_90} AED")
        elif "60" in user_message.lower():
            _price_60 = get_price("body_massage_60")
            dialog_manager.update_booking_data(user_id, "service_duration", 60)
            dialog_manager.update_booking_data(user_id, "price", _price_60)
            logger.info(f"Обновлена длительность ДО GPT: 60 мин, {_price_60} AED")

    # Обрабатываем выбор между volume/classic для eyelash extension
    if context.state == "consulting":
        msg_lower = user_message.lower()
        current_service = context.booking_data.get("service_type") or ""

        # Если услуга eyelash extension уже выбрана, и клиент уточняет volume/classic
        if current_service and "eyelash" in current_service.lower():
            if "russian" in msg_lower or "russian volume" in msg_lower:
                _lp = get_price("lash_ext_russian")
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension Russian volume")
                dialog_manager.update_booking_data(user_id, "price", _lp)
                logger.info(f"Обновлена услуга ДО GPT: Eyelash extension Russian volume, {_lp} AED")
            elif "2d" in msg_lower:
                _lp = get_price("lash_ext_2d")
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension 2D volume")
                dialog_manager.update_booking_data(user_id, "price", _lp)
                logger.info(f"Обновлена услуга ДО GPT: Eyelash extension 2D volume, {_lp} AED")
            elif "volume" in msg_lower:
                _lp = get_price("lash_ext_2d")
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension 2D volume")
                dialog_manager.update_booking_data(user_id, "price", _lp)
                logger.info(f"Обновлена услуга ДО GPT: Eyelash extension 2D volume, {_lp} AED")
            elif "classic" in msg_lower or "classical" in msg_lower:
                _lp = get_price("lash_ext_classic")
                dialog_manager.update_booking_data(user_id, "service_type", "Eyelash extension classical volume")
                dialog_manager.update_booking_data(user_id, "price", _lp)
                logger.info(f"Обновлена услуга ДО GPT: Eyelash extension classical volume, {_lp} AED")


async def _extract_and_save_data(
    user_id: int,
    telegram_id: str,
    user_message: str,
    bot_response: str,
    context,  # DialogContext object
    client,
    last_msg_obj=None,
) -> None:
    """Извлечь и сохранить данные из диалога в БД ПОСЛЕ ответа GPT"""

    # Guard: bot_response must be a string
    if not bot_response:
        return
    bot_response = str(bot_response)

    # Извлекаем медицинские заметки
    medical_keywords = ["cesarean", "surgery", "operation", "birth", "pregnant", "pain", "bleeding", "medical", "doctor", "hospital"]
    if any(keyword in user_message.lower() for keyword in medical_keywords):
        await client_service.update_client(telegram_id, medical_notes=user_message.strip())
        logger.warning(f"⚕️ Медицинская заметка: {user_message.strip()}")

        # Send alert to group
        if notification_service:
            await notification_service.send_medical_note_alert(client, user_message.strip())

    # Извлекаем информацию о услуге из ответа бота (когда бот показывает цены)
    # Проверяем что услуга еще не была выбрана
    if ("aed" in bot_response.lower() or "vat" in bot_response.lower()) and context.state == "consulting" and not context.booking_data.get("service_selected", False):
        # Определяем услугу из сообщения пользователя
        # Цены берутся из prices.py (единый источник правды)
        _p = get_price  # shorthand
        service_name = "Body massage"  # default
        duration = 60  # default
        base_price = _p("body_massage_60")  # default

        msg_lower = user_message.lower()

        # Определяем тип услуги
        # ВАЖНО: Проверяем комбо Body + Face ПЕРЕД отдельными услугами
        if ("body" in msg_lower and "face" in msg_lower) and ("massage" in msg_lower or "+" in msg_lower):
            service_name = "Body + Face massage"
            duration = get_service("body_face_combo")["duration"]
            base_price = _p("body_face_combo")
        elif "body massage" in msg_lower or ("body" in msg_lower and "massage" in msg_lower):
            service_name = "Body massage"
            if "90" in msg_lower or "ninety" in msg_lower:
                duration = 90
                base_price = _p("body_massage_90")
            else:
                duration = 60
                base_price = _p("body_massage_60")
        elif "neck" in msg_lower and ("shoulder" in msg_lower or "back" in msg_lower):
            service_name = "Neck/shoulders/back massage"
            duration = 30
            base_price = _p("neck_shoulders")
        elif "foot" in msg_lower or "reflexology" in msg_lower:
            service_name = "Foot reflexology"
            duration = 30
            base_price = _p("foot_reflexology")
        elif "face massage" in msg_lower or ("face" in msg_lower and "massage" in msg_lower):
            service_name = "Face massage"
            duration = 50
            base_price = _p("face_massage")
        elif "manicure" in msg_lower and "pedicure" in msg_lower:
            if "japanese" in msg_lower:
                service_name = "Japanese mani + pedi"
                base_price = _p("japanese_combo")
            else:
                service_name = "Combo mani + pedi"
                base_price = _p("russian_combo")
            duration = None
        elif "manicure" in msg_lower or "mani" in msg_lower:
            if "russian" in msg_lower or "gelish" in msg_lower:
                service_name = "Russian gelish manicure"
                base_price = _p("russian_mani")
            elif "japanese" in msg_lower:
                service_name = "Japanese manicure"
                base_price = _p("japanese_mani")
            else:
                service_name = "Russian gelish manicure"
                base_price = _p("russian_mani")
            duration = None
        elif "pedicure" in msg_lower or "pedi" in msg_lower:
            if "russian" in msg_lower or "gelish" in msg_lower:
                service_name = "Russian gelish pedicure"
                base_price = _p("russian_pedi")
            elif "japanese" in msg_lower:
                service_name = "Japanese pedicure"
                base_price = _p("japanese_pedi")
            else:
                service_name = "Russian gelish pedicure"
                base_price = _p("russian_pedi")
            duration = None
        # ВАЖНО: Проверяем комбо ПЕРЕД отдельными услугами
        elif ("eyebrow" in msg_lower or "brow" in msg_lower) and ("eyelash" in msg_lower and ("lifting" in msg_lower or "lift" in msg_lower)):
            service_name = "Eyebrow lamination + Eyelash lifting"
            base_price = _p("lash_brow_combo")
            duration = None
        elif "eyelash" in msg_lower or "lash" in msg_lower:
            if "extension" in msg_lower:
                if "russian" in msg_lower:
                    service_name = "Eyelash extension Russian volume"
                    base_price = _p("lash_ext_russian")
                elif "2d" in msg_lower:
                    service_name = "Eyelash extension 2D volume"
                    base_price = _p("lash_ext_2d")
                elif "volume" in msg_lower:
                    service_name = "Eyelash extension 2D volume"
                    base_price = _p("lash_ext_2d")
                else:
                    service_name = "Eyelash extension classical volume"
                    base_price = _p("lash_ext_classic")
                duration = None
            elif "lifting" in msg_lower or "lift" in msg_lower:
                service_name = "Eyelash lifting"
                base_price = _p("lash_lifting")
                duration = None
        elif "eyebrow" in msg_lower or "brow" in msg_lower:
            service_name = "Eyebrow lamination"
            duration = None
            base_price = _p("brow_lamination")
        elif "permanent" in msg_lower or "pmu" in msg_lower:
            if "lip" in msg_lower:
                service_name = "Permanent makeup lips"
                base_price = _p("pmu_lips")
            elif "brow" in msg_lower or "eyebrow" in msg_lower:
                service_name = "Permanent makeup eyebrows"
                base_price = _p("pmu_eyebrows")
            elif "eyeliner" in msg_lower or "eye line" in msg_lower:
                service_name = "Permanent makeup eyeliner"
                base_price = _p("pmu_eyeliner")
            else:
                service_name = "Permanent makeup"
                base_price = _p("pmu_eyebrows")
            duration = None
        elif "wax" in msg_lower:
            if "full" in msg_lower:
                service_name = "Full face waxing"
                base_price = _p("wax_full_face")
            elif "lip" in msg_lower:
                service_name = "Upper lip waxing"
                base_price = _p("wax_upper_lip")
            elif "chin" in msg_lower:
                service_name = "Chin waxing"
                base_price = _p("wax_chin")
            else:
                service_name = "Face waxing"
                base_price = _p("wax_full_face")
            duration = None
        elif "cupping" in msg_lower or "hijama" in msg_lower:
            service_name = "Cupping"
            base_price = get_price("cupping")
            duration = 15
        elif "deep face clean" in msg_lower or "deep facial" in msg_lower or "deep cleansing" in msg_lower:
            service_name = "Deep facial cleansing"
            duration = 90
            base_price = _p("deep_facial_cleansing")
        elif "carboxy" in msg_lower:
            service_name = "Carboxy-therapy"
            duration = 40
            base_price = _p("carboxy_therapy")
        elif "hair" in msg_lower and "makeup" in msg_lower:
            service_name = "Hair and makeup"
            base_price = _p("hair_makeup")
            duration = None
        elif "hair" in msg_lower:
            service_name = "Hairstyle"
            base_price = _p("hairstyle")
            duration = None
        elif "makeup" in msg_lower:
            service_name = "Makeup"
            base_price = _p("makeup")
            duration = None

        # Сохраняем в booking_data
        dialog_manager.update_booking_data(user_id, "service_type", service_name)
        dialog_manager.update_booking_data(user_id, "service_duration", duration)
        dialog_manager.update_booking_data(user_id, "price", base_price)

        # ВАЖНО: Помечаем что услуга выбрана, чтобы не обрабатывать повторно
        context.booking_data["service_selected"] = True

        logger.info(f"Сохранена услуга: {service_name}, {duration} мин, {base_price} AED")

    # Определяем завершение бронирования
    if "booked" in bot_response.lower() and "✅" in bot_response:
        # Booking confirmed!
        booking_data = context.booking_data

        # Получаем данные из context (with safe None handling)
        service_name = booking_data.get("service_type") or "Body massage"
        duration = booking_data.get("service_duration") or 60
        base_price = booking_data.get("price") or 350.0
        booking_time = booking_data.get("time") or "TBD"
        payment_method = booking_data.get("payment_method") or "cash"

        # Try to extract time from GPT response if not in context
        from datetime import datetime, timedelta
        import re

        if booking_time == "TBD":
            # Parse from bot response: "booked on Thursday 26th of March at 5pm"
            time_in_response = re.search(r'at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))', bot_response.lower())
            if time_in_response:
                booking_time = time_in_response.group(1)
                logger.info(f"Extracted time from GPT response: {booking_time}")

        # Определяем дату (today/tomorrow)
        booking_date_str = (booking_data.get("date") or "").lower()
        if "today" in booking_date_str:
            booking_date = datetime.now()
        else:
            booking_date = datetime.now() + timedelta(days=1)  # default: tomorrow

        # Пытаемся извлечь время из строки типа "5pm", "12:00 p.m", "3 pm"
        if booking_time and booking_time != "TBD":
            time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(a\.?m\.?|p\.?m\.?|am|pm)', booking_time.lower())
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                am_pm = time_match.group(3).replace('.', '').replace(' ', '')

                if 'p' in am_pm and hour != 12:
                    hour += 12
                elif 'a' in am_pm and hour == 12:
                    hour = 0

                booking_date = booking_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                logger.info(f"Parsed booking time: {booking_time} → {booking_date}")
            else:
                logger.warning(f"Could not parse booking time: {booking_time}")

        # Create booking in database
        booking = await booking_service.create_booking(
            telegram_id=telegram_id,
            service_name=service_name,
            duration=duration,
            base_price=base_price,
            booking_date=booking_date,
            payment_method=payment_method,
        )

        # Update status
        await booking_service.update_booking_status(booking.id, "confirmed")

        dialog_manager.update_state(user_id, "completed")
        logger.info(f"✅ Бронирование {booking.id} создано для {telegram_id}")

        # Create booking in YClients (if connected)
        if yclients_service and not config.MOCK_YCLIENTS:
            try:
                # Find service and staff IDs in YClients
                yc_service_id = await yclients_service.find_service_id(service_name)
                yc_staff_id = await yclients_service.find_staff_id()
                yc_date = booking_date.strftime("%Y-%m-%d")
                yc_time = booking_date.strftime("%H:%M")

                fresh_client = await client_service.get_or_create_client(telegram_id)
                client_name = fresh_client.name or ""
                client_phone = fresh_client.phone or ""

                if yc_service_id and yc_staff_id:
                    yc_result = await yclients_service.create_booking(
                        staff_id=yc_staff_id,
                        service_ids=[yc_service_id],
                        date=yc_date,
                        time=yc_time,
                        client_name=client_name,
                        client_phone=client_phone,
                        comment=f"Telegram bot booking #{booking.id}",
                        is_test=True,  # Mark as test during testing phase
                    )
                    if yc_result:
                        logger.info(f"✅ YClients booking created: #{yc_result.get('id', '?')}")
                    else:
                        logger.warning("⚠️ YClients booking creation failed")
                else:
                    logger.warning(f"⚠️ YClients: service_id={yc_service_id}, staff_id={yc_staff_id} — skipping")
            except Exception as e:
                logger.error(f"❌ YClients booking error: {e}")

        # Send notification to group
        if notification_service:
            # ВАЖНО: Получаем свежие данные клиента из БД (с актуальным именем и локацией)
            fresh_client = await client_service.get_or_create_client(telegram_id)
            conversation_link = f"tg://openmessage?user_id={user_id}"
            await notification_service.send_booking_confirmed(fresh_client, booking)

        # Upselling: suggest complementary service after booking
        if follow_up_service:
            upsell = follow_up_service.get_upsell_message(service_name)
            if upsell:
                # Delay upsell by 30 seconds for natural flow
                async def _send_upsell(msg_obj, text):
                    await asyncio.sleep(30)
                    await msg_obj.answer(text)
                if last_msg_obj:
                    asyncio.create_task(_send_upsell(last_msg_obj, upsell))


async def main() -> None:
    """Главная функция запуска бота"""
    global client_service, message_service, booking_service, dialog_session_service, notification_service, follow_up_service, msg_buffer

    # Проверка конфигурации
    if not config.validate():
        logger.error("Ошибка конфигурации! Проверьте .env файл")
        return

    # Initialize message buffer (Redis or in-memory fallback)
    msg_buffer = await init_buffer(config.REDIS_URL)

    # Initialize database
    logger.info("Initializing database...")
    db = init_db(config.DATABASE_URL)
    await db.create_tables()  # Create tables if they don't exist

    # Initialize services
    client_service = ClientService(db)
    message_service = MessageService(db)
    booking_service = BookingService(db)
    dialog_session_service = DialogSessionService(db)

    logger.info("✅ Database services initialized")

    # Инициализация бота и диспетчера
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Initialize notification service
    if config.ADMIN_GROUP_CHAT_ID:
        notification_service = NotificationService(bot, config.ADMIN_GROUP_CHAT_ID)
        logger.info(f"✅ Notifications enabled for group {config.ADMIN_GROUP_CHAT_ID}")
    else:
        logger.warning("⚠️ ADMIN_GROUP_CHAT_ID not set - group notifications disabled")

    # Initialize follow-up service
    async def _send_telegram_follow_up(user_id: str, text: str):
        """Send follow-up message via Telegram."""
        try:
            await bot.send_message(chat_id=int(user_id), text=text)
        except Exception as e:
            logger.error(f"Failed to send follow-up to {user_id}: {e}")

    async def _send_telegram_photo(user_id: str, photo_path: str, caption: str):
        """Send follow-up photo via Telegram."""
        try:
            from aiogram.types import FSInputFile
            photo = FSInputFile(photo_path)
            await bot.send_photo(chat_id=int(user_id), photo=photo, caption=caption)
        except Exception as e:
            logger.error(f"Failed to send photo to {user_id}: {e}")
            # Fallback to text-only
            await _send_telegram_follow_up(user_id, caption)

    follow_up_service = FollowUpService(
        send_message=_send_telegram_follow_up,
        notification_service=notification_service,
        send_photo=_send_telegram_photo,
    )
    await follow_up_service.start(check_interval=60)  # Check every 1 min (for 5-min trial follow-up)
    logger.info("Follow-up service started")

    # Initialize YClients service (if not in mock mode)
    global yclients_service
    if not config.MOCK_YCLIENTS and config.YCLIENTS_PARTNER_TOKEN and config.YCLIENTS_USER_TOKEN:
        yclients_service = YClientsService()
        # Test connection
        try:
            staff = await yclients_service.get_staff()
            logger.info(f"✅ YClients connected: {len(staff)} staff members loaded")
        except Exception as e:
            logger.error(f"❌ YClients connection failed: {e}")
            yclients_service = None
    else:
        logger.info("⚠️ YClients in MOCK mode — using mock data")

    # Установка команд меню бота
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать диалог / Показать услуги"),
        BotCommand(command="status", description="Показать статус бронирования"),
        BotCommand(command="clear", description="Сброс истории и контекста"),
    ])

    logger.info("🤖 Crystal Lab Booking Bot запущен!")
    logger.info(f"   Модель: {config.OPENAI_MODEL}")
    logger.info(f"   Database: {config.DATABASE_URL}")
    logger.info(f"   Mock режим: YClients={config.MOCK_YCLIENTS}, WhatsApp={config.MOCK_WHATSAPP}")

    # Запуск обработки входящих обновлений
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        if follow_up_service:
            await follow_up_service.stop()
        if msg_buffer:
            await msg_buffer.close()
        await bot.session.close()
        await db.close()


def start_polling():
    """Запуск бота"""

    logger.info("🚀 Запуск Crystal Lab Booking Bot...")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")


if __name__ == "__main__":
    start_polling()
