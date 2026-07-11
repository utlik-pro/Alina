"""Render the audit result as a readable markdown report."""

from __future__ import annotations

from typing import Dict, List

from .findings import Finding, FAIL, WARN, FLAG_HUMAN, OK

_SEV_ICON = {FAIL: "🔴", WARN: "🟠", FLAG_HUMAN: "🟡", OK: "🟢"}
_COV_ICON = {"full": "✅", "partial": "⚠️", "none": "❌"}


def _pipeline_stats(findings: List[Finding]) -> Dict[str, Dict[str, int]]:
    stats: Dict[str, Dict[str, int]] = {}
    for f in findings:
        s = stats.setdefault(f.pipeline, {FAIL: 0, WARN: 0, FLAG_HUMAN: 0, OK: 0})
        s[f.severity] += 1
    return stats


def render(findings: List[Finding], gap: Dict, meta: Dict) -> str:
    active = [f for f in findings if not f.suppressed]
    stats = _pipeline_stats(active)
    n_fail = sum(1 for f in active if f.severity == FAIL)
    n_flag = sum(1 for f in active if f.severity == FLAG_HUMAN)

    L: List[str] = []
    L.append("# Pipeline Audit — Crystal Lab WhatsApp agent\n")
    L.append(f"Window: **{meta.get('date_from')} → {meta.get('date_to')}**  ·  "
             f"episodes: **{meta.get('episodes', 0)}**  ·  "
             f"YClients records: **{meta.get('records', 0)}**  ·  "
             f"turn_logs: **{meta.get('turn_logs', 0)}**\n")
    L.append(f"**{n_fail} FAIL · {n_flag} to review**\n")

    # ── Pipeline health ──
    L.append("## Pipeline health (regression)\n")
    L.append("| Pipeline | 🔴 FAIL | 🟡 review | 🟢 OK |")
    L.append("|---|---|---|---|")
    for pl in ("booking_integrity", "cancel_reschedule", "booking_gate",
               "area_routing", "manual_override"):
        s = stats.get(pl, {})
        L.append(f"| {pl} | {s.get(FAIL,0)} | {s.get(FLAG_HUMAN,0)} | {s.get(OK,0)} |")
    L.append("")

    # ── Gap to full administrator ──
    score = gap.get("admin_coverage_score", 0.0)
    L.append("## Gap to full administrator\n")
    L.append(f"Agent covers **~{score*100:.0f}%** of the classified admin workload "
             f"({gap.get('total_human_comments',0)} real comments; "
             f"{gap.get('unmatched',0)} free-text → human queue).\n")
    p_read, p_tot = gap.get("package_readable", 0), gap.get("package_total", 0)
    if p_tot:
        L.append(f"> 📦 Package parser (built, not yet wired to the agent) already "
                 f"machine-reads **{p_read}/{p_tot} ({p_read/p_tot*100:.0f}%)** of package "
                 f"comments into a session counter — the lever to close the biggest gap.\n")
    L.append("| Admin responsibility | Real load | Agent |")
    L.append("|---|---|---|")
    for r in gap.get("rows", []):
        L.append(f"| {r['responsibility']} | {r['count']} ({r['share']*100:.0f}%) | "
                 f"{_COV_ICON.get(r['coverage'],'?')} {r['coverage']} |")
    L.append("")

    # ── Findings that need action ──
    actionable = sorted([f for f in active if f.severity in (FAIL, WARN, FLAG_HUMAN)],
                        key=lambda f: f.sort_key)
    L.append(f"## Findings ({len(actionable)})\n")
    if not actionable:
        L.append("_No failures or review items in this window._\n")
    for f in actionable[:80]:
        L.append(f"- {_SEV_ICON.get(f.severity,'')} **{f.pipeline}** "
                 f"(`{f.phone}`, conf {f.confidence:.1f}) — {f.summary}")
        ev = f.evidence or {}
        if ev.get("agent_msg"):
            L.append(f"    - said: _{ev['agent_msg']}_")
        if ev.get("expected") or ev.get("actual"):
            L.append(f"    - expected: `{ev.get('expected')}` · actual: `{ev.get('actual')}`")
        if ev.get("yclients_id"):
            L.append(f"    - record: `{ev['yclients_id']}` ({ev.get('date','')})")
    L.append("")
    return "\n".join(L)
