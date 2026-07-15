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
- **Nails (Elena/Safina): Abu Dhabi ONLY** — a Dubai/Al Ain client asking for a
  manicure has no nail tech in their area (tell them honestly, don't say "no slots").
- 🔑 **Emirate is PER-DAY for floating masters, not just the name tag.** Discovered
  live in YClients 2026-07-09: the salon marks a floating master's emirate-of-the-day
  with a **~09:00 admin record, no client, comment = the emirate** ("Дубай" /
  "Абу-Даби" / "Al ain"). **Lyudmila is the only floater** — her tag "Людмила Дубай"
  is only her default; her real emirate varies daily (e.g. 10 Jul = Abu Dhabi, from
  11 Jul = Dubai). Code now reads that marker for the date (`_marker_area_from_records`
  / `_is_emirate_marker` in `yclients_service.py`) in slot display AND booking
  validation (`staff_area_of`/`find_staff_id` take a `date`). The marker record is
  also EXCLUDED from the travel buffer (it's a pin, not a visit — it used to hide her
  10:00/10:30). To move any master, the salon just sets the day's marker (or renames).
- Area is detected from the client message via the shared `detect_area()` helper in
  `webhook_app.py` (used by prod AND the sim — keep it the single source). Russian
  "Абу-Даби" (hyphen) must resolve — it silently didn't before 2026-07-09.

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
- 💚🚫 **MASTER PREFERENCE / replacement persists across sessions (added 2026-07-15).**
  Positive: `client.preferred_therapist` is stored (the master they booked with, or
  an explicit "only Elena") so "same as last time" works even after a restart.
  Negative/replacement: `client.avoid_therapist` (new column, auto-migrated) is set
  when the client says "don't send X / didn't like X / не понравилась X" (a NAMED
  master; unnamed "give me someone else" stays conversational) → admin alert + the
  master is dropped from the injected slots (`_pref_note`) AND a **hard booking
  guard** in `_maybe_create_booking` blocks a record with the avoided master even
  if the LLM ignores the note. Detection tolerates RU case endings (`_find_master_name`
  stems + short-form map). Verified live: avoid=Makhabat → she vanishes from the
  offered list. Tests: `tests/unit/test_master_preference.py`.
- 👥 **GROUP booking is TEAM-MEDIATED for the extra people (added 2026-07-15).**
  «для меня и мамы» / couple / friends: each person needs their OWN therapist
  (one master can't serve two at once). `book_appointment` now has a `guests`
  array; the agent books the MAIN client and puts extras in `guests`, and says
  the honest line "your mom's spot is being arranged by the team". ⚠️ **The LLM
  is UNRELIABLE at filling `guests`** (live sim 2026-07-15 dropped it), so a CODE
  safety net backs it: `_looks_like_group()` (high-precision phrases) sets a
  sticky `booking_data["group_requested"]`; on a booking with that flag but no
  guests, (a) `_enforce_reply_wording` appends the honest "being arranged by the
  team" line to the CLIENT reply, and (b) the admin ALWAYS gets a «ГРУППОВАЯ
  ЗАПИСЬ — добавьте записи вручную» alert. This kills the silent bug where two
  people got ONE record (live-caught 2026-07-14, Annette «бронь только на
  одного»). Full auto multi-record (pick a 2nd free master + create it) is NOT
  done — it needs live 2-master availability + partial-failure rollback; the
  extra records are added by a human in YClients for now. Tests:
  `tests/unit/test_group_booking.py`.
- 🔑 **SERVICE-FIRST is a CODE gate (added 2026-07-15).** Slots are NOT injected /
  shown until the client has named a service — even once the area is known.
  Live-caught 2026-07-15: a client said only "записаться на завтра", the agent asked
  the emirate and then DUMPED massage slots; the client actually wanted a manicure
  ("почему вы не спросили какая услуга?"). Prompt guidance said service-first but the
  LLM skipped it → now gated in `webhook_app.py`: if `area known && !service_named`,
  inject "ask the service first" instead of slots. `_service_named()` is broader than
  `_detect_service_category()` — it also recognises lashes / brows / facial cleansing
  (which the category detector doesn't route) so the gate never re-asks a client who
  already said what they want; a sticky `booking_data["service_named"]` flag survives
  later filler turns (villa/name) so it can't re-fire mid-flow. Test:
  `tests/unit/test_service_category.py::test_gate_replays_the_2026_07_15_bug`.
- 🌐 **Language = English by default, switch when the client can't follow it
  (revised 2026-07-15).** ⚠️ The earlier "English-only, mirroring removed" rule was
  labelled "owner decision 2026-07-09" but a forensic sweep of the WHOLE corpus
  (`feedback_log.json`, all 22 chat exports, meetings, requirements) found **NO client
  request for English-only** — it was OUR change (commit `7efe830`, author `utlik-pro`,
  2026-07-10; it replaced the original `MIRROR the client's language` prompt). On
  2026-07-15 the owner (Madam Crystal) complained the agent "keeps talking in English
  when clients write that they don't understand English." Current rule (`booking_agent.py`
  LANGUAGE block + the ARABIC sub-rule): reply in English by default, but if the client
  explicitly says they don't understand English / asks for RU/AR / keeps writing only in
  their language → **switch and continue the whole dialogue in that language**. A single
  foreign greeting ("Привет") is NOT a trigger — stay English. **Do NOT re-assert
  "always English no matter what".** Needs a live end-to-end check (see checklist).

### Cancel / reschedule — TEAM-MEDIATED again (DELETE is API-walled)
- ⚠️ **LIVE-PROVEN 2026-07-11: the YClients token CANNOT delete records.**
  `DELETE /record/{company}/{id}` → **403 «Нет прав на управление филиалом 1094806»**.
  POST (create) and PUT (move) work; DELETE does not. So **cancel cannot be
  automated** with the current token, and the "agent fully manages YClients"
  wording (14ed77b) was reverted: cancel + reschedule now say the HONEST
  team-mediated line ("passed to the team — we'll confirm shortly") + admin alert.
  **Do NOT re-enable "cancelled ✅"/"moved ✅" until the salon grants the token
  DELETE permission** — otherwise the agent lies (master drives to a cancelled visit).
- Reschedule MOVE (PUT) does work when the slot is genuinely free, but fails 409
  on an overlapping slot (a 90-min booking can't move to a time inside its own
  tail) and the handler creates a local booking before the move → local/YClients
  desync. Treat reschedule as team-mediated until hardened.
- 🔁 **Reschedule messaging + self-overlap fixed (2026-07-15).** Two live-caught
  bugs from Annette's «время есть, но не переносит»: (1) the agent sent a
  CONTRADICTORY pair — «передал перенос на 4:30 команде ✅» immediately followed by
  «4:30 не свободно». Root cause: `_enforce_reply_wording` promised "passed to the
  team" for ANY reschedule BEFORE `_handle_reschedule` re-checked availability.
  Fix: the turn's reply is now a NEUTRAL "one moment, let me check {time}" line;
  the DEFINITIVE outcome (passed-to-team OR "not free, here are alternatives") is
  sent by `_handle_reschedule` after the check. (2) The availability check counted
  the client's OWN booking as occupying the target → 4:00→4:30 was falsely blocked.
  Fix: `is_slot_available(..., exclude_record_id=)` drops the record being moved
  before computing free slots. Tests: `test_reply_wording.py`, `test_slots.py`.
- Owner still wants full automation (2026-07-10) — blocked on: (1) DELETE
  permission, (2) loyalty scope for packages. Both = salon-side YClients token grants.
- **HARD GUARD (do not weaken):** a record is only mutated when its client phone
  matches the WhatsApp client asking (`_phones_match`, last-9-digits). Other clients'
  records, admin records and emirate markers (no client) can never be touched; a
  mismatch/outage refuses and alerts the admin instead. Old bookings without a stored
  record id are resolved via `find_record_by_phone` (unique live match only).
- YClients record id is persisted on create (`set_yclients_id`); cancel/reschedule
  target through it. If the YClients mutation fails → admin alert «уберите/обновите
  вручную» + (reschedule only) an honest follow-up to the client.
- 🔔 **Cancel alert is LOUD + actionable (2026-07-15).** Because DELETE always 403s,
  removal is a MANUAL admin step — the record used to hang in the app (live-caught
  2026-07-14, Татьяна «после отмены запись висит»). The alert now leads with a
  «‼️ УДАЛИТЕ ЗАПИСЬ ВРУЧНУЮ В YCLIENTS» header + WHOSE calendar to open (master +
  emirate) + record id + the consequence. **Waiting-list notify is gated on
  `yc_deleted`** — a still-occupied slot must NOT be promised as free; the admin
  offers it to the waiting list after the manual removal.
- Agent wording (client-facing): cancel → HONEST team-mediated line "passed to the
  team — we'll confirm shortly" (NOT "cancelled ✅", which would lie while the record
  still exists); reschedule → "passed your reschedule to [time] to the team".
  Unconfirmed cancel still asks "shall I cancel?".
- With >1 active booking, don't guess which — the cancel/reschedule tools carry an
  `old_date`/`old_time` selector (the slot the client names, "move my 5:30 PM");
  `_match_booking_by_old_slot` picks the unique match, and ONLY an unresolvable
  ambiguity asks the client. (Before 2026-07-10 the clarifying answer had no path
  back → "which one?" looped forever — live-caught and fixed.)

## Reliability invariants (hardened 2026-07-09 — do NOT regress)
- **Outage ≠ day-off.** `get_available_times` returns **None** on a YClients API
  failure, `[]` only on a real empty schedule. `get_real_available_slots` returns
  None on outage. `get_available_slots_summary` says "SCHEDULE TEMPORARILY
  UNAVAILABLE… checking with the team" on outage (never a false "no availability").
  `is_slot_available` **fails OPEN** on outage (never blocks a real confirmed slot).
- **YClients HTTP has a 15s timeout** — a hung backend must not freeze a turn / hold
  the per-phone lock.
- **Client `area` is a DB column** (`clients.area`, auto-migrated) — persisted on
  capture, restored on a fresh context. In-memory + history-recovery are fallbacks.
- **Booking de-dup fingerprint (`last_booking_sig`) is set ONLY after a confirmed
  YClients sync** — a failed sync must stay retryable, not be suppressed as a dup.
  A failed or unresolved YClients create **alerts the admin** (never a silent log).
- **Slot-reality gate keys off `booking_call.area`** (authoritative), not the
  in-memory context area (which may be None → gate silently skipped).
- **Explicit-confirm is a CODE gate** (`_client_confirmed` + recap override in
  `webhook_app.py`): no record until the client's LAST message reads as a
  yes/confirm/да/подтверждаю. A premature "booked ✅" becomes the recap question
  "…Shall I confirm?". Proven live 2026-07-10 ([TEST] records #9/#10).
- **Admin mutation endpoints deny by default** — never open when `WEBHOOK_SECRET`
  is unset.
- **A deploy must not eat client messages.** Wappi webhooks are ACKed 200
  immediately — Wappi never redelivers. Render SIGTERM used to kill turns
  sitting in the 20s collect buffer or mid-LLM → dead air (live-caught
  2026-07-10 14:41: a push to develop redeployed prod exactly while a tester
  asked two questions). `_drain_wappi_turns` in `webhook_app.py` now flushes
  buffers + awaits in-flight turns on shutdown (22s, `WAPPI_DRAIN_TIMEOUT`);
  turns that can't finish get a "please repeat" nudge + admin-group alert. A
  flush exception also sends a fallback instead of silence. ⚠️ Corollary:
  **pushing to develop = instant prod deploy** — don't push while testers are
  mid-conversation.

## Pipeline auditor — the instrument toward "agent = full administrator"
- **North star (owner, 2026-07-11): the WhatsApp agent must work like a human
  administrator.** The 500+ YClients record comments admins write ARE the job
  description. `scripts/audit_pipelines.py --from --to` replays real dialogues
  (`logs/wappi_chats`) against real YClients state and reports two things,
  deterministically (pure logic, NO prompts/LLM — by owner requirement):
  1. **Regression** — say-do integrity (`booked ✅` ↔ real record; distinguishes
     phantom from moved-after-confirm), cancel/reschedule completion, manual-
     override (admin touched an agent booking = signal). Code: `services/pipeline_audit/`.
  2. **Gap-to-admin** — coverage map from comment taxonomy. First run
     (2026-07-11): agent covers **~16%** of admin workload. Biggest gap by far:
     **packages/абонементы = 58% of comments, agent is blind to them.**
- ⚠️ **Package data is API-walled:** `GET /company/1094806/loyalty/abonements`
  → 403 «Недостаточно прав» / 404. Two-track plan (owner-approved): parse the
  package counters admins write in comments ("5+", "ост. 150 мин") NOW, and
  Alina requests a loyalty-scope YClients token in parallel. Do NOT let the
  agent SPEAK package info until the parser is auditor-verified accurate.
- Auditor findings are FAIL / WARN / FLAG_HUMAN — free-text comment semantics,
  blame attribution and conversational quality are NOT logic-checkable → they go
  to a human-review queue, never a silent pass.
- Roadmap: v1 = #1 say-do / #6 manual-override / #7 cancel-reschedule + gap.
  v2 = #3 area-routing (record Area stamp vs staff emirate, marker-aware) + #4
  gate (confirm from dialogue, Address stamp from record). ⚠️ **#2 slot-replay is
  watchdog-only** — replaying "was the slot free" on a PAST date is meaningless
  (the schedule changed); it belongs in the continuous mode on future-dated
  offers, NOT historical batch. **#5 duration-fit via service titles is too noisy**
  (titles bundle multiple durations: "Cupping 15 + body 30") — v2.1 does it via
  dialogue-intent ("90 min") vs record seance_length instead. Next: comment-token
  cross-checks + watchdog wrap (launchd, dedup, alert Dmitry).

## Verification checklist before saying "done"
- [ ] Drove the FULL live conversation (service→area→slot→location→name→payment→confirm)
      and saw a correct YClients record created.
- [ ] Reschedule and cancel driven live.
- [ ] Slots verified against live YClients for the exact date/master.
- [ ] `pytest` green; pushed to `develop`; stated the deploy/prod caveat.

## Reference
- Model **gpt-5.4** (config.py default + local .env; also set in Render env
  `OPENAI_MODEL` — changing config does NOT change prod). Company id **1094806**.
- Admin group "Crystal Lab - Leads" `-1003250489002`. Dev group "Crystal разработка"
  `-5059625262`. Feedback auto-triage → Dmitry DM `1379584180`.
- Related memory: [[reference-area-routing]], [[reference-yclients-slots]],
  [[reference-feedback-monitor]].
