"""Finding model for the pipeline auditor.

A Finding is one structured, evidence-backed observation about whether an agent
pipeline behaved like a human administrator would. It is deterministic: the same
(dialogue, YClients state) always produces the same findings — no LLM, no prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


# Severity — how the finding should be treated.
#   FAIL       : the agent demonstrably did the wrong thing (say-do mismatch,
#                phantom confirmation, cross-emirate). High confidence, act on it.
#   WARN       : likely wrong but context-dependent / lower confidence.
#   FLAG_HUMAN : logic can't decide — surface to a human (unparsed comment,
#                anomaly without a determinable cause).
#   OK         : an explicit pass (kept so reports can show coverage, not only
#                the negatives).
FAIL = "FAIL"
WARN = "WARN"
FLAG_HUMAN = "FLAG_HUMAN"
OK = "OK"

_SEVERITY_RANK = {FAIL: 0, WARN: 1, FLAG_HUMAN: 2, OK: 3}


@dataclass
class Finding:
    pipeline: str                 # "booking_integrity" | "manual_override" | ...
    severity: str                 # FAIL | WARN | FLAG_HUMAN | OK
    summary: str                  # one-line human statement of the observation
    phone: str = ""               # client phone (last-9 join key lives elsewhere)
    episode_ts: Optional[int] = None   # unix ts of the episode this belongs to
    confidence: float = 1.0       # 0..1 — how sure the deterministic check is
    evidence: Dict[str, Any] = field(default_factory=dict)  # agent_msg / record / expected / actual
    suppressed: bool = False      # matched a known-legit suppression rule

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def sort_key(self):
        # Most severe, then least confident-first within severity so the shakiest
        # FAILs surface for review, then by pipeline for stable grouping.
        return (_SEVERITY_RANK.get(self.severity, 9), self.confidence, self.pipeline)
