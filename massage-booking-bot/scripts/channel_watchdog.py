#!/usr/bin/env python3.11
"""Сторож канала Instagram: кричит, когда агент перестал получать людей.

Зачем. 2026-08-25 подписка ManyChat (Pro TRIAL) истекла около 14:30. Оба
направления умерли молча: External Request — функция платного тарифа —
перестал вызывать наш вебхук, а Sending API начал отвечать 401. Ночная
смена шла вхолостую, реклама крутилась, лиды писали в пустоту. Заметили
только потому, что владелец сам зашёл в ManyChat.

Ровно так же в июле отвалился Wappi — и это не замечали три недели. Урок
записан в правилах, но проверки не было ни одной, потому что «канал же
работает». Работает — пока не перестанет, и тишина выглядит как затишье.

Что проверяет:
  1. Ключ ManyChat жив (getInfo ≠ 401/403) — прямой признак подписки.
  2. Давно ли приходило входящее от РЕАЛЬНОГО контакта. Внутри ночного
     окна порог жёсткий (канал обязан жить), днём — мягче: днём трафик
     разрежен сам по себе.
  3. Не падают ли отправки подряд.

Тревога уходит в Telegram Дмитрию, не чаще раза в час, и повторяется,
пока канал не оживёт: одно сообщение в шуме теряется, а мёртвый канал
стоит денег каждый час.

Запуск: python3.11 scripts/channel_watchdog.py [--once]
"""

from __future__ import annotations

import argparse
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

STATE_PATH = os.path.join(_BOT_DIR, "logs", "_channel_watchdog.json")
PROD = "https://crystal-lab-bot.onrender.com"
ALERT_CHAT_ID = os.getenv("LOGPULL_ALERT_CHAT_ID", "1379584180")   # Dmitry DM
ALERT_COOLDOWN_SEC = 3600
SILENCE_NIGHT_MIN = 75      # ночью канал обязан приносить людей
SILENCE_DAY_MIN = 300       # днём трафик разрежен — порог мягче
POLL_SEC = 300


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


def _state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(st: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _alert(text: str, st: dict) -> None:
    now = time.time()
    if now - st.get("last_alert_ts", 0) < ALERT_COOLDOWN_SEC:
        return
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("!! нет TELEGRAM_BOT_TOKEN — тревога только в консоль")
        print(text)
        return
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": ALERT_CHAT_ID, "text": text}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
        st["last_alert_ts"] = now
    except Exception as e:
        print(f"не удалось отправить тревогу: {e}")


def _manychat_alive() -> tuple[bool, str]:
    key = _env("MANYCHAT_API_KEY")
    if not key:
        return True, "ключ не настроен — проверка пропущена"
    req = urllib.request.Request("https://api.manychat.com/fb/page/getInfo",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = (json.load(r).get("data") or {})
        return True, f"pro={data.get('is_pro')}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"HTTP {e.code} — подписка/ключ недействительны"
        return True, f"HTTP {e.code} (не про подписку)"
    except Exception as e:
        return True, f"сеть недоступна: {e}"


def _last_inbound_minutes() -> tuple[float | None, int]:
    """Минут с последнего входящего от РЕАЛЬНОГО контакта + число подряд
    неудачных отправок в хвосте лога."""
    secret = _env("MANYCHAT_WEBHOOK_SECRET")
    url = f"{PROD}/admin/night-log?" + urllib.parse.urlencode(
        {"secret": secret, "limit": 120})
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            events = json.load(r).get("events", [])
    except Exception:
        return None, 0
    now = datetime.now(timezone(timedelta(hours=4))).replace(tzinfo=None)
    last, fails = None, 0
    for e in events:
        who = str(e.get("who") or "").replace("ig:", "")
        if who.startswith("7700") or who == "999888777":
            continue                       # наши пробники — не трафик
        try:
            t = datetime.fromisoformat(str(e.get("ts", ""))).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
        if e.get("kind") == "inbound":
            last = t if last is None else max(last, t)
        if e.get("kind") == "send_failed":
            fails += 1
        elif e.get("kind") == "sent":
            fails = 0
    if last is None:
        return None, fails
    return (now - last).total_seconds() / 60.0, fails


def check_once() -> int:
    from agents.instagram_agent import ig_live_now

    st = _state()
    live = ig_live_now()
    alive, why = _manychat_alive()
    silent_min, fails = _last_inbound_minutes()
    limit = SILENCE_NIGHT_MIN if live else SILENCE_DAY_MIN

    problems = []
    if not alive:
        problems.append(f"ManyChat API не отвечает: {why}. "
                        "Похоже на истёкшую подписку — канал мёртв в обе стороны.")
    if silent_min is not None and silent_min > limit:
        problems.append(f"нет входящих {int(silent_min)} мин "
                        f"(порог {limit}, окно {'открыто' if live else 'закрыто'})")
    if fails >= 3:
        problems.append(f"{fails} неудачных отправок подряд")

    stamp = datetime.now().strftime("%d.%m %H:%M")
    if problems:
        text = ("🔴 Crystal Lab — канал Instagram молчит\n"
                + "\n".join(f"• {p}" for p in problems)
                + f"\n\nПроверено {stamp}. Реклама крутится, лиды уходят в пустоту.")
        print(text)
        _alert(text, st)
        st["broken_since"] = st.get("broken_since") or time.time()
    else:
        if st.get("broken_since"):
            down = int((time.time() - st["broken_since"]) / 60)
            _alert(f"🟢 Crystal Lab — канал Instagram снова живой "
                   f"(простой ~{down} мин). {stamp}", st)
            st.pop("broken_since", None)
            st["last_alert_ts"] = 0        # восстановление сообщаем сразу
        print(f"[{stamp}] канал в порядке | ManyChat: {why} | "
              f"тишина: {int(silent_min) if silent_min is not None else '—'} мин")
    _save(st)
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="одна проверка и выход")
    args = ap.parse_args()
    if args.once:
        return check_once()
    while True:
        try:
            check_once()
        except Exception as e:                      # сторож не имеет права падать
            print(f"проверка сорвалась: {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    sys.exit(main())
