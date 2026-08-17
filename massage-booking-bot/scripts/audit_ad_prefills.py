#!/usr/bin/env python3
"""Run every advertising prefill through the real agent and audit the prices.

Instagram fills the client's first message from the creative they tapped —
nine of them (three campaigns × three emirates). The creative is invisible to
us, so the prefill is the ONLY signal of which offer the client came for, and
a wrong price here is a wrong price to a paying lead.

This drives the same brain as prod (BookingAgent + the Instagram brief, live
YClients) through each prefill plus two price-forcing follow-ups, then checks
every "<number> AED" in the transcripts against the catalog. Reported:

  ✗ BANNED     — a figure the client never confirmed (3,000 / 2,590 / 2,200)
  ✗ UNKNOWN    — a number that matches nothing in prices.py (invented)
  ⚠ MISSING    — the package prefill that never mentions its own 275 offer

Usage:
    python3.11 scripts/audit_ad_prefills.py            # all nine
    python3.11 scripts/audit_ad_prefills.py --only package
    python3.11 scripts/audit_ad_prefills.py --jobs 1   # serial (rate limits)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prices import PACKAGES, SERVICE_CATALOG, SPECIAL_OFFERS  # noqa: E402

EMIRATES = ["Abu Dhabi", "Al Ain", "Dubai"]

CAMPAIGNS = {
    "consult": "I would like to consult on a massage and make an appointment in {e}",
    "package": "Hello i would like to sign up for a massage package in {e} at a discount",
    "summer": "Hello i would like to sign up for the summer promotion in {e}",
    # No emirate in this prefill — the client's rule (2026-08-16): this text
    # is ALWAYS the deep-cleansing creative. {e} is ignored via a fixed text.
    "cleansing": "Hello, I want to know the details about the promotion and get advice",
}

# The follow-ups exist to FORCE a price out of the agent: without them a
# well-behaved reply is just a clarifying question and nothing is auditable.
# "Tell me about both please" is the real phrase that made the agent dump the
# banned course prices to a live lead on 2026-08-15. The tail then walks into
# a concrete date so the offered TIMES become auditable against YClients too.
FOLLOW_UPS = ["how much?", "Tell me about both please",
              "body massage", "60 min", "20 August"]
SLOT_DATE = "2026-08-20"  # the date the client names above
SLOT_DURATION = 60

BANNED = {3000, 2590, 2200}
PRICE_RE = re.compile(r"(\d[\d,\s]{1,7})\s*(?:AED|aed|дирхам)")


def allowed_prices() -> dict[int, str]:
    """Every figure the agent is allowed to say, and where it comes from."""
    ok: dict[int, str] = {}
    for key, svc in SERVICE_CATALOG.items():
        price = svc.get("price")
        if price:
            ok.setdefault(int(price), f"catalog:{key}")
    for key, offer in SPECIAL_OFFERS.items():
        for field in ("price", "was"):
            val = offer.get(field)
            if val:
                ok.setdefault(int(val), f"offer:{key}.{field}")
    for key, pkg in PACKAGES.items():
        if pkg.get("quotable"):
            for field in ("price", "was"):
                if pkg.get(field):
                    ok.setdefault(int(pkg[field]), f"package:{key}.{field}")
    return ok


async def run_one(campaign: str, emirate: str, jobs_sem: asyncio.Semaphore) -> dict:
    scenario = {
        "title": f"{campaign} / {emirate}",
        "channel": "instagram",
        "turns": [CAMPAIGNS[campaign].format(e=emirate)] + FOLLOW_UPS,
    }
    async with jobs_sem:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("sim_conversation.py")),
            json.dumps(scenario),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    return {
        "campaign": campaign, "emirate": emirate,
        "transcript": out.decode(), "error": err.decode()[-400:] if proc.returncode else "",
    }


def agent_text(transcript: str) -> str:
    """Everything the AGENT said, whole turns included.

    A reply is multi-line (the admins' rhythm splits it into bubbles), so
    matching only lines that START with "AGENT" reads the first line and
    silently drops every price below it — which is how the first version of
    this audit reported "no banned prices" while the transcripts were full of
    them.
    """
    out, collecting = [], False
    for line in transcript.splitlines():
        if line.startswith("CLIENT ▶") or line.startswith("### "):
            collecting = False
        elif line.startswith("AGENT"):
            collecting = True
            out.append(line.split("◀", 1)[-1])
        elif collecting:
            out.append(line)
    return "\n".join(out)


_AMPM_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)


def _times_ampm(text: str) -> set[str]:
    """Every clock time the text mentions, as 24h 'HH:MM'."""
    out = set()
    for h, m, mer in _AMPM_RE.findall(text):
        hour, minute = int(h), int(m or 0)
        if mer.upper() == "PM" and hour < 12:
            hour += 12
        elif mer.upper() == "AM" and hour == 12:
            hour = 0
        out.add(f"{hour:02d}:{minute:02d}")
    return out


async def real_slots(emirate: str) -> set[str]:
    """The genuinely free times for SLOT_DATE in `emirate`, straight from
    YClients — the ground truth the agent's offers are judged against."""
    from services.yclients_service import YClientsService
    area = {"Abu Dhabi": "abu_dhabi", "Al Ain": "al_ain", "Dubai": "dubai"}[emirate]
    yc = YClientsService()
    summary = await yc.get_available_slots_summary(
        date=SLOT_DATE, service_category="massage",
        area=area, service_duration=SLOT_DURATION)
    if not summary or "TEMPORARILY UNAVAILABLE" in summary:
        return None  # outage — judge nothing rather than judge against a lie
    return _times_ampm(summary)


def audit_slots(result: dict, truth) -> list[str]:
    """The times the agent offered for SLOT_DATE must exist in the calendar.

    Only the turns AFTER the client named the date are judged — earlier turns
    legitimately talk about tomorrow. Offering a taken time sends a therapist
    into an overlap; claiming a free day has nothing loses the booking.
    """
    if truth is None:
        return ["⚠ SLOTS NOT JUDGED — YClients was rate-limited/unreachable "
                "while fetching the ground truth"]
    problems = []
    turns = agent_turns(result["transcript"])
    dated = turns[len(FOLLOW_UPS):] if len(turns) > len(FOLLOW_UPS) else turns[-1:]
    dated_text = " ".join(dated)
    offered = set()
    for t in dated:
        offered |= _times_ampm(t)
    # The honest empty-day answer ("fully booked … the nearest we have is
    # <other day>: times") carries times that belong to the ALTERNATIVE day —
    # the runtime slot-reality gate built them from the calendar itself, so
    # judging them against SLOT_DATE's truth flags honesty as a ghost.
    honest_alt = re.search(r"fully booked|nearest we have", dated_text, re.I)
    ghost = offered - truth
    if ghost and not honest_alt:
        problems.append(
            f"✗ GHOST SLOT — offered {sorted(ghost)} on {SLOT_DATE}, "
            f"not free in YClients (real: {sorted(truth)[:8]}…)")
    if truth and not offered:
        tail = " ".join(dated).lower()
        if re.search(r"not available|no availab|fully booked|нет свободн", tail):
            problems.append(
                f"✗ FALSE 'NO AVAILABILITY' — {len(truth)} real openings on "
                f"{SLOT_DATE} were denied")
    return problems


def agent_turns(transcript: str) -> list[str]:
    """Each AGENT reply as one string (bubble separators removed)."""
    turns, current = [], None
    for line in transcript.splitlines():
        if line.startswith("AGENT"):
            if current is not None:
                turns.append(current)
            current = line.split("◀", 1)[-1]
        elif line.startswith("CLIENT ▶") or line.startswith("### "):
            if current is not None:
                turns.append(current)
                current = None
        elif current is not None:
            current += "\n" + line
    if current is not None:
        turns.append(current)
    return [t.replace("---MESSAGE_SPLIT---", " ").strip() for t in turns]


def audit(result: dict, ok: dict[int, str]) -> list[str]:
    problems = []
    agent_lines = agent_text(result["transcript"])
    for raw in PRICE_RE.findall(agent_lines):
        value = int(re.sub(r"[,\s]", "", raw))
        if value in BANNED:
            problems.append(f"✗ BANNED {value:,} AED — never confirmed by the client")
        elif value not in ok:
            problems.append(f"✗ UNKNOWN {value:,} AED — matches nothing in prices.py")
    if result["campaign"] == "package" and "275" not in agent_lines:
        problems.append("⚠ MISSING 275 — the offer this very ad sells was never quoted")
    if result["campaign"] == "cleansing" and "420" not in agent_lines:
        problems.append("⚠ MISSING 420 — the cleansing ad's own offer was never quoted")

    # A dialogue with NO price at all passes every check above while being the
    # worst outcome of them all: the client asked "how much?" twice and was
    # asked the same clarifying question back. Silence is not correctness.
    if not PRICE_RE.search(agent_lines):
        problems.append("✗ NO PRICE EVER QUOTED — the client asked and never got a number")
    # A loop is a reply that is ONLY the question again — asking the same
    # follow-up after actually answering is just conversation, and counting
    # that as a loop buries the real stonewalls in false alarms.
    bare_questions = [
        t for t in agent_turns(result["transcript"])
        if "?" in t and not re.search(r"\d", t)
        # Asking which city is a REQUIRED step (some prefills carry no
        # emirate) and repeating it when the client ignores it is correct —
        # not a stonewall.
        and not re.search(r"abu dhabi.*al ain.*dubai", t, re.I | re.S)
    ]
    if len(bare_questions) >= 2:
        problems.append(
            f"✗ STONEWALL — {len(bare_questions)} replies that are only a "
            f"question, no answer: {bare_questions[0].strip()[:60]!r}")
    if result["error"]:
        problems.append(f"✗ SIM FAILED: {result['error'].strip()[:200]}")
    return problems


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(CAMPAIGNS), help="one campaign only")
    ap.add_argument("--jobs", type=int, default=1,
                    help="parallel simulations (default 1 — YClients rate-limits bursts)")
    ap.add_argument("--save", default="logs/ad_prefill_audit.md")
    args = ap.parse_args()

    campaigns = [args.only] if args.only else list(CAMPAIGNS)
    sem = asyncio.Semaphore(args.jobs)
    tasks = [run_one(c, e, sem) for c in campaigns for e in EMIRATES]
    print(f"running {len(tasks)} prefills through the real agent "
          f"({args.jobs} at a time)…\n")
    results = await asyncio.gather(*tasks)

    ok = allowed_prices()
    truth_by_emirate = {e: await real_slots(e) for e in EMIRATES}
    failed = 0
    report = [f"# Ad-prefill price audit (slots vs YClients, {SLOT_DATE})\n"]
    for e, t in truth_by_emirate.items():
        report.append(f"- real {SLOT_DATE} openings, {e}: {sorted(t)}\n")
    for r in results:
        problems = audit(r, ok) + audit_slots(r, truth_by_emirate[r["emirate"]])
        mark = "✅" if not problems else "❌"
        if problems:
            failed += 1
        print(f"{mark} {r['campaign']:8} / {r['emirate']}")
        for p in problems:
            print(f"     {p}")
        report.append(f"\n## {mark} {r['campaign']} / {r['emirate']}\n")
        report += [f"- {p}\n" for p in problems]
        report.append("\n```\n" + r["transcript"].strip() + "\n```\n")

    Path(args.save).write_text("".join(report))
    print(f"\n{len(results) - failed}/{len(results)} clean — full transcripts in {args.save}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
