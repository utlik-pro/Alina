# База данных и уведомления в Telegram группу

## 🎯 Что добавлено

### 1. **База данных SQLite**
Все клиенты, сообщения и бронирования теперь сохраняются в БД!

**Таблицы:**
- `clients` - Клиенты (имя, телефон, локация, медицинские заметки)
- `messages` - История всех сообщений
- `bookings` - Бронирования с ценами и статусом
- `dialog_sessions` - Сессии диалогов для tracking контекста
- `packages` - Пакеты услуг (4/8/10 сеансов)

### 2. **Уведомления в Telegram группу**
Бот автоматически отправляет уведомления в админ-группу о:
- 🆕 Новых клиентах
- 📋 Новых заявках на бронирование
- ✅ Подтвержденных бронированиях
- ❌ Отменах
- ⚠️ "Потерянных" клиентах (нет ответа >1 часа)
- ⚕️ Медицинских противопоказаниях

---

## 🚀 Быстрый старт

### Шаг 1: Создать Telegram группу для уведомлений

1. **Создай новую группу в Telegram**
   - Назови её, например: "Crystal Lab - Заявки"

2. **Добавь своего бота в группу**
   - Найди бота по username (который создавал через @BotFather)
   - Добавь как администратора группы

3. **Получи Chat ID группы**
   - Добавь бота [@userinfobot](https://t.me/userinfobot) в группу
   - Он пришлет сообщение с `chat_id`
   - Формат будет: `-1001234567890` (начинается с минуса!)

4. **Скопируй Chat ID** и вставь в `.env`:
   ```env
   ADMIN_GROUP_CHAT_ID=-1001234567890
   ```

### Шаг 2: База данных уже готова!

База данных была автоматически создана когда ты запустил:
```bash
.venv/bin/python scripts/init_db.py
```

Файл базы данных: `crystal_lab.db` (в корне проекта)

---

## 📊 Структура базы данных

### Таблица `clients`

```sql
CREATE TABLE clients (
    id INTEGER PRIMARY KEY,
    telegram_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255),
    phone VARCHAR(50),
    location_latitude FLOAT,
    location_longitude FLOAT,
    location_details VARCHAR(500),  -- Villa/Apartment
    medical_notes TEXT,
    preferred_therapist VARCHAR(255),
    total_bookings INTEGER DEFAULT 0,
    is_vip BOOLEAN DEFAULT FALSE,
    tags JSON,  -- ["regular", "package_buyer", etc.]
    created_at DATETIME,
    updated_at DATETIME
);
```

### Таблица `messages`

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id),
    role VARCHAR(20),  -- "user" or "assistant"
    content TEXT NOT NULL,
    telegram_message_id INTEGER,
    created_at DATETIME
);
```

### Таблица `bookings`

```sql
CREATE TABLE bookings (
    id INTEGER PRIMARY KEY,
    client_id INTEGER REFERENCES clients(id),
    service_name VARCHAR(255) NOT NULL,
    duration INTEGER,  -- minutes
    booking_date DATETIME,
    therapist_name VARCHAR(255),
    base_price FLOAT,
    vat_rate FLOAT DEFAULT 0.05,
    vat_amount FLOAT,
    total_price FLOAT,
    status VARCHAR(50) DEFAULT 'draft',
    -- draft, confirmed, in_progress, completed, cancelled
    notes TEXT,
    cancellation_reason VARCHAR(500),
    yclients_appointment_id VARCHAR(255),
    created_at DATETIME,
    updated_at DATETIME,
    completed_at DATETIME,
    cancelled_at DATETIME
);
```

### Таблица `dialog_sessions`

```sql
CREATE TABLE dialog_sessions (
    id INTEGER PRIMARY KEY,
    telegram_id VARCHAR(50) NOT NULL,
    state VARCHAR(50) DEFAULT 'initial',
    -- initial, consulting, collecting_location, selecting_slot, confirming, completed
    context_data JSON,  -- Полный контекст диалога
    is_active BOOLEAN DEFAULT TRUE,
    is_lost_client BOOLEAN DEFAULT FALSE,
    started_at DATETIME,
    last_activity_at DATETIME,
    ended_at DATETIME
);
```

---

## 🔧 Использование в коде

### Работа с клиентами

```python
from database import init_db, ClientService, MessageService

# Initialize database
db = init_db(config.DATABASE_URL)

# Create services
client_service = ClientService(db)
message_service = MessageService(db)

# Get or create client
client = await client_service.get_or_create_client(telegram_id="123456789")

# Update client info
await client_service.update_client(
    telegram_id="123456789",
    name="Sarah",
    location_latitude=24.4539,
    location_longitude=54.3773,
    location_details="Villa 25, Khalifa City",
    medical_notes="Cesarean 2 months ago",
)

# Get client statistics
stats = await client_service.get_client_stats(telegram_id="123456789")
# {
#     "client_id": 1,
#     "name": "Sarah",
#     "total_bookings": 5,
#     "completed_bookings": 4,
#     "total_spent": 1470.0,
#     "is_vip": False,
# }
```

### Сохранение сообщений

```python
# Save user message
await message_service.save_message(
    telegram_id="123456789",
    role="user",
    content="I want body massage",
)

