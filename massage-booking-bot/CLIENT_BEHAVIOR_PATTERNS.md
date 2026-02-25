# 🎭 Паттерны поведения реальных клиентов Crystal Lab

## 🚨 КРИТИЧЕСКОЕ НАБЛЮДЕНИЕ: Клиенты не отвечают линейно!

### ❌ Что ожидает бот (линейный флоу):
```
Бот: "Which duration would you like?"
Клиент: "90 min please"
Бот: "Could you send your location?"
Клиент: [Location]
Бот: "What is your villa number?"
Клиент: "villa 25"
```

### ✅ Что делают РЕАЛЬНЫЕ клиенты:

---

## 📋 ПАТТЕРН 1: Множественные сообщения подряд

### Пример 1: Jennifer
```
Менеджер: "When and what time is preferable for you?"
Клиент: "Maybe 19th feb dear"          ← Первое сообщение
Клиент: "Aroun 11"                     ← Второе сообщение (через 20 сек)
Клиент: "Its 1 hr rite?"               ← Третье сообщение (еще через 18 сек)
```

**Проблема для бота:** Если бот отвечает после первого сообщения, второе и третье перебивают его!

### Пример 2: Fatima - изменение решения
```
Менеджер: "Do you need body massage or face?"
Менеджер: "Or both?"
Клиент: "Body"                         ← Первое решение
Клиент: "Both"                         ← Изменила решение через 4 секунды!
Клиент: "Its fine with with me"        ← Подтверждение
```

### Пример 3: Fatima - комплексное расписание
```
Клиент: "As agreed with therapist i'll do Sunday at morning"
Клиент: "Tuesday at 5 pm"
Клиент: "Thursday at 5 pm"
Клиент: "Or this week i can do morning"
```
**4 сообщения подряд с разными вариантами!**

---

## 📋 ПАТТЕРН 2: Дополнительные вопросы во время бронирования

### Пример 1: Jennifer - вопрос после согласия
```
Бот: "Your face massage is booked for 19 February at 11am 🌹"
Клиент: "Thx dear n mask do i need to.decide now???"
```
**Сразу после подтверждения задаёт новый вопрос!**

### Пример 2: Jennifer - вопрос во время выбора
```
Менеджер: [Объясняет разницу между массажами]
Клиент: "Ok dear"
Клиент: "Ok n u can do home service rite?"  ← Задаёт вопрос вместо выбора
```

### Пример 3: Jennifer - вопрос о длительности
```
Клиент: "Maybe 19th feb dear"
Клиент: "Aroun 11"
Клиент: "Its 1 hr rite?"  ← Спрашивает о длительности, хотя не просили
```

---

## 📋 ПАТТЕРН 3: Комбинированные ответы (всё сразу)

### Пример 1: Jennifer - имя + локация
```
Менеджер: "Could you send your name and location please"
Клиент: "Jennifer Leslie, MBZ sector 10"  ← Имя + текстовая локация
[Потом отдельно GPS]
```

### Пример 2: Fatima - локация сразу 3 способами
```
Клиент: [GPS координаты]
Клиент: "Villa 20"
Клиент: [Фото виллы]
```
**Всё за 1 секунду, 3 сообщения!**

---

## 📋 ПАТТЕРН 4: Отложенные ответы и забывчивость

### Пример: Fatima - через 2 часа после вопроса
```
[20/10/2024, 4:28:15 PM] Менеджер: "What is your second name?"
...
[20/10/2024, 4:28:59 PM] Клиент: "Al hammadi"  ← Ответ через 44 секунды
```

Это быстро, но бывает клиенты отвечают через часы:
```
[7/2/2025, 2:28:22 PM] Клиент: "Hi dear any chance u hv apmt for 10th feb?"
[7/2/2025, 2:28:46 PM] Менеджер: "Good afternoon dear"
[7/2/2025, 2:28:49 PM] Менеджер: "What time is preferable for"
[7/2/2025, 2:29:05 PM] Клиент: "10.30am or 11am?"  ← 16 секунд, но могло быть часами
```

---

## 📋 ПАТТЕРН 5: Изменение темы или приоритета

