#!/usr/bin/env python3
"""Faithful conversation simulator for the Crystal Lab WhatsApp agent.

Drives the REAL BookingAgent exactly like the webhook does — same per-turn area
/ service / duration detection, the same real-YClients slot injection, and the
same code-level wording override — so the printed transcript is what a client
would actually receive on WhatsApp. Used to audit conversational QUALITY.

Usage:
    python3.11 scripts/sim_conversation.py '<scenario_json>'
    echo '<scenario_json>' | python3.11 scripts/sim_conversation.py

scenario_json = {
  "title": "...",
  "date": "2026-07-08",           # optional; default tomorrow (UAE)
  "turns": ["client msg 1", "client msg 2", ...],
  "gps_at_turn": 2                 # optional: client shares a GPS pin before this turn index (0-based)
}
Area / service / duration are inferred from the messages, just like prod.
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from agents.booking_agent import BookingAgent
from dialog_context import DialogContext
import webhook_app as wh
from services.yclients_service import YClientsService

_UAE = timezone(timedelta(hours=4))


async def _inject_slots(yc, ctx, date):
    """Mirror the webhook's slot injection into ctx.extra_system_info."""
    area = ctx.client_data.get("area")
    if not area:
        ctx.extra_system_info = ""
        return
    # Service-first gate — mirror the webhook: no slots until a service is named
    # (uses the SAME constant so the sim can't drift from prod).
    if not (ctx.booking_data.get("service_named") or ctx.booking_data.get("service_type")):
        ctx.extra_system_info = wh.SERVICE_FIRST_GATE_MSG
        return
    now = datetime.now(_UAE)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    svc = ctx.booking_data.get("service_type") or ""
    dur = ctx.booking_data.get("service_duration")
    dates = []
    for d in (today, tomorrow, date):
        if d and d not in dates:
            dates.append(d)
    blocks = []
    for d in dates[:3]:
        try:
            s = await yc.get_available_slots_summary(
                date=d, service_name=svc, area=area, service_duration=dur)
        except Exception as e:
            s = f"(slots unavailable: {e})"
        wd = datetime.strptime(d, "%Y-%m-%d").strftime("%A")
        blocks.append(f"{wd} ({d}):\n{s}")
    note = {"al_ain": "Client in AL AIN — only Al Ain therapists.",
            "dubai": "Client in DUBAI — only Dubai therapists.",
            "abu_dhabi": "Client in ABU DHABI — only Abu Dhabi therapists."}.get(area, "")
    pref = ""
    _pm = ctx.client_data.get("preferred_therapist")
    _am = ctx.client_data.get("avoid_therapist")
    if _pm:
        pref += f"\n💚 This client PREFERS {_pm} — offer {_pm}'s times first."
    if _am:
        pref += f"\n🚫 This client asked NOT to be sent {_am} — NEVER offer or book {_am}."
    ctx.extra_system_info = (
        "\n\nREAL AVAILABLE SLOTS (ground truth — AM/PM, overrides anything you said before):\n"
        + "\n\n".join(blocks) + f"\n🚨 Use ONLY these real slots. {note}{pref}"
    )


async def run(scenario):
    yc = YClientsService()
    agent = BookingAgent(model=scenario.get("model"))  # optional model override for bake-offs
    ctx = DialogContext(user_id=90001)
    # Preset stored preferences (simulate a returning client), like the webhook
    # hydrates them from the client record.
    if scenario.get("preferred_therapist"):
        ctx.client_data["preferred_therapist"] = scenario["preferred_therapist"]
    if scenario.get("avoid_therapist"):
        ctx.client_data["avoid_therapist"] = scenario["avoid_therapist"]
    date = scenario.get("date") or (datetime.now(_UAE) + timedelta(days=1)).strftime("%Y-%m-%d")
    gps_at = scenario.get("gps_at_turn", None)

    lines = [f"### {scenario.get('title','(untitled)')}  [model: {agent.model}]"]
    for i, msg in enumerate(scenario["turns"]):
        if gps_at is not None and i == gps_at:
            ctx.client_data["location"] = {"lat": 24.47, "lng": 54.37}
            lines.append("CLIENT ▶ [shares GPS location 📍]")

        low = msg.lower()
        # Per-turn detection, mirroring the webhook.
        # Sticky "service named" flag drives the service-first gate (see webhook).
        if wh._service_named(msg):
            ctx.booking_data["service_named"] = True
        # Master preference / replacement detection (mirror the webhook).
        _av = wh._detect_avoided_master(msg)
        if _av:
            ctx.client_data["avoid_therapist"] = _av
        _pr = wh._detect_preferred_master(msg)
        if _pr:
            ctx.client_data["preferred_therapist"] = _pr
        cat = wh._detect_service_category(msg)
        if cat and cat != ctx.booking_data.get("service_type"):
            ctx.booking_data["service_type"] = cat
            if ctx.booking_data.get("service_duration"):
                ctx.booking_data["service_duration"] = None
        # Use the SAME detector prod uses, so the sim can't drift from the
        # webhook (it used to only know "abu dhabi" and missed "Абу-Даби").
        _ar = wh.detect_area(msg)
        if _ar:
            ctx.client_data["area"] = _ar
        dur = wh._detect_duration_minutes(low) or wh._detect_service_duration(low)
        if dur:
            ctx.booking_data["service_duration"] = dur

        await _inject_slots(yc, ctx, date)

        ctx.recent_messages.append({"role": "user", "content": msg})
        resp, actions = await agent.process_message_with_tools(msg, ctx)
        final = wh._enforce_reply_wording(
            resp, actions, actions.booking_call, ctx.client_data, user_text=msg,
            already_booked_sig=getattr(ctx, "last_booking_sig", None))
        ctx.recent_messages.append({"role": "assistant", "content": final})

        bc = actions.booking_call
        tag = ""
        if bc is not None:
            if getattr(bc, "guests", None):
                _g = ", ".join(g.get("client_name", "?") for g in bc.guests)
                tag += f" [+{len(bc.guests)} guest(s): {_g}]"
            _sig = (bc.service, bc.date, bc.time)
            has_loc, has_name = wh._booking_has_location_and_name(bc, ctx.client_data)
            if getattr(ctx, "last_booking_sig", None) == _sig:
                tag = " [duplicate — suppressed]"
            elif wh._booking_day_mismatch(msg, bc):
                tag = " [gate: wrong-day — blocked]"
            elif has_loc and has_name:
                tag = " [✅ RECORD CREATED]"
                ctx.last_booking_sig = _sig
            else:
                tag = " [gate: NO record — missing info]"
        if actions.reschedule_call is not None:
            tag = " [reschedule request]"
        if actions.cancel_call is not None:
            tag = " [cancel request]"
        lines.append(f"CLIENT ▶ {msg}")
        lines.append(f"AGENT  ◀ {final}{tag}")
    print("\n".join(lines))


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    scenario = json.loads(raw)
    asyncio.run(run(scenario))


if __name__ == "__main__":
    main()
