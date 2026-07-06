"""Structured per-turn logger for the WhatsApp agent.

Persists one JSON line per client turn with the fields needed to debug the
booking pipeline later (area/service detection, whether real slots were
injected, which tool fired, booking outcome). Conversations themselves are
already stored in the DB `messages` table — this captures the INTERNAL
decisions that the message text doesn't show.

Writes to the Render persistent disk (/data) when available so logs survive
redeploys; falls back to ./logs locally. Path override: TURN_LOG_PATH.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger


def _default_path() -> str:
    if os.getenv("TURN_LOG_PATH"):
        return os.getenv("TURN_LOG_PATH")
    if os.path.isdir("/data"):        # Render persistent disk
        return "/data/turn_logs.jsonl"
    return os.path.join("logs", "turn_logs.jsonl")


LOG_PATH = _default_path()


def log_turn(
    phone: str,
    client_text: str,
    *,
    area: Optional[str] = None,
    service: Optional[str] = None,
    had_slots: bool = False,
    reply: Optional[str] = None,
    action: Optional[str] = None,
    booking: Optional[Any] = None,
    error: Optional[str] = None,
) -> None:
    """Append one structured turn record (best-effort — never raises)."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        rec = {
            # naive UAE local time to match the rest of the system
            "ts": (datetime.utcnow() + timedelta(hours=4)).isoformat(timespec="seconds"),
            "phone": phone,
            "client": (client_text or "")[:500],
            "area": area,
            "service": service,
            "had_slots": had_slots,
            "action": action,          # book_appointment | cancel | reschedule | None
            "booking": booking,        # e.g. {"id":.., "yclients_id":..} or None
            "reply": (reply or "")[:800],
            "error": error,
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # logging must never break a turn
        logger.warning(f"turn_logger failed: {e}")


def read_recent(n: int = 50) -> list:
    """Return the last n turn records (for the admin log endpoint)."""
    try:
        if not os.path.exists(LOG_PATH):
            return []
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out
    except Exception as e:
        logger.warning(f"turn_logger read failed: {e}")
        return []
