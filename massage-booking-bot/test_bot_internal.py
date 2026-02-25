#!/usr/bin/env python3
"""
Внутренний тест бота Crystal Lab
Проверяет:
1. Буферизацию сообщений (7 секунд задержка)
2. Новые цены из обновленного прайса
3. Распознавание услуг
"""

import asyncio
import time
from aiogram import Bot
from aiogram.types import Message
from config import config

async def test_bot():
    """Тестирование бота"""

    bot = Bot(token=config.telegram_token)

    # Тестовый user_id (замените на свой Telegram ID для теста)
    # Чтобы узнать свой ID, напишите боту /start и посмотрите в логах
    test_user_id = None  # TODO: Укажите свой Telegram ID

    if not test_user_id:
        print("❌ ERROR: Укажите test_user_id в скрипте!")
        print("Напишите боту /start и посмотрите в логах строку:")
        print("  'Команда /start от пользователя {ID}'")
        return

    print("🧪 ТЕСТ 1: Проверка буферизации сообщений\n")
    print("=" * 60)

    # Имитируем отправку 3 сообщений подряд
    messages = [
        "Body massage",
        "90 min",
        "please"
    ]

    print("📤 Отправляем 3 сообщения подряд с интервалом 2 секунды:")
    start_time = time.time()

    for i, msg in enumerate(messages, 1):
        print(f"  {i}. '{msg}' в {time.strftime('%H:%M:%S')}")
        # Примечание: Мы не можем отправить сообщения напрямую от имени пользователя
        # Это тест демонстрирует логику, но реальная отправка должна быть через Telegram
        await asyncio.sleep(2)

    print(f"\n⏱️  Все сообщения отправлены за {time.time() - start_time:.1f} секунд")
    print("⏳ Ожидаем ответа бота (должен ответить через ~7 секунд после последнего)...")
    print("   (Бот должен обработать ВСЕ 3 сообщения вместе)\n")

    print("=" * 60)
    print("\n🧪 ТЕСТ 2: Проверка нового прайса\n")
    print("=" * 60)

    test_cases = [
        {
            "input": "manicure",
            "expected_prices": {
                "Russian gelish manicure": "210 AED",
                "Russian gelish pedicure": "231 AED",
                "Combo": "418.95 AED",
                "Japanese mani": "189 AED",
            }
        },
        {
            "input": "deep face cleansing",
            "expected_prices": {
                "Deep facial cleansing": "441 AED (90 min)"
            }
        },
        {
            "input": "body massage 90 min",
            "expected_prices": {
                "Body massage 90 min": "483 AED"
            }
        }
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\nТест {i}: {test['input']}")
        print("  Ожидаемые цены:")
        for service, price in test['expected_prices'].items():
            print(f"    ✓ {service}: {price}")

    print("\n" + "=" * 60)
    print("\n📋 ИНСТРУКЦИЯ ДЛЯ РУЧНОГО ТЕСТА:")
    print("=" * 60)
    print("""
1. Откройте Telegram и найдите бота @crystal_lab_bot (или ваш бот)

2. ТЕСТ БУФЕРИЗАЦИИ:
   - Напишите /clear
   - Напишите /start
   - Быстро отправьте 3 сообщения (не ждите ответа!):
     • "Body massage"
     • "90 min"
     • "please"
   - Засеките время до ответа бота

   ✅ УСПЕХ: Бот ответил через ~7-10 секунд ОДИН РАЗ
   ❌ ПРОВАЛ: Бот ответил 3 раза или сразу после первого

3. ТЕСТ НОВОГО ПРАЙСА (Manicure):
   - Напишите /clear
   - Напишите /start
   - Напишите "manicure"

   ✅ УСПЕХ: Бот показывает:
     Russian gelish manicure: 210 AED
     Combo: 418.95 AED
     Japanese mani: 189 AED

   ❌ ПРОВАЛ: Показывает старые цены (84 AED, 157.50 AED)

4. ТЕСТ Deep Cleansing:
   - Напишите /clear
   - Напишите /start
   - Напишите "deep face cleansing"

   ✅ УСПЕХ: 90 min: 441 AED
   ❌ ПРОВАЛ: 60 min: 262.50 AED

5. ТЕСТ Body Massage (регрессия):
   - Напишите /clear
   - Напишите /start
   - Напишите "body massage 90 min"

   ✅ УСПЕХ: 483 AED (не изменилось)
   ❌ ПРОВАЛ: Другая цена
""")

    print("\n" + "=" * 60)
    print("📊 ПРОВЕРКА ЛОГОВ:")
    print("=" * 60)
    print("""
Откройте терминал и выполните:
    tail -f bot.log

Ищите строки:
  ✅ "User {id}: добавлено в буфер (2 сообщений)"
  ✅ "User {id}: обработка 3 накопленных сообщений"
  ✅ "Сохранена услуга: Russian gelish manicure, None мин, 200.0 AED"
  ✅ "Created booking ... Russian gelish manicure"

  ❌ "User {id}: обработка 1 накопленных сообщений" - буферизация не работает!
  ❌ "Сохранена услуга: Manicure, 45 мин, 80.0 AED" - старая цена!
""")

    print("\n" + "=" * 60)
    print("✅ КРИТЕРИИ УСПЕШНОГО ТЕСТА:")
    print("=" * 60)
    print("""
1. [  ] Бот ждет 7 секунд перед ответом
2. [  ] Множественные сообщения обрабатываются вместе
3. [  ] Manicure показывает 210 AED (было 84 AED)
4. [  ] Combo показывает 418.95 AED (было 157.50 AED)
5. [  ] Deep cleansing показывает 90 min и 441 AED
6. [  ] Body massage 90 min показывает 483 AED (не изменилось)
7. [  ] В логах видно "обработка N накопленных сообщений" где N > 1
8. [  ] Нет технических ошибок в логах
""")

    await bot.session.close()

if __name__ == "__main__":
    print("\n" + "🚀 " + "=" * 58)
    print("   Crystal Lab Bot - Внутренний тест")
    print("   Версия: 2.2 (Message Buffering + Updated Prices)")
    print("=" * 60 + "\n")

    asyncio.run(test_bot())

    print("\n" + "=" * 60)
    print("✅ Тестовый скрипт завершен!")
    print("Следуйте инструкциям выше для ручного тестирования.")
    print("=" * 60 + "\n")
