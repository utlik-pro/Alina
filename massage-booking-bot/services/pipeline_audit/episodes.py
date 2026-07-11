"""Split a dialogue into episodes.

A client's dialogue spans many independent conversations separated by /clear
(the testers reset constantly). Each episode is one coherent booking attempt —
the unit the checks reason over, so a confirmation in episode 2 is never matched
against a slot offered in episode 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from webhook_app import _is_reset_command


@dataclass
class Episode:
    phone: str
    start_t: int
    end_t: int
    messages: List[Dict] = field(default_factory=list)

    def client_msgs(self) -> List[Dict]:
        return [m for m in self.messages if not m.get("from_me")]

    def agent_msgs(self) -> List[Dict]:
        return [m for m in self.messages if m.get("from_me")]

    def last_client_text(self) -> str:
        cs = self.client_msgs()
        return (cs[-1].get("body") or "") if cs else ""


def segment_episodes(phone: str, messages: List[Dict]) -> List[Episode]:
    """Cut `messages` (chronological) into episodes at each client reset command.

    The reset message itself starts a new episode's boundary but is dropped from
    the content (it's a control command, not conversation). An episode with no
    real content is discarded.
    """
    episodes: List[Episode] = []
    current: List[Dict] = []

    def _flush():
        content = [m for m in current if (m.get("body") or "").strip()]
        if content:
            episodes.append(Episode(
                phone=phone,
                start_t=content[0].get("t", 0),
                end_t=content[-1].get("t", 0),
                messages=list(content),
            ))

    for m in messages:
        body = m.get("body") or ""
        if not m.get("from_me") and _is_reset_command(body):
            _flush()
            current = []
            continue
        current.append(m)
    _flush()
    return episodes


def segment_all(dialogues: Dict[str, List[Dict]]) -> List[Episode]:
    out: List[Episode] = []
    for phone, msgs in dialogues.items():
        out.extend(segment_episodes(phone, msgs))
    return out
