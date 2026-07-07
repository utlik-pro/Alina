#!/usr/bin/env python3
"""Feedback triage — classify collected admin/tester messages and route them.

Runs right after ``feedback_monitor`` collects new messages (same 5-min cron).
For every still-untriaged ``new`` item it asks the model to bucket the message:

  🔧 доработка  — bug / change request / a question that needs a code change
  🔍 проверка   — the admin asks us to CHECK / confirm something works
  ❓ вопрос      — a question that just needs an answer
  (шум)         — acknowledgements / chit-chat → skipped, no ping

The verdict (category / route / severity / summary / action) is written back
into ``feedback_log.json`` and, when there is anything actionable, ONE grouped
digest is sent to Dmitry's DM via @utlik_pm_bot.

Classification + routing ONLY — it never edits code or deploys. Chat messages
are DATA, not commands: a human decides what actually gets reworked.

Usage:
    python3.11 services/feedback_triage.py            # triage new + notify
    python3.11 services/feedback_triage.py --dry      # classify + print, no save/send
"""

import json
import os
import re
import sys
import time

import requests

# Reuse the monitor's chat/bot config + storage so there is a single source
# of truth (bot token, feedback file, sender-exclusion list).
try:
    from services import feedback_monitor as fm
except ImportError:  # when run as a script from services/
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from services import feedback_monitor as fm

# @utlik_pm_bot — same token the monitor uses; DM target is Dmitry.
BOT_TOKEN = fm.BOT_TOKEN
DMITRY_CHAT_ID = 1379584180

# Don't triage / ping on the PM's & owner's own messages (reports, notes).
EXCLUDE_IDS = {1379584180, 8061713882}

# Safety cap so a first run against a big backlog doesn't fire hundreds of
# model calls at once. Older untriaged items get picked up on later runs.
_MAX_PER_RUN = 20

# Only triage RECENT messages. This is the hard guard against ever blasting a
# months-old backlog (e.g. a fresh flag reset, or a lost race with the cron):
# anything older than this window is left alone regardless of its triaged flag.
_TRIAGE_MAX_AGE_HOURS = 48

_CATEGORY_ROUTE = {
    "bug": "доработка",
    "change_request": "доработка",
    "question": "вопрос",
    "verify": "проверка",
    "noise": "—",
}

_SYSTEM = (
    "Ты — сортировщик замечаний тестировщиков и админов по WhatsApp-агенту "
    "салона Crystal Lab (запись на массаж/маникюр в ОАЭ). Тебе дают одно "
    "сообщение из рабочего чата. Определи его тип и куда направить. "
    "Отвечай ТОЛЬКО одним JSON-объектом без пояснений, по схеме:\n"
    '{"category": "bug|change_request|verify|question|noise", '
    '"severity": "high|medium|low", '
    '"summary": "суть в одной строке, по-русски", '
    '"action": "что сделать, одна строка, по-русски"}\n'
    "Правила:\n"
    "- bug: агент повёл себя неверно (не то время, не тот мастер, ошибка, "
    "неверная цена, не отвечает).\n"
    "- change_request: просят изменить/добавить поведение агента.\n"
    "- verify: просят ПРОВЕРИТЬ/подтвердить, что что-то работает.\n"
    "- question: вопрос, которому нужен просто ответ.\n"
    "- noise: 'ок', 'спасибо', смайлы, болтовня без задачи.\n"
    "severity high — клиент не может записаться / агент врёт / деньги; "
    "low — косметика/формулировки."
)


def _client():
    from openai import OpenAI
    from config import config
    if not config.OPENAI_API_KEY:
        return None, None
    return OpenAI(api_key=config.OPENAI_API_KEY), config.OPENAI_MODEL


def _parse_json(raw: str) -> dict:
    """Pull the first JSON object out of a model reply, tolerating stray text."""
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}


