# Crystal Lab - Актуальный прайс-лист (2025)

**Дата обновления**: 04.11.2025
**Источник**: Анализ WhatsApp чатов + CLIENT_MEETING_NOTES.md

---

## 🏠 Основные услуги

### Массажи

| Услуга | Длительность | Цена без VAT | +5% VAT | Итого |
|--------|--------------|--------------|---------|-------|
| Body massage | 60 мин | 350 AED | 17.50 AED | **367.50 AED** |
| Body massage | 90 мин | 460 AED | 23 AED | **483 AED** |
| Face massage | 50 мин | 370 AED | 18.50 AED | **388.50 AED** |
| Body + Face | 110 мин | 590 AED | 29.50 AED | **619.50 AED** |

### Дополнительные процедуры

| Услуга | Цена без VAT | +5% VAT | Итого |
|--------|--------------|---------|-------|
| Carboxy therapy | 300 AED | 15 AED | **315 AED** |
| Alginate mask | 100 AED | 5 AED | **105 AED** |
| Foot reflexology | 150 AED (30 мин) | 7.50 AED | **157.50 AED** |

---

## 📦 Пакеты (Packages)

**Преимущества пакетов**:
- Значительная экономия при покупке
- Срок действия: 90 дней с момента покупки
- Можно использовать для любых массажей из списка
- Можно дарить или делить с семьёй

| Пакет | Сеансов | Цена без VAT | +5% VAT | Итого | Экономия |
|-------|---------|--------------|---------|-------|----------|
| Small package | 4 sessions | 1,080 AED | 54 AED | **1,134 AED** | ~270 AED |
| Medium package | 6 sessions | 2,350 AED | 117.50 AED | **2,467.50 AED** | ~Not calculated |
| **BEST VALUE** | **8 sessions** | **2,000 AED** | **100 AED** | **2,100 AED** | **~940 AED** |
| Large package | 10 sessions | 3,000 AED | 150 AED | **3,150 AED** | ~675 AED |

**Расчёт экономии для 8-session package**:
- 8 × 367.50 AED (60 мин с VAT) = 2,940 AED
- Цена пакета: 2,100 AED
- **Экономия: 840 AED** (~29%)

---

## 🎯 Акции и специальные предложения

### Текущие промо (ноябрь 2025)

**⚠️ ВНИМАНИЕ**: Необходимо уточнить у клиента актуальные акции!

Из WhatsApp анализа найдены упоминания:
- ~~"Old price - 500 AED, Now - 300 AED"~~ (старая акция, больше не актуальна)
- Пакеты всегда в наличии и являются лучшим предложением

### Сезонные скидки

- **День рождения клиента**: Уточнить у администратора
- **Привести друга (Referral)**: Уточнить у администратора
- **Праздничные дни**: Специальные пакеты (Ramadan, New Year, Christmas)

---

## ⚖️ Важная информация по VAT

**КРИТИЧНО**: С 1 августа 2024 года в ОАЭ действует 5% VAT на **ВСЕ** платежи.

❌ **НЕВЕРНО** (старая информация в некоторых чатах):
> "Cash payment is tax-free"

✅ **ВЕРНО**:
> "All payments include +5% VAT (cash, card, bank transfer)"

**Пример расчёта для клиента**:
```
Body massage 60 min: 350 AED
+ 5% VAT: 17.50 AED
Total to pay: 367.50 AED
```

**Хранение в системе (backend)**:
```javascript
{
  "service": "Body massage 60 min",
  "base_price": 350.00,
  "vat_rate": 0.05,
  "vat_amount": 17.50,
  "total_price": 367.50,
  "currency": "AED"
}
```

---

## 🏘️ Зоны обслуживания

### Abu Dhabi
- **Бесплатная транспортировка** мастера и оборудования
- Portable massage table включена
- Районы: Khalifa City, Al Reem Island, Saadiyat Island, Yas Island, и другие

### Al Ain
- **Бесплатная транспортировка**
- Все районы города

### Другие эмираты
- Уточнять у администратора наличие
- Возможна дополнительная плата за транспорт

---

## 🕒 Рабочие часы

**Понедельник - Воскресенье**: 9:00 AM - 10:00 PM
- Первое бронирование: с 9:00 AM
- Последнее бронирование: 9:00 PM (окончание до 10:00 PM)

**Национальные праздники**: Возможны изменения, уточнять заранее

---

## 👩‍⚕️ Мастера

- **Русские сертифицированные мастера**
- **Женщины-мастера** (для комфорта клиенток)
- Опыт работы: от 3+ лет
- Владение языками: русский, английский, базовый арабский

**Предпочтения по мастерам**:
- Можно запросить конкретного мастера при бронировании
- Если мастер занят, предложим альтернативы

---

## 🩺 Медицинские противопоказания

