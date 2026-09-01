#!/usr/bin/env python3.11
"""Прод-тестировщик: гоняет сценарии через НАСТОЯЩИЙ вебхук и судит ответы.

Зачем. Неделя запуска показала один и тот же паттерн четыре раза подряд:
юнит-тесты зелёные, а живое поведение другое — потому что юниты проверяют
функции, а клиент разговаривает с конвейером. Единственная проверка, которой
можно верить, — прогнать настоящий диалог через настоящий прод и посмотреть
на настоящие ответы. Всю неделю это делалось руками; этот скрипт делает то
же самое сам.

Как устроено. Каждый сценарий пишет с фиктивного ID 770099xxx (см.
`_is_smoke_id` в webhook_app.py): такие «клиенты» проходят весь конвейер как
тестеры — гейты, YClients, гонки буфера, — но их исходящие не уходят в
ManyChat, а только в ночной лог, откуда смоук их и читает. Ни один сценарий
не доходит до «yes»: записи не создаются, календарь не засоряется.

Проверки двух видов:
  - текстовые правила (оффер 275 с «instead of 430», чистка 420, карточки,
    запрет цен 3000/2590, запрет выдуманных ссылок, номер один раз, …);
  - каждое AM/PM-время из ответа сверяется с ЖИВЫМ YClients — предложенное
    занятое время это провал, даже если текст красивый.

Запуск:  python3.11 scripts/prod_smoke.py [--no-telegram] [--only NAME]
Вердикт: код 0 = всё зелёное; 1 = есть провалы (+ отчёт в Telegram Дмитрию).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BOT_DIR)

PROD = "https://crystal-lab-bot.onrender.com"
ALERT_CHAT_ID = os.getenv("LOGPULL_ALERT_CHAT_ID", "1379584180")   # Dmitry DM
TURN_WAIT = 27          # буфер 20с + генерация; ответ читается после паузы
_AMPM_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)


def _env(name: str) -> str:
    v = os.getenv(name)
    if v:
        return v
    try:
        for line in open(os.path.join(_BOT_DIR, ".env"), encoding="utf-8",
                         errors="replace"):
            m = re.match(rf"\s*{name}\s*=\s*(.+)", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


# ── сценарии ────────────────────────────────────────────────────────────────
# assert-правила получают СКЛЕЕННЫЙ текст всех ответов агента в сценарии и
# возвращают строку-претензию или None. Времена проверяются отдельно, для
# каждого ответа, против живого YClients.

def _has(*needles, why=""):
    def check(text):
        missing = [n for n in needles if n.lower() not in text.lower()]
        if missing:
            return f"нет {missing} — {why}"
        return None
    return check


def _lacks(*needles, why=""):
    def check(text):
        found = [n for n in needles if n.lower() in text.lower()]
        if found:
            return f"запрещённое {found} — {why}"
        return None
    return check


def _once(needle, why=""):
    def check(text):
        n = text.lower().count(needle.lower())
        if n > 1:
            return f"«{needle}» встретилось {n} раза — {why}"
        return None
    return check


SCENARIOS = [
    {
        "name": "package_abu_dhabi",
        "sid": "770099001",
        "area": "abu_dhabi",
        "turns": [
            "Hello, I would like to sign up for a massage package in Abu Dhabi at a discount.",
        ],
        "asserts": [
            _has("275", "430", why="оффер банок обязан идти со старой ценой"),
            _lacks("3000", "2590", "2,590", "3,000",
                   why="легаси-курсы запрещены (Татьяна 15.08)"),
            _has("number", why="номер спрашивается сразу после цены (Татьяна 25.08)"),
            _lacks("body massage or facial",
                   why="на баночной рекламе выбора тело/лицо нет"),
        ],
    },
    {
        "name": "summer_leads_with_cleansing",
        "sid": "770099002",
        "area": "abu_dhabi",
        "turns": [
            "Hello, I would like to sign up for the summer promotion in Abu Dhabi.",
        ],
        "asserts": [
            _has("420", why="summer-креатив сейчас про чистку (Татьяна 27.08)"),
            _has("770", why="скидка без старой цены — не скидка"),
        ],
    },
    {
        "name": "cleansing_prefill",
        "sid": "770099003",
        "area": None,
        "turns": [
            "Hello, I want to know the details about the promotion and get advice",
        ],
        "asserts": [
            _has("420", why="чистка = 420"),
            _lacks("50 min - 370", "50 min — 370",
                   why="цена лицевого массажа на вопрос о чистке (баг 18.08)"),
        ],
    },
    {
        "name": "new_face_prefill_al_ain",
        "sid": "770099004",
        "area": "al_ain",
        "turns": [
            "Hello, I would like to consult you about a facial massage in Al Ain",
        ],
        "asserts": [
            _has("370", why="новая связка на лицо → 370 (Татьяна 30.08)"),
        ],
    },
    {
        "name": "bare_hi_asks_then_cards",
        "sid": "770099005",
        "area": None,
        "turns": ["Hi", "face"],
        # Татьяна 01.09: на голое «Hi» — вопрос лицо/тело/чистка; карточка —
        # после выбора. Эмират спрашивается до времён.
        "asserts": [
            _has("face massage", "body massage", "cleansing",
                 why="на «Hi» агент спрашивает, что нужно"),
            _has("1650", why="после «face» — полная карточка лица (абонемент)"),
            _lacks("1550", why="карточка тела не уходит, когда выбрано лицо"),
            _lacks("what services are you interested in",
                   why="меню на первом ходе заменено вопросом об услуге"),
        ],
        "forbid_times": True,
    },
    {
        "name": "evening_time_and_no_double_number",
        "sid": "770099006",
        "area": "abu_dhabi",
        "turns": [
            "Hello, I would like to sign up for a massage package in Abu Dhabi at a discount.",
            "Evening at 9:00",
        ],
        "asserts": [
            _lacks("9:00 AM", why="«Evening at 9:00» — это вечер, не утро (кейс Самар)"),
            _once("your number", why="номер спрашивается один раз (кейс 27.08)"),
        ],
    },
    {
        "name": "location_question",
        "sid": "770099007",
        "area": None,
        "turns": [
            "Hello, I would like to sign up for a massage package in Dubai at a discount.",
            "Location",
        ],
        "asserts": [
            _has("home service", why="«Location» = вопрос где мы (Татьяна 26.08)"),
        ],
    },
    {
        "name": "what_tame_is_a_time_question",
        "sid": "770099009",
        "area": "abu_dhabi",
        "turns": [
            "Hello, I would like to sign up for a massage package in Abu Dhabi at a discount.",
            "what tame",
        ],
        # «Когда?» с опечаткой не может быть отвечен голым прайсом
        # (Um Nasser 30.08). В ответе обязано быть хоть что-то о времени.
        "asserts": [
            # Раньше требовалось слово «day» — и сценарий проходил только
            # потому, что «Today» его содержит; «Tomorrow we have 10:00 AM…»
            # (образцовый ответ) заваливался. Ложная тревога 01.09 21:32.
            (lambda t: None if (_AMPM_RE.search(t) or re.search(
                r"\b(?:today|tomorrow|which day|what time)\b", t, re.I))
             else "ответ на «what tame» не говорит ни о времени, ни о дне"),
        ],
    },
    {
        "name": "no_times_without_emirate",
        "sid": "770099008",
        "area": None,
        "turns": [
            "Hello, I want to know the details about the promotion and get advice",
            "What time tomorrow?",
        ],
        # Ни одного конкретного времени, пока эмират неизвестен (Алина 30.08).
        "asserts": [
            _has("Abu Dhabi", why="без эмирата агент обязан спросить город"),
        ],
        "forbid_times": True,
    },
]


# ── обвязка ────────────────────────────────────────────────────────────────

def _post(secret: str, sid: str, text: str) -> None:
    body = json.dumps({"secret": secret, "subscriber_id": sid, "text": text})
    req = urllib.request.Request(
        f"{PROD}/webhook/manychat", data=body.encode(),
        headers={"Content-Type": "application/json"})
    # Первый прогон попал в прогрев Render сразу после деплоя: три сценария
    # умерли на 502. Смоук обязан переживать перезапуск сервиса.
    for attempt in range(3):
        try:
            urllib.request.urlopen(req, timeout=35).read()
            return
        except urllib.error.HTTPError as e:
            if e.code not in (502, 503) or attempt == 2:
                raise
            time.sleep(12)


def _agent_texts(secret: str, sid: str, since) -> list:
    url = f"{PROD}/admin/night-log?" + urllib.parse.urlencode(
        {"secret": secret, "limit": 300})
    with urllib.request.urlopen(url, timeout=30) as r:
        events = json.load(r).get("events", [])
    out = []
    for e in events:
        if str(e.get("who") or "").replace("ig:", "") != sid:
            continue
        if e.get("kind") != "sent":
            continue
        try:
            t = datetime.fromisoformat(str(e.get("ts", ""))).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
        if t >= since:
            out.append(str(e.get("text") or ""))
    return out


async def _times_really_free(replies: list, area: str) -> list:
    """Каждое предложенное время должно существовать в живом календаре."""
    from services.yclients_service import YClientsService

    problems = []
    if not area:
        return problems
    yc = YClientsService()
    now = datetime.now(timezone(timedelta(hours=4)))
    for reply in replies:
        # День определяется ПОСТРОЧНО: ответ «Today we have… / Tomorrow…»
        # относил завтрашние времена к сегодняшнему календарю — ложная
        # тревога 31.08 (агент был прав, смоук ошибся).
        for line in reply.split("\n"):
            low = line.lower()
            if "today" in low:
                day = now.strftime("%Y-%m-%d")
            elif "tomorrow" in low:
                day = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                continue                # день не назван — время не проверить
            reply = line
            for h, m, mer in _AMPM_RE.findall(reply):
                hh = int(h) % 12 + (12 if mer.upper() == "PM" else 0)
                hhmm = f"{hh:02d}:{int(m or 0):02d}"
                try:
                    ok = await yc.is_slot_available(area, day, hhmm, 45)
                except Exception:
                    continue            # сбой API ничего не судит
                if ok is False:
                    problems.append(
                        f"предложено занятое {h}:{m or '00'} {mer} на {day}")
    return problems


def _telegram(text: str) -> None:
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": ALERT_CHAT_ID, "text": text}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--only", default=None, help="имя одного сценария")
    args = ap.parse_args()

    secret = _env("MANYCHAT_WEBHOOK_SECRET")
    if not secret:
        print("нет MANYCHAT_WEBHOOK_SECRET")
        return 2

    todo = [s for s in SCENARIOS if not args.only or s["name"] == args.only]
    failures, passed = [], 0
    for sc in todo:
        since = datetime.now(timezone(timedelta(hours=4))).replace(tzinfo=None)
        print(f"▶ {sc['name']}")
        try:
            _post(secret, sc["sid"], "/clear")
            time.sleep(10)
            for turn in sc["turns"]:
                _post(secret, sc["sid"], turn)
                time.sleep(TURN_WAIT)
            time.sleep(8)
            replies = _agent_texts(secret, sc["sid"], since)
        except Exception as e:
            failures.append(f"{sc['name']}: обвязка упала — {e}")
            continue
        if not replies:
            failures.append(f"{sc['name']}: агент не ответил вовсе")
            continue
        blob = "\n".join(r for r in replies if "Memory cleared" not in r)
        probs = [p for chk in sc["asserts"] if (p := chk(blob))]
        if sc.get("forbid_times") and _AMPM_RE.search(blob):
            probs.append("названы конкретные времена при неизвестном эмирате")
        probs += asyncio.run(_times_really_free(replies, sc.get("area")))
        if probs:
            failures.append(f"{sc['name']}:\n   " + "\n   ".join(probs))
            print(f"   ❌ {probs}")
        else:
            passed += 1
            print("   ✅")

    stamp = datetime.now().strftime("%d.%m %H:%M")
    if failures:
        report = (f"🔴 Смоук прода Crystal Lab {stamp}: "
                  f"{passed}/{len(todo)} ок\n\n" + "\n\n".join(failures))
        print(report)
        if not args.no_telegram:
            _telegram(report[:3800])
        return 1
    print(f"🟢 смоук: {passed}/{len(todo)} сценариев чисто ({stamp})")
    if not args.no_telegram:
        _telegram(f"🟢 Смоук прода Crystal Lab: {passed}/{len(todo)} чисто ({stamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
