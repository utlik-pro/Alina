"""Cancellation & penalty logic for Crystal Lab (FR-5.1–5.3).

Pure functions — no I/O — so they're trivially testable. The webhook /
agent layer calls these to decide whether a cancellation is free, incurs
a transportation charge, or should deduct a package session, and whether
the stated reason is a force-majeure (always free).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Transportation charge for same-day / master-en-route cancellations.
# Configurable — Crystal Lab can tune via env without a code change.
TRANSPORTATION_PENALTY_AED: float = float(os.getenv("TRANSPORTATION_PENALTY_AED", "50"))

# UAE is UTC+4 (no DST). Booking datetimes are stored as naive UAE-local,
# so penalty math must compare against UAE-local "now".
_UAE_OFFSET = timedelta(hours=4)


def _uae_now() -> datetime:
    return datetime.utcnow() + _UAE_OFFSET


# Force-majeure patterns (FR-5.3). Word-boundary / phrase matched — NOT bare
# substring — so common phrasing ("food delivery is late", "booked by
# accident", "labor day") doesn't trigger a free cancellation and skip the
# <1h hard-penalty band. A cancellation citing any of these is never charged.
_FORCE_MAJEURE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\bhospital(?:i[sz]ed|i[sz]ation)?\b",
        r"\bemergency\b",
        r"\bI\.?C\.?U\.?\b",
        r"\bIV\s*drip\b",
        r"\bambulance\b",
        r"\bnewborn\b", r"\bnew\s*born\b", r"\bgave\s+birth\b",
        r"\b(?:in|into|going\s+into)\s+lab(?:ou)?r\b",
        r"\bpassed\s+away\b", r"\bfuneral\b", r"\bbereavement\b",
        r"\b(?:a\s+)?death\s+(?:in|of)\b", r"\b(?:she|he|they|mother|father|son|daughter)\s+died\b",
        r"\bcar\s+accident\b", r"\bhad\s+an\s+accident\b", r"\bserious\s+accident\b",
        r"\b(?:urgent|emergency)\s+surgery\b",
        # Russian stems
        r"больниц", r"скорая\s*помощь", r"капельниц", r"\bроды\b", r"родила",
        r"смерт", r"похорон", r"\bавари", r"несчастн(?:ый|ого)\s+случ",
    )
]


def is_force_majeure(text: str) -> bool:
    """True if the cancellation reason looks like a genuine force-majeure event."""
    if not text:
        return False
    return any(p.search(text) for p in _FORCE_MAJEURE_PATTERNS)


def hours_until(booking_date: datetime, now: Optional[datetime] = None) -> float:
    """Hours from now until the booking (negative if already passed)."""
    now = now or _uae_now()
    return (booking_date - now).total_seconds() / 3600.0


def calculate_penalty(
    booking_date: datetime,
    *,
    is_package: bool = False,
    master_en_route: bool = False,
    reason: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Decide the penalty for a cancellation.

    Returns a dict:
        {
          "free": bool,            # no charge / no deduction
          "force_majeure": bool,
          "charge_aed": float,     # transportation charge (new clients)
          "deduct_session": bool,  # deduct one package session (package clients)
          "warn_only": bool,       # same-day window: warn before they confirm
          "reason": str,           # human-readable explanation
        }

    Rules (FR-5.2):
      >24h or 12–24h  → free
      <12h (same day) → warn; if they still cancel: package→deduct, new→charge
      <1h / en route  → package→deduct session, new→transportation charge
    Force-majeure (FR-5.3) overrides everything → free.
    """
    now = now or _uae_now()
    result = {
        "free": False,
        "force_majeure": False,
        "charge_aed": 0.0,
        "deduct_session": False,
        "warn_only": False,
        "reason": "",
    }

    if is_force_majeure(reason):
        result.update(
            free=True, force_majeure=True,
            reason="Force-majeure — no charge (FR-5.3).",
        )
        return result

    h = hours_until(booking_date, now)

    # >= 12h ahead → always free
    if h >= 12 and not master_en_route:
        result.update(free=True, reason="More than 12h notice — no charge.")
        return result

    # < 1h or master already en route → hard penalty
    if master_en_route or h < 1:
        if is_package:
            result.update(
                deduct_session=True,
                reason="Master en route / <1h — one package session deducted.",
            )
        else:
            result.update(
                charge_aed=TRANSPORTATION_PENALTY_AED,
                reason=f"Master en route / <1h — transportation charge "
                       f"{TRANSPORTATION_PENALTY_AED:.0f} AED.",
            )
        return result

    # 1–12h (same day) → warn first; penalty applies if they proceed
    if is_package:
        result.update(
            warn_only=True, deduct_session=True,
            reason="Same-day cancellation — warn about session deduction.",
        )
    else:
        result.update(
            warn_only=True, charge_aed=TRANSPORTATION_PENALTY_AED,
            reason="Same-day cancellation — warn about transportation charge.",
        )
    return result


# Client-facing message snippets (English — bot replies in English).
PENALTY_WARNING_NEW = (
    "Please note that cancellations on the day of appointment may result in a "
    "charge for transportation. Would you still like to cancel or prefer to "
    "reschedule? 🌹"
)
PENALTY_WARNING_PACKAGE = (
    "Please note that same-day cancellations may deduct one session from your "
    "package. Would you still like to cancel or prefer to reschedule? 🌹"
)
FORCE_MAJEURE_REPLY = (
    "We completely understand dear 🌹 No charge for this cancellation. Hope "
    "everything is okay! When you're ready, just let us know and we'll book you in."
)
