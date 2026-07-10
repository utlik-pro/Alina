#!/usr/bin/env python3
"""Pull WhatsApp dialogues (admin/tester conversations with the agent) from
Wappi — the token-rot-proof log channel.

Why this exists: the Render CLI log stream died silently for a MONTH (expired
OAuth token → the launchd streamer wrote nothing but "Unauthorized" 12-24 MB/day
and nobody noticed) — the whole client testing sprint ran blind. This puller
depends ONLY on WAPPI_TOKEN (a static API key we already need for the agent to
reply at all — if it dies, the agent stops answering, which is noticed within
minutes, never silently).

What it does (one shot; launchd re-runs it on an interval):
  1. GET /api/sync/chats/get            → all dialogs
  2. GET /api/sync/messages/get per chat → recent messages
  3. Append NEW messages (dedup by id) to logs/wappi_chats/<phone>.jsonl
  4. On repeated failures → Telegram DM alert (rate-limited) so a dead channel
     is NEVER silent again.

Run:  python3.11 scripts/pull_wappi_chats.py           # incremental pull
      python3.11 scripts/pull_wappi_chats.py --status  # show channel health
"""

import asyncio
import json
import os
import sys
import time

import aiohttp
from dotenv import load_dotenv

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BOT_DIR, ".env"))

WAPPI_TOKEN = os.getenv("WAPPI_TOKEN")
WAPPI_PROFILE = os.getenv("WAPPI_PROFILE_ID")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALERT_CHAT_ID = os.getenv("LOGPULL_ALERT_CHAT_ID", "1379584180")  # Dmitry DM
# Optional 2nd channel: the bot's structured turn logs (internal decisions —
# gates, detected area/service, slot injection). Needs WEBHOOK_SECRET copied
# ONCE from the Render dashboard (Environment tab) into the local .env.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
PROD_URL = os.getenv("PROD_URL", "https://crystal-lab-bot.onrender.com")
TURN_LOG_OUT = os.path.join(_BOT_DIR, "logs", "prod_turn_logs.jsonl")

OUT_DIR = os.path.join(_BOT_DIR, "logs", "wappi_chats")
STATE_PATH = os.path.join(OUT_DIR, "_state.json")
PER_CHAT_LIMIT = 100          # messages per chat per pull
ALERT_COOLDOWN_SEC = 6 * 3600  # don't spam: one alert per 6h
FAILS_BEFORE_ALERT = 3         # consecutive failed pulls before alerting


def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


async def _alert(session: aiohttp.ClientSession, text: str, state: dict) -> None:
    """Telegram DM, rate-limited via state — a dying channel must be LOUD."""
    now = time.time()
    if now - state.get("last_alert_ts", 0) < ALERT_COOLDOWN_SEC:
        return
    state["last_alert_ts"] = now
    if not TG_TOKEN:
        return
    try:
        await session.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": ALERT_CHAT_ID, "text": text},
            timeout=aiohttp.ClientTimeout(total=15),
        )
    except Exception:
        pass  # alerting is best-effort


async def _get(session: aiohttp.ClientSession, path: str, params: dict) -> dict:
    async with session.get(
        "https://wappi.pro" + path,
        params=params,
        headers={"Authorization": WAPPI_TOKEN},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as r:
        data = await r.json(content_type=None)
        if r.status != 200 or str(data.get("status", "")).lower() not in ("done", "ok", "success"):
            raise RuntimeError(f"Wappi {path} HTTP {r.status}: {str(data)[:200]}")
        return data


def _norm_msg(m: dict) -> dict:
    """Keep the fields that matter for reviewing a test conversation."""
    raw = m.get("body") or m.get("text") or m.get("caption") or ""
    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False)  # media/location bodies are dicts
    mid = m.get("id") or m.get("message_id")
    if isinstance(mid, dict):  # some Wappi variants nest the id
        mid = mid.get("id") or mid.get("_serialized") or json.dumps(mid, sort_keys=True)
    return {
        "id": mid,
        "t": m.get("timestamp") or m.get("time") or m.get("t"),
        "from_me": bool(m.get("fromMe")),
        "type": m.get("type") or "chat",
        "body": raw[:2000],
    }


