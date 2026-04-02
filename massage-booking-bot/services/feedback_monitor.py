#!/usr/bin/env python3
"""Feedback Monitor — автоматический сбор замечаний из чата Crystal разработка.

Запускается по крону каждые 5 минут.
Сохраняет новые сообщения от тестировщиков в feedback_log.json.
Пропускает сообщения от ботов и свои же отчёты.

Usage:
    python3.11 services/feedback_monitor.py
"""

import json
import os
import sys
import requests
from datetime import datetime

# Config
BOT_TOKEN = "8294238787:AAGyCIaaL41nSHrsuy4ONUr4emylTtJvVj8"
CHAT_ID = -5059625262
FEEDBACK_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "feedback_log.json")

# Bot usernames to ignore (our own bots)
IGNORE_BOTS = {"utlik_pm_bot", "crystal_lab_bot"}


def load_feedback() -> dict:
    """Load existing feedback log."""
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_check_date": 0, "items": []}


def save_feedback(data: dict):
    """Save feedback log."""
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_new_messages(last_date: int) -> list:
    """Fetch new messages from the chat after last_date."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": -100, "limit": 100}, timeout=10)
    data = resp.json()

    if not data.get("ok"):
        print(f"Error fetching updates: {data}")
        return []

    messages = []
    for update in data.get("result", []):
        msg = update.get("message", {})
        chat = msg.get("chat", {})

        # Only our chat
        if chat.get("id") != CHAT_ID:
            continue

        # Only after last check
        msg_date = msg.get("date", 0)
        if msg_date <= last_date:
            continue

        # Skip bot messages
        from_user = msg.get("from", {})
        if from_user.get("is_bot"):
            continue
        username = from_user.get("username", "")
        if username in IGNORE_BOTS:
            continue

        # Skip our own report messages (from Dmitry via bot)
        first_name = from_user.get("first_name", "")
        # Include ALL human messages

        text = msg.get("text", "") or msg.get("caption", "")
        has_photo = bool(msg.get("photo"))

        if text or has_photo:
            messages.append({
                "date": msg_date,
                "datetime": datetime.fromtimestamp(msg_date).strftime("%Y-%m-%d %H:%M"),
                "from": f"{first_name} {from_user.get('last_name', '')}".strip(),
                "from_id": from_user.get("id"),
                "text": text,
                "has_photo": has_photo,
                "photo_file_id": msg["photo"][-1]["file_id"] if has_photo else None,
                "status": "new",  # new → in_progress → done → wont_fix
            })

    return messages


def run():
    """Main monitoring loop iteration."""
    feedback = load_feedback()
    last_date = feedback.get("last_check_date", 0)

    new_msgs = get_new_messages(last_date)

    if not new_msgs:
        return 0

    # Deduplicate by date+from_id
    existing_keys = {(item["date"], item.get("from_id")) for item in feedback["items"]}

    added = 0
    for msg in new_msgs:
        key = (msg["date"], msg.get("from_id"))
        if key not in existing_keys:
            feedback["items"].append(msg)
            existing_keys.add(key)
            added += 1

    if added > 0:
        # Update last check date
        feedback["last_check_date"] = max(m["date"] for m in new_msgs)
        save_feedback(feedback)
        print(f"[{datetime.now().strftime('%H:%M')}] Added {added} new feedback items (total: {len(feedback['items'])})")

    return added


def show_pending():
    """Show all pending (unfixed) feedback items."""
    feedback = load_feedback()
    pending = [item for item in feedback["items"] if item["status"] in ("new", "in_progress")]

    if not pending:
        print("✅ No pending feedback items!")
        return

    print(f"\n📋 PENDING FEEDBACK ({len(pending)} items):\n")
    for i, item in enumerate(pending, 1):
        status_icon = "🆕" if item["status"] == "new" else "🔧"
        photo_icon = " 📷" if item.get("has_photo") else ""
        print(f"{status_icon} [{item['datetime']}] {item['from']}:{photo_icon}")
        if item["text"]:
            # Truncate long texts
            text = item["text"][:200] + "..." if len(item["text"]) > 200 else item["text"]
            print(f"   {text}")
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        show_pending()
    else:
        run()
