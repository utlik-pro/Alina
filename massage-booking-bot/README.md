# Crystal Lab Booking Bot - Telegram MVP

Telegram бот для автоматизации бронирования массажных услуг Crystal Lab в Абу-Даби.

## 🎯 Цель MVP

Создать работающий прототип AI-агента для:
1. ✅ Консультации клиентов по услугам
2. ✅ Сбора информации (имя, локация, предпочтения)
3. ✅ Предложения слотов для бронирования
4. ✅ Обработки медицинских противопоказаний
5. ✅ Отслеживания "потеряшек" (lost clients)

После тестирования → подключение к WhatsApp Business API и YClients.

## 📊 Основано на реальных данных

Агент обучен на анализе **5 реальных WhatsApp чатов** (30+ успешных бронирований):
- Тон голоса и стиль коммуникации
- Поток бронирования (локация → слоты → подтверждение)
- Обработка edge cases (отмены, изменения мастера, медицинские заметки)
- Upselling пакетов после первого сеанса

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
cd massage-booking-bot
python3 -m venv .venv
source .venv/bin/activate  # На Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Настройка переменных окружения

Скопируйте `.env.example` в `.env`:

```bash
cp .env.example .env
```

Заполните:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

**Как получить токены:**

- **Telegram Bot Token**:
  1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
  2. Отправьте `/newbot`
  3. Следуйте инструкциям
  4. Скопируйте токен

- **OpenAI API Key**:
  1. Зайдите на [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
  2. Создайте новый ключ
  3. Скопируйте (ключ показывается только один раз!)

### 3. Запуск бота

```bash
python run.py
```

Вы увидите:
```
🤖 Crystal Lab Booking Bot запущен!
   Модель: gpt-4o-mini
   Mock режим: YClients=True, WhatsApp=True
```

### 4. Тестирование

Откройте вашего бота в Telegram и отправьте `/start`

## 📋 Доступные команды

- `/start` - Начать диалог / Показать список услуг
- `/status` - Показать текущее состояние бронирования
- `/clear` - Сброс истории и начало нового диалога

## 🗂️ Структура проекта

```
massage-booking-bot/
├── bot.py                  # Главный файл бота (handlers)
├── config.py               # Конфигурация и переменные окружения
├── dialog_context.py       # Менеджер контекста диалогов
├── requirements.txt        # Python зависимости
├── run.py                  # Скрипт запуска
├── .env                    # Переменные окружения (НЕ комит в git!)
├── .env.example            # Пример переменных окружения
├── agents/
│   └── booking_agent.py    # AI агент с system prompt
├── logs/                   # Логи бота
└── docs/                   # Документация
    ├── TESTING_GUIDE.md    # 📘 Полный гайд по тестированию
    └── PRICE_LIST.md       # 💰 Актуальный прайс-лист
```

## 📚 Документация

- **[TESTING_GUIDE.md](docs/TESTING_GUIDE.md)** - Подробный гайд по настройке и тестированию бота
  - Получение токенов
  - 10 готовых тестовых сценариев
  - Проверка логов
  - Troubleshooting

- **[PRICE_LIST.md](docs/PRICE_LIST.md)** - Актуальный прайс-лист Crystal Lab
  - Все услуги с ценами (включая VAT)
  - Пакеты и скидки
  - Политика отмен
  - Медицинские противопоказания

## 🎭 Как работает AI-агент

### System Prompt

Агент следует детальному промпту, основанному на реальных WhatsApp диалогах:

1. **Личность**: Дружелюбный админ Crystal Lab, использует "dear", эмодзи умеренно
2. **Услуги**: Полный прайс-лист с VAT (+5% на все)
3. **Поток бронирования**: Строгая последовательность шагов
4. **Критичные правила**: Медицинские заметки, изменение мастера, recurring appointments
5. **Tone of Voice**: Короткие сообщения, позитив, never argue

### Контекст диалога

Бот сохраняет:
- Историю последних 20 сообщений
- Данные клиента (имя, телефон, локация, медицинские заметки)
- Данные бронирования (услуга, дата, время, мастер, статус)
- Состояние диалога (consulting/collecting_location/selecting_slot/etc.)

### "Потеряшки" (Lost Clients)

Бот автоматически отслеживает клиентов, которые:
- Не отвечают > 1 часа
- Имеют активный диалог (> 2 сообщений)
- Не завершили бронирование

Позже: автоматические напоминания через 1 час и на следующий день.

## 🔌 Следующие шаги (после тестирования MVP)

### Phase 2: WhatsApp Integration
- [ ] Подключить WhatsApp Business API
- [ ] Перенести всю логику из Telegram в WhatsApp
- [ ] Webhook для входящих сообщений

### Phase 3: YClients Integration
- [ ] API для проверки доступности мастеров
- [ ] Создание карточек клиентов
- [ ] Создание бронирований
- [ ] Синхронизация статусов

### Phase 4: Advanced Features
- [ ] Recurring appointments (автоматическое бронирование)
- [ ] Автоматические напоминания за день
- [ ] Upselling пакетов
- [ ] Сбор отзывов после сеанса

## 🧪 Тестовые сценарии

### Сценарий 1: Простое бронирование

```
User: Hi, I want body massage
Bot: [Показывает цены и опции]
User: 60 minutes
Bot: Could you send your location please?
User: [Отправляет location]
Bot: Apartment or villa number?
User: Villa 25
Bot: [Предлагает слоты]
User: 7pm tomorrow
Bot: What is your good name?
User: Sara
Bot: Your body massage is booked on [date] at 7:00 p.m. with Svetlana✅
```

### Сценарий 2: Медицинские противопоказания

```
User: I want massage but I had cesarean 2 months ago
Bot: Okay dear, thank you. I will inform the therapist
[Сохраняет медицинскую заметку]
[Предлагает подходящие техники]
```

### Сценарий 3: Изменение мастера

```
User: Not Oksana please, my body was hurting after
Bot: [Предлагает 3 альтернативы с разным временем]
Bot: Any suitable for you?
```

## 📊 Метрики для отслеживания

- Количество начатых диалогов
- Конверсия в бронирование (%)
- Количество "потеряшек"
- Среднее время до бронирования
- Количество отмен/переносов

## ⚠️ Известные ограничения MVP

1. **Mock данные**: Нет реальной интеграции с YClients
2. **Нет платежей**: Пока не обрабатываются
3. **Нет уведомлений**: Не отправляются подтверждения мастерам/водителям
4. **Только Telegram**: WhatsApp будет в Phase 2

## 🐛 Отладка

Включите DEBUG режим в `.env`:

```env
DEBUG=True
LOG_LEVEL=DEBUG
```

Логи сохраняются в `logs/` директории.

## 💡 Полезные ссылки

- [Aiogram документация](https://docs.aiogram.dev/)
- [OpenAI API](https://platform.openai.com/docs)
- [WhatsApp Business API](https://developers.facebook.com/docs/whatsapp)
- [YClients API](https://yclients.docs.apiary.io/)

## 📝 TODO

- [ ] Добавить unit тесты
- [ ] Добавить интеграционные тесты с mock GPT
- [ ] Создать admin panel для просмотра диалогов
- [ ] Добавить A/B тестирование разных промптов
- [ ] Мультиязычность (английский + русский)

---

**Создано**: 2025-11-04
**Статус**: MVP Ready for Testing
**Следующая версия**: WhatsApp Integration
