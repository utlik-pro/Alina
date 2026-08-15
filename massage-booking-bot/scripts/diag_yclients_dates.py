"""One-shot diagnostic: probe YClients schedule for the dates the bot
is reportedly mishandling (Wed 2026-04-29, Thu 2026-04-30).

Prints, for each relevant master:
  • whether they exist in staff
  • their full record (id, name, specialization)
  • result of get_available_dates(staff_id) — what YClients thinks is bookable
  • result of get_available_times(staff_id, date) for Wed and Thu
  • the same get_available_slots_summary the bot uses

This tells us whether the "I don't have info yet" comes from empty
schedule data on YClients side, or from our code mishandling a
non-empty response.
"""

import asyncio
import json
import sys
from pathlib import Path

# Allow running from project root without packaging
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.yclients_service import YClientsService


TARGET_DATES = ["2026-04-29", "2026-04-30"]  # Wed, Thu
NAME_HINTS = ["olesya", "alesya", "оле", "але", "farida", "фарид"]


async def main() -> int:
    yc = YClientsService()
    print("→ Loading staff...")
    staff = await yc.get_staff()
    print(f"   {len(staff)} staff members loaded\n")

    # Show every staff record briefly so we can spot Farida even if mistyped
    print("=== ALL STAFF (id | name | specialization) ===")
    for s in staff:
        print(
            f"  {s.get('id'):>6} | {s.get('name', '?'):<35} | "
            f"{s.get('specialization', '-')}"
        )
    print()

    # Filter masters of interest
    of_interest = []
    for s in staff:
        name_l = (s.get("name") or "").lower()
        if any(h in name_l for h in NAME_HINTS):
            of_interest.append(s)

    if not of_interest:
        print("⚠️  Could not find anyone matching Olesya/Alesya/Farida by substring.")
        print("    (Hints tried:", NAME_HINTS, ")")
    else:
        print(f"=== MASTERS OF INTEREST ({len(of_interest)}) ===")
        for s in of_interest:
            print(json.dumps(s, ensure_ascii=False, indent=2))
            print()

    # Probe schedule for each master of interest
    for s in of_interest:
        sid = s.get("id")
        name = s.get("name")
        print(f"\n=== SCHEDULE PROBE: {name} (id={sid}) ===")

        try:
            dates = await yc.get_available_dates(staff_id=sid)
            print(f"  available_dates ({len(dates)}): {dates[:30]}")
        except Exception as e:
            print(f"  available_dates → EXCEPTION: {e}")

        for date in TARGET_DATES:
            try:
                times = await yc.get_available_times(staff_id=sid, date=date)
                # Show count + first 5 raw entries
                preview = times[:5] if isinstance(times, list) else times
                print(f"  available_times {date}: count={len(times) if isinstance(times, list) else '?'}, sample={preview}")
            except Exception as e:
                print(f"  available_times {date} → EXCEPTION: {e}")

    # And the high-level summary that the bot actually feeds the LLM
    print("\n=== get_available_slots_summary (what the bot sends to LLM) ===")
    for date in TARGET_DATES:
        try:
            summary = await yc.get_available_slots_summary(
                date=date, service_name="lymphatic drainage"
            )
            print(f"\n--- {date} ---\n{summary}\n")
        except Exception as e:
            print(f"--- {date} → EXCEPTION: {e}")

    await yc.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
