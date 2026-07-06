#!/usr/bin/env python3
"""Daily Crystal Lab system report — sent by Zhora (@utlik_pm_bot) to Dmitry's DM.

Combines three sources:
  1. System status  — prod health + Wappi profile status / payment expiry.
  2. Agent metrics  — from the prod turn-logs (/admin/logs): conversations,
     bookings, drop-off, errors/timeouts, top services & areas (last 24h).
  3. Bug reports    — new tester feedback from feedback_log.json.

Metrics need the prod WEBHOOK_SECRET (env WEBHOOK_SECRET) to read /admin/logs;
without it the report still sends status + bug reports and notes metrics are
unavailable.

Run daily via launchd/cron. Usage:
    python3.11 scripts/daily_report.py            # build + send
    python3.11 scripts/daily_report.py --dry      # print, don't send
"""

import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PROD = "https://crystal-lab-bot.onrender.com"
DMITRY_CHAT_ID = 1379584180
FEEDBACK_FILE = os.path.join(ROOT, "feedback_log.json")
# Exclude PM/dev senders by Telegram id (names use stylised unicode, so
# substring matching on the display name is unreliable).
EXCLUDE_IDS = {1379584180, 8061713882}  # Dmitry, Yana


def _bot_token() -> str:
    spec = importlib.util.spec_from_file_location(
        "fm", os.path.join(ROOT, "services", "feedback_monitor.py"))
    fm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fm)
    return fm.BOT_TOKEN


def uae_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=4)))


# ── 1) system status ──────────────────────────────────────────────────
def system_status() -> str:
    lines = []
    try:
        h = requests.get(f"{PROD}/", timeout=15).json()
        lines.append(f"• Сервер: {'🟢 работает' if h.get('status') == 'ok' else '🔴 ' + str(h)}")
    except Exception as e:
        lines.append(f"• Сервер: 🔴 недоступен ({str(e)[:60]})")

    # Wappi status via local creds (config reads .env)
    try:
        from config import config
        if config.WAPPI_TOKEN and config.WAPPI_PROFILE_ID:
            r = requests.get(
                "https://wappi.pro/api/sync/get/status",
                params={"profile_id": config.WAPPI_PROFILE_ID},
                headers={"Authorization": config.WAPPI_TOKEN}, timeout=15,
            ).json()
            st = r.get("app_status", "?")
            auth = r.get("authorized")
            exp = (r.get("payment_expired_at") or "")[:10]
            emoji = "🟢" if (st == "open" and auth) else "🔴"
            warn = ""
            if exp:
                try:
                    days = (datetime.fromisoformat(exp) - datetime.utcnow()).days
                    warn = f" ⚠️ истекает через {days} дн." if days <= 5 else ""
                except Exception:
                    pass
                warn += f" (оплата до {exp})"
            lines.append(f"• WhatsApp (Wappi): {emoji} {st}/authorized={auth}{warn}")
        else:
            lines.append("• WhatsApp (Wappi): ключи не заданы локально")
    except Exception as e:
        lines.append(f"• WhatsApp (Wappi): проверка не удалась ({str(e)[:50]})")
    return "\n".join(lines)


# ── 2) agent metrics from prod turn-logs ──────────────────────────────
def agent_metrics() -> str:
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        # Optional gitignored file so the prod secret stays out of the plist.
        _sf = os.path.join(ROOT, ".report_secret")
        if os.path.exists(_sf):
            secret = open(_sf, encoding="utf-8").read().strip()
    if not secret:
        return ("метрики недоступны: не задан WEBHOOK_SECRET для чтения "
                "prod-логов (добавь его в env, чтобы видеть конверсию и т.д.)")
    try:
        r = requests.get(f"{PROD}/admin/logs", params={"n": 800},
                         headers={"X-Admin-Secret": secret}, timeout=25)
        if r.status_code != 200:
            return f"_метрики: /admin/logs вернул {r.status_code}_"
        logs = r.json().get("logs", [])
    except Exception as e:
        return f"_метрики: ошибка чтения логов ({str(e)[:60]})_"

    cutoff = (uae_now() - timedelta(hours=24)).replace(tzinfo=None)
    day = []
    for x in logs:
        try:
            if datetime.fromisoformat(x["ts"]) >= cutoff:
                day.append(x)
        except Exception:
            continue
    if not day:
        return "_за сутки диалогов не было_"

    phones = {x.get("phone") for x in day if x.get("phone")}
    bookings = sum(1 for x in day if x.get("action") == "book_appointment")
    errors = sum(1 for x in day if x.get("error"))
    had_slots = sum(1 for x in day if x.get("had_slots"))
    services = Counter(x.get("service") for x in day if x.get("service"))
    areas = Counter(x.get("area") for x in day if x.get("area"))
    conv = f"{(bookings / len(phones) * 100):.0f}%" if phones else "—"

    top_svc = ", ".join(f"{s}×{c}" for s, c in services.most_common(3)) or "—"
    top_area = ", ".join(f"{a}×{c}" for a, c in areas.most_common()) or "—"
    return (
        f"• Диалогов (сообщений): {len(day)}\n"
        f"• Уникальных клиентов: {len(phones)}\n"
        f"• Броней создано: {bookings}  (конверсия ~{conv})\n"
        f"• Ходов со слотами: {had_slots}\n"
        f"• Ошибок/сбоев: {errors}\n"
        f"• Топ услуг: {top_svc}\n"
        f"• Районы: {top_area}"
    )


# ── 3) new tester bug reports ─────────────────────────────────────────
def bug_reports() -> str:
    try:
        data = json.load(open(FEEDBACK_FILE, encoding="utf-8"))
    except Exception:
        return "_feedback_log недоступен_"
    items = data.get("items", [])
    cutoff = int((uae_now() - timedelta(hours=24)).timestamp())
    new = []
    for i in items:
        if i.get("status") != "new":
            continue
        if i.get("from_id") in EXCLUDE_IDS:
            continue
        if int(i.get("date", 0)) < cutoff:
            continue
        new.append(i)
    total_pending = sum(1 for i in items if i.get("status") == "new"
                        and i.get("from_id") not in EXCLUDE_IDS)
    if not new:
        return f"Новых за сутки: 0  (всего в разборе: {total_pending})"
    lines = [f"Новых за сутки: {len(new)}  (всего в разборе: {total_pending})"]
    # strip markdown-breaking chars from free text below
    for i in new[:8]:
        who = (i.get("from") or "?")[:18]
        txt = (i.get("text") or "").replace("\n", " ")[:90]
        lines.append(f"  • {who}: {txt}")
    return "\n".join(lines)


def build_report() -> str:
    now = uae_now()
    return (
        f"📊 Crystal Lab — ежедневный отчёт\n"
        f"{now:%d.%m.%Y %H:%M} (UAE)\n\n"
        f"🖥 СИСТЕМА\n{system_status()}\n\n"
        f"🤖 АГЕНТ ЗА СУТКИ\n{agent_metrics()}\n\n"
        f"🐛 БАГ-РЕПОРТЫ ТЕСТЕРОВ\n{bug_reports()}\n"
    )


def send(text: str):
    # Plain text (no parse_mode) — stylised unicode names and underscores in
    # log fields break Telegram Markdown.
    requests.post(
        f"https://api.telegram.org/bot{_bot_token()}/sendMessage",
        json={"chat_id": DMITRY_CHAT_ID, "text": text},
        timeout=20,
    ).raise_for_status()


def main():
    report = build_report()
    if "--dry" in sys.argv:
        print(report)
        return
    send(report)
    print("report sent")


if __name__ == "__main__":
    main()
