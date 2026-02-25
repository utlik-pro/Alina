# Crystal Lab AI Bot — Report for Alina

**Date:** February 25, 2026
**Bot version:** Telegram MVP with Database Integration

---

## 1. Current Bot State

The bot is ready for testing in Telegram. Here's what's implemented:

| Feature | Status |
|---------|--------|
| AI agent (GPT-4o-mini) with human-like personality | Done |
| Message buffering (waits 20 sec for multiple messages) | Done |
| Service detection from user messages | Done |
| VAT calculation (5% for transfer, 0% for cash) | Done |
| Location extraction (GPS + villa/apartment number) | Done |
| Name extraction from messages | Done |
| Payment method detection (cash/transfer) | Done |
| Medical notes detection and alert to admin | Done |
| Follow-up messages for inactive clients (5 attempts) | Done |
| Upselling after booking | Done |
| Booking confirmation with date/time | Done |
| Admin group notifications | Done |
| Database (SQLite for dev, PostgreSQL for prod) | Done |
| 92 automated tests | Done |

### What the bot does NOT do yet:
- YClients API integration (mock mode — uses fake time slots)
- Real payment processing
- WhatsApp integration (Telegram only for now)
- Subscription management

---

## 2. Current Prices (February 2026)

All prices are managed in ONE file: `prices.py`. Change a price there — it updates everywhere.

### Body Massage
| Service | Duration | Price |
|---------|----------|-------|
| Body massage | 60 min | 350 AED |
| Body massage | 90 min | 480 AED |
| Body + Face combo | 85 min | 650 AED |

### Face Massage
| Service | Duration | Price |
|---------|----------|-------|
| Face massage | 50 min | 370 AED |

### Additional Body Services
| Service | Duration | Price |
|---------|----------|-------|
| Back massage | 30 min | 175 AED |
| Full body scrubbing | 30 min | 200 AED |
| Head spa massage | 15 min | 85 AED |
| Hand spa massage | 15 min | 85 AED |
| Foot reflexology | 30 min | 175 AED |
| Lifting body bandage | 30 min | 250 AED |
| Drainage body bandage | 30 min | 250 AED |
| Taping | — | from 100 AED |
| Neck and shoulders massage | 30 min | 200 AED |
| Cupping therapy | 60 min | 350 AED |

### Facials & Treatments
| Service | Duration | Price |
|---------|----------|-------|
| Deep facial cleansing (8 steps) | 90 min | 420 AED |
| Carboxy-therapy | 40 min | 300 AED |
| Vitamin C Brightening Program | 60 min | 420 AED |
| CO2 Carboxy-therapy | 40 min | 300 AED |
| Express facial Unstressed | 40 min | 300 AED |

### Nails
| Service | Price |
|---------|-------|
| Russian gelish manicure | 200 AED |
| Russian gelish pedicure | 220 AED |
| Combo Russian mani + pedi | 380 AED |
| Japanese manicure | 180 AED |
| Japanese pedicure | 200 AED |
| Combo Japanese mani + pedi | 330 AED |
| Nail extensions soft gel | 380 AED |
| Nail extensions hard gel | 450 AED |

### Lashes & Brows
| Service | Price |
|---------|-------|
| Classical eyelash extension | 300 AED |
| 2D volume eyelash extension | 350 AED |
| Russian volume eyelash extension | 400 AED |
| Eyelash lifting | 150 AED |
| Eyebrow lamination (shaping included) | 200 AED |
| Combo eyelash lifting + eyebrow lamination | 200 AED |

### Permanent Makeup
| Service | Price |
|---------|-------|
| Lips | 1,200 AED |
| Eyebrows | 1,000 AED |
| Eyeliner | 800 AED |

### Hair & Makeup
| Service | Price |
|---------|-------|
| Wavy blow dry | 250 AED |
| Hairstyles | from 250 AED |
| Makeup | 300 AED |
| Hair + makeup | 500 AED |
| Evening makeup | 600 AED |

### Current Special Offers
| Offer | Price | Was |
|-------|-------|-----|
| WINTER BODY COMBO (100 min) | 499 AED | 720 AED |
| RAMADAN Deep Facial Cleansing | 420 AED | 770 AED |
| WINTER NAILS Japanese mani + pedi | 330 AED | 380 AED |
| WINTER NAILS Russian mani + pedi | 380 AED | 420 AED |
| WINTER LAMINATION lash + brow | 200 AED | 350 AED |
| TRIAL SESSION (new clients) 80 min | 350 AED | 700 AED |
| BOOK A FRIEND (referral coupon) | 50 AED off | — |

### Massage Packages
| Package | Sessions | Price | Was |
|---------|----------|-------|-----|
| Face massage 5x50min | 5 | 1,650 AED | 1,850 AED |
| Body massage 5x60min | 5 | 1,550 AED | 1,750 AED |
| Body massage 10x60min | 10 | 3,000 AED | 3,500 AED |
| Body massage 6x90min | 6 | 2,590 AED | 2,760 AED |
| Body + Facial 5x85min | 5 | 2,200 AED | 2,675 AED |

