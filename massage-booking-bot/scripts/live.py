#!/usr/bin/env python3
"""Живой монитор ночной смены — смотреть систему в реальном времени.

Держи открытым в отдельном окне, пока тестируешь: каждый входящий и каждый
ответ агента появляются здесь через 3–5 секунд после того, как случились в
Instagram. Читает постоянный лог из Postgres (переживает деплой), поэтому
показывает и то, что произошло до запуска монитора.

Показывает как диалог, подсвечивает важное:
  📅 создана запись   ❌ сбой отправки   🔇 заблокировано днём

Usage:
    python3.11 scripts/live.py                 # весь поток, обновление 5 сек
    python3.11 scripts/live.py --who 868311272 # только один клиент
    python3.11 scripts/live.py --tail 30       # показать 30 прошлых событий
    python3.11 scripts/live.py --every 3       # опрашивать чаще
"""

from __future__ import annotations

import argparse
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
MINSK = timezone(timedelta(hours=3))

DIM = "\033[2m"; BOLD = "\033[1m"; RESET = "\033[0m"
BLUE = "\033[94m"; GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"


def _secret() -> str:
    from config import config
    if not config.MANYCHAT_WEBHOOK_SECRET:
        sys.exit("MANYCHAT_WEBHOOK_SECRET не задан в .env")
    return config.MANYCHAT_WEBHOOK_SECRET


def fetch(secret: str, limit: int = 400) -> dict:
    q = urllib.parse.urlencode({"secret": secret, "limit": limit})
    with urllib.request.urlopen(f"{PROD}/admin/night-log?{q}", timeout=30) as r:
        return json.loads(r.read())


def health() -> str:
    try:
        with urllib.request.urlopen(f"{PROD}/", timeout=20) as r:
            d = json.loads(r.read())
        ig = d.get("ig", {})
        win = f"{GREEN}ОКНО ОТКРЫТО{RESET}" if ig.get("live_now") else f"{DIM}окно закрыто (день){RESET}"
        return (f"прод: {d.get('status')} | {win} | бронь: "
                f"{'вкл' if ig.get('booking_enabled') else 'ВЫКЛ'} | {ig.get('model')}")
    except Exception as e:
        return f"{RED}прод НЕ ОТВЕЧАЕТ: {str(e)[:50]}{RESET}"


def key(e: dict) -> str:
    return f"{e.get('ts')}|{e.get('kind')}|{e.get('who')}|{str(e.get('text'))[:70]}"


def show(e: dict) -> None:
    """Одно событие в виде строки диалога (время — минское)."""
    raw = str(e.get("ts", ""))
    try:
        t = datetime.fromisoformat(raw).astimezone(MINSK).strftime("%H:%M:%S")
    except ValueError:
        t = raw[11:19]
    kind = e.get("kind", "")
    who = str(e.get("who") or "").replace("ig:", "")[:12]
    text = str(e.get("text") or "")

    if kind == "inbound":
        print(f"{DIM}{t}{RESET} {BOLD}{BLUE}КЛИЕНТ{RESET} {DIM}{who}{RESET}")
        for line in text.splitlines():
            print(f"          {line}")
    elif kind == "sent":
        print(f"{DIM}{t}{RESET} {BOLD}{GREEN}АГЕНТ {RESET} {DIM}{who}{RESET}")
        for line in text.splitlines():
            print(f"          {line}")
    elif kind == "booking_created":
        print(f"{DIM}{t}{RESET} {BOLD}{GREEN}📅 ЗАПИСЬ СОЗДАНА{RESET} #{e.get('record')} "
              f"{e.get('service')} {e.get('date')} {e.get('time')} "
              f"{e.get('master') or ''} {DIM}({who}){RESET}")
    elif kind == "send_failed":
        print(f"{DIM}{t}{RESET} {BOLD}{RED}❌ СБОЙ ОТПРАВКИ{RESET} {who} {text[:70]}")
    elif kind == "send_blocked_daytime":
        print(f"{DIM}{t}{RESET} {YELLOW}🔇 заблокировано (день){RESET} {who} {text[:60]}")
    elif kind == "routed_to_booking":
        print(f"{DIM}{t}   → передано в booking-пайплайн{RESET}")
    else:
        print(f"{DIM}{t}   [{kind}] {who} {text[:60]}{RESET}")
    sys.stdout.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", help="только этот subscriber_id")
    ap.add_argument("--every", type=int, default=5, help="интервал опроса, сек")
    ap.add_argument("--tail", type=int, default=10, help="сколько прошлых событий показать")
    args = ap.parse_args()

    secret = _secret()
    seen: set[str] = set()
    print(f"\n{BOLD}═══ ЖИВОЙ МОНИТОР ═══{RESET}  {health()}")
    print(f"{DIM}обновление каждые {args.every} сек · Ctrl+C для выхода{RESET}\n")

    first = True
    last_health = time.time()
    while True:
        try:
            data = fetch(secret)
        except Exception as e:
            print(f"{RED}!! лог недоступен: {str(e)[:60]}{RESET}")
            time.sleep(args.every)
            continue

        events = [e for e in (data.get("events") or [])
                  if not args.who or args.who in str(e.get("who") or "")]
        if first:
            tail = events[-args.tail:] if args.tail else []
            for e in events[:-args.tail] if args.tail else events:
                seen.add(key(e))
            if tail:
                print(f"{DIM}— последние {len(tail)} событий —{RESET}")
            for e in tail:
                seen.add(key(e))
                show(e)
            print(f"{DIM}— ждём новые… (источник: {data.get('source')}, "
                  f"всего в базе: {data.get('total_kept')}) —{RESET}\n")
            first = False
        else:
            for e in events:
                k = key(e)
                if k not in seen:
                    seen.add(k)
                    show(e)

        # раз в 5 минут напоминаем состояние прода — чтобы падение не осталось незамеченным
        if time.time() - last_health > 300:
            print(f"\n{DIM}[{datetime.now(MINSK):%H:%M}] {health()}{RESET}\n")
            last_health = time.time()

        time.sleep(args.every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nмонитор остановлен")
