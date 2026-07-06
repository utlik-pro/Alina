"""End-to-end verification of the BOOKING pipeline into YClients.

Runs the REAL _maybe_create_booking path (find_service_id + find_staff_id +
YClients create) against a genuinely FREE slot, then reads the record back
from YClients to confirm it landed at the right master/time/service.

The record is marked [TEST] (YCLIENTS_TEST_BOOKINGS=true). It is a REAL row in
the salon calendar — the bot cannot delete it (safety rule), so an admin must
remove it afterwards. The script prints the record id to delete.
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ["YCLIENTS_TEST_BOOKINGS"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_bk_verify.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _FakeWappi:
    async def send_message(self, phone, body): return {"status": "ok"}
    async def close(self): pass


class _FakeNotif:
    group_chat_id = "t"
    def __init__(self): self.events = []
    class _Bot:
        async def send_message(self, **k): pass
    bot = _Bot()
    async def send_booking_confirmed(self, *a, **k): self.events.append("confirmed")
    async def send_booking_failed(self, *a, **k): self.events.append(("FAILED", str(k.get("reason", ""))[:120]))
    async def send_medical_note_alert(self, *a, **k): pass
    async def send_new_client(self, *a, **k): pass


async def main():
    from config import config
    config.DATABASE_URL = os.environ["DATABASE_URL"]
    import bot as bot_module
    import webhook_app
    from database import (init_db, ClientService, MessageService, BookingService,
                          DialogSessionService, PackageService, WaitingListService)
    from services.yclients_service import YClientsService
    from dialog_context import dialog_manager
    from agents.tools import BookingCall
    from datetime import datetime, timedelta, timezone

    db = init_db(config.DATABASE_URL)
    await db.create_tables()
    bot_module.client_service = ClientService(db)
    bot_module.message_service = MessageService(db)
    bot_module.booking_service = BookingService(db)
    bot_module.dialog_session_service = DialogSessionService(db)
    bot_module.package_service = PackageService(db)
    bot_module.waiting_list_service = WaitingListService(db)
    bot_module.notification_service = _FakeNotif()
    bot_module.follow_up_service = None
    yc = YClientsService()                 # NOTE: create_booking NOT stubbed
    bot_module.yclients_service = yc
    webhook_app.wappi_client = _FakeWappi()

    uae = timezone(timedelta(hours=4))
    tomorrow = (datetime.now(uae) + timedelta(days=1)).strftime("%Y-%m-%d")

    # Pick a real massage master in Abu Dhabi + a genuinely free slot.
    MASTER_ID, MASTER = 3853586, "Natalia"   # Наталья
    slots = await yc.get_real_available_slots(MASTER_ID, tomorrow, 60)
    print(f"Free slots for {MASTER} on {tomorrow}: {slots}")
    if not slots:
        print("No free slots — cannot verify. Try another master/date.")
        await yc.close(); await db.close(); return
    pick = next((s for s in slots if 11 <= int(s.split(':')[0]) <= 15), slots[len(slots)//2])
    print(f"Booking a [TEST] appointment: {MASTER} {tomorrow} {pick}, body massage 60min, cash")

    bc = BookingCall(
        service="body_massage", duration_minutes=60, date=tomorrow, time=pick,
        area="abu_dhabi", payment_method="cash", client_name="[TEST] Pipeline",
        base_price_aed=350.0, master_name=MASTER, client_phone="375000000001",
    )
    user_id = "wappi_375000000001"
    ctx = dialog_manager.get_or_create_context(user_id)
    await bot_module.client_service.get_or_create_client(user_id)

    await webhook_app._maybe_create_booking(
        user_id, user_id, "375000000001", "Test", ctx,
        f"Your body massage is booked ✅", bc,
    )
    print(f"admin events: {bot_module.notification_service.events}")

    # Read back from YClients — did the record land?
    recs = await yc.get_records(MASTER_ID, tomorrow)
    hit = None
    for r in (recs or []):
        cl = (r.get('client') or {}).get('name', '')
        if '[TEST]' in cl or (r.get('datetime', '').endswith(f"{pick}:00+03:00")):
            hit = r
    print("\n=== VERIFY ===")
    if hit:
        svc = (hit.get('services') or [{}])[0]
        print(f"✅ RECORD CREATED IN YCLIENTS:")
        print(f"   id={hit.get('id')} datetime={hit.get('datetime')} "
              f"len={hit.get('seance_length')}s")
        print(f"   staff={hit.get('staff',{}).get('name')} "
              f"service={svc.get('title')} cost={svc.get('cost')}")
        print(f"   client={(hit.get('client') or {}).get('name')}")
        print(f"\n⚠️  DELETE THIS [TEST] RECORD IN YCLIENTS: id={hit.get('id')}")
    else:
        print("❌ NO record found — booking pipeline FAILED to create in YClients")
        print(f"   (records on {tomorrow} for {MASTER}: {len(recs or [])})")

    await yc.close()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
