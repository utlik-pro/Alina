---
name: crystal-lab
description: Canonical business rules, gotchas and verification checklist for the Crystal Lab WhatsApp booking agent (home massage / nails / lashes, UAE). Invoke BEFORE touching massage-booking-bot — booking flow, slots, areas, service durations, hours, payment, cancel/reschedule — so a client rule is never lost and a косяк is never repeated. Also invoke when the client (Alina / Crystal Lab admins) states any new rule, to record it here.
---

# Crystal Lab — client knowledge base (single source of truth)

**Read this before touching `/Users/admin/Alina/massage-booking-bot/`.** Whenever the
client states a new rule, ADD it here in the same edit as the code change.

Scope: **WhatsApp path** — `webhook_app.py`, `agents/booking_agent.py`,
`agents/tools.py`, `services/yclients_service.py` — plus the **Instagram entry
point** (`services/instagram_client.py`, `agents/instagram_agent.py`).
`bot.py` (Telegram) is legacy.

### Instagram entry point — consult & funnel ONLY (owner request 2026-08-09)
- **Tool: official Meta "Instagram API with Instagram Login"** — free, no
  Facebook Page needed. Wappi does NOT support Instagram (WA/TG/Max/Авито/VK
  only), so IG runs on Meta directly. Sends via `graph.instagram.com`
  (config `INSTAGRAM_GRAPH_BASE`; switch to `graph.facebook.com` only if the
  Page-token flavor ends up used).
