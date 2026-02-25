# Crystal Lab Telegram Bot - Testing Guide

**MVP Version**: 1.0
**Дата**: 04.11.2025

---

## 🚀 Quick Start

### 1. Получение Telegram Bot Token

1. Открой Telegram и найди [@BotFather](https://t.me/BotFather)
2. Отправь команду `/newbot`
3. Выбери имя бота (например: `Crystal Lab Booking Bot`)
4. Выбери username (например: `crystal_lab_booking_test_bot`)
5. BotFather отправит тебе **token** вида:
   ```
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567
   ```
6. **Сохрани этот token** - он понадобится для .env файла

### 2. Получение OpenAI API Key

1. Открой [platform.openai.com](https://platform.openai.com)
2. Войди в аккаунт (или зарегистрируйся)
3. Перейди в [API Keys](https://platform.openai.com/api-keys)
4. Нажми **"Create new secret key"**
5. Скопируй ключ вида:
   ```
   sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
6. **Сохрани этот ключ** - он показывается только один раз

> **Важно**: На аккаунте OpenAI должны быть средства (минимум $5 для тестирования)

### 3. Настройка проекта

```bash
# Перейди в директорию проекта
cd /Users/admin/Alina/massage-booking-bot

# Создай виртуальное окружение Python
python3 -m venv .venv

# Активируй виртуальное окружение
source .venv/bin/activate  # macOS/Linux
# ИЛИ
.venv\Scripts\activate  # Windows

# Установи зависимости
pip install -r requirements.txt
```

### 4. Создание .env файла

```bash
# Скопируй пример
cp .env.example .env

# Открой .env в редакторе
nano .env  # или используй любой текстовый редактор
```

Заполни файл своими ключами:

```env
# Telegram Bot Token (получен у @BotFather)
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567

# OpenAI API Key
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o-mini

# Режим отладки
DEBUG=True
LOG_LEVEL=INFO

# Настройки агента
RESPONSE_TIMEOUT=30
MAX_RETRIES=3

# Временно для MVP (позже будет YClients API)
MOCK_YCLIENTS=True

# Временно для MVP (позже будет WhatsApp Business API)
MOCK_WHATSAPP=True
```

### 5. Запуск бота

```bash
# Убедись, что виртуальное окружение активировано
source .venv/bin/activate

# Запусти бота
python run.py
```

Ты должен увидеть:
```
2025-11-04 10:00:00.123 | INFO | Bot started successfully
2025-11-04 10:00:00.456 | INFO | Polling...
```

### 6. Тестирование бота

1. Открой Telegram
2. Найди своего бота по username (например, `@crystal_lab_booking_test_bot`)
3. Нажми **Start**
4. Начни тестирование!

---

## 🧪 Тестовые сценарии

### Сценарий 1: Простое бронирование body massage

**Цель**: Проверить базовый flow бронирования

```
User: /start
Bot: [Welcome message с полным списком услуг]

User: Hi, I want body massage
Bot: [Показывает цены на массажи]

User: 60 minutes
Bot: Could you send your location please?

User: [Отправляет location через Telegram]
Bot: Thank you! What is your villa or apartment number?

User: Villa 25
Bot: [Предлагает доступные слоты]
   Tomorrow 10:00 a.m. 12:00 p.m. 4:00 p.m. 7:30 p.m. are available
   Any suitable for you?

User: 7:30 pm is good
Bot: What is your good name?

User: Sarah
Bot: Thank you dear! Your body massage is booked on [date] at 7:30 pm ✅
```

**Проверить**:
- ✅ Бот запросил локацию ДО предложения слотов
- ✅ Бот использует "dear" в сообщениях
- ✅ Бот подтвердил все детали бронирования

---

### Сценарий 2: Медицинские противопоказания

**Цель**: Проверить обработку медицинской информации

```
User: I want massage but I had cesarean 2 months ago
Bot: Okay dear, thank you for letting me know. I will inform the therapist.
     Could you send your location please?

[Продолжить обычный flow...]
```

**Проверить**:
- ✅ Бот НЕ паникует и НЕ отказывает в услуге
- ✅ Бот благодарит за информацию
- ✅ Бот обещает уведомить мастера
- ✅ Бот продолжает бронирование

**Проверить в логах или базе**:
- ✅ Медицинская информация сохранена в контексте диалога

---

### Сценарий 3: Изменение времени

**Цель**: Проверить гибкость при небольших изменениях

```
User: I booked for 7:30 pm but can we make it 8 pm?
Bot: Let me check the availability for 8:00 PM...
     Yes, 8:00 PM works perfectly! I've updated your booking ✅
```

**Проверить**:
- ✅ Бот НЕ применяет штрафы
- ✅ Бот пытается accommodate изменение
- ✅ Дружелюбный тон

---

### Сценарий 4: Отмена визита

**Цель**: Проверить обработку отмены без негатива

```
User: Sorry I need to cancel tomorrow
Bot: No problem dear! Would you like to reschedule for another day?

User: Not sure yet
Bot: Okay dear, no problem. Just let us know when you're ready 🌹
```

**Проверить**:
- ✅ Бот НЕ обвиняет клиента
- ✅ Предлагает альтернативу (reschedule)
- ✅ Принимает отказ спокойно
- ✅ Использует "dear" и эмодзи

---

### Сценарий 5: Запрос пакета (package)

**Цель**: Проверить upselling и информацию о пакетах

```
User: Do you have any packages?
Bot: Yes dear! We have special packages:

     4 sessions: 1,134 AED (save ~270 AED)
     6 sessions: 2,468 AED
     8 sessions: 2,100 AED (BEST VALUE - save ~840 AED!)
     10 sessions: 3,150 AED (save ~675 AED)

     Valid for 90 days. Would you like to book a package?

User: Yes, 8 sessions
Bot: Great choice dear! The 8-session package is 2,100 AED including VAT.
     How would you like to proceed with payment?
```

**Проверить**:
- ✅ Цены включают +5% VAT
- ✅ Указан срок действия (90 дней)
- ✅ Показана экономия
- ✅ Переход к оплате

---

### Сценарий 6: Вопрос о VAT

**Цель**: Проверить правильную информацию о налогах

```
User: Is cash payment tax-free?
Bot: All payments include +5% VAT as per UAE law.
     This applies to cash, card, and bank transfers.

User: So 350 + 5%?
Bot: Exactly! Body massage 60 min is 350 AED + 17.50 AED VAT = 367.50 AED total.
```

**Проверить**:
- ✅ Бот НЕ говорит "cash tax-free" (старая неверная информация)
- ✅ Бот правильно объясняет 5% VAT на все платежи
- ✅ Бот показывает расчёт

---

### Сценарий 7: Recurring appointments

**Цель**: Проверить поддержку регулярных визитов

```
User: Can I book every Wednesday at 1 pm?
Bot: Absolutely dear! I can set up weekly appointments for you.
     Let's start with this Wednesday at 1:00 PM. Is that okay?

User: Yes
Bot: Perfect! I'll send you a confirmation before each session.
     See you this Wednesday at 1:00 PM ✅
```

**Проверить**:
- ✅ Бот понимает запрос на регулярные визиты
- ✅ Бот начинает с первого визита
- ✅ Бот обещает подтверждать каждый раз

---

### Сценарий 8: Жалоба на мастера (Escalation)

**Цель**: Проверить escalation к администратору

```
User: The therapist last time was not good
Bot: I'm sorry to hear that dear. Let me connect you with our manager
     to discuss this and find the best solution for you.
     They will contact you shortly.
```

**Проверить**:
- ✅ Бот НЕ спорит
- ✅ Бот НЕ защищает мастера
- ✅ Бот escalate к менеджеру
- ✅ Эмпатичный тон

**Важно**: В продакшене это должно:
1. Отправить уведомление администратору
2. Пометить диалог как "требует внимания"
3. Логировать причину escalation

---

### Сценарий 9: "Lost Client" reminder

**Цель**: Проверить автоматические напоминания

**Настройка теста**:
1. Начни бронирование
2. Остановись на этапе выбора слота (НЕ подтверждай)
3. Жди 1 час (или измени время в `dialog_context.py` для теста)

**Ожидаемое поведение**:
```
[Через 1 час после последнего сообщения]
Bot: Hello dear! Just checking in. We have available slots for today.
     Would you still like to book?
```

**Проверить**:
- ✅ Reminder отправлен после 1 часа неактивности
- ✅ Тон дружелюбный (не агрессивный)
- ✅ Предлагает конкретные слоты

---

### Сценарий 10: Команды бота

**Цель**: Проверить все команды

```
User: /start
Bot: [Welcome message]

User: /status
Bot: Your current booking status:
     - Service: Body massage 60 min
     - Date: Tomorrow
     - Time: 7:30 PM
     - Therapist: TBD
     - Status: Confirmed ✅

User: /clear
Bot: Your conversation history has been cleared.
     Type /start to begin a new booking.
```

**Проверить**:
- ✅ `/start` показывает welcome message
- ✅ `/status` показывает текущее бронирование
- ✅ `/clear` очищает контекст диалога

---

## 🐛 Проверка логов

Логи сохраняются в `logs/bot.log`. Для просмотра в реальном времени:

```bash
tail -f logs/bot.log
```

**Что проверять в логах**:

1. **Успешная обработка сообщений**:
   ```
   INFO | User 123456789 sent: "I want massage"
   INFO | AI response generated in 1.2s
   INFO | Response sent to user 123456789
   ```

2. **Сохранение данных**:
   ```
   INFO | Extracted name: Sarah
   INFO | Extracted location: 24.4539, 54.3773
   INFO | Booking status updated: confirmed
   ```

3. **Медицинские заметки**:
   ```
   WARNING | Medical note detected: cesarean 2 months ago
   INFO | Medical note saved to context
   ```

4. **Ошибки**:
   ```
   ERROR | OpenAI API error: Rate limit exceeded
   ERROR | Failed to send message to user 123456789
   ```

---

## 📊 Что отслеживать во время тестирования

### Метрики успешности

| Метрика | Цель | Как проверить |
|---------|------|---------------|
| Completion rate | >80% | Сколько диалогов дошло до confirmed booking |
| Response time | <3s | Время ответа AI (в логах) |
| Medical notes captured | 100% | Все упоминания медицинской информации сохранены |
| Escalation accuracy | 100% | Escalate только в нужных случаях |
| VAT calculation | 100% | Всегда правильно считает +5% VAT |

### Чек-лист по тону голоса

- [ ] Использует "dear" часто (но не в каждом сообщении)
- [ ] Эмодзи умеренно: ✅ 🙌🏼 🌹 🙏🏻
- [ ] Короткие сообщения (2-3 предложения)
- [ ] Никогда не спорит с клиентом
- [ ] При ошибке: "Maybe it was misunderstanding🙈" + решение

### Чек-лист по flow

- [ ] Локация запрашивается ДО слотов
- [ ] Имя запрашивается ПОСЛЕ выбора слота
- [ ] Подтверждение содержит все детали (service, date, time, therapist)
- [ ] День-перед confirmation (11-12 часов до визита)

---

## ❌ Известные ограничения MVP

1. **Mock данные**:
   - Слоты не реальные (всегда одинаковые)
   - YClients API не подключён
   - WhatsApp не подключён

2. **Нет персистентности**:
   - При перезапуске бота вся история теряется
   - Нет базы данных (только in-memory context)

3. **Нет оплаты**:
   - Бот не обрабатывает платежи
   - Только информация о ценах

4. **Telegram только**:
   - WhatsApp и Instagram будут в Phase 2

5. **Нет админ-панели**:
   - Администратор не видит брони
   - Escalation отправляется в логи, а не реальному человеку

---

## 🚀 Следующие шаги после успешного тестирования

1. **Подключить реальную БД** (PostgreSQL):
   - Сохранять все брони
   - Хранить клиентскую информацию
   - Логировать все диалоги

2. **Интегрировать YClients API**:
   - Получать реальные слоты
   - Создавать брони в YClients
   - Синхронизировать статус

3. **Подключить WhatsApp Business API**:
   - Переключить с Telegram на WhatsApp
   - Сохранить всю логику и system prompt

4. **Добавить админ-панель**:
   - Просмотр всех броней
   - Ручная корректировка
   - Real-time уведомления при escalation

5. **Добавить оплату**:
   - Интеграция с платёжным шлюзом
   - Автоматические чеки
   - Tracking оплат

6. **Analytics**:
   - Conversion rate
   - Most popular services
   - Peak booking times
   - Lost client analysis

---

## 📞 Troubleshooting

### Бот не запускается

**Ошибка**:
```
ERROR: TELEGRAM_BOT_TOKEN not found in environment
```

**Решение**:
1. Проверь, что `.env` файл существует
2. Проверь, что token указан правильно (без лишних пробелов)
3. Убедись, что виртуальное окружение активировано

---

### Бот не отвечает

**Ошибка**:
```
ERROR: OpenAI API error: Incorrect API key provided
```

**Решение**:
1. Проверь `OPENAI_API_KEY` в `.env`
2. Убедись, что на аккаунте OpenAI есть средства
3. Проверь, что ключ не истёк

---

### Медленные ответы (>10 секунд)

**Возможные причины**:
1. Медленный интернет
2. OpenAI API перегружен
3. Слишком длинная история диалога

**Решение**:
- Используй более быструю модель: `OPENAI_MODEL=gpt-4o-mini`
- Уменьши `MAX_RETRIES` в `.env`

---

### Бот отвечает не в характере

**Решение**:
1. Проверь `system_prompt` в `agents/booking_agent.py`
2. Убедись, что используется правильная модель (не старая GPT-3)
3. Попробуй очистить контекст: `/clear`

---

## ✅ Финальный чек-лист перед запуском

- [ ] Виртуальное окружение создано и активировано
- [ ] Все зависимости установлены (`requirements.txt`)
- [ ] `.env` файл создан и заполнен
- [ ] Telegram bot token получен у @BotFather
- [ ] OpenAI API key получен и на аккаунте есть средства
- [ ] Бот успешно запускается без ошибок
- [ ] Бот отвечает на `/start`
- [ ] Логи пишутся в `logs/bot.log`

**После успешного прохождения всех тестов, бот готов к демонстрации клиенту! 🎉**

---

**Удачного тестирования!**
