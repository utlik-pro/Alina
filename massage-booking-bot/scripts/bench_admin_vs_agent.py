"""Admin-vs-agent benchmark on REAL Instagram dialogues.

Every case below is a verbatim client message from the ManyChat inbox
(11–15.08.2026) together with what the human admins actually replied.
The script feeds the same message to our IG agent and scores both sides
on the things that decide whether a lead converts:

  answers   — does the reply answer the question that was asked?
  value     — is the selling line there (home service / free transport /
              Russian therapists)?
  cta       — does it end with a question or a clear next step?
  contact   — does it move toward a contact/booking (phone ask or link)?
  honest    — does it avoid promising slots nobody checked?

Usage:  python3.11 scripts/bench_admin_vs_agent.py [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import instagram_agent as ia  # noqa: E402

# (case id, client message, what the admins really answered, expected fact)
CASES = [
    ("fatima/prefill-body",
     "I would like to consult on a massage and make an appointment in Abu Dhabi",
     "Hello. We provide home service. Free transportation to your home. Top Russian "
     "therapist. We have available slots for today and tomorrow. Could you send your "
     "name and WhatsApp number please, I will send you more information",
     None),
    ("shivani/prefill-package",
     "Hello, I would like to sign up for a massage package in Abu Dhabi at a discount.",
     "Hello. We provide home service... Could you send your name and WhatsApp number "
     "please I will send you more information",
     "275"),
    ("mohamed/how-much",
     "How much",
     "Hello 👋 WE have an offer for 60min body massage. New price 60 min - 350 aed. "
     "Body package 5 sessions-1550 aed. HOME SERVICE. FREE TRANSPORTATION. Russian "
     "female certified therapist. Would you like to book?",
     "350"),
    ("hendaq/face",
     "Face massage",
     "Hello 👋 WE have an offer for facial massage!!! the old price -550 aed - NOW 370 "
     "aed. Face massage package 5 sessions-1650 aed. Techniques: lifting drainage, "
     "buccal, myofascial, signature mix - 50 min. Would you like to book?",
     "370"),
    ("hk/lymph-package",
     "Do you have packages for the lymphatic massage",
     "Hello. Yes dear. Body lymph massage -350aed. 5 session -1550aed. Have trial "
     "session for new clients... Would you like to book?",
     "350"),
    ("benzii/cupping",
     "Cupping and massage",
     "(agent answered: 350/460 + combo 275)",
     "275"),
    ("anum/combo-content",
     "It's only cupping or lymphatic drainage included also",
     "Lymphatic body massage 30min, Cupping 15, Head massage 15. Included also. "
     "We work with world champion for massage. Visible results after 1 session",
     "30"),
    ("amira/pregnant",
     "Im pregnant. Is it ok?",
     "Of course. Our therapist with medical education. Don't worry. We have prenatal "
     "massage 350aed. Share please your WhatsApp number",
     "prenatal"),
    ("viola/card",
     "is possible to pay with card?",
     "Yes, have card machine. Share please your WhatsApp",
     "card"),
    ("viola/availability",
     "Good morning, it means there is availability to come at home?",
     "Yes dear. What time is preferable for you?",
     None),
    ("viola/afternoon",
     "what time do you have in the afternoon?",
     "We will find convenient time for you. Share please your WhatsApp dear",
     None),
    ("sam/results",
     "Are u sure we can see the results?",
     "You will see results. Share please your WhatsApp we consult you",
     None),
    ("sam/studio",
     "Where is your studio?",
     "We have a massage studio in Abudhabi, Al Raha. But it currently closed for "
     "maintenance. We provide home service, come to your home, transportation is free",
     "Raha"),
    ("hkn/sharjah",
     "Sharjah home service ??",
     "What is your Location In Sharjah -> Oh sorry :(( we provide service in Dubai, "
     "Abu Dhabi and Al Ain. It's a remote location",
     "Sharjah"),
    ("ummahra/one-session",
     "how much for one session",
     "Body+cupping -275aed. Lymphatic massage -350aed",
     "275"),
    ("sina/give-number",
     "Send me the phone number",
     "97155 193 3662",
     "971"),
    ("zauraiz/photos",
     "Thank you! Can I get some more pictures of lash lift results?",
     "(admins ignored the question) Would you like to try?",
     None),
    ("diya/face-lymph",
     "Hello, how much would it be for lymphatic drainage massage for the face only",
     "(agent answered 370/50min; admin then pasted the template on top)",
     "370"),
    ("zoubida/arabic",
     "مرحبا، ممكن احجز جلسة",
     "Hello dear. Yes. We provide home service... Share please your WhatsApp number "
     "I give you good price",
     None),
    ("mariam/buccal",
     "Hi hope you are well I want the bucal massage please I live in ad",
     "What time is preferable for you? For the booking dear?",
     "370"),
    ("gayatri/promo",
     "Hello, I want to know the details about the promotion and get advice",
     "Hello. Our administrator write to you in WhatsApp  <-- DEAD END, no number asked",
     None),
    ("noone/what-is-this",
     "What is this",
     "We provide home service. Free transportation. Top Russian therapist. We have "
     "available slots for today and tomorrow",
     None),
]

VALUE_RE = re.compile(r"home|transport|russian|therapist", re.I)
CONTACT_RE = re.compile(r"wa\.me|whatsapp|phone|number|book", re.I)
FAKE_SLOTS_RE = re.compile(r"slots? (for )?(today|tomorrow)|available (today|tomorrow)", re.I)


def score(text: str, expect: str | None) -> dict:
    t = text.strip()
    return {
        "answers": bool(expect is None or re.search(re.escape(expect), t, re.I)),
        "value": bool(VALUE_RE.search(t)),
        # "?" may be followed by an emoji/space: "Would you like to book? 😊"
        "cta": bool(re.search(r"\?[\s\W]{0,4}$", t)) or bool(
            re.search(r"would you like|shall i|book\b", t, re.I)),
        "contact": bool(CONTACT_RE.search(t)),
        "honest": not FAKE_SLOTS_RE.search(t),
        "len": len(t),
    }


def fmt(s: dict) -> str:
    flags = "".join(
        ("✅" if s[k] else "❌") for k in ("answers", "value", "cta", "contact", "honest")
    )
    return f"{flags} {s['len']:>4}ch"


async def main(limit: int | None) -> None:
    cases = CASES[:limit] if limit else CASES
    rows = []
    for cid, client, admin, expect in cases:
        reply = await ia.generate_ig_reply(f"bench::{cid}", client)
        a_s, g_s = score(admin, expect), score(reply, expect)
        rows.append((cid, client, admin, reply, a_s, g_s))
        print("=" * 78)
        print(f"[{cid}]  CLIENT: {client}")
        print(f"  ADMIN  {fmt(a_s)}\n    {admin[:300]}")
        print(f"  AGENT  {fmt(g_s)}\n    {reply[:300]}")

    print("\n" + "=" * 78)
    print("SUMMARY  (answers / value / cta / contact / honest)")
    for who, idx in (("ADMINS", 4), ("AGENT ", 5)):
        agg = {k: sum(1 for r in rows if r[idx][k]) for k in
               ("answers", "value", "cta", "contact", "honest")}
        avg = sum(r[idx]["len"] for r in rows) // max(len(rows), 1)
        print(f"  {who}: " + "  ".join(f"{k}={v}/{len(rows)}" for k, v in agg.items())
              + f"  avg_len={avg}ch")

    worse = [r for r in rows if sum(r[5][k] for k in ("answers", "value", "cta", "contact", "honest"))
             < sum(r[4][k] for k in ("answers", "value", "cta", "contact", "honest"))]
    if worse:
        print("\n  AGENT WEAKER THAN ADMINS ON:")
        for r in worse:
            print(f"   - {r[0]}: {r[1][:60]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    asyncio.run(main(args.limit))