- **IG job = 2 things:** consult on services/prices (catalog straight from
  `prices.py`) and funnel to WhatsApp with a wa.me deep link (prefill carries
  the client's ask). **NO booking, NO slot/availability promises in IG** —
  the agent there has no YClients access; hard rule in the prompt.
- Route: `/webhook/instagram` in `webhook_app.py` (GET verify + POST, HMAC
  signature check, `mid` dedup against Meta redeliveries) → background
  `_instagram_consult_task` → `agents/instagram_agent.generate_ig_reply`
  (gpt via `OPENAI_MODEL`, per-sender in-memory history, ≤950 chars) →
  fallback to the static handoff line on ANY LLM failure.
- 🗣️ **LANGUAGE (client rule 2026-08-16, supersedes 07-15): English always;
  RUSSIAN is the ONLY allowed switch** (admins speak it; switch only when the
  client can't follow English — a lone «Привет» stays English). **Arabic or
  any other language → NEVER mirror it**: answer the substance in English and
  add "In English please 🙏" («чтобы мы потом смогли с ними общаться» — after
  the agent answered an Arabic ad-reply with a whole Arabic paragraph).
  Code-enforced both ways: `_is_non_english_script()` injects an
  English-only instruction on such inbound, `_enforce_english_reply()`
  replaces any non-English-script OUTBOUND with the polite English ask
  (Cyrillic exempt). Tests: `tests/unit/test_english_only.py`.
  Prices plain "350 AED" (no VAT math), payment only when asked.
- Go-live needs (user-side, Meta dashboard): IG professional account with
  message access allowed, Meta app + Instagram Login, webhook subscribed
  (verify token `INSTAGRAM_VERIFY_TOKEN`, default `crystal_lab_ig_2026`),
  Render env: `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_APP_SECRET`,
  `WHATSAPP_CTA_NUMBER`. Until tokens are set the code path is inert
  (logs the would-be reply). Tests: `tests/unit/test_instagram.py`.
- ⚠️ **Code lives on branch `feature/instagram-entry`** (commit 491fd82,
  2026-08-09, local only — not pushed) so develop/prod stays untouched;
  develop has only the old inert scaffold. Merge the branch before go-live.
- **Comment-to-DM** (keyword in a post comment → auto private reply) is NOT
  built yet. If wanted: embed in OUR webhook (subscribe the same Meta app to
  the `comments` field + private-reply API call) — do NOT deploy OpenReply
  (github.com/diwenne/openreply, MIT, comment-to-DM only, no AI/no dialogue;
  Next.js+Postgres+Redis+worker) as a second service: one Meta app has one
  webhook callback URL, a separate receiver risks stealing DM events from
  our consult agent. Its repo = reference implementation only.
- 🤝 **ManyChat = chosen IG front (owner decision 2026-08-09,** despite our
  direct-Meta recommendation — cost accepted). Bridge endpoint
  `/webhook/manychat` in `webhook_app.py`: ManyChat External Request POSTs
  `{"subscriber_id","text"}` + header `X-Manychat-Secret` (=
  `MANYCHAT_WEBHOOK_SECRET`, deny-by-default when unset) → returns flat
  `{"reply"}` AND ManyChat v2 dynamic-block. Same consult brain
  (`generate_ig_reply`), histories namespaced `mc:<id>`. ⚠️ When IG is
  connected through ManyChat, ManyChat owns the Meta webhook — do NOT also
  subscribe our direct `/webhook/instagram` app to the same account (double
  replies); the direct path stays as the no-ManyChat fallback. Needs
  ManyChat paid tier with External Request (Pro $29/mo — confirmed via the
  full plan-comparison table: API access is Pro+, Essential has only Google
  Sheets) + `MANYCHAT_WEBHOOK_SECRET` in Render env.
- ✅ **ManyChat side CONFIGURED & LIVE (2026-08-09, done via user's Chrome):**
  account fb5409282 (IG CRYSTAL connected, Pro TRIAL), automation
  "Instagram Default Reply": trigger User-sends-DM (every time, enabled) →
  External Request POST prod `/webhook/manychat` (auth = `"secret"` INSIDE
  the body JSON: `{"secret":"<MANYCHAT_WEBHOOK_SECRET>","subscriber_id":
  "{{Contact Id}}","text":"{{Last Text Input}}"}`, mapping `$.reply`→user
  field `ai_reply`) → **Condition `ai_reply isn't [SHADOW]`** → yes: message
  node sends `{{ai_reply}}`; no: flow ends silently. Bridge response is
  mapping-only `{"reply": ...}` (no v2 content — avoids double-render);
  shadow returns the `[SHADOW]` sentinel because ManyChat's mapper errors
  on empty strings ("Invalid value type in json path"). E2E verified 2026-08-11.
- 📋 **TATYANA'S RULES for the IG track (2026-07-28 thread, relayed
  2026-08-14 — client-confirmed, authoritative):**
  1. **Variant A confirmed: FULL booking inside Instagram Direct** — the
     phone number is collected as a data field (for the YClients record +
     morning follow-up), NOT to push the client to WhatsApp.
  2. Booking closing line (verbatim template): «Ваша запись сделана
     (краткая информация какая). Завтра с вами свяжется администратор и
     подтвердит запись.» Record is created in YClients marked as night/IG;
     admins confirm by phone in the morning (Tatyana calls clients herself).
  3. **Live window 21:00→08:00 Minsk** (= 22:00→09:00 Abu Dhabi; Tatyana
     still watches 21:00–23:00). Fixed in config default (0acd1b5).
     🔇 **ABSOLUTE DAYTIME SILENCE (fd043ea, owner demand 2026-08-15 after a
     stale reply reached a lead at 14:58).** Outside the window NOTHING may
     reach an IG client — consult replies, booking turns, confirmations,
     media nudges, **and appointment reminders** (owner: "напоминания
     оставь как есть — не напоминать, мы работаем с 21-8"). Enforced by
     FOUR independent guards; do NOT "fix" any of them back:
       a) routing in `/webhook/manychat` — window is mandatory, and the
          IG_TEST_SUBSCRIBERS whitelist NO LONGER bypasses it (it only
          bypasses IG_BOOKING_ENABLED, i.e. lets a tester rehearse booking
          at night while the flag is off);
       b) `_send_to_client()` refuses any `ig:` send outside the window —
          all 17 outbound call sites (incl. ReminderScheduler) funnel here;
       c) `manychat_send_text()` refuses at transport level;
       d) ManyChat flow itself: action **Set ai_reply = [SHADOW] BEFORE**
          the External Request (order matters — after it would erase the
          real night answer and mute the channel). Added manually in the
          ManyChat editor 2026-08-15; if the flow is ever rebuilt, restore
          this step first.
     Regression suite: `tests/unit/test_daytime_silence.py` (8 paths).
     Known accepted consequence: a dialogue still open at 08:00 gets no
     further replies, and IG clients get no reminders at all.
  3c. **NIGHT LOG — how to review a shift (67f4d2b, 3c3b5b8).** Render's
     log stream needs a CLI token that died 2026-06-16, and
     `logs/ig_turns.jsonl` is inside an ephemeral container, so the ONLY
     outside-readable trail is the in-memory ring (1000 events) served by
     `GET /admin/night-log?secret=$MANYCHAT_WEBHOOK_SECRET`. Morning retro:
     `python3.11 scripts/night_report.py` (add `--full` for every event).
     It prints contacts, per-kind counts, every booking with its YClients
     record id, all failures, and WHO WROTE BUT GOT NO REPLY. Events:
     inbound / routed_to_booking / sent / send_failed /
     send_blocked_daytime / booking_created. ⚠️ The ring is memory-only —
     a redeploy or restart wipes it, so pull the report BEFORE deploying
     anything in the morning.
  3e. **NAILS HAVE NO STAFF (observed 2026-08-15).** YClients lists 8
     massage therapists + 1 lash-maker (Бота) + a service "ЛИСТ ОЖИДАНИЯ"
     record — and NO nail tech at all (Elena/Safina are gone), while the
     price list still carries 35 nail/lash services and the welcome texts
     promise "Manicure and pedicure". A nails request therefore returns no
     availability. Owner decision: **leave the greetings as they are, just
     offer whatever is free — the admins will sort it out.** Do NOT edit
     the welcome/reset copy for this.
  3d. **CLOCKS — two different ones, on purpose (owner confirmed
     2026-08-15).** Everything the CLIENT experiences is UAE time: slot
     computation, quoted times, the YClients record, the local booking row,
     admin/driver alerts, the night log. The record is sent as
     `<date>T<UAE wall-clock>+03:00` because the YClients account is
     configured in UTC+3 while the salon types Abu-Dhabi wall-clock against
     it — verified against live records (2026-08-16T15:30:00+03:00 IS 15:30
     in the salon's calendar). Do NOT "fix" this into a real timezone
     conversion; that would move every night booking by an hour.
     The SHIFT WINDOW alone stays in Minsk time (21:00–08:00 Europe/Minsk =
     22:00–09:00 UAE) — owner declined switching it to UAE. Practical note:
     the "book for tomorrow → book for today" flip happens at 23:00 Minsk,
     because that is midnight in Abu Dhabi.
  3b. **HUMAN WINS THE CHAT (owner decision 2026-08-15).** If an admin has
     answered in a conversation, the agent does not butt in — the admin
     owns that dialogue. Implemented WITHOUT code, via ManyChat:
     Settings → Inbox Behavior → "Pause automations during conversations"
     = **3 hours** (was 30 min). Any reply an Inbox Agent sends pauses all
     automations for that contact, so our flow isn't even triggered; after
     3h of admin silence the agent picks the conversation back up. 3h was
     chosen because the admins' own follow-up cycle is ~2.5h (Fatima Tami
     15.08: 10:37 template → 13:12 "should we book?"), and it lines up with
     Tatyana watching until 23:00 while the night shift runs to 08:00.
     ⚠️ LIMITATION: the pause triggers on replies sent through the ManyChat
     Inbox. If an admin answers from the Instagram app directly, ManyChat
     may not register it as an agent reply and the pause may not fire —
     watch the first nights for a doubled reply and, if it happens, ask the
     team to answer from ManyChat (or add a tag-based guard).
  4. Lead alerts → the SAME group as WhatsApp leads (Crystal Lab - Leads).
  5. **Ad prefill texts (9)** identify service intent + emirate — do NOT
     re-ask the emirate: "I would like to consult on a massage and make an
     appointment in {Dubai|Abu Dhabi|Al Ain}" (тело/лицо); "Hello i would
     like to sign up for a massage package in {emirate} at a discount"
     (пакеты/«банки»); "Hello i would like to sign up for the summer
     promotion in {emirate}". Packages remain API-walled → package leads =
     collect contact + team-mediated handoff, no package prices from agent.
  6. **Pricing: NO discounts on manicure & lamination** («этих офферов
     НЕТ») — cancelled winter offers removed from prices.py (d0157e3);
     regular catalog prices apply.
     ⚠️ **PACKAGE PRICES (prices.PACKAGES: 5×60 1550 / 10×60 3000 / 6×90
     2590 / 5×face 1650 / 5×b+f 2200) are UNVERIFIED legacy data** — the
     client never confirmed them. Tatyana complained 2026-08-15 when the
     IG agent quoted them to a cupping-ad lead (they'd crept into the IG
     prompt via format_special_offers_for_prompt's package tail). Fixed
     (cca6747): include_packages=False for IG — the IG agent NEVER quotes
     course prices; "massage package at a discount" prefill → present the
     275 cupping combo + "courses are arranged personally by the team".
     WhatsApp prompt still carries the package list — awaiting the
     client's confirm/refresh; drop it there too if they disown it.
  6d. **Admin-practice facts + link dedupe (f2255d5, full-inbox read
     2026-08-15, ~82 chats / 15 full dialogues):**
     - PREGNANCY (Amira case): reassure — therapists with medical
       education, prenatal massage 350 AED/60 min; never refuse.
     - "Where is your studio?" (Sam Sam case): Abu Dhabi studio (Al
       Raha) temporarily closed for maintenance → home service, free
       transportation. Never invent a walk-in address.
     - "Can I pay by card?" (Viola case): simple "yes, we have a card
       machine" (terminal-on-request rule unchanged).
     - wa.me link is CODE-deduped (jwrrrrrry glued it to 4 replies):
       survives once per conversation, repeats stripped unless the
       client explicitly asks for the link again.
     - PRENATAL precisely: available AFTER 4 MONTHS of pregnancy (admin
       body-offer card «Prenatal after 4 months»); postpartum and
       after-surgery massage exist. All therapists = Russian certified
       FEMALE specialists (6160205 added both to the prompts).
     - Admin OFFER CARDS (their ready answers to "how much"): Body —
       350/60min + package 5×1550 + technique list (lymphatic,
       maderatherapie, anti-cellulite, postpartum, mixed, guasha, deep
       tissue, prenatal 4m+, aftersurgery); Face — «old 550 → NOW 370»
       + package 5×1650 + techniques (lifting drainage, buccal,
       myofascial non-surgical lift, signature mix — 50 min each).
       ⚠️ Face card + welcome say «Abu Dhabi and Alain» only, NO Dubai —
       ask Tatyana whether face works in Dubai (agent currently quotes
       face in all 3 emirates).
     - Admins also mass-broadcast copy-paste re-engagement to the whole
       subscriber base (2 waves 12.08, ~25 msgs, ≈0 replies) — dead
       instrument, do NOT replicate.
     - **COMBO 275 = 45 MIN — Tatyana's final word (2026-08-16),
       OVERRIDING the earlier 60.** Her exact rule: if asked what it
       includes — «30 минут массаж, 15 банки, 15 массаж головы. Все вместе
       45». Yes, the parts sum to 60; her TOTAL wins and matches the ad
       creative's 45. Quote the breakdown, book and promise 45. History:
       admins' 15.08 answer read as 60 (4cd593f), owner relay 16.08 said 60,
       Tatyana then corrected to 45 — do not flip it back without her word.
     - Arabic openers («مرحبا / ممكن احجز جلسة») are answered by admins in
       ENGLISH and the client keeps going in English and leaves a phone —
       supports our English-by-default policy (no auto-switch on a lone
       foreign greeting).
     - The number admins hand out in IG = 971551933662 = our
       WHATSAPP_CTA_NUMBER. Funnel is consistent; don't "fix" it.
     - Dead-end pattern to NEVER copy: «Our administrator will write to
       you in WhatsApp» sent WITHOUT asking for the number (sireenoo,
       Siobhán Forde, Gayatri — 3 cases in 4 days). The agent must always
       secure the contact before promising a handoff.
     - Clients DO give phones in Direct: 8 numbers in 4 days — collecting
       the contact inside Instagram is proven, no need to push to WA
       first.
     - ✅ PACKAGES RESOLVED by evidence (9f0b942), no Tatyana ping needed.
       The admins' rule, copied exactly: on the AD PREFILL "massage
       package at a discount" they NEVER quote course prices (template +
       ask for the number) — the prefill belongs to the cupping creative,
       so the agent answers 275. On a DIRECT client question ("do you
       have packages?") they DO quote, daily: 5×body 60min = 1550,
       5×face 50min = 1650 (hk.xx7 15.08, um mahra, محمد احمد, Hendaq).
       Agent now mirrors this. The other three legacy figures (10×60
       3000, 6×90 2590, 5×body+facial 2200) stay BANNED — no admin has
       ever used them; they are what Tatyana actually saw dumped on the
       cupping lead. Her complaint = the 5-line dump on a prefill, NOT
       course prices as such.
     - Admin follow-up pattern the agent LACKS: silent lead → "Hi. Can
       you update us? We have available slots for tomorrow. Should we
       book for you?" ~2.5h later; rejection → "Have a nice day dear ❤️".
     - Agent/admin overlap 21:00–23:00 is REAL and harmful: Diya case —
       agent answered price perfectly at 22:42, admin dumped the
       template on top, morning double push-up → "Sorry, will not be
       booking". Needs an owner decision (admins off at 21:00 or flag
       agent-handled chats).
  6c. **Admin-style consult flow (f36d45e, from 19 real dialogues):** broad
     prefill → greeting + ONE selling line («We come to your home — free
     transportation, top Russian therapists») + ONE clarifying question;
     quote only the asked service, offer-first; END WITH "Would you like
     to book?" — the wa.me link goes out ONLY after a yes (a question
     keeps the dialogue alive, a bare link kills it). Admin skeleton
     copied, their flaws dropped (they never answer the actual question,
     promise "slots today/tomorrow" without checking, and lose collected
     numbers — Meem/Su Guer cases).
  6b. **IG reply STYLE rules (Tatyana complaints 2026-08-15/16, f711a38):**
     broad ad opener → short greeting + ONE clarifying question (body or
     facial? — the "consult and make an appointment" prefill is SHARED by
     both campaigns, the ad creative is invisible to us), NO price dump;
     quote only the asked service (1–3 lines); cupping questions → lead
     with the 275 combo, not the 350 body price; wa.me link only on
     booking intent, max once per conversation, alone on the last line. ⚠️ Full CURRENT offer list (incl. what
     "summer promotion" contains) still needed from the client — Tatyana's
     price photos did not reach us.
  7. The July "Meta app access" request is OBSOLETE — the ManyChat path
     (authorized by Tatyana) replaced the direct Meta app.
  8. **Current prices confirmed 2026-08-14** (Tatyana's price cards): body
     350 / face 370 / deep cleansing 420 / lashes-brows unchanged; PMU new
     1000 (lips/brows/eyeliner), corrections 500, lashliner 800/400,
     recovery 1200; waxing eyebrow 80, zones 50, full face 200, brow
     shaping 80 — prices.py updated (07fb431). **«Банки 275» SOLVED
     (2026-08-14, ad creatives):** it's the 4th advertised offer —
     lymphatic drainage + cupping + head spa, 45 min, 275 AED (was 430).
     **The FOUR live ad creatives** (SPECIAL_OFFERS, 61894ab): deep
     cleansing 420 (was 770) · body 60' 350 (was 500) · face 50' 370
     (was 550) · lymph+cupping+headspa 45' 275 (was 430). Stale
     winter_body_combo removed; trial_session (350/80min) & book-a-friend
     kept (not cancelled). IG consult prompt now includes the offers +
     ad-prefill note (emirate from the ad text — never re-ask).
  8b. **PRICES RE-CONFIRMED FROM THE CLIENT'S OWN CARDS (2026-08-16).** She
     sent three cards + the four ad creatives and stated: «Тело 350, лицо 370,
     банки 275, чистка 2 часа 420… последние 4 фото — основные эти и реклама
     на них». Every card matched `prices.py` to the figure — permanent makeup
     9/9, face waxing 6/6, lashes & brows 11/11 — so PMU/waxing "changed" only
     relative to older lists, and she notes clients rarely ask about them.
     Two things did NOT match and were fixed (`1d7d683`):
     · **Deep facial cleansing is 120 min, not 90.** The catalog said 90 while
       the offer entry and her creative both say a 2-hour treatment — a
       booking made from the catalog reserved half an hour too little and the
       therapist walked into an overlap.
     · **"Summer promotion" = the four advertised creatives** (deep cleansing
       420/770 · body 60' 350/500 · face 50' 370/550 · lymph+cupping+headspa
       275/430). This ANSWERS the long-open "what is in the summer promotion".
       `trial_session` (350/80 min) and `book_a_friend` are NOT advertised —
       `format_ad_offers_for_prompt()` serves only the four, because the agent
       had been presenting the trial session as a current campaign.
     · Nail prices stay CURRENT and quotable; only the nail *discount* offer is
       withdrawn, and there is still no nail master.
     ✅ **BOTH FOLLOW-UPS ANSWERED BY THE OWNER 2026-08-16:**
     · **Cupping combo 275: SUPERSEDED — Tatyana corrected it to 45 MIN
       later the same day** («45 минут банки… все вместе 45»); the creative
       was right after all. prices.py duration=45, IG brief quotes the
       30+15+15 breakdown with a 45 total. See the entry above.
     · **`lash_brow_combo` (lamination + lifting, 350) is WITHDRAWN** — it is
       not on her lashes card. Removed from the catalog, the prompt, the
       upsell in `follow_up.py` and the legacy Telegram branch; the two
       services are quoted separately now.
  9. **No nail master at the moment** (Tatyana 2026-08-14): nail catalog
     prices are correct and quotable, but nail bookings can't be fulfilled
     right now — YClients will simply show no nail slots (fails honest);
     do NOT hardcode "no master" into prompts, it will rot when hiring.
- 🌙 **First night (11→12 Aug): agent LIVE 21:00→09:00 worked.** 2 clean live
  consults (exact prices + wa.me link + context across turns: Vishnu Priya
  21:06, Jess Ann Joseph 22:04); shadow correctly silent before/after the
  window (lizaxjones 09:13 → [SHADOW], no send). **1 bug found+fixed:**
  a 3-line client message broke ManyChat's body template ("Invalid payload
  json" ~08:50, client joja got no reply) → fix deployed (330b441):
  endpoint pulls last_input_text via ManyChat API when the payload has no
  text. ✅ ACTIVATED 2026-08-12: `MANYCHAT_API_KEY` in Render env, flow body
  switched to ids-only `{"secret":"...","subscriber_id":"{{Contact Id}}"}` —
  raw client text never rides the body template anymore. Also 2026-08-12:
  wa.me link slimmed (static prefill only, link on its own last line —
  owner feedback: URL-encoded client question looked monstrous in IG).
  ✋ **OWNER DECISION 2026-08-12: WHATSAPP_CTA_NUMBER stays = 971551933662
  (live admins' number) — deliberately.** IG leads go to HUMAN admins in
  WhatsApp who book manually; the IG agent consults + funnels only. Do NOT
  "fix" this to the Wappi agent number without a new owner decision (the
  option is known: switching the env var would make the booking agent
  handle IG leads end-to-end).
  Admin night style observed: humans write "Our administrator wrote to you
  in WhatsApp" / "Dear check please WhatsApp" — don't confuse with agent
  output when auditing (agent replies always carry prices/wa.me per prompt).
  ⚠️ ManyChat editor gotchas (live-fought 2026-08-11): (1) **header VALUES
  silently never persist** (key does; value field = token-input that drops
  uncommitted text) → auth secret lives in the request BODY
  (`{"secret": ...}`; endpoint also accepts ?secret= and the header —
  commit 68bbc72). (2) **Inserting text next to a variable chip hijacks
  typing into the chip's "Variable Type" editor** and everything vanishes
  on save — to edit the body, RETYPE THE WHOLE LINE from scratch (cmd+a →
  type → chips via "{+} Add a Field" → Save immediately, no tab switches);
  verify by reopening the dialog (body IS shown on reopen, headers aren't).
  (3) Escape closes the whole dialog, not the popup. (4) External Request
  worked fine on the TRIAL Pro (docs said it might be blocked — it wasn't;
  the "Forbidden" in Settings→Logs was OUR 403 from the empty header).
  (5) IG track LIVE window = 21:00→09:00 Europe/Minsk (`IG_ACTIVE_*`),
  otherwise SHADOW: reply generated + logged ([IG-SHADOW] in Render logs +
  logs/ig_turns.jsonl, ephemeral), nothing sent — bridge returns empty
  messages. Render env has `MANYCHAT_WEBHOOK_SECRET` + `WHATSAPP_CTA_NUMBER`
  (added by user 2026-08-11). E2E verified: real DM → trigger fired →
  request hit prod (first with 403 → fixed via body secret → 200 shadow).
  ⚠️ Render CLI log stream died AGAIN 2026-08-11 (AUTH DEAD, token rot) —
  ig_turns visibility on prod needs the token refreshed or /admin/logs.
- 🚧 **IG BOOKING (variant A) — IN PROGRESS since 2026-08-14.** Stage 0
  DONE (728ca6e): `manychat_send_text()` via Sending API + async bridge
  path behind `IG_ASYNC_SEND`; media/voice DMs get a "type it as text"
  nudge. **Stage 1 DONE (8affec4): ig:<subscriber> identities flow through
  the ENTIRE WhatsApp booking pipeline** — same buffering/locks/context/
  gates/YClients/alerts, zero forked logic. Seams: `_send_to_client()`
  channel router (ig:→ManyChat Sending API, numbers→Wappi, 15 call sites);
  `ig_<id>` telegram_id (scheduler phone-derivations safely yield None);
  **PHONE GATE** (IG-only): reply override asks for the number after
  loc/name and before confirm + binding ≥9-digit record block in
  `_maybe_create_booking`; the ig-key NEVER leaks into YClients/clients.
  phone — only booking_call.client_phone; YClients comment = "Instagram
  agent booking (night) + Phone"; IG prompt brief (collect phone, close
  with Tatyana's template, no wa.me in booking channel). Bridge routes to
  booking ONLY when `IG_BOOKING_ENABLED` && live window; day = consult/
  shadow as before. BOTH FLAGS OFF — prod unchanged. **Stage-3 sims DONE
  2026-08-14 (42c3ad0):** sim_conversation grew `"channel": "instagram"`
  (shared `_ig_channel_brief()` — one source with prod); two gpt-5.4 runs
  against live YClients passed: ad-prefill path (emirate not re-asked,
  real per-master slots incl. the Dubai floater, phone asked before
  payment) and the gate path ("yes, confirm" with no number → phone
  question, record only after the number). `IG_TEST_SUBSCRIBERS` env (csv
  of ManyChat ids) = tester whitelist: full booking pipeline at ANY hour,
  YClients records forced [TEST]. Live E2E via Dmitry's IG (subscriber
  868311272): add IG_TEST_SUBSCRIBERS=868311272 to Render env; the first
  live reply also verifies manychat_send_text (Sending API) for real.
  Watch in live test: Tatyana's closing template after the record (sim
  couldn't verify it — duplicate-suppress kicked in) and the weak
  greeting-only first turn. Model = the WA booking_agent's (gpt-5.4).
  Packages still blocked on the loyalty-scope YClients token; comment-to-DM
  = ManyChat built-in trigger (needs client's keywords/posts).
- ✅ **IG BOOKING PROVEN LIVE END-TO-END (2026-08-15, 23:00 Abu Dhabi,
  record #1908955686).** Driven from Dmitry's own Instagram through the whole
  flow: ad prefill → one clarifying question (body/face) → duration → real
  slots → typed address + name → payment → **phone gate** → explicit confirm →
  YClients record. Verified against the live calendar: `2026-08-22T19:00+03:00`
  (UAE wall-clock per the clock rule), 3600 s, Makhabat (Abu Dhabi), client
  phone from the dialogue (the `ig:` key never leaked), comment `[TEST]
  Instagram agent booking (night) #20 … Area … Address`, and Tatyana's closing
  template. Slots were re-checked against YClients afterwards — every time the
  agent offered was genuinely free. `IG_BOOKING_ENABLED=true` is now set
  GLOBALLY in Render (not just for the tester whitelist).
  **Four defects the run exposed, all fixed in `1f8d609`:**
  1. 💵 **Payment terms silently disappeared.** The brevity rules stripped
     "(tax free)"/"(+5% VAT)" off the menu, the model's own recap quoted a bare
     "350 AED" for a bank-transfer booking, and the confirmation then said
     "368 AED" (`base * 1.05`) — the client agreed to one number and was
     confirmed at another, and the VAT arithmetic is explicitly forbidden by
     the prompt itself. Now CODE-enforced (`_enforce_payment_terms`, applied to
     every outgoing reply): a bare menu line regains its label; once the client
     has chosen a method every later price carries that footnote; prices quoted
     BEFORE the choice stay clean (consult phase). The confirmation quotes the
     BASE price. Sticky `booking_data["payment_method"]`. Tests:
     `tests/unit/test_payment_terms.py`.
  2. 📞 **The morning caller was blind to the payment method** — it never
     reached the YClients comment, though the admin phones the client to
     confirm and cash vs transfer differ by 5%. Now `Payment: …` is in the
     comment (both channels).
  3. 📍 **"Share your location 📍" is a dead end in Instagram** — an attachment
     never reaches the bridge (ManyChat passes text), so a pin only earns the
     client a "type it as text" nudge. IG now asks for a TYPED address (code
     gate + brief); WhatsApp keeps the pin, which works there.
  4. 👤 **The night log lost the therapist** on every IG booking: the event read
     `staff_name`, a field that never existed on the tool call (it is
     `master_name`), and IG deliberately never names a therapist to the client.
     Now resolved from the staff id actually booked.
  ✅ **NOT a defect (checked):** "body massage" mapping to the YClients service
  *"Lymphatic drainage 60 min (new)"* is deliberate — `yclients_service.py:525`
  documents it as the catalog's default body offer in the new price list.
  ⚠️ **The test record #1908955686 could NOT be deleted** — `DELETE
  /record/1094806/{id}` still answers **403 «Нет прав на управление филиалом»**
  (re-verified 2026-08-15), and `record_hash` (the client-side cancel path) is
  not stored at creation. It must be removed by hand in YClients. Consider
  persisting `record_hash` from the create response — it may unlock
  `DELETE /user/records/{id}/{hash}` without a new token grant.
- 🔴 **REAL LEAD HIT THREE BUGS AT ONCE (2026-08-15, 23:14 Abu Dhabi,
  subscriber 135906395)** — the night's most valuable evidence, caught only
  because a snapshot happened to be taken. He arrived on the PACKAGE ad
  prefill ("sign up for a massage package in Abu Dhabi at a discount"), asked
  "tell me about both", and was answered with **1,550 / 3,000 / 2,590 / 1,650
  in one dump plus the payment menu** — never seeing the 275 combo he came
  for. No booking. Whether he replied after 23:15:33 is unknowable: three
  deploys wiped the ring. Fixes, all live:
  · **Unverified package prices can no longer be spoken** (`afd1f85`).
    `PACKAGES` entries now carry `quotable`; only 5×60 = 1,550 and 5×50 face =
    1,650 (the two the admins quote daily) reach the prompt, followed by "any
    other course length is arranged personally by the team". 3,000 / 2,590 /
    2,200 stay in the file as data, unspoken, until the client confirms them.
    ⚠️ Root cause worth remembering: `include_packages=False` on the CONSULT
    path was never enough — IG **booking** runs on the WhatsApp
    `booking_agent` prompt, which carried the full list.
  · **The ad creative is now detected and remembered** (`83427b8`,
    `_detect_ad_prefill` → sticky `booking_data["ad_prefill"]`). The prefill
    lands in message #1 while the price question comes two turns later, so a
    per-turn read was useless. On the package prefill the cupping combo (275,
    was 430, 60 min) is injected as the offer to lead with. `summer` is
    detected but has NO content — the client's summer-promotion prices still
    have not reached us.
  · **A merged slot offer is presentation, not truth** (`62a5787`). The agent
    told a client 7:00 PM was unavailable on a day it was free (verified:
    `is_slot_available` → True, Nina) because the "merge everything into 3–4
    times" rule made anything outside its own short list read as non-existent.
    When the client names a concrete time and the date is known, that exact
    time is now checked against YClients on the same turn and the verdict is
    injected as ground truth.
  · ⚠️ **A prompt line that says HOW without saying WHEN moves the step**
    (`07509d8`). Two "wording only" additions (type the address / how the
    payment menu reads) made the model ask for the address instead of showing
    times, and offer payment next to the price list. Any new wording rule must
    name the step it belongs to and say it is not a new step.
- ⚠️ **DO NOT DEPLOY WHILE THE WINDOW IS LIVE unless the fix is worth it.**
  Every push restarts Render: the night-log ring dies (evidence gone) and an
  in-flight ManyChat request can be dropped, so a real client's message
  vanishes without a trace. On 2026-08-15 five pushes landed between 21:40 and
  23:00 Minsk. If a push is unavoidable, snapshot first —
  `python3.11 scripts/night_report.py --full > logs/night_snapshots/<date>_<tag>.json`.
- 🚫 **OUT-OF-AREA = GRACEFUL GOODBYE, NOT A FUNNEL (client rule 2026-08-16,
  Sharjah screenshot: «зачем спрашивать какой сервис… можно попрощаться
  красиво и всё»).** After "we don't work in Sharjah" the agent asked "what
  service are you interested in?" on the client's "Okay". Now sticky
  `booking_data["out_of_area"]` (`_detect_out_of_area`: Sharjah/Ajman/RAK/
  Fujairah/UAQ + RU spellings): first turn = warm refusal naming our three
  cities, every later turn = ONE short goodbye («If you are ever in Abu
  Dhabi, Al Ain or Dubai — we would be happy to pamper you 🙏»), no service
  questions/prices/times. Naming a served emirate lifts the flag and the
  funnel resumes. Sim mirrors it; replayed the exact dialogue — all three
  states correct. Tests in `test_english_only.py`.
- 🎁 **COMBO CHOICE FIXES THE DURATION (night 2, 2026-08-16).** A hot lead
  chose the 275 offer ("I like the special offer / Cupping") and the duration
  gate asked "60 or 90 min dear?" — nonsense for a fixed 30+15+15 session; the
  client answered "But it includes massage" and left. Now
  `_detect_combo_choice()` (client says special offer / 275 / cupping / банки /
  hijama) sets `service_type=lymphatic_cupping_combo` + `duration=60` in CODE,
  the combo key deliberately does NOT match `_is_massage_service` so neither
  massage gate fires, the anti-downgrade shield covers it, the IG brief says
  "never ask 60-or-90 for the combo", and YClients books it onto the
  lymphatic-drainage 60-min service (no combo entry exists; the comment
  carries the contents). Replayed the lost dialogue in the sim — the lead now
  reaches day/time. Also that night: "lead with 275 on the package prefill"
  is only half-obeyed (first reply often quotes 1,550/1,650 without 275) —
  known, minor, prompt-level.
- 🌃 **FIRST AD NIGHT (17→18.08): 10 contacts, 33 replies, 0 send failures,
  0 bookings; one lead reached the name step and went silent.** Two leads
  wrote minutes BEFORE 21:00 and never returned — messages arriving before
  the window are NOT reprocessed at open (known edge; catch-up = backlog
  candidate). «سلام» got English + "In English please 🙏" live ✅. Two prompt
  disobediences found and made DETERMINISTIC (day deploy 18.08):
  · package prefill answered with 1,550/1,650 and NO 275 in all three night
    cases → `_enforce_package_offer_first()` prepends the offer to any
    package-priced reply that lacks it;
  · "Deep Facial cleansing in Abu Dhabi?" was answered "50 min - 370" (the
    FACIAL MASSAGE pair) → a cleansing keyword in the client text now pins
    the facts (120 min / 420 / was 770) in the context.
  Night evidence archiver: `scripts/archive_night_log.py` + launchd
  `com.crystal-lab.night-archive` (every 5 min → logs/night_archive/<shift
  date>.jsonl, restart-proof, dedup by ts+kind+who+text).
- 📌 **DETAILS ARRIVE IN ANY ORDER — NEVER RESTART THE FUNNEL (client
  complaint 2026-08-16: «она уже дала номер, зачем по второму кругу диалог
  вести?»).** A typed UAE number (`_detect_phone_in_text`, any spelling →
  +9715XXXXXXXX) is captured the moment it appears — client record + phone
  gate see it, it is never asked again. Every turn injects an ALREADY-KNOWN
  recap (phone/name/city/service/duration/date) with «continue from the
  FIRST missing step». Sim mirrors both.
- 🧴 **FOURTH AD PREFILL = DEEP CLEANSING (Tatyana 2026-08-16, screenshot):**
  the text «Hello, I want to know the details about the promotion and get
  advice» is ALWAYS the deep-cleansing creative — «видим этот текст —
  скидываем чистку и дальше ведём диалог». `_detect_ad_prefill` → "cleansing";
  the injected instruction leads with 420 AED instead of 770 (8 steps, 2 h,
  medical education) and FORBIDS listing the other promotions (the agent was
  dumping all five — that was the complaint). ⚠️ This prefill carries NO
  emirate — ask the city later in the normal flow. Audit covers it
  (MISSING 420 check); sim mirrors it.
- 🧠 **PERSISTENT MEMORY SHIPPED (2026-08-18, fc292d3+eaf2461) — the deploy
  amnesia is over.** Research proved every deploy wiped EVERYTHING: Render
  env had `DATABASE_URL=sqlite:////data/…` with NO disk behind it (disks API
  404), the night ring lived in RAM, ig_turns.jsonl in the container. Twelve
  deploys in three days = twelve total wipes (dialogue history, client
  fields, bookings, telemetry) — the real root of «зачем по второму кругу».
  Now: **managed Postgres `crystal-lab-db` (dpg-da23u9u417fc73bvnlmg-a,
  basic_256mb/1GB, oregon, PG16, ~$7/mo)**; DATABASE_URL switched to
  `postgresql+asyncpg://` (old value backed up in
  `~/.render/old_database_url.backup`; external conn string in
  `~/.render/crystal_db_external.txt`; Render API key in
  `~/.render/manual.key`). Service created all 7 tables on boot. Plus:
  `NightEvent` table — `_night_event` fire-and-forgets every event to
  Postgres (ring stays as fast fallback), `/admin/night-log` reads the DB
  first and reports `source: db|ring`; the daytime shadow path now persists
  client inbound into message history (night agent finally knows the
  daytime context). E2E-proven: probe event → full redeploy → still there.
  ⚠️ Gotcha: `get_db()` returns the Database object — sessions via
  `async with get_db().session() as db:`, NEVER `async for`.
  ⚠️ Local sqlite `crystal_lab.db` stays for dev only.
  🔴 STILL OPEN: Render workspace shows «Payment failed» — update the card
  or the whole service (and this DB) gets suspended.
- 🎯 **INSTAGRAM IS THE MAIN CHANNEL NOW (owner, 2026-08-16: «сейчас у нас
  главное это инстаграм»).** All effort goes to the IG night shift. The
  WhatsApp (Wappi) agent channel is DORMANT: the subscription lapsed
  2026-07-24 («Profile not paid») and nobody noticed for 3+ weeks — the
  channel carried no real client traffic (archive: July follow-ups to
  testers, no replies). The number on the price cards (+971 55 193 36 62)
  is the ADMINS' own WhatsApp, not the agent's — card clients reach live
  admins as before. The local chat-puller launchd job is UNLOADED (it had
  5,662 consecutive fails). Prod keeps WAPPI_* env harmlessly; WA-side
  follow-ups/reminders are off with it. To revive a WhatsApp agent later:
  pay the Wappi profile, rescan the QR, then
  `launchctl load ~/Library/LaunchAgents/com.crystal-lab.wappi-pull.plist`.
- 🌙 **OUR SCOPE = THE NIGHT SHIFT ONLY (owner decision 2026-08-16).** Daytime
  IG leads are the admins' territory: do NOT send lead alerts about daytime
  messages, do NOT propose replying to them, do NOT touch daytime ManyChat
  conversations — «днём мы не лезем, там админы порешают». The morning retro
  reviews the night's QUALITY (agent replies inside the window); daytime
  inbound in the log is context, not a task list. Lead alerts to the group
  remain what the agent itself sends at night for its own bookings/failures.
- 🛡️ **SLOT-REALITY GATE on every outgoing reply (`c8630ad`, 2026-08-16) — the
  night's deepest three-layer find.** Auditing all nine ad prefills against
  live YClients (`scripts/audit_ad_prefills.py` — prices AND offered-times
  dimensions, 9/9 green) uncovered, layer under layer:
  1. The model OFFERED FOUR TIMES FOR AN EMPTY DAY (Al Ain 20 Aug) despite the
     injected "do NOT invent times". Now `_enforce_slot_reality()` checks every
     AM/PM time in the outgoing text against `context.slot_truth` (captured at
     injection) and rewrites invention into the honest answer — the day's real
     times, or "fully booked + nearest real day". Outage judges nothing.
  2. Beneath it: **the body-or-face gate never released** — the category
     detector only yields generic `massage`, nothing upgraded it, so slots
     were never injected and the model free-styled. The client's "body
     massage" answer now upgrades `service_type→body_massage` (duration
     survives; no downgrade back). The gate itself also now answers a price
     question first instead of repeating itself (the client asked "how much?"
     three times and never heard a number).
  3. Beneath that: **a YClients 429 masqueraded as an empty day** — `get_staff`
     returned [] on outage and two summary early-exits skipped the outage
     wording. `_get` now honours the 429 retry hint once; `get_staff` returns
     None on outage; both exits say TEMPORARILY UNAVAILABLE. ⚠️ Never run
     parallel sims against live YClients (the audit defaults to `--jobs 1`).
  Tests: `tests/unit/test_slot_reality.py`. ✅ Validated live minutes after
  deploy: real IG lead 00:28 «I want deep facial cleaning» → «120 min —
  420 AED. Would you like to book dear?» (new duration, right price, 25 s).
- 👁️ **Watch a shift live:** `python3.11 scripts/watch_night_log.py --who
  <subscriber> [--seconds N]` tails `/admin/night-log` and prints only new
  turns (stops on `booking_created`). `night_report.py` stays the morning
  retro. ⚠️ **Deploys blind the log:** three pushes between 21:13 and 21:42
  Minsk on 2026-08-15 wiped the in-memory ring for that half-hour of the LIVE
  window — if a real client wrote then, there is no trace at all. Snapshot the
  ring (`night_report.py --full > logs/night_snapshots/…`) before every push
  during a shift.
- 🧠 **IG/ManyChat model = `gpt-5.4`** via `IG_OPENAI_MODEL` — UNIFIED with
  the WhatsApp brain (owner decision 2026-08-14, was gpt-5.6-sol Aug 9–14).
  ⚠️ **gpt-5.6-sol CANNOT drive the booking tools**: chat/completions 400s
  ("function tools with reasoning_effort are not supported … use
  /v1/responses or reasoning_effort='none'") — bake-off 2026-08-14, every
  turn fell to the error fallback. Don't retry sol for tool paths without
  migrating to the Responses API first.
- Competitors assessed 2026-08-09: **Brevo** — no Instagram at all
  (email/SMS/WhatsApp/site-chat only). **ChatPlace** — own AI only
  (Creator $45/mo, ~3000 AI msgs), no documented custom-LLM webhook →
  can't run OUR brain. (`MANYCHAT_API_KEY` in config.py is a dead
  early-iteration stub, still unused; the bridge uses only the secret.)

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
