#!/usr/bin/env python3
"""Проверка ВСЕЙ цепочки: клиент → ManyChat → прод → мозг → YClients → БД.

Один вызов отвечает на вопрос «работает подключение или нет» по каждому
звену отдельно, чтобы не гадать, где обрыв. Каждая проверка независима:
падение одной не мешает остальным, в конце — сводка.

Usage:
    python3.11 scripts/doctor.py            # все проверки
    python3.11 scripts/doctor.py --quick    # без LLM и YClients (быстро)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROD = "https://crystal-lab-bot.onrender.com"
UAE = timezone(timedelta(hours=4))
MINSK = timezone(timedelta(hours=3))

OK, FAIL, WARN = "✅", "❌", "⚠️ "
results: list[tuple[str, str, str]] = []


def note(mark: str, name: str, detail: str = "") -> None:
    results.append((mark, name, detail))
    print(f"{mark} {name}" + (f" — {detail}" if detail else ""), flush=True)


def _get_json(url: str, timeout: int = 25, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check_prod() -> dict:
    """Звено 1: сам сервис на Render отвечает."""
    try:
        t0 = time.time()
        d = _get_json(f"{PROD}/", timeout=30)
        ms = int((time.time() - t0) * 1000)
        ig = d.get("ig", {})
        note(OK, "Прод (Render)", f"status={d.get('status')}, {ms} ms")
        note(OK if ig.get("manychat") else FAIL, "ManyChat-ключ в проде",
             "настроен" if ig.get("manychat") else "MANYCHAT_API_KEY пуст!")
        note(OK if ig.get("booking_enabled") else WARN, "Бронирование в IG",
             "включено" if ig.get("booking_enabled") else "ВЫКЛЮЧЕНО")
        live = ig.get("live_now")
        note(OK if live else WARN, "Ночное окно",
             f"{'ОТКРЫТО (агент отвечает)' if live else 'закрыто (день — тишина)'}"
             f", {ig.get('window')}")
        note(OK, "Модель", str(ig.get("model")))
        return d
    except Exception as e:
        note(FAIL, "Прод (Render)", f"НЕ ОТВЕЧАЕТ: {str(e)[:90]}")
        return {}


def check_bridge_and_db() -> None:
    """Звенья 2-3: мост ManyChat→прод принимает запрос, и событие ложится в
    Postgres (а не только в память, которая умирает при деплое)."""
    from config import config

    secret = config.MANYCHAT_WEBHOOK_SECRET
    if not secret:
        note(FAIL, "Мост /webhook/manychat", "MANYCHAT_WEBHOOK_SECRET не задан локально")
        return
    probe = f"doctor probe {datetime.now(MINSK):%H:%M:%S}"
    try:
        req = urllib.request.Request(
            f"{PROD}/webhook/manychat?secret={urllib.parse.quote(secret)}",
            data=json.dumps({"subscriber_id": "999888777", "text": probe}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        note(OK, "Мост ManyChat → прод", f"ответ {json.dumps(resp)[:60]}")
    except Exception as e:
        note(FAIL, "Мост ManyChat → прод", str(e)[:90])
        return

    time.sleep(4)
    try:
        q = urllib.parse.urlencode({"secret": secret, "limit": 400})
        d = _get_json(f"{PROD}/admin/night-log?{q}", timeout=30)
        src = d.get("source")
        found = any(probe in str(e.get("text") or "") for e in d.get("events", []))
        note(OK if src == "db" else FAIL, "Хранилище логов",
             f"источник={src} ({'Postgres — переживёт деплой' if src == 'db' else 'ПАМЯТЬ — умрёт при деплое!'})")
        note(OK if found else FAIL, "Запись события в БД",
             "проба долетела" if found else "проба НЕ найдена в логе")
        note(OK, "Событий в базе", str(d.get("total_kept")))
    except Exception as e:
        note(FAIL, "Чтение /admin/night-log", str(e)[:90])


def check_manychat_api() -> None:
    """Звено 4: наш ключ к ManyChat жив (иначе не сможем ни писать, ни читать)."""
    from config import config

    if not config.MANYCHAT_API_KEY:
        note(FAIL, "ManyChat API", "ключ не задан")
        return
    try:
        d = _get_json("https://api.manychat.com/fb/page/getInfo",
                      headers={"Authorization": f"Bearer {config.MANYCHAT_API_KEY}"})
        data = d.get("data", {})
        note(OK, "ManyChat API", f"аккаунт «{str(data.get('name'))[:32]}», "
                                 f"Pro={data.get('is_pro')}")
    except Exception as e:
        note(FAIL, "ManyChat API", str(e)[:90])


async def check_yclients() -> None:
    """Звено 5: календарь отвечает и отдаёт реальные слоты."""
    from services.yclients_service import YClientsService

    try:
        y = YClientsService()
        staff = await y.get_staff()
        if staff is None:
            note(FAIL, "YClients", "API не ответил (outage/лимит)")
            return
        note(OK, "YClients: персонал", f"{len(staff)} мастеров")
        tomorrow = (datetime.now(UAE) + timedelta(days=1)).strftime("%Y-%m-%d")
        s = await y.get_available_slots_summary(
            date=tomorrow, service_category="massage",
            area="abu_dhabi", service_duration=60)
        first = (s or "").splitlines()[0][:60]
        bad = "TEMPORARILY UNAVAILABLE" in (s or "")
        note(FAIL if bad else OK, f"YClients: слоты на {tomorrow}",
             "сбой API" if bad else first)
    except Exception as e:
        note(FAIL, "YClients", str(e)[:90])


async def check_llm() -> None:
    """Звено 6: мозг агента отвечает (модель + ключ OpenAI)."""
    try:
        from agents.instagram_agent import generate_ig_reply
        t0 = time.time()
        reply = await asyncio.wait_for(
            generate_ig_reply("doctor:probe", "hello, how much is a body massage?"),
            timeout=45)
        ms = int((time.time() - t0) * 1000)
        ok = bool(reply and len(reply) > 5)
        note(OK if ok else FAIL, "Мозг агента (OpenAI)",
             f"{ms} ms, ответ: {str(reply)[:60]}…")
    except Exception as e:
        note(FAIL, "Мозг агента (OpenAI)", str(e)[:90])


def check_telegram() -> None:
    """Звено 7: алерты о лидах/сбоях дойдут до админ-группы."""
    from config import config

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        note(WARN, "Telegram-алерты", "токен не задан")
        return
    try:
        d = _get_json(f"https://api.telegram.org/bot{token}/getMe", timeout=20)
        note(OK, "Telegram-бот", f"@{d['result']['username']}")
    except Exception as e:
        note(FAIL, "Telegram-бот", str(e)[:90])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="без LLM и YClients")
    args = ap.parse_args()

    print(f"\n=== ДИАГНОСТИКА ЦЕПОЧКИ  {datetime.now(MINSK):%d.%m %H:%M} Минск "
          f"/ {datetime.now(UAE):%H:%M} Абу-Даби ===\n")
    check_prod()
    print()
    check_manychat_api()
    check_bridge_and_db()
    print()
    check_telegram()
    if not args.quick:
        print()
        await check_yclients()
        await check_llm()

    bad = [r for r in results if r[0] == FAIL]
    warn = [r for r in results if r[0] == WARN]
    print(f"\n=== ИТОГ: {len(results) - len(bad) - len(warn)} ок, "
          f"{len(warn)} предупреждений, {len(bad)} сбоев ===")
    for mark, name, detail in bad + warn:
        print(f"  {mark} {name} — {detail}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    asyncio.run(main())