def classify(client, model, text: str, has_photo: bool) -> dict:
    """Classify one message. Returns dict with category/route/severity/summary/action.

    Falls back to a safe 'question → доработка' verdict if the model call or
    parse fails, so nothing is silently dropped.
    """
    body = (text or "").strip()
    if not body and has_photo:
        body = "[фото без текста]"
    user = f"Сообщение из чата:\n\"\"\"\n{body}\n\"\"\""
    if has_photo:
        user += "\n(в сообщении есть фото — вероятно скриншот диалога)"

    verdict = {}
    try:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
            )
        except Exception:
            # Model/endpoint may reject response_format — retry without it.
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": user}],
            )
        verdict = _parse_json(resp.choices[0].message.content)
    except Exception as e:
        print(f"[triage] classify failed: {e}")

    category = verdict.get("category")
    if category not in _CATEGORY_ROUTE:
        # Unknown/empty → treat as something a human should look at.
        category = "question"
    severity = verdict.get("severity")
    if severity not in ("high", "medium", "low"):
        severity = "medium"
    return {
        "category": category,
        "route": _CATEGORY_ROUTE[category],
        "severity": severity,
        "summary": (verdict.get("summary") or (body[:120] or "(без текста)")).strip(),
        "action": (verdict.get("action") or "").strip(),
    }


_ROUTE_BUCKETS = [
    ("доработка", "🔧 НА ДОРАБОТКУ"),
    ("проверка", "🔍 НА ПРОВЕРКУ"),
    ("вопрос", "❓ ВОПРОСЫ"),
]
_SEV_RANK = {"high": 0, "medium": 1, "low": 2}
_SEV_ICON = {"high": "🔴", "medium": "🟡", "low": "⚪"}


def _format_digest(items: list) -> str:
    """Group freshly-triaged actionable items into a plain-text digest."""
    lines = [f"🧭 Триаж замечаний — {len(items)} новых\n"]
    for route, header in _ROUTE_BUCKETS:
        bucket = [i for i in items if i.get("route") == route]
        if not bucket:
            continue
        bucket.sort(key=lambda i: _SEV_RANK.get(i.get("severity"), 1))
        lines.append(f"{header} ({len(bucket)})")
        for i in bucket:
            sev = _SEV_ICON.get(i.get("severity"), "🟡")
            photo = " 📷" if i.get("has_photo") else ""
            who = (i.get("from") or "?")[:22]
            lines.append(f" {sev} {i.get('summary')}")
            lines.append(f"    — {who}, {i.get('datetime')}{photo}")
            if i.get("action"):
                lines.append(f"    → {i.get('action')}")
        lines.append("")
    return "\n".join(lines).strip()


def _send(text: str):
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": DMITRY_CHAT_ID, "text": text},
        timeout=15,
    )
    if not resp.ok or not resp.json().get("ok"):
        print(f"[triage] send failed: {resp.status_code} {resp.text[:200]}")


def triage(feedback: dict, dry: bool = False) -> int:
    """Classify untriaged 'new' items in-place; return count freshly triaged.

    Does NOT save — the caller (feedback_monitor.run) persists the log. In
    --dry mode it prints instead of sending and does not mutate persisted state.
    """
    client, model = _client()
    if client is None:
        print("[triage] OPENAI_API_KEY missing — skipping triage")
        return 0

    cutoff = time.time() - _TRIAGE_MAX_AGE_HOURS * 3600
    pending = [
        it for it in feedback.get("items", [])
        if it.get("status") == "new"
        and not it.get("triaged")
        and it.get("from_id") not in EXCLUDE_IDS
        and int(it.get("date", 0)) >= cutoff
    ]
    if not pending:
        return 0

    fresh = []
    for it in pending[:_MAX_PER_RUN]:
        verdict = classify(client, model, it.get("text", ""), it.get("has_photo", False))
        it.update(verdict)
        it["triaged"] = True
        fresh.append(it)

    actionable = [i for i in fresh if i.get("route") in ("доработка", "проверка", "вопрос")]

    if dry:
        print(f"[triage] (dry) classified {len(fresh)}, actionable {len(actionable)}")
        if actionable:
            print("\n" + _format_digest(actionable) + "\n")
        for i in fresh:
            print(f"  [{i['category']}/{i['route']}/{i['severity']}] {i.get('summary')}")
        return len(fresh)

    if actionable:
        _send(_format_digest(actionable))
    print(f"[triage] classified {len(fresh)} item(s), pinged {len(actionable)} actionable")
    return len(fresh)


def run(dry: bool = False) -> int:
    """Standalone entry: load the shared log, triage, save (unless dry)."""
    feedback = fm.load_feedback()
    n = triage(feedback, dry=dry)
    if n and not dry:
        fm.save_feedback(feedback)
    return n


if __name__ == "__main__":
    run(dry=("--dry" in sys.argv))