### Пример 1: Mariam - забыла упомянуть маску
```
[18/6/2025, 12:24:37 AM] Клиент: "I want to take the package please"
[18/6/2025, 12:25:34 AM] Клиент: "How much is the package"
[18/6/2025, 12:25:53 AM] Менеджер: "Today ur first session"
[18/6/2025, 12:26:05 AM] Менеджер: "And alginate mask right?"
[18/6/2025, 12:26:23 AM] Клиент: "Not sure of the mask name"
```

### Пример 2: Fatima - хочет перенести
```
[22/10/2024, 5:29:29 PM] Клиент: "dear what time is available for thursday rather than 5 pm"
```
**Во время подтверждения бронирования сразу просит изменить!**

---

## 🎯 КРИТИЧЕСКИЕ ВЫВОДЫ ДЛЯ БОТА:

### 1. ⏰ **Бот должен ЖДАТЬ перед ответом**

**Проблема:** Клиент отправляет 3-4 сообщения подряд за 10-30 секунд.

**Решение:** Бот должен:
- Подождать **5-10 секунд** после получения сообщения
- Проверить, есть ли ещё сообщения от клиента
- Обработать **все сообщения вместе** как один контекст

**Пример логики:**
```python
# Псевдокод
async def handle_message(message):
    # Запомнить время последнего сообщения
    last_message_time = now()

    # Подождать 5 секунд
    await asyncio.sleep(5)

    # Проверить, были ли новые сообщения
    if новых_сообщений_нет_5_секунд():
        # Обработать все накопленные сообщения
        all_messages = get_messages_since(last_message_time)
        response = process_all_together(all_messages)
        send_response(response)
```

---

### 2. 🔄 **Бот должен обрабатывать изменение решений**

**Примеры:**
```
Клиент: "Body"
Клиент: "Both"  ← ИЗМЕНИЛ РЕШЕНИЕ
```

**Решение:** Последнее сообщение **перезаписывает** предыдущее, если противоречит.

---

### 3. 📦 **Бот должен принимать всё сразу**

**Примеры:**
```
Клиент: "Jennifer Leslie, MBZ sector 10"  ← Имя + локация текстом
Клиент: [GPS] + "Villa 20" + [Photo]     ← 3 сообщения за секунду
```

**Решение:** Парсить **все части** из разных сообщений:
- Извлекать имя из текста
- Извлекать локацию из GPS
- Извлекать номер виллы из текста
- Не переспрашивать, если хоть что-то получено

---

### 4. ❓ **Бот должен отвечать на вопросы ВО ВРЕМЯ бронирования**

**Примеры:**
```
Бот: "Your massage is booked..."
Клиент: "n mask do i need to.decide now???"  ← Сразу вопрос!
```

**Решение:** Бот должен:
- Распознавать вопросы (`?` в конце, ключевые слова: "can", "do you", "is it", "how")
- Отвечать на вопрос
- Возвращаться к флоу бронирования

---

### 5. 🔀 **Бот должен понимать контекст из множественных сообщений**

**Пример:**
```
Клиент: "As agreed with therapist i'll do Sunday at morning"
Клиент: "Tuesday at 5 pm"
Клиент: "Thursday at 5 pm"
Клиент: "Or this week i can do morning"
```

**Решение:** GPT должен:
- Прочитать **все 4 сообщения**
- Понять что клиент предлагает **варианты**
- Выбрать из доступных или предложить альтернативу

---

## 🛠️ ТЕХНИЧЕСКИЕ РЕШЕНИЯ

### Решение 1: Буферизация сообщений
```python
message_buffer = {}  # {user_id: [messages]}
last_activity = {}   # {user_id: timestamp}

async def handle_message(user_id, message):
    # Добавить в буфер
    if user_id not in message_buffer:
        message_buffer[user_id] = []

    message_buffer[user_id].append(message)
    last_activity[user_id] = time.now()

    # Запустить таймер (если ещё не запущен)
    if not timer_running(user_id):
        asyncio.create_task(process_after_delay(user_id, 5))

async def process_after_delay(user_id, delay_seconds):
    await asyncio.sleep(delay_seconds)

    # Проверить что нет новых сообщений последние N секунд
    if time.now() - last_activity[user_id] >= delay_seconds:
        # Обработать все сообщения из буфера
        messages = message_buffer[user_id]
        combined_text = "\n".join(m.text for m in messages)

        response = await booking_agent.process_message(combined_text, context)
        await send_response(user_id, response)

        # Очистить буфер
        message_buffer[user_id] = []
```

