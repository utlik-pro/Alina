---
name: crystal-lab
description: Canonical business rules, gotchas and verification checklist for the Crystal Lab WhatsApp booking agent (home massage / nails / lashes, UAE). Invoke BEFORE touching massage-booking-bot — booking flow, slots, areas, service durations, hours, payment, cancel/reschedule — so a client rule is never lost and a косяк is never repeated. Also invoke when the client (Alina / Crystal Lab admins) states any new rule, to record it here.
---

# Crystal Lab — client knowledge base (single source of truth)

**Read this before touching `/Users/admin/Alina/massage-booking-bot/`.** Whenever the
client states a new rule, ADD it here in the same edit as the code change.

Scope: **WhatsApp path only** — `webhook_app.py`, `agents/booking_agent.py`,
`agents/tools.py`, `services/yclients_service.py`. `bot.py` (Telegram) is legacy.

## ⚠️ Why the косяки happened — the hard lessons (do NOT repeat)
1. **Drive the real conversation, not just the logic.** Slot/area/duration bugs are
   caught by YClients probes + unit tests. **Flow bugs** (books without confirming,
   never asks name/location, reschedule not reflected in YClients) show up ONLY in a
   full end-to-end dialogue. Never say "done" until the live agent was driven through
   the whole flow.
2. **No hard gate = bug.** The prompt tells the agent to gather location/name/confirm,
   but the LLM skips steps — so the CODE must ALSO refuse to create a record without
   them. Prompt guidance is advisory; code gates are binding.
3. **Verify against LIVE YClients**, never assume. Schedules change hourly during tests.
4. **Prod ≠ code.** Fixes land on `develop` → Render auto-deploys (a few min). Render
   sets its OWN env (e.g. `OPENAI_MODEL`). Tester reports may predate the deploy.
   Multiple actors commit to this repo in parallel — check `git log` before assuming.
5. Report what's **verified** vs only **coded**. Don't imply the whole flow works when
   only part was tested.

## Business rules (authoritative)

### Emirates / area routing
- Serves **Abu Dhabi, Al Ain, Dubai**. Each master serves EXACTLY ONE emirate, tagged
  in the YClients display name ("Элиза Al Ain", "Людмила Дубай"; untagged = Abu Dhabi).
  To move a master to another emirate: rename them in YClients (no code change).
- Lyudmila = Dubai. Eliza = Al Ain. Natalia / Masha / Tatyana / Makhabat / Ekaterina =
  Abu Dhabi. Elena / Safina = nails.
- A client only ever sees / is booked with masters in their own emirate.
- **Lash extensions: Abu Dhabi ONLY** (not Al Ain, not Dubai).

### Hours & travel buffer
- First booking start **10:00**. **Last booking START 21:00** (session may finish up
  to 23:00 — the cap is on the START time, duration-fit handles the end).
- **Travel buffer 60 min** between home visits (default). May drop to **30 min** if the
  client genuinely can't do another time — the admin then shuffles / negotiates.

### Service durations — a slot must fit the WHOLE session (comes from the SERVICE)
| Service | Duration |
|---|---|
| Russian gel manicure | 2h |
| Russian gel pedicure | 2h |
| Combo Russian mani + pedi | 3h |
| Japanese manicure | 1.5h |
| Japanese pedicure | 1.5h |
| Combo Japanese mani + pedi | 2.5h |
| Russian manicure (cleaning + coating) | 1h |
| Russian pedicure (smart disc) | 1h |
| Nail extension (soft gel) | 2.5–3h |
| Nail extension (hard gel) | 2.5–3h |
| Massage (body) | 60 or 90 min (client choice; price list has only these two) |
For nails especially, the duration is a property of the service — do NOT wait for the
client to state minutes; look it up from the service. For body massage, ask 60 or 90.

### Payment
- **Cash** — tax free. **Bank transfer** — +5% VAT. Always pay AFTER the service
  (never "transfer first to confirm").
- **Card by terminal** — ON REQUEST ONLY. Do NOT offer it proactively (1 terminal for
  6 masters). When the client asks for it, add **"нужен терминал"** to the YClients
  record comment.
- Prices shown without VAT + footnote: "Cash — tax free / Bank transfer + 5% VAT".
- Client-facing time = **12h AM/PM** (UAE). Booking stays 24h internally.

### Booking flow — DO NOT create the YClients record until ALL are gathered
`service → area → slot (fits duration, 10:00–21:00, buffer clear) → LOCATION (GPS or
text address) → NAME → payment → explicit CONFIRM`. Phone is already known (WhatsApp).
A booking created without location + confirmation is a bug.

### Cancel / reschedule
- YClients records are NOT auto-modified (safety rule). **Open decision:** reschedule
  currently makes a local record but does NOT move the YClients slot, so the calendar
  keeps the old time ("перенёс с 2 на 4 — осталась на 2"). Either update YClients or
  tell the client "requested — admin will confirm". Resolve with the client.
- With >1 active booking, don't guess which — ask the client.

## Verification checklist before saying "done"
- [ ] Drove the FULL live conversation (service→area→slot→location→name→payment→confirm)
      and saw a correct YClients record created.
- [ ] Reschedule and cancel driven live.
- [ ] Slots verified against live YClients for the exact date/master.
- [ ] `pytest` green; pushed to `develop`; stated the deploy/prod caveat.

## Reference
- Model **gpt-5.4-mini** (also set in Render env `OPENAI_MODEL`). Company id **1094806**.
- Admin group "Crystal Lab - Leads" `-1003250489002`. Dev group "Crystal разработка"
  `-5059625262`. Feedback auto-triage → Dmitry DM `1379584180`.
- Related memory: [[reference-area-routing]], [[reference-yclients-slots]],
  [[reference-feedback-monitor]].