---

## 3. VAT Rules

| Payment Method | VAT | Client sees |
|----------------|-----|-------------|
| Cash | 0% (tax free) | Base price only |
| Bank transfer | +5% | Base price + "Bank transfer + 5% VAT" note |
| Terminal | +5% | Base price + "Bank transfer + 5% VAT" note |

The bot NEVER shows VAT calculations to clients. It only shows base prices and adds a footnote:
```
Cash - tax free
Bank transfer + 5% VAT
```

---

## 4. How the Bot Communicates

The AI is configured to write exactly like you (Alina) in your real WhatsApp chats:

- **Short messages** — 1-2 sentences max, never paragraphs
- **Casual tone** — "Ok dear", "Yes home service", "Share with your location please"
- **Emojis** — used strategically, not on every line
- **Message splitting** — long responses are split into 2-3 separate messages (like a real person)
- **Buffering** — waits 20 seconds before responding (clients often send 3-5 messages in a row)
- **Cultural adaptation** — adapts to Arab clients, expats, Russian clients
- **Never sounds like a bot** — trained on 12 forbidden phrases like "Thank you for reaching out!"

---

## 5. Testing Checklist for Telegram Bot

### How to test:
1. Find the bot in Telegram (ask the developer for the bot username)
2. Send messages as if you're a client
3. Check each scenario below

### 10 Test Scenarios:

**Scenario 1: New client greeting**
- Send: "Hi"
- Expected: Bot responds with "Hi dear" + asks about services
- Check: Response is short, warm, not robotic

**Scenario 2: Body massage inquiry**
- Send: "I want body massage"
- Expected: Bot shows prices (350 AED / 480 AED) + VAT note
- Check: Prices are correct, no VAT calculation shown

**Scenario 3: Multiple messages at once**
- Send quickly: "body massage" then "60 minutes" then "tomorrow"
- Expected: Bot waits ~20 seconds, then responds to ALL messages at once
- Check: Bot doesn't respond to each message separately

**Scenario 4: Combo service**
- Send: "I want both body and face massage"
- Expected: Bot offers Body + Face combo at 650 AED
- Check: Combo detected correctly (not just body or just face)

**Scenario 5: Payment method — cash**
- When bot asks about payment, send: "cash"
- Expected: Total = base price (no VAT added)
- Check: No "5%" or "VAT" in the total

**Scenario 6: Payment method — transfer**
- When bot asks about payment, send: "transfer" or "bank"
- Expected: Bot mentions 5% VAT will apply
- Check: Total includes 5% VAT

**Scenario 7: Medical information**
- Send: "I had a cesarean section last month"
- Expected: Bot acknowledges warmly ("Ok dear, thank you for letting me know") + informs therapist
- Check: Bot doesn't give medical advice

**Scenario 8: Full booking flow**
- Go through: Service → Duration → Location → Villa number → Time → Name → Payment
- Expected: Booking confirmation with date, time, service
- Check: Bot asks each question ONCE, doesn't repeat

**Scenario 9: Nails inquiry**
- Send: "manicure"
- Expected: Bot shows Russian and Japanese manicure options with prices
- Check: All prices match the price list above

**Scenario 10: Client changes mind**
- Send "body massage" then immediately send "actually both body and face"
- Expected: Bot uses the LAST message (combo, not just body)
- Check: Bot doesn't get confused by the first message

### What to look for (quality checks):
- Bot NEVER says "Thank you for reaching out!" or "I'd be happy to help!"
- Bot NEVER shows VAT calculations (no "350 + 5% = 367.50")
- Bot doesn't repeat questions (if you gave your name, it shouldn't ask again)
- Messages feel like texting a real person, not a customer service chatbot
- Prices match the price list in this document

---

## 6. How to Change Prices in the Future

**One file, one change — updates everywhere.**

Open `prices.py` in the project root. Find the service you want to change:

```python
# Example: change Body massage 60min from 350 to 400 AED
"body_massage_60": {
    "name": "Body massage",
    "duration": 60,
    "price": 400.0,  # <-- change this number
    ...
},
```

Save the file. That's it. The price will automatically update in:
- Bot responses (system prompt)
- Booking calculations
- All test assertions
- Upsell messages
- Special offers (if they reference this service)

**To verify:** run `python3.11 -m pytest tests/ -v` — all 92 tests should pass with new prices.

---

## 7. Project Files Overview

| File | What it does |
|------|-------------|
| `prices.py` | All prices — change them HERE |
| `bot.py` | Main Telegram bot logic |
| `agents/booking_agent.py` | AI personality and system prompt |
| `services/booking_flow.py` | Booking process orchestration |
| `services/follow_up.py` | Automatic follow-up messages |
| `services/message_buffer.py` | Message buffering (20 sec wait) |
| `database/models.py` | Database models (Client, Booking) |
| `tests/` | 92 automated tests |

---

*Report prepared automatically. For questions contact the developer.*