### Решение 2: Умное извлечение из множественных сообщений

```python
async def _preprocess_multiple_messages(messages, context):
    """Обработать несколько сообщений как один контекст"""
    combined_text = " ".join(m.text for m in messages)

    # Извлечь всё что можно из всех сообщений
    # Имя
    if "name" in context.last_question.lower():
        for msg in messages:
            if possible_name(msg.text):
                save_name(msg.text)
                break

    # Время - взять последнее упоминание
    times = []
    for msg in messages:
        if time_mentioned(msg.text):
            times.append(extract_time(msg.text))
    if times:
        save_time(times[-1])  # Последнее = актуальное

    # Локация - из любого сообщения
    for msg in messages:
        if msg.location:
            save_location(msg.location)
        if "villa" in msg.text.lower():
            save_villa(extract_villa(msg.text))
```

### Решение 3: Распознавание вопросов

```python
def is_question(text: str) -> bool:
    """Проверить является ли сообщение вопросом"""
    question_indicators = [
        "?",
        "can you",
        "do you",
        "is it",
        "how much",
        "how long",
        "what time",
        "when",
        "where",
        "how",
        "rite?",
        "right?",
    ]

    text_lower = text.lower()
    return any(indicator in text_lower for indicator in question_indicators)

async def handle_question_during_booking(question, context):
    """Ответить на вопрос и продолжить бронирование"""
    # Ответить на вопрос
    answer = await booking_agent.answer_question(question)
    await send_response(answer)

    # Не менять состояние, продолжить откуда остановились
    # Не переспрашивать последний вопрос
```

---

## 📊 СТАТИСТИКА ИЗ РЕАЛЬНЫХ ЧАТОВ

### Множественные сообщения подряд:
- **Fatima:** 4 сообщения за 1 секунду (локация)
- **Fatima:** 4 сообщения за 27 секунд (расписание)
- **Jennifer:** 3 сообщения за 38 секунд (дата + время + вопрос)

### Изменение решений:
- **Fatima:** "Body" → "Both" (за 4 секунды)

### Вопросы во время бронирования:
- **Jennifer:** 3 дополнительных вопроса во время одного бронирования

---

## 🎯 ПРИОРИТЕТЫ РЕАЛИЗАЦИИ

### ФАЗА 1 (КРИТИЧНО):
1. ✅ **Буферизация сообщений** (5-10 секунд задержка)
2. ✅ **Обработка множественных сообщений** как один контекст
3. ✅ **Последнее сообщение перезаписывает** предыдущее

### ФАЗА 2 (ВАЖНО):
4. ⚠️ **Распознавание вопросов** во время бронирования
5. ⚠️ **Ответы на вопросы** без потери контекста
6. ⚠️ **Умное извлечение** из разных сообщений (имя + локация в одном)

### ФАЗА 3 (ДОПОЛНИТЕЛЬНО):
7. 💡 **Обработка переноса/отмены** во время бронирования
8. 💡 **Распознавание вариантов** ("Sunday or Tuesday or Thursday")

---

## ⚠️ ВАЖНОЕ ЗАМЕЧАНИЕ

**Без буферизации сообщений бот будет:**
- Отвечать слишком быстро после первого сообщения
- Игнорировать второе и третье сообщение клиента
- Создавать путаницу ("Я уже написал!")
- Переспрашивать то, что клиент уже сказал во втором сообщении

**Пример проблемы:**
```
Клиент: "Maybe 19th feb dear"
Бот: "What time would you like?" ← Отвечает сразу
Клиент: "Aroun 11" ← Уже отправил, но бот его не видел
Клиент: "Its 1 hr rite?" ← И ещё вопрос
Бот: ??? ← Не понимает контекст
```

**С буферизацией:**
```
Клиент: "Maybe 19th feb dear"
Клиент: "Aroun 11"
Клиент: "Its 1 hr rite?"
[Бот ждёт 5 секунд]
Бот: "50 minutes for face massage. Your face massage is booked for 19 February at 11am 🌹"
← Обработал всё вместе!
```

---

**Дата анализа:** 04.11.2025
**Критичность:** 🔴 ВЫСОКАЯ - без этого бот будет "разговаривать мимо" клиентов