# Save bot response
await message_service.save_message(
    telegram_id="123456789",
    role="assistant",
    content="Body massage 60 min: 350 AED + 5% VAT = 367.50 AED",
)

# Get recent messages (last 20)
messages = await message_service.get_recent_messages(telegram_id="123456789")

# Get conversation history for AI
history = await message_service.get_conversation_history(telegram_id="123456789")
# [
#     {"role": "user", "content": "I want body massage"},
#     {"role": "assistant", "content": "Body massage 60 min: ..."},
# ]
```

### Уведомления в группу

```python
from services.notifications import NotificationService

# Initialize notification service
notification_service = NotificationService(
    bot=bot,
    group_chat_id=config.ADMIN_GROUP_CHAT_ID,
)

# Send new client notification
await notification_service.send_new_client(client)

# Send booking request notification
await notification_service.send_booking_request(
    client=client,
    booking=booking,
    conversation_link=f"tg://openmessage?user_id={client.telegram_id}",
)

# Send medical note alert
await notification_service.send_medical_note_alert(
    client=client,
    note="Client mentioned cesarean 2 months ago",
)

# Send lost client alert
await notification_service.send_lost_client_alert(
    client=client,
    last_message="I want massage",
)
```

---

## 📋 Примеры уведомлений в группе

### Новый клиент
```
🆕 Новый клиент!

👤 Telegram ID: 123456789
📅 Зарегистрирован: 04.11.2025 17:30

Ожидаем первое бронирование...
```

### Новая заявка
```
📋 Новая заявка на бронирование!

👤 Sarah
📞 Telegram: @sarah_uae

🛎️ Услуга: Body massage
⏱️ Длительность: 60 мин
📅 Дата: 05.11.2025 19:00
💰 367.50 AED (включая 5% VAT)

📍 Локация на карте
🏠 Villa 25, Khalifa City

📊 Статус: Подтверждено ✅
```

### Медицинское предупреждение
```
⚕️ ВАЖНО: Медицинская информация!

👤 Sarah
📞 Telegram: @sarah_uae

Клиент упомянул медицинское противопоказание:
💬 "I had cesarean 2 months ago"

⚠️ Необходимо проинформировать мастера перед визитом!
```

### Потерянный клиент
```
⚠️ Потенциально потерянный клиент!

👤 Sarah
📞 Telegram: @sarah_uae

Более 1 часа нет активности в диалоге.

Последнее сообщение клиента:
💬 "I want body massage"

Рекомендуется связаться с клиентом!
```

---

## 🛠️ Полезные команды

### Проверить базу данных

```bash
# Запустить SQLite CLI
sqlite3 crystal_lab.db

# Посмотреть все таблицы
.tables

# Посмотреть клиентов
SELECT * FROM clients;

# Посмотреть последние сообщения
SELECT * FROM messages ORDER BY created_at DESC LIMIT 10;

# Посмотреть все бронирования
SELECT c.name, b.service_name, b.status, b.total_price
FROM bookings b
JOIN clients c ON b.client_id = c.id;

# Выйти
.quit
```

### Сброс базы данных (осторожно!)

```bash
# Удалить файл БД
rm crystal_lab.db

# Создать заново
.venv/bin/python scripts/init_db.py
```

---

## 🔒 Безопасность

1. **Не коммитить** `crystal_lab.db` в git (уже в .gitignore)
2. **Не делиться** Chat ID группы публично
3. **Бэкапить БД** регулярно:
   ```bash
   cp crystal_lab.db backups/crystal_lab_$(date +%Y%m%d_%H%M%S).db
   ```

---

## 📈 Следующие шаги

### Планы на будущее:

1. **Миграция на PostgreSQL** (для production)
2. **Админ-панель** для просмотра броней
3. **Аналитика** (dashboard с метриками)
4. **Автоматические бэкапы** БД
5. **Интеграция с YClients** (sync в обе стороны)

---

## ❓ FAQ

**Q: Где хранятся данные?**
A: В файле `crystal_lab.db` (SQLite) в корне проекта. Для production рекомендуется PostgreSQL.

**Q: Как посмотреть все сообщения клиента?**
A:
```python
messages = await message_service.get_recent_messages(telegram_id="123456789", limit=100)
for msg in messages:
    print(f"[{msg.role}] {msg.content}")
```

**Q: Бот не отправляет уведомления в группу**
A: Проверь:
1. ADMIN_GROUP_CHAT_ID установлен в .env
2. Бот добавлен в группу как администратор
3. Chat ID начинается с минуса (для групп)

**Q: Как получить Chat ID группы?**
A: Добавь бота [@userinfobot](https://t.me/userinfobot) в группу, он покажет chat_id.

**Q: Можно ли использовать несколько групп?**
A: Пока нет, но можно легко добавить. Создай issue если нужно.

---

**База данных и уведомления готовы к использованию! 🎉**
