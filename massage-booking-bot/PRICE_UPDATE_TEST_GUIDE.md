# 🧪 Тестирование обновленных цен - Quick Guide

**Дата:** 05.11.2025
**Бот PID:** 14230
**Статус:** 🟢 Запущен с новыми ценами

---

## ⚡ 5 быстрых тестов (10 минут)

### ✅ ТЕСТ 1: Russian gelish manicure (новая цена)

**Команды:**
```
/clear
/start
→ manicure
```

**✅ Ожидаемый результат:**

Бот показывает:
```
Manicure and pedicure 🌹
Russian gelish:
- Manicure: 200 AED + 5% VAT = 210 AED
- Pedicure: 220 AED + 5% VAT = 231 AED
- Combo: 399 AED + 5% VAT = 418.95 AED

Japanese:
- Mani: 180 AED + 5% VAT = 189 AED
- Pedicure: 200 AED + 5% VAT = 210 AED
- Combo: 380 AED + 5% VAT = 399 AED
```

**Выбираем:**
```
→ russian manicure
→ [Location]
→ villa 10
→ 3pm
→ Anna
```

**В уведомлении должно быть:**
```
👤 Anna
🛎️ Russian gelish manicure
💰 210.00 AED  ← ВАЖНО! Было 84.00 AED
```

---

### ✅ ТЕСТ 2: Russian gelish combo (новая цена)

**Команды:**
```
/clear
/start
→ manicure and pedicure
→ combo russian
```

**В уведомлении:**
```
💰 418.95 AED  ← ВАЖНО! Было 157.50 AED
```

---

### ✅ ТЕСТ 3: Japanese combo (новая услуга)

**Команды:**
```
/clear
/start
→ manicure and pedicure
→ japanese combo
```

**В уведомлении:**
```
🛎️ Japanese mani + pedi
💰 399.00 AED  ← Новая услуга!
```

---

### ✅ ТЕСТ 4: Deep facial cleansing (новая цена + длительность)

**Команды:**
```
/clear
/start
→ deep face cleansing
```

**Бот показывает:**
```
Deep facial cleansing (8 steps treatment):
90 min: 420 AED + 5% VAT = 441 AED
```

**В уведомлении:**
```
🛎️ Deep facial cleansing (90 мин)  ← Было 60 мин
💰 441.00 AED  ← Было 262.50 AED
```

---

### ✅ ТЕСТ 5: Body massage (БЕЗ изменений - регрессия)

**Команды:**
```
/clear
/start
→ body massage
→ 90 min
```

**В уведомлении:**
```
🛎️ Body massage (90 мин)
💰 483.00 AED  ← Не изменилось (было 483.00 AED)
```

---

## 📊 Таблица проверки цен

| Услуга | Старая цена (с VAT) | Новая цена (с VAT) | Статус |
|--------|---------------------|-------------------|--------|
| Russian gelish manicure | 84.00 AED | **210.00 AED** | ⚠️ Проверить |
| Russian gelish pedicure | 105.00 AED | **231.00 AED** | ⚠️ Проверить |
| Russian combo | 157.50 AED | **418.95 AED** | ⚠️ Проверить |
| Japanese mani | - | **189.00 AED** | 🆕 Новая |
| Japanese pedicure | - | **210.00 AED** | 🆕 Новая |
| Japanese combo | - | **399.00 AED** | 🆕 Новая |
| Deep facial cleansing | 262.50 AED | **441.00 AED** | ⚠️ Проверить |
| Carboxy-therapy | 315.00 AED | **315.00 AED** | ✅ Не изменилось |
| Body massage 60 min | 367.50 AED | **367.50 AED** | ✅ Не изменилось |
| Body massage 90 min | 483.00 AED | **483.00 AED** | ✅ Не изменилось |

---

## ❌ СТОП-ФАКТОРЫ (тест провален)

- [ ] Показывает старую цену для nails
- [ ] Нет выбора между Russian и Japanese
- [ ] Deep cleansing показывает 60 min вместо 90 min
- [ ] Цена в уведомлении неправильная
- [ ] Технические ошибки

---

## 🔍 Как проверить в логах

```bash
tail -f bot.log
```

**Ищите строки:**

### Правильно ✅:
```
Сохранена услуга: Russian gelish manicure, None мин, 200.0 AED
Created booking 15 for client 3: Russian gelish manicure on 2025-11-06
```

### Неправильно ❌:
```
Сохранена услуга: Manicure, 45 мин, 80.0 AED  ← Старая цена!
```

---

## 🚨 Частые проблемы

### Проблема 1: Бот показывает старые цены

**Причина:** Бот не перезапущен после обновления

**Решение:**
```bash
pkill -9 -f "python.*bot.py"
source .venv/bin/activate
nohup python bot.py > bot.log 2>&1 &
```

---

### Проблема 2: Нет опции Japanese

**Причина:** GPT не предлагает выбор между Russian и Japanese

**Решение:** Проверить system prompt в [agents/booking_agent.py](agents/booking_agent.py) lines 145-155

---

### Проблема 3: Неправильная длительность для Deep cleansing

**Ожидается:** 90 min
**Если показывает:** 60 min

**Решение:** Проверить [bot.py](bot.py) lines 492-495

---

## ✅ Критерии успешного теста

- [ ] Все 5 тестов прошли успешно
- [ ] Цены соответствуют новому прайсу
- [ ] Japanese услуги доступны
- [ ] Deep cleansing показывает 90 min и 441 AED
- [ ] Body massage не изменился (регрессия OK)
- [ ] Нет технических ошибок в логах

---

## 📞 Если что-то не работает

1. Сделайте скриншот переписки
2. Скопируйте последние 50 строк логов:
   ```bash
   tail -50 bot.log
   ```
3. Укажите какой тест провалился
4. Опишите что ожидали vs что получили

---

**Дата создания:** 05.11.2025
**Статус бота:** 🟢 Running (PID: 14230)
**Версия:** 2.2 с обновленным прайсом
