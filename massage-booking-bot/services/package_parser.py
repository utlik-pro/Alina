"""Deterministic package-state parser for Crystal Lab.

Package/abonement data is NOT reachable via the YClients API for this account
(loyalty endpoints → 403/404). But the admins maintain the package ledger IN the
record comments — this module reads their notation so the agent can stop being
blind to packages.

Notation (reverse-engineered from 350+ live comments):
  "3+"            → 3rd session done (default = BODY track)
  "B3+" / "В3+"   → 3rd BODY session (B latin or В cyrillic)
  "F2+" / "Ф2+"   → 2nd FACE session
  "5+(последний сеанс по пакету)" → 5th session, LAST one
  "ост. на нач. дня 08.07- 210 мин" → 210 minutes remaining
  "по пакету" / "абонемент"        → package client, counter unknown

Guardrail: a session number is 1..15. "499+", "130+", "90+" in comments are
money/minutes, NOT session counters — those are rejected.

⚠️ Consumer rule: do NOT let the agent SPEAK package info to a client until this
parser is auditor-verified accurate on live data. It is a READ aid, best-effort.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

_MAX_SESSION = 15  # a real package is 5 or 10 sessions (+ intro) — never 400+

# counter: optional track letter (B/b/В/в latin+cyrillic, F/f/Ф/ф) then 1-2 digits then '+'
_COUNTER_RE = re.compile(r"(?<![\w.])([BbВвFfФф])?(\d{1,2})\+")
# remaining minutes: "ост… [на тело|на лицо] [DD.MM-] NNN мин"
_REMAIN_RE = re.compile(
    r"ост[а-я.]*\b[^0-9]*?(?:на\s+(тело|лицо)\s+)?(?:\d{2}\.\d{2}\s*[-–]?\s*)?(\d{2,4})\s*мин",
    re.IGNORECASE,
)
_LAST_RE = re.compile(r"последн", re.IGNORECASE)
_PKG_KW_RE = re.compile(r"по пакету|пакет|абонемент|остал|ост\.|депозит", re.IGNORECASE)

_BODY_LETTERS = {"b", "в"}
_FACE_LETTERS = {"f", "ф"}


@dataclass
class PackageState:
    has_package: bool = False
    body_session: Optional[int] = None   # Nth body session done
    face_session: Optional[int] = None   # Nth face session done
    is_last: bool = False                # explicitly the last session
    remaining_minutes: Optional[int] = None
    remaining_track: Optional[str] = None  # "body" | "face" | None
    confidence: float = 0.0
    raw: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def parse_comment(comment: str) -> Optional[PackageState]:
    """Parse ONE record comment into a PackageState, or None if not package-related."""
    if not comment:
        return None
    text = comment.strip()
    st = PackageState(raw=text[:200])

    for m in _COUNTER_RE.finditer(text):
        letter = (m.group(1) or "").lower()
        n = int(m.group(2))
        if not (1 <= n <= _MAX_SESSION):
            continue  # money/minutes, not a session number
        if letter in _FACE_LETTERS:
            st.face_session = n
        elif letter in _BODY_LETTERS:
            st.body_session = n
        else:
            # untagged counter = default body track (their convention)
            if st.body_session is None:
                st.body_session = n
        st.has_package = True

    rm = _REMAIN_RE.search(text)
    if rm:
        track = rm.group(1)
        st.remaining_minutes = int(rm.group(2))
        st.remaining_track = {"тело": "body", "лицо": "face"}.get(track)
        st.has_package = True

    if _LAST_RE.search(text):
        st.is_last = True
        # "последний" alone strongly implies a package context
        if _PKG_KW_RE.search(text) or st.body_session or st.face_session:
            st.has_package = True

    if not st.has_package and _PKG_KW_RE.search(text):
        st.has_package = True

    if not st.has_package:
        return None

    # confidence: a concrete counter or remaining-minutes = high; keyword-only = low
    if st.body_session or st.face_session or st.remaining_minutes is not None:
        st.confidence = 0.9
    else:
        st.confidence = 0.4  # "по пакету"/"последний" without a number → human should confirm
    return st


def client_package_state(records: List[Dict]) -> Optional[PackageState]:
    """Aggregate a client's records → their CURRENT package state.

    Picks the most recent record carrying a parseable package marker (latest
    session count is the current one). Body and face counters from that record
    are both kept. Records without a client's own comment are ignored.
    """
    dated = []
    for r in records:
        if r.get("deleted"):
            continue
        st = parse_comment(r.get("comment") or "")
        if st:
            dated.append((r.get("date") or "", st))
    if not dated:
        return None
    dated.sort(key=lambda x: x[0])  # chronological; last = most recent
    return dated[-1][1]
