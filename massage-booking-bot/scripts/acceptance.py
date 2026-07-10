#!/usr/bin/env python3
"""Acceptance battery for the Crystal Lab WhatsApp agent.

Drives the REAL BookingAgent through a curated set of conversations (same code
path as prod: per-turn area/service/duration detection, real-YClients slot
injection, code-level wording override). SAFE — never creates a YClients record
(it only tags whether one WOULD be created).

Run:  python3.11 scripts/acceptance.py
      python3.11 scripts/acceptance.py 3        # only scenario #3

Each scenario prints WHAT-TO-EYEBALL so a human can verify the fix held.
"""

import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from scripts.sim_conversation import run  # reuse the faithful driver

SCENARIOS = [
    {
        "title": "1. Massage happy path (gate: location→name→payment→confirm)",
        "check": "Books ONLY after location+name+payment+explicit yes; [RECORD CREATED]; 90m=460 AED.",
        "turns": ["Hi", "body massage 90 min", "Abu Dhabi", "earliest please",
                  "Sarah", "cash", "yes confirm"],
        "gps_at_turn": 4,
    },
    {
        "title": "2. Russian 'Абу-Даби' → English reply + REAL slots",
        "check": "Agent replies in ENGLISH, recognises the emirate, shows real Abu Dhabi slots (no re-ask).",
        "turns": ["привет", "хочу массаж тела 90 минут", "Абу-Даби", "какое время есть?"],
    },
    {
        "title": "3. Package question — no hallucination",
        "check": "Never claims the client has a package / a session count; defers to admin.",
        "turns": ["Hello", "How many sessions do I have left on my package?"],
    },
    {
        "title": "4. Manicure in Abu Dhabi — nail techs only + right duration",
        "check": "Offers ONLY Elena/Safina (nails), never a massage therapist; slots fit ~2h.",
        "turns": ["Hi", "I want a russian gel manicure", "Abu Dhabi", "what times?"],
    },
    {
        "title": "5. Manicure in Dubai — honest area limit (no endless 'try another day')",
        "check": "Says nails are Abu Dhabi ONLY — does NOT loop offering other days.",
        "turns": ["Hello", "gel manicure please", "Dubai", "what do you have?"],
    },
    {
        "title": "6. Specific weekday request",
        "check": "Matches the named weekday to real slots, doesn't say 'no schedule for that day'.",
        "turns": ["Hi", "body massage", "Abu Dhabi", "do you have Saturday?"],
    },
    {
        "title": "7. Card terminal by request",
        "check": "Accepts card/terminal on request (doesn't refuse); would tag 'нужен терминал' on the record.",
        "turns": ["Hi", "body massage 60", "Abu Dhabi", "earliest", "Mona",
                  "can I pay by card terminal?"],
        "gps_at_turn": 3,
    },
]


async def main():
    only = None
    if len(sys.argv) > 1:
        try:
            only = int(sys.argv[1])
        except ValueError:
            pass
    for i, sc in enumerate(SCENARIOS, 1):
        if only and i != only:
            continue
        print("\n" + "=" * 72)
        print(f"👀 EYEBALL: {sc['check']}")
        print("=" * 72)
        await run(sc)


if __name__ == "__main__":
    asyncio.run(main())
