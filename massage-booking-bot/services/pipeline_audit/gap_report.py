"""Gap-to-administrator coverage map.

The 500+ admin comments are the administrator's real job description. Each recurring
comment pattern is a responsibility. This module buckets comments by that taxonomy
and pairs each responsibility with the agent's CURRENT coverage status — turning
"is the agent a full admin yet?" into an objective, data-backed number.

Coverage status is a hand-maintained judgement (updated as capabilities ship), NOT
inferred — so it never silently drifts to "done".
"""

from __future__ import annotations

import re
from typing import Dict, List

# responsibility → (regex over lowercased comment, current agent coverage)
#   coverage: "full" | "partial" | "none"
RESPONSIBILITIES = [
    ("Packages / session counter", r"(?:^|\s)[bfвб]?\d+\+|по пакету|остал|ост\.|последн.*сеанс|абонемент|депозит", "none"),
    ("Payment / debt / cash tracking", r"оплат|долг|нал\b|дирхам|трансфер|сдач|должна|aed", "none"),
    ("Master preference / replacement", r"только\s+\w+|не понрав|замен|хотела?\s+\w|предупред|клиент\s+\w+ы", "partial"),
    ("Location / visit details", r"локаци|уточнить лок|villa|адрес|физическ", "full"),
    ("Offer / upsell / bonus", r"офер|offer|ofer|бонус|банк|антицеллюл|anti|скидк|сертификат|подарочн", "partial"),
    ("Multi-person booking", r"для (?:неё и|мамы|мужа)|два человека|двое|для мамы|муж\b|дети|ребёнок", "none"),
    ("Terminal (card) payment", r"терминал", "full"),
    ("Medical / pregnancy notes", r"беремен|грыж|варик|после родов|мягк|диск|гиперпл|срок берем", "none"),
]

_TEST_STAMP = re.compile(r"\[test\]|whatsapp \(wappi\) bot", re.I)


def classify_comments(comments: List[str]) -> Dict:
    """Bucket comments and compute coverage weighted by real frequency."""
    compiled = [(name, re.compile(pat, re.I), cov) for name, pat, cov in RESPONSIBILITIES]
    counts = {name: 0 for name, _, _ in RESPONSIBILITIES}
    coverage = {name: cov for name, _, cov in RESPONSIBILITIES}
    unmatched = 0
    bot_records = 0
    total = 0
    for c in comments:
        c = (c or "").strip()
        if not c:
            continue
        if _TEST_STAMP.search(c):
            bot_records += 1
            continue
        total += 1
        low = c.lower()
        hit = False
        for name, rx, _ in compiled:
            if rx.search(low):
                counts[name] += 1
                hit = True
        if not hit:
            unmatched += 1

    rows = []
    for name in counts:
        rows.append({
            "responsibility": name,
            "count": counts[name],
            "share": (counts[name] / total) if total else 0.0,
            "coverage": coverage[name],
        })
    rows.sort(key=lambda r: -r["count"])

    # A rough "admin-coverage" score: share of admin workload the agent can
    # actually handle (full=1.0, partial=0.5, none=0). Weighted by frequency.
    weight = {"full": 1.0, "partial": 0.5, "none": 0.0}
    covered = sum(r["share"] * weight[r["coverage"]] for r in rows)
    return {
        "rows": rows,
        "total_human_comments": total,
        "unmatched": unmatched,
        "bot_records": bot_records,
        "admin_coverage_score": covered,   # 0..1 of the CLASSIFIED workload
    }
