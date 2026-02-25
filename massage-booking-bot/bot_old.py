"""Crystal Lab Booking Bot - Telegram MVP"""

import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BotCommand
from aiogram.filters import CommandStart, Command
from loguru import logger

from config import config
from dialog_context import dialog_manager
from agents.booking_agent import BookingAgent

# Инициализация роутера
router = Router()

# Инициализация агента
booking_agent = BookingAgent()


@router.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """Обработчик команды /start"""

    user_id = message.from_user.id
    logger.info(f"Команда /start от пользователя {user_id}")

    # Приветственное сообщение (основано на реальных WhatsApp чатах)
    greeting = """Welcome to Crystal lab home service🙌

Certified Russian technicians and free transportation to your home 🏠
Abudhabi and Alain

We can offer you a lot of beauty services on offer price 🌹

-Body massage different techniques
-Face massage
-Deep face cleansing
-Manicure and pedicure
-Eyelashes extension
-Eyebrow lamination and eyelash lifting

What services are you interested in? We will give you all the details 🌹"""

    await message.answer(greeting)

    # Сохраняем в контекст
    dialog_manager.add_user_message(user_id, "/start")
    dialog_manager.add_bot_response(user_id, greeting)
    dialog_manager.update_state(user_id, "consulting")


@router.message(Command("clear"))
async def command_clear_handler(message: Message) -> None:
    """Обработчик команды /clear - очистка истории диалога"""

    user_id = message.from_user.id
    logger.info(f"Команда /clear от пользователя {user_id}")

    # Очищаем контекст диалога
    dialog_manager.clear_context(user_id)

    await message.answer("История диалога очищена. Можете начать новый разговор! 🌹")
    logger.info(f"Контекст пользователя {user_id} очищен")


@router.message(Command("status"))
async def command_status_handler(message: Message) -> None:
    """Обработчик команды /status - показать текущее состояние бронирования"""

    user_id = message.from_user.id
    context = dialog_manager.get_context_for_agent(user_id)

    client_data = context.get("client_data", {})
    booking_data = context.get("booking_data", {})
    state = context.get("state", "initial")

    status_text = f"""📊 Статус вашего бронирования:

Состояние: {state}
Имя: {client_data.get('name') or 'не указано'}
Локация: {client_data.get('location') or 'не указана'}
Услуга: {booking_data.get('service_type') or 'не выбрана'}
Дата/время: {booking_data.get('date') or 'не выбрано'} {booking_data.get('time') or ''}
Статус брони: {booking_data.get('status', 'draft')}"""

    await message.answer(status_text)


@router.message(F.location)
async def handle_location(message: Message) -> None:
    """Обработчик локации"""

    user_id = message.from_user.id
    latitude = message.location.latitude
    longitude = message.location.longitude

    logger.info(f"Получена локация от {user_id}: {latitude}, {longitude}")

    # Сохраняем локацию
    dialog_manager.update_client_data(user_id, "location", f"{latitude},{longitude}")
    dialog_manager.add_user_message(user_id, f"[Отправлена локация: {latitude}, {longitude}]")

    # Ответ бота
    response = "Thank you dear! Could you also share your apartment or villa number please?"

    await message.answer(response)
    dialog_manager.add_bot_response(user_id, response)
    dialog_manager.update_state(user_id, "location_received")


@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Обработчик фото"""

    user_id = message.from_user.id
    logger.info(f"Получено фото от {user_id}")

    # Добавляем в историю
    dialog_manager.add_user_message(user_id, "[Клиент прислал фото]")

    response = "Thank you for the photo! I will share it with our specialist. 📸"

    await message.answer(response)
    dialog_manager.add_bot_response(user_id, response)


@router.message(F.text)
async def handle_message(message: Message) -> None:
    """Обработчик текстовых сообщений"""

    user_id = message.from_user.id
    user_message = message.text

    logger.info(f"Сообщение от {user_id}: {user_message}")

    # Добавляем сообщение в историю
    dialog_manager.add_user_message(user_id, user_message)

    # Получаем контекст
    context = dialog_manager.get_context_for_agent(user_id)

    try:
        # Обрабатываем через AI агента
        response = await booking_agent.process_message(user_message, context)

        # Отправляем ответ
        await message.answer(response)

        # Сохраняем ответ в историю
        dialog_manager.add_bot_response(user_id, response)

        # Пытаемся извлечь данные из ответа и сообщения
        await _extract_and_save_data(user_id, user_message, response, context)

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения от {user_id}: {e}")
        await message.answer("Извините, произошла техническая ошибка. Попробуйте еще раз.")


async def _extract_and_save_data(user_id: int, user_message: str, bot_response: str, context: dict) -> None:
    """Извлечь и сохранить данные из диалога"""

    # Простая эвристика для извлечения данных
    # TODO: Можно улучшить с помощью NER или регулярок

    # Извлекаем имя если бот спрашивает "What is your good name?"
    if "name" in bot_response.lower() and context.get("state") == "consulting":
        dialog_manager.update_client_data(user_id, "name", user_message.strip())
        logger.info(f"Извлечено имя: {user_message.strip()}")

    # Извлекаем детали локации (villa/apartment number)
    if context.get("state") == "location_received" and any(word in user_message.lower() for word in ["villa", "apartment", "apt", "flat"]):
        dialog_manager.update_client_data(user_id, "location_details", user_message.strip())
        dialog_manager.update_state(user_id, "selecting_slot")
        logger.info(f"Извлечены детали локации: {user_message.strip()}")

    # Извлекаем медицинские заметки
    medical_keywords = ["cesarean", "surgery", "operation", "birth", "pregnant", "pain", "bleeding", "medical"]
    if any(keyword in user_message.lower() for keyword in medical_keywords):
        dialog_manager.update_client_data(user_id, "medical_note", user_message.strip())
        logger.warning(f"⚕️ Медицинская заметка: {user_message.strip()}")

    # Определяем состояние диалога
    if "booked" in bot_response.lower() and "✅" in bot_response:
        dialog_manager.update_booking_data(user_id, "status", "confirmed")
        dialog_manager.update_state(user_id, "completed")
        logger.info(f"✅ Бронирование подтверждено для {user_id}")


async def main() -> None:
    """Главная функция запуска бота"""

    # Проверка конфигурации
    if not config.validate():
        logger.error("Ошибка конфигурации! Проверьте .env файл")
        return

    # Инициализация бота и диспетчера
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Установка команд меню бота
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать диалог / Показать услуги"),
        BotCommand(command="status", description="Показать статус бронирования"),
        BotCommand(command="clear", description="Сброс истории и контекста"),
    ])

    logger.info("🤖 Crystal Lab Booking Bot запущен!")
    logger.info(f"   Модель: {config.OPENAI_MODEL}")
    logger.info(f"   Mock режим: YClients={config.MOCK_YCLIENTS}, WhatsApp={config.MOCK_WHATSAPP}")

    # Запуск обработки входящих обновлений
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.session.close()


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
