"""End-to-end pipeline harness for the Crystal Lab WhatsApp agent.

Drives the REAL _process_wappi_message path per turn:
  - real OpenAI agent (process_message_with_tools)
  - LIVE YClients reads (staff / services / slots) via YClientsService
  - full webhook glue (area detection, slot injection, weekday persistence,
    booking guards, cancel/reschedule)

SAFETY:
  - YClients WRITE (create_booking) is stubbed → NO real records created.
  - Outbound WhatsApp is captured, not sent → no real messages.
  - Admin notifications are captured, not sent.

Usage:
  python3.11 scripts/pipeline_harness.py            # run all, print transcripts
  python3.11 scripts/pipeline_harness.py <name>     # run one scenario
  python3.11 scripts/pipeline_harness.py --json out.json   # dump transcripts JSON
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Scenarios: ordered client messages per pipeline ───────────────────
SCENARIOS = {
    "massage_abu_dhabi": [
        "Hello", "I want a body massage", "Abu Dhabi",
        "tomorrow please", "any of those is fine, the earliest",
        "Sara, Villa 12 Khalifa city", "cash",
    ],
    "nails_routing": [
        "Hi", "I'd like a manicure", "Abu Dhabi", "tomorrow",
    ],
    "al_ain_booking": [
        "Hi", "body massage please", "Al Ain", "tomorrow", "the first one",
        "Mariam, villa 4", "cash",
    ],
    "sunday_persist": [
        "Hi", "body massage", "Abu Dhabi", "can I do Sunday?",
        "Villa 23 Al Reef",   # no weekday word — must KEEP Sunday
    ],
    "second_booking": [
        "Hi", "body massage", "Abu Dhabi", "tomorrow, earliest", "Lina, villa 7", "cash",
        "thanks!",                       # must NOT re-book / go silent
        "actually I also want a face massage on Monday",  # NEW booking must be allowed
    ],
    "price_question": [
        "Hi", "how much is a body massage?",
    ],
    "reset_midflow": [
        "Hi", "body massage", "/clean",  # reset must clear + greet
    ],
    "cancel_flow": [
        "Hi", "I need to cancel my appointment",
    ],
}


class FakeWappi:
    """Captures outbound WhatsApp instead of sending."""
    def __init__(self):
        self.sent = {}
    async def send_message(self, phone, body):
        self.sent.setdefault(phone, []).append(body)
        return {"status": "ok"}
    async def close(self):
        pass


class FakeAdminBot:
    def __init__(self, sink): self.sink = sink
    async def send_message(self, **kw): self.sink.append(("admin_raw", kw.get("text", "")[:120]))


class FakeNotif:
    def __init__(self):
        self.events = []
        self.group_chat_id = "test"
        self.bot = FakeAdminBot(self.events)
    async def send_new_client(self, *a, **k): self.events.append(("new_client",))
    async def send_lead(self, *a, **k): self.events.append(("lead",))
    async def send_booking_request(self, *a, **k): self.events.append(("booking_request",))
    async def send_booking_confirmed(self, *a, **k): self.events.append(("booking_confirmed",))
    async def send_booking_failed(self, *a, **k): self.events.append(("booking_FAILED", str(k.get("reason", ""))[:100]))
    async def send_booking_cancelled(self, *a, **k): self.events.append(("cancelled",))
    async def send_medical_note_alert(self, *a, **k): self.events.append(("medical",))
    async def send_lost_client_alert(self, *a, **k): self.events.append(("lost",))


async def setup():
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_pipeline_test.db")
    from config import config
    config.DATABASE_URL = "sqlite+aiosqlite:///./_pipeline_test.db"
    import bot as bot_module
    import webhook_app
    from database import (
        init_db, ClientService, MessageService, BookingService,
        DialogSessionService, PackageService, WaitingListService,
    )
    from services.yclients_service import YClientsService

    db = init_db(config.DATABASE_URL)
    await db.create_tables()
    bot_module.client_service = ClientService(db)
    bot_module.message_service = MessageService(db)
    bot_module.booking_service = BookingService(db)
    bot_module.dialog_session_service = DialogSessionService(db)
    bot_module.package_service = PackageService(db)
    bot_module.waiting_list_service = WaitingListService(db)
    bot_module.notification_service = FakeNotif()
    bot_module.follow_up_service = None

    yc = YClientsService()
    # SAFETY: stub the WRITE so no real YClients record is ever created.
    async def _no_write(*a, **k):
        return {"id": 90000000, "test_stub": True}
    yc.create_booking = _no_write
    bot_module.yclients_service = yc

    fake = FakeWappi()
    webhook_app.wappi_client = fake
    return webhook_app, bot_module, fake, db


async def run_scenario(name, webhook_app, bot_module, fake):
    from dialog_context import dialog_manager
    phone = "9715" + str(abs(hash(name)) % 100000000).zfill(8)
    fake.sent.pop(phone, None)
    bot_module.notification_service.events.clear()
    dialog_manager.clear_context(f"wappi_{phone}")

    transcript = []
    for msg in SCENARIOS[name]:
        before = len(fake.sent.get(phone, []))
        try:
            await webhook_app._process_wappi_message(phone, msg, "Tester")
        except Exception as e:
            transcript.append({"client": msg, "bot": [f"‼️ EXCEPTION: {e}"]})
            continue
        replies = fake.sent.get(phone, [])[before:]
        transcript.append({"client": msg, "bot": replies})
    return {
        "scenario": name,
        "phone": phone,
        "transcript": transcript,
        "admin_events": list(bot_module.notification_service.events),
    }


def _print(result):
    print("\n" + "=" * 70)
    print(f"PIPELINE: {result['scenario']}")
    print("=" * 70)
    for turn in result["transcript"]:
        print(f"\n👤 {turn['client']}")
        for b in turn["bot"]:
            print(f"🤖 {b}")
    if result["admin_events"]:
        print(f"\n📋 admin: {result['admin_events']}")


async def live_drive(phone, messages, delay=14):
    """LIVE mode: drive a real conversation and SEND real WhatsApp replies via
    Wappi to `phone`. YClients WRITE is still stubbed (no real record). The
    client's messages are injected locally (they won't appear in WhatsApp),
    but the agent's REPLIES are real and visible to the recipient.
    """
    webhook_app, bot_module, _fake, db = await setup()
    from services.wappi_client import WappiClient
    from dialog_context import dialog_manager
    webhook_app.wappi_client = WappiClient()   # REAL sends
    dialog_manager.clear_context(f"wappi_{phone}")

    for msg in messages:
        print(f"\n[client→agent] {msg!r}")
        try:
            await webhook_app._process_wappi_message(phone, msg, "Dmitry Test")
            print("  ✅ agent replied (sent to WhatsApp)")
        except Exception as e:
            print(f"  ‼️ {e}")
        await asyncio.sleep(delay)

    await db.close()
    try:
        await webhook_app.wappi_client.close()
        await bot_module.yclients_service.close()
    except Exception:
        pass


async def main():
    args = sys.argv[1:]
    if args and args[0] == "--live":
        # scripts/pipeline_harness.py --live <phone> <scenario|msg1;msg2;...>
        phone = args[1]
        spec = args[2] if len(args) > 2 else "massage_abu_dhabi"
        msgs = SCENARIOS.get(spec) or spec.split(";")
        await live_drive(phone, msgs)
        return

    json_out = None
    if args and args[0] == "--json":
        json_out = args[1]; args = args[2:]
    only = args[0] if args else None

    webhook_app, bot_module, fake, db = await setup()
    names = [only] if only else list(SCENARIOS)
    results = []
    for name in names:
        r = await run_scenario(name, webhook_app, bot_module, fake)
        results.append(r)
        _print(r)
    await db.close()
    try:
        await bot_module.yclients_service.close()
    except Exception:
        pass
    if json_out:
        Path(json_out).write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n\n[wrote {json_out}]")


if __name__ == "__main__":
    asyncio.run(main())
