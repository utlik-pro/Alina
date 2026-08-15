# Полная карта логики общения админов — и сопоставление с агентом

Дата: 2026-08-15. База: ManyChat-инбокс за всю жизнь канала (11–15.08),
82 чата: 38 вычитаны целиком (19 в анализе от 14.08 + 19 сегодня),
остальные классифицированы по превью последнего сообщения.
Ограничение: переписка живых админов в WhatsApp (971551933662) не видна —
только IG-часть воронки.

## Состав инбокса (82 чата за 4 дня)

| Класс | Сколько | Что это |
|---|---|---|
| Живые диалоги | ~45 | клиент написал, кто-то ответил |
| Broadcast-дожимы | ~25 | 2 волны 12.08 по базе подписчиков, ~0 ответов |
| Welcome-only | ~10 | подписался, получил автоприветствие, молчит |

Темп: ~30 живых лидов/сутки к 15.08 (рост: 18 → 45 → 82).

## Скелет админского диалога (наблюдается в ~95% чатов)

1. **Любой вход** → шаблон: «Hello / We provide home service / Free
   transportation to your home / Top Russian therapist / We have available
   slots for today and tomorrow» + **«Could you send your name and WhatsApp
   number please — I will send you more information / I give you good price»**.
2. **Номер получен** → «Thank you, dear🌸 One minutes please We message you
   in WhatsApp» → пишут с личного WhatsApp → «Check please WhatsApp».
3. **Молчание ~2–3 ч** → follow-up: «Hi. Can you update us? We have
   available slots for tomorrow. Should we book for you?»
4. **Отказ** → «Have a nice day dear ❤️». Отложка → «We will be waiting
   for you )».

## Ветки-обработчики (все — из реальных кейсов, имена = чаты)

- **«How much» / категория услуги** → готовая **оффер-карточка**:
  - *Body* (محمد احمد): 60 мин — 350; **package 5 сеансов — 1550**;
    техники: lymphatic drainage, maderatherapie, anti-cellulite,
    postpartum, mixed, guasha, deep tissue, **prenatal after 4 months**,
    aftersurgery; «Russian **female** certified therapist».
  - *Face* (Hendaq, HKN): «old price 550 → NOW 370»; **package 5 — 1650**;
    техники: lifting drainage, buccal, myofascial (non-surgical lift),
    signature mix — все 50 мин; зона в карточке: «Abu Dhabi and Alain»
    (без Дубая — вопрос Татьяне).
- **Пакетный вопрос** (hk.xx7): «Body lymph 350, 5 session — 1550» —
  называют цену сразу + «trial session for new clients».
- **Беременность** (Amira): «Of course. Our therapist with medical
  education. We have prenatal massage. 350aed» → номер взят.
- **Оплата картой** (Viola): «Yes, have card machine».
- **«Где студия?»** (Sam Sam): «Studio in Abudhabi, Al Raha — currently
  closed for maintenance. We provide home service».
- **Скепсис** (Sam Sam): «You will see results»; прогревы: «We work with
  world champion for massage», «Visible results after 1 session».
- **Вне зоны** (HKN, Sharjah): сначала «What is your Location in
  Sharjah?» → потом «Oh sorry :(( we provide service in Dubai, Abu Dhabi
  and Al Ain. It's a remote location».
- **Эмират не назван / не тот** (Rhizlaine, Oksana): уточняют одним
  вопросом, при смене эмирата клиентом переключаются без трения.
- **Вопрос времени** (Viola): «What time is preferable for you? We will
  find convenient time for you» — **слоты никогда не проверяют**.
- **Реактивация базы**: массовые рассылки-копипасты (2 волны 12.08:
  «Hello dear❤️ How are you?…» ×16, «Hi Dear ❤️ How are you ?!…» ×9) —
  конверсия ≈ 0.

## Системные слабости админов (подтверждены на 38 диалогах)

1. **Нет единой логики**: одинаковый вход → разные ответы (Shivani —
   полный шаблон; Siobhán — «Our administrator write to you in WhatsApp»
   без запроса номера = невыполнимое обещание, тупик).
2. **Не отвечают на заданный вопрос** (zauraiz08 просила фото — не
   прислали; Gayatri спросила про промо — «administrator will write»).
3. **Слепые обещания слотов** («slots today and tomorrow» — всем).
4. **Потери собранных номеров** (Meem, Su Guer, 0603365151, 0508943943 —
   анализ 14.08).
5. **Перехлёст с агентом 21:00–23:00**: Diya — агент дал точную цену в
   22:42, админ поверх шаблон, утром двойной дожим → «Sorry, will not be
   booking». Также benzii (22:00), Noone.

## Сопоставление: админы vs агент

| Элемент | Админы | Агент (после f2255d5 + prenatal-фикс) | Статус |
|---|---|---|---|
| Ответ на префилл | шаблон 4 строки + номер | приветствие + 1 selling line + 1 вопрос | ✅ скелет перенят, без стены |
| Вопрос цены | карточка категории целиком | 1–3 строки, offer-first (275→) | ✅ точнее админов |
| Пакеты | называют 1550 / 1650 | запрещено называть (cca6747) | ⚠️ противоречие → Татьяна |
| Слоты | «today and tomorrow» не глядя | ночью реальные из YClients (при IG_BOOKING_ENABLED) | ✅ агент честнее |
| Сбор контакта | имя + WhatsApp в каждом чате | phone gate перед бронью / wa.me | ✅ |
| Беременность | prenatal 350, мед. образование | то же + «после 4 месяцев» | ✅ перенято + точнее |
| Карта | «yes, card machine» | то же (+VAT-правила по запросу) | ✅ перенято |
| Студия | «Al Raha, closed for maintenance» | то же | ✅ перенято |
| Пол мастера | «Russian female certified» | female-строка добавлена | ✅ перенято |
| Гео-отказ | уточнить район → отказ | честный отказ | ✅ (уточнение района — опция) |
| Follow-up молчунам | через 2–3 ч, вручную | **нет** | ❌ дыра — кандидат №1 |
| Реактивация базы | broadcast ×2, конверсия 0 | нет (и не надо в таком виде) | — |
| Отказ/отложка | «Have a nice day ❤️» | вежливое закрытие | ✅ (дата выходного — опция) |
| Ссылка wa.me | не нужна (личный WA) | 1 раз за диалог, код-дедуп | ✅ |
| Тон | dear🌸❤️, короткие строки | 🌹😊, 2–6 предложений | ✅ |
| Стабильность | зависит от смены | детерминированные правила | ✅ |

## Открытые вопросы (Татьяне)

1. **Пакеты**: админы продают 5×body=1550 и 5×face=1650 в открытую. Агенту
   запрещено. Подтвердить цифры и снять бан — или запретить админам?
2. **Face в Дубае**: карточка лица и welcome говорят «Abu Dhabi and Alain»,
   реклама и агент работают и на Дубай. Что верно для face-услуг?
3. **Перехлёст 21:00–23:00**: админы прекращают отвечать в 21:00 (или
   помечаем чаты, где ответил агент)?
4. **«World champion for massage»** — можно ли агенту использовать этот
   клейм (мы его не верифицировали)?