**ОБЯЗАТЕЛЬНО сообщать администратору**:
- Недавние операции (особенно кесарево сечение)
- Беременность (особенно ранние сроки)
- Хронические заболевания
- Аллергии на масла/кремы
- Боли в спине/суставах

**Действие при получении медицинской информации**:
1. Записать в медицинские заметки клиента
2. Уведомить мастера перед визитом
3. Адаптировать технику массажа под состояние клиента

---

## 💳 Способы оплаты

1. **Наличные (Cash)**: После сеанса, мастеру
2. **Банковский перевод**: По реквизитам (запросить у администратора)
3. **Онлайн оплата**: Уточнить доступность

**Все способы включают +5% VAT**

---

## 📋 Политика отмен и изменений

### Изменения времени
- **Мелкие изменения** (±30-60 мин): Стараемся accommodate
- **Изменение на другой день**: Бесплатно, если за 12+ часов до визита

### Отмены
- **За 12+ часов**: Без штрафов
- **Менее 12 часов**: Обсуждается индивидуально
- **No-show**: Обсуждается индивидуально

**Тон при отмене** (из WhatsApp анализа):
```
"Would you like to reschedule?"
"Okay dear, no problem. Let us know when you're ready"
```

❌ **НИКОГДА**:
- Не обвинять клиента
- Не упоминать штрафы автоматически
- Не проявлять негатив

---

## 🔄 Recurring Appointments (Регулярные визиты)

Многие клиенты предпочитают регулярные визиты:

**Популярные схемы**:
- "Every Wednesday at 1:00 PM"
- "Every Saturday morning"
- "Twice a week: Monday + Thursday"

**Как обрабатывать**:
1. Записать предпочтение в профиле клиента
2. За день до: "Next Wednesday 1:00 PM is okay for you?"
3. Подтверждать каждый визит отдельно

---

## 📊 Upselling (Допродажи)

### После первого сеанса
```
"How was your session today?"
[Клиент отвечает положительно]
"We currently have special promotions on our massage packages.
Would you like to hear more details?"
```

### Во время визита
- Мастер может предложить дополнительные процедуры:
  - Carboxy therapy (+300 AED)
  - Alginate mask (+100 AED)
  - Face massage (+370 AED)

**Согласие клиента ОБЯЗАТЕЛЬНО** перед добавлением услуг.

---

## 🆘 Escalation (Когда передавать администратору)

AI-агент должен передать администратору в следующих случаях:

1. **Медицинские жалобы**: bleeding, severe pain, injury
2. **Жалобы на качество**: therapist complaints
3. **Споры по ценам**: discount requests, price disputes
4. **Множественные отмены**: 3+ подряд
5. **Нет ответа**: 2+ confirmation attempts без ответа
6. **Услуги вне каталога**: requests for services not offered

**Фраза для escalation**:
```
"Let me check with our manager regarding your request.
I will get back to you shortly."
```

---

## 📝 Примечания для разработчиков

### Хранение цен в базе данных

```sql
CREATE TABLE services (
  id UUID PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT,
  duration INTEGER NOT NULL, -- minutes
  base_price DECIMAL(10,2) NOT NULL, -- без VAT
  vat_rate DECIMAL(5,4) DEFAULT 0.05,
  category VARCHAR(100), -- 'massage', 'facial', 'additional'
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE packages (
  id UUID PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  sessions INTEGER NOT NULL,
  base_price DECIMAL(10,2) NOT NULL,
  validity_days INTEGER DEFAULT 90,
  description TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Расчёт цены с VAT (JavaScript)

```javascript
function calculatePriceWithVAT(basePrice) {
  const VAT_RATE = 0.05; // 5%
  const vatAmount = basePrice * VAT_RATE;
  const totalPrice = basePrice + vatAmount;

  return {
    basePrice: Math.round(basePrice * 100) / 100,
    vatRate: VAT_RATE,
    vatAmount: Math.round(vatAmount * 100) / 100,
    totalPrice: Math.round(totalPrice * 100) / 100
  };
}

// Пример:
const result = calculatePriceWithVAT(350);
console.log(result);
// {
//   basePrice: 350.00,
//   vatRate: 0.05,
//   vatAmount: 17.50,
//   totalPrice: 367.50
// }
```

---

## ✅ TODO: Необходимо уточнить у клиента

- [ ] Актуальные акции на ноябрь 2025
- [ ] Цены на manicure/pedicure, eyelash extension, eyebrow lamination
- [ ] Цены на deep face cleansing
- [ ] Политика referral программы (скидки за приведённого друга)
- [ ] Условия birthday discount
- [ ] Доступность онлайн оплаты (карты, PayPal, etc.)

---

**Этот документ должен обновляться при изменении цен или появлении новых акций.**