async def pull() -> int:
    """One incremental pull. Returns number of NEW messages written."""
    state = _load_state()
    os.makedirs(OUT_DIR, exist_ok=True)
    new_total = 0
    async with aiohttp.ClientSession() as session:
        try:
            chats = await _get(session, "/api/sync/chats/get", {"profile_id": WAPPI_PROFILE})
            dialogs = chats.get("dialogs") or []
            for d in dialogs:
                chat_id = d.get("id") or ""
                # personal chats only ("...@c.us"); skip groups/status/newsletter
                if not chat_id.endswith("@c.us"):
                    continue
                phone = chat_id.split("@")[0]
                msgs_raw = await _get(
                    session, "/api/sync/messages/get",
                    {"profile_id": WAPPI_PROFILE, "chat_id": chat_id, "limit": str(PER_CHAT_LIMIT)},
                )
                seen = set(state.get("seen", {}).get(phone, []))
                out_path = os.path.join(OUT_DIR, f"{phone}.jsonl")
                fresh = []
                for m in (msgs_raw.get("messages") or []):
                    nm = _norm_msg(m)
                    if not nm["id"] or nm["id"] in seen:
                        continue
                    fresh.append(nm)
                    seen.add(nm["id"])
                if fresh:
                    fresh.sort(key=lambda x: x.get("t") or 0)
                    with open(out_path, "a", encoding="utf-8") as f:
                        for nm in fresh:
                            f.write(json.dumps(nm, ensure_ascii=False) + "\n")
                    new_total += len(fresh)
                # cap the per-phone dedup memory (last 500 ids is plenty)
                state.setdefault("seen", {})[phone] = list(seen)[-500:]

            state["last_ok_ts"] = time.time()
            state["consec_fails"] = 0
            state.pop("last_error", None)

            # Channel 2 (optional): structured turn logs off the prod /data
            # disk via /admin/logs. Skipped quietly until WEBHOOK_SECRET is set.
            if WEBHOOK_SECRET:
                try:
                    async with session.get(
                        f"{PROD_URL}/admin/logs", params={"n": "300"},
                        headers={"X-Admin-Secret": WEBHOOK_SECRET},
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as r:
                        if r.status == 200:
                            payload = await r.json(content_type=None)
                            seen_ts = set(state.get("turn_seen", []))
                            fresh = []
                            for rec in payload.get("logs") or []:
                                key = f"{rec.get('ts')}|{rec.get('phone')}"
                                if key in seen_ts:
                                    continue
                                fresh.append(rec)
                                seen_ts.add(key)
                            if fresh:
                                with open(TURN_LOG_OUT, "a", encoding="utf-8") as f:
                                    for rec in fresh:
                                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                                new_total += len(fresh)
                            state["turn_seen"] = list(seen_ts)[-1000:]
                        else:
                            print(f"turn-log pull HTTP {r.status} (check WEBHOOK_SECRET)", file=sys.stderr)
                except Exception as e:
                    print(f"turn-log pull failed: {e}", file=sys.stderr)
        except Exception as e:
            state["consec_fails"] = state.get("consec_fails", 0) + 1
            state["last_error"] = str(e)[:300]
            if state["consec_fails"] >= FAILS_BEFORE_ALERT:
                await _alert(
                    session,
                    "⚠️ Crystal Lab: канал логов Wappi НЕ работает "
                    f"({state['consec_fails']} подряд): {str(e)[:150]}\n"
                    "Переписки тестеров не собираются — проверь WAPPI_TOKEN.",
                    state,
                )
            _save_state(state)
            print(f"PULL FAILED ({state['consec_fails']} consec): {e}", file=sys.stderr)
            return -1
    _save_state(state)
    return new_total


def status() -> None:
    state = _load_state()
    ok = state.get("last_ok_ts")
    age = f"{int((time.time() - ok) / 60)} min ago" if ok else "never"
    print(f"last successful pull : {age}")
    print(f"consecutive failures : {state.get('consec_fails', 0)}")
    print(f"last error           : {state.get('last_error', '—')}")
    files = [f for f in os.listdir(OUT_DIR) if f.endswith(".jsonl")] if os.path.isdir(OUT_DIR) else []
    print(f"chats collected      : {len(files)}")
    for f in sorted(files):
        path = os.path.join(OUT_DIR, f)
        with open(path, encoding="utf-8") as fh:
            n = sum(1 for _ in fh)
        print(f"  {f}: {n} messages")


if __name__ == "__main__":
    if "--status" in sys.argv:
        status()
    else:
        n = asyncio.run(pull())
        if n >= 0:
            print(f"OK: {n} new messages")
