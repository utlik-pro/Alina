"""Regressions from live test T4 (2026-09-22, summer promotion → Al Ain →
face massage instead of cleansing), Tatyana's F02 / F11 / F14 script.

D5 «I want face massage instead of cleansing» got the CLEANSING card back and
   the summer gate kept prepending the 420 offer up to the booking confirmation.
D6 that card («✅WE have an offer…») was reported to the admins as a phantom
   booking — a false alarm.
D4 the phone-first gate marked the number as asked while the composer had
   dropped its line as a "second question".
"""
from types import SimpleNamespace

import webhook_app as wh
from prices import ADMIN_CARD_CLEANSING, ADMIN_CARD_FACE
from services.reply_composer import compose_reply


def _ctx(bd=None, cd=None, history=None):
    return SimpleNamespace(booking_data=dict(bd or {}), client_data=dict(cd or {}),
                           recent_messages=list(history or []), user_id="ig_1", state="initial",
                           slot_truth={})


# ── D5a: the card follows the CURRENT service, not a keyword ────────────────

def test_switch_to_face_never_gets_the_cleansing_card():
    ctx = _ctx({"service_type": "face_massage", "service_duration": 50, "ad_prefill": "summer"},
               {"area": "al_ain"}, [{"role": "assistant", "content": "Which day would you like to book?"}])
    out = wh._enforce_admin_service_card(
        "Face massage 50 min — 370 AED 🌹\nWhich day would suit you?", ctx,
        inbound_text="I want face massage instead of cleansing", who="t")
    assert "8steps" not in out and "Deep facial cleansing(" not in out
    assert "1650" in out                       # the FACE card went out instead
    assert ctx.booking_data.get("face_card_sent") and not ctx.booking_data.get("cleansing_card_sent")


def test_cleansing_card_still_goes_out_when_cleansing_is_the_service():
    ctx = _ctx({"ad_prefill": "summer"}, {"area": "abu_dhabi"})
    out = wh._enforce_admin_service_card("Deep facial cleansing 420 AED", ctx,
                                         inbound_text="I want the cleansing please", who="t")
    assert "8steps" in out and ctx.booking_data.get("cleansing_card_sent")


# ── D5b: the summer gate stops once another service is chosen ───────────────

def test_summer_gate_is_silent_after_an_explicit_service_switch():
    reply = "So dear — 50-min face massage, Friday 2 Oct at 2:00 PM, 370 AED (cash — tax free) 🌹 Shall I confirm?"
    assert wh._enforce_summer_offers(reply, "summer", "face_massage") == reply
    assert wh._enforce_summer_offers(reply, "summer", "body_massage") == reply
    # No service chosen yet → the ad requirement still applies.
    assert wh._enforce_summer_offers(reply, "summer", "").startswith("Deep facial cleansing — 420")


# ── D6: a service card is not a phantom booking ─────────────────────────────

def test_service_card_is_not_reported_as_a_phantom_booking():
    card_reply = ADMIN_CARD_CLEANSING + "\n\nSee you soon dear 🌹\nWhich day would suit you?"
    assert not wh._looks_like_phantom_confirmation(card_reply, _ctx({"service_type": "face_massage"}))
    assert not wh._looks_like_phantom_confirmation(ADMIN_CARD_FACE, _ctx({"date": "2026-10-02"}))
    # A real phantom at a booking stage is still caught; negations are not.
    booked = _ctx({"date": "2026-10-02", "time": "14:00"})
    assert wh._looks_like_phantom_confirmation("Your face massage is booked ✅", booked)
    assert wh._looks_like_phantom_confirmation("All set ✅ see you on Friday!", booked)
    assert not wh._looks_like_phantom_confirmation("It is not yet booked ✅ dear", booked)
    # Outside a booking stage even «you're booked» wording is left to the other gate.
    assert not wh._looks_like_phantom_confirmation("Your face massage is booked ✅", _ctx({}))


# ── D4: the number request survives the composer ─────────────────────────────

def test_composer_keeps_the_number_request_over_the_models_question():
    ctx = _ctx({}, {"area": "abu_dhabi"},
               [{"role": "user", "content": "Hello, I would like to sign up for the summer promotion in Abu Dhabi."}])
    text = ("Hello dear 🌹 Summer promotion in Abu Dhabi:\n"
            "Deep facial cleansing, 2 hours — 420 AED instead of 770\n"
            "Which one would you like dear?\n\n" + wh.PHONE_FIRST_LINE)
    out = compose_reply(text, ctx)
    assert "number" in out.lower()
    assert "which one would you like" not in out.lower()
    assert "420 AED" in out                    # the facts stay


def test_composer_without_a_pending_number_keeps_the_first_question():
    ctx = _ctx({}, {"area": "abu_dhabi", "phone": "+971501112233"},
               [{"role": "user", "content": "0501112233"}])
    out = compose_reply("Which day would suit you?\n\nAnd what time suits you better — morning or evening?", ctx)
    assert "which day" in out.lower() and "morning or evening" not in out.lower()
