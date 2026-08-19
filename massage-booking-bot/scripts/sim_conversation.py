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
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from agents.booking_agent import BookingAgent
from dialog_context import DialogContext
import webhook_app as wh
from services.yclients_service import YClientsService

_UAE = timezone(timedelta(hours=4))


async def _inject_slots(yc, ctx, date, last_user_text: str = "", is_ig: bool = False):
    """Mirror the webhook's slot injection into ctx.extra_system_info."""
    ctx.slot_truth = {}  # mirror prod: reset every turn, stale truth is worse than none
    area = ctx.client_data.get("area")
    if not area:
        # Mirror prod: a timing ask (incl. a bare date) with no area gets the
        # never-invent-times injection, not silence.
        _low_na = (last_user_text or "").lower()
        _now_na = datetime.now(_UAE)
        _asks = any(kw in _low_na for kw in (
            "when", "time", "available", "slot", "schedule", "today",
            "tomorrow", "morning", "afternoon", "evening",
        )) or bool(wh._detect_explicit_date(_low_na, _now_na)) \
           or bool(wh._detect_requested_time(_low_na))
        ctx.extra_system_info = (
            "\n\n⚠️ CLIENT AREA IS STILL UNKNOWN.\n"
            "🚨 NEVER show or invent specific times before area is "
            "confirmed. Ask: 'Are you in Abu Dhabi, Al Ain or Dubai "
            "dear? 🌹'"
        ) if _asks else ""
        return
    # Service-first gate — mirror the webhook: no slots until a service is named
    # (uses the SAME constant so the sim can't drift from prod).
    if not (ctx.booking_data.get("service_named") or ctx.booking_data.get("service_type")):
        ctx.extra_system_info = wh.SERVICE_FIRST_GATE_MSG
        return
    # Mirror prod's duration gate (IG): no times until 60/90 is chosen, since
    # the free windows differ. Without this the sim showed times prod would
    # have withheld — a simulator that flatters the agent is worse than none.
    _svc = ctx.booking_data.get("service_type") or ""
    if is_ig and wh._is_massage_service(_svc) and not wh._massage_kind_known(_svc):
        ctx.extra_system_info = wh.MASSAGE_KIND_GATE_MSG
        return
    if (is_ig and not ctx.booking_data.get("service_duration")
            and wh._is_massage_service(_svc)):
        ctx.extra_system_info = wh.DURATION_FIRST_GATE_MSG
        return
    now = datetime.now(_UAE)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    svc = ctx.booking_data.get("service_type") or ""
    dur = ctx.booking_data.get("service_duration")
    dates = []
    # Mirror prod's weekday detection: a client saying "next Saturday" must
    # get THAT day's slots loaded. Without it the sim answered "22 Aug is not
    # loaded yet" while prod would have shown the day — a false alarm that
    # cost real debugging time (2026-08-15).
    _day_kw = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "понедел": 0, "вторник": 1, "сред": 2, "четверг": 3,
        "пятниц": 4, "суббот": 5, "воскрес": 6,
    }
    _low = (last_user_text or "").lower()
    # explicit dates first ("20 August", "22/08"), then weekday names
    _named = wh._detect_explicit_date(_low, now)

    for _kw, _wd in _day_kw.items():
        if _named:
            break  # an explicit date wins over a weekday word
        if re.search(r"\b" + _kw, _low):
            _ahead = (_wd - now.weekday()) % 7
            if _ahead == 0 and ("next" in _low or "следующ" in _low):
                _ahead = 7
            _named = (now + timedelta(days=_ahead)).strftime("%Y-%m-%d")
            break
    # Prod persists the chosen day in booking_data so later turns ("7 pm",
    # the address, "cash") keep loading THAT day. Without it the day is
    # forgotten on the very next message.
    if _named:
        ctx.booking_data["date"] = _named
    _sticky = ctx.booking_data.get("date")
    for d in (today, tomorrow, _named or _sticky, date):
        if d and d not in dates:
            dates.append(d)
    blocks = []
    ctx.slot_truth = {}  # mirror prod: ground truth for the outgoing slot gate
    for d in dates[:3]:
        try:
            s = await yc.get_available_slots_summary(
                date=d, service_name=svc, area=area, service_duration=dur)
        except Exception as e:
            s = f"(slots unavailable: {e})"
        wd = datetime.strptime(d, "%Y-%m-%d").strftime("%A")
        blocks.append(f"{wd} ({d}):\n{s}")
        ctx.slot_truth[d] = wh._times_from_summary(s)
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

    # Mirror prod: a concrete time the client named is checked against the
    # calendar and the verdict injected, so a merged short list can never be
    # mistaken for the whole schedule.
    _asked_time = wh._detect_requested_time(last_user_text or "")
    _asked_date = ctx.booking_data.get("date") or (_named or "")
    if _asked_time and _asked_date:
        try:
            _free = await yc.is_slot_available(area, _asked_date, _asked_time, dur or 60)
        except Exception:
            _free = None
        if _free is not None:
            from services.yclients_service import _to_ampm as _ampm
            ctx.extra_system_info += (
                f"\n\n🎯 THE CLIENT ASKED FOR {_ampm(_asked_time)} on {_asked_date} — "
                "CHECKED AGAINST THE CALENDAR JUST NOW: "
                + ("that time IS FREE. Confirm it and move to the next step. "
                   "NEVER tell them it is unavailable."
                   if _free else
                   "that time is NOT free. Say so honestly and offer the "
                   "nearest real alternatives from the schedule above.")
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
        # Sticky group-intent flag (mirror the webhook) — drives the group net.
        if wh._looks_like_group(msg):
            ctx.booking_data["group_requested"] = True
        # Master preference / replacement detection (mirror the webhook).
        _av = wh._detect_avoided_master(msg)
        if _av:
            ctx.client_data["avoid_therapist"] = _av
        _pr = wh._detect_preferred_master(msg)
        if _pr:
            ctx.client_data["preferred_therapist"] = _pr
        cat = wh._detect_service_category(msg)
        cur = ctx.booking_data.get("service_type") or None
        # Mirror prod: never downgrade body_massage/face_massage → 'massage'.
        if (cat and cat != cur
                and not (cat == "massage"
                         and (wh._massage_kind_known(cur or "")
                              or cur == wh._COMBO_KEY))):
            ctx.booking_data["service_type"] = cat
            if ctx.booking_data.get("service_duration"):
                ctx.booking_data["service_duration"] = None
        # Mirror prod: the client's "body massage" answer upgrades the kind
        # (same category — the duration survives).
        kind = wh._massage_kind_from_text(msg)
        cur = ctx.booking_data.get("service_type") or ""
        if kind and wh._is_massage_service(cur) and not wh._massage_kind_known(cur):
            ctx.booking_data["service_type"] = f"{kind}_massage"
        # Mirror prod: a typed phone number is sticky from the moment it appears.
        _ph = wh._detect_phone_in_text(msg)
        if _ph:
            ctx.client_data["phone"] = _ph

        # Mirror prod: out-of-area is sticky, lifted only by naming our city.
        _ooa = wh._detect_out_of_area(msg)
        if _ooa:
            ctx.booking_data["out_of_area"] = _ooa
        elif wh.detect_area(msg) and ctx.booking_data.get("out_of_area"):
            ctx.booking_data["out_of_area"] = None

        # Mirror prod: picking the cupping combo fixes service AND duration.
        if (scenario.get("channel") == "instagram" and wh._detect_combo_choice(msg)
                and ctx.booking_data.get("service_type") != wh._COMBO_KEY):
            from prices import SPECIAL_OFFERS as _SO
            ctx.booking_data["service_type"] = wh._COMBO_KEY
            ctx.booking_data["service_duration"] = int(_SO[wh._COMBO_KEY]["duration"])
        # Use the SAME detector prod uses, so the sim can't drift from the
        # webhook (it used to only know "abu dhabi" and missed "Абу-Даби").
        _ar = wh.detect_area(msg)
        if _ar:
            ctx.client_data["area"] = _ar
        dur = wh._detect_duration_minutes(low) or wh._detect_service_duration(low)
        if dur:
            ctx.booking_data["service_duration"] = dur

        await _inject_slots(yc, ctx, date, msg,
                            is_ig=scenario.get("channel") == "instagram")

        # Instagram channel: mirror the webhook — same brief, same phone gate.
        is_ig = scenario.get("channel") == "instagram"
        if is_ig:
            ctx.extra_system_info = (ctx.extra_system_info or "") + wh._ig_channel_brief(
                (ctx.client_data.get("phone") or "").strip()
            )

        # Mirror prod: which ad creative sent this client, kept sticky, and the
        # offer they must hear first. The prefill arrives in message #1 while
        # the price question comes later, so a per-turn read would miss it.
        _ad = wh._detect_ad_prefill(msg)
        if _ad and not ctx.booking_data.get("ad_prefill"):
            ctx.booking_data["ad_prefill"] = _ad
        # Mirror prod: the ALREADY-KNOWN recap keeps the model from restarting.
        _known = []
        if ctx.client_data.get("phone"):
            _known.append(f"phone {ctx.client_data['phone']}")
        if ctx.client_data.get("name"):
            _known.append(f"name {ctx.client_data['name']}")
        if ctx.client_data.get("area"):
            _known.append(f"city {ctx.client_data['area']}")
        if ctx.booking_data.get("service_type"):
            _known.append(f"service {ctx.booking_data['service_type']}")
        if ctx.booking_data.get("service_duration"):
            _known.append(f"duration {ctx.booking_data['service_duration']} min")
        if ctx.booking_data.get("date"):
            _known.append(f"date {ctx.booking_data['date']}")
        if _known:
            ctx.extra_system_info = (ctx.extra_system_info or "") + (
                "\n\n📌 ALREADY KNOWN (never re-ask any of these, and never "
                "restart the flow from the beginning): " + "; ".join(_known)
                + ". The client may give details in ANY order — accept them, "
                "thank briefly, and continue from the FIRST missing step."
            )

        if ctx.booking_data.get("out_of_area"):
            if _ooa:  # named this very turn — the refusal itself comes first
                ctx.extra_system_info = (ctx.extra_system_info or "") + (
                    f"\n\n🚫 THE CLIENT IS OUTSIDE OUR SERVICE AREA (they "
                    f"named '{_ooa}'). Tell them warmly, ONCE: we don't work "
                    "there — we do home service in Abu Dhabi, Al Ain and "
                    "Dubai. Then CLOSE gracefully. DO NOT ask what service "
                    "they want, no prices, no times."
                )
            else:
                ctx.extra_system_info = (ctx.extra_system_info or "") + (
                    f"\n\n🚫 THE CLIENT IS OUTSIDE OUR SERVICE AREA "
                    f"('{ctx.booking_data['out_of_area']}') and we have "
                    "ALREADY told them so. The funnel is closed: no service "
                    "questions, no prices, no times. ONE short warm goodbye. "
                    "Resume ONLY if they say they can come to one of OUR "
                    "cities."
                )
        if ctx.booking_data.get("ad_prefill") == "cleansing":
            from prices import SPECIAL_OFFERS as _SOC
            _cl = _SOC["offer_deep_cleansing"]
            ctx.extra_system_info = (ctx.extra_system_info or "") + (
                "\n\n🎯 THIS CLIENT CAME FROM THE DEEP-CLEANSING AD (the "
                "'details about the promotion and get advice' prefill). Lead "
                f"with THAT offer and nothing else: {_cl['name']} — "
                f"{int(_cl['price'])} AED instead of {int(_cl['was'])}, "
                f"{int(_cl['duration'])} min, specialist with medical "
                "education. Do NOT list the other promotions. Then continue "
                "the NORMAL flow — ask the emirate when the time comes."
            )
        elif ctx.booking_data.get("ad_prefill") == "summer":
            from prices import format_ad_offers_for_prompt as _offers
            ctx.extra_system_info = (ctx.extra_system_info or "") + (
                "\n\n🎯 THIS CLIENT CAME FROM THE SUMMER-PROMOTION AD. We have "
                "no separate 'summer' price list, so lead with the discounts "
                "that ARE running, briefly, was→now, and then ask which one "
                "they want. Do NOT answer with a bare question — they asked "
                "about an offer and must hear real numbers:\n"
                + _offers()
            )
        elif ctx.booking_data.get("ad_prefill") == "package":
            from prices import SPECIAL_OFFERS as _OFFERS
            _combo = _OFFERS["lymphatic_cupping_combo"]
            ctx.extra_system_info = (ctx.extra_system_info or "") + (
                f"\n\n🎯 THIS CLIENT CAME FROM THE PACKAGE/CUPPING AD "
                f"('massage package at a discount'). Lead with THAT offer: "
                f"{_combo['description']} — {int(_combo['price'])} AED "
                f"(was {int(_combo['was'])}), {_combo['duration']} min. "
                "Quote it as soon as they say what they want, BEFORE the plain "
                "per-session prices. NEVER quote course/abonement prices on "
                "this prefill — say courses are arranged personally by the "
                "team. The emirate is already in their message: never re-ask it."
            )

        ctx.recent_messages.append({"role": "user", "content": msg})
        resp, actions = await agent.process_message_with_tools(msg, ctx)
        _bc = actions.booking_call
        _needs_phone = False
        if is_ig and _bc is not None:
            import re as _re
            _known = (getattr(_bc, "client_phone", None)
                      or ctx.client_data.get("phone") or "")
            _needs_phone = len(_re.sub(r"\D", "", str(_known))) < 9
        final = wh._enforce_reply_wording(
            resp, actions, actions.booking_call, ctx.client_data, user_text=msg,
            already_booked_sig=getattr(ctx, "last_booking_sig", None),
            group_requested=bool(ctx.booking_data.get("group_requested")),
            needs_phone=_needs_phone, is_ig=is_ig)
        # Mirror prod: the cleansing facts pin (asked about cleansing →
        # 420/120, never the facial-massage pair).
        if "cleansing" in msg.lower() or "чистк" in msg.lower():
            ctx.extra_system_info = (ctx.extra_system_info or "") + (
                "\n\n🎯 THE CLIENT IS ASKING ABOUT DEEP FACIAL CLEANSING. Its "
                "facts: 8 steps, 120 min (2 hours), 420 AED instead of 770, "
                "specialist with medical education. NEVER quote 370 AED or "
                "50 min for cleansing — those are the FACIAL MASSAGE numbers, "
                "a different service."
            )
        # Mirror prod: no invented times survive to the client.
        final = wh._enforce_slot_reality(final, ctx, actions.booking_call)
        final = await wh._verify_reply_times_against_calendar(
            final, ctx, ctx.client_data.get("area") or "", who="sim")
        # Mirror prod's binding payment-terms pass (labels on the menu, the
        # chosen method's footnote on every later price).
        _pay = (getattr(actions.booking_call, "payment_method", None)
                or wh._detect_payment_method(msg)
                or ctx.booking_data.get("payment_method"))
        if _pay:
            ctx.booking_data["payment_method"] = _pay
        final = wh._enforce_payment_terms(final, _pay)
        _shown = bool(ctx.booking_data.get("offer_275_shown"))
        final = wh._enforce_package_offer_first(
            final, ctx.booking_data.get("ad_prefill"),
            inbound_text=msg, already_shown=_shown)
        if not _shown and "275" in final:
            ctx.booking_data["offer_275_shown"] = True
        final = wh._enforce_cleansing_facts(final, msg)
        final = wh._enforce_summer_offers(final, ctx.booking_data.get("ad_prefill"))
        final = wh._enforce_price_sanity(final, who="sim")
        _mom = final
        final = await wh._ensure_booking_momentum(
            final, ctx, ctx.client_data.get("area") or "", inbound_text=msg, who="sim")
        if final != _mom:
            ctx.booking_data["momentum_shown"] = True

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
            elif _needs_phone:
                tag = " [gate: NO record — PHONE missing (IG)]"
            elif not wh._client_confirmed(msg):
                # prod defers the record until an explicit "yes" to the recap
                tag = " [gate: awaiting explicit confirm — no record]"
            elif has_loc and has_name:
                tag = " [✅ RECORD CREATED]"
                ctx.last_booking_sig = _sig
                if is_ig and getattr(bc, "client_phone", None):
                    ctx.client_data["phone"] = bc.client_phone
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
