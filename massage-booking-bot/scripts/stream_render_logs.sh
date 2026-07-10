#!/bin/bash
# Stream Render logs to persistent local file — runs forever via launchd
# Rotates log file daily by appending to YYYY-MM-DD.log
#
# HARDENED 2026-07-10: the stream died silently for a MONTH (expired Render
# CLI token → nothing but "Unauthorized" in the files, 12-24 MB/day of noise,
# nobody noticed; the whole client-testing sprint ran blind). Now:
#   - an auth failure fires a Telegram DM alert (rate-limited to 1/6h)
#   - auth-failure retries back off to 5 min instead of hammering every 5 s
# NOTE: Wappi chat pulling (scripts/pull_wappi_chats.py, launchd
# com.crystal-lab.wappi-pull) is the PRIMARY, token-rot-proof log channel;
# this Render stream is secondary (infra-level logs).

LOG_DIR="/Users/admin/Alina/massage-booking-bot/logs"
BOT_DIR="/Users/admin/Alina/massage-booking-bot"
ALERT_STAMP="$LOG_DIR/.render_auth_alert_ts"
mkdir -p "$LOG_DIR"

alert_auth_dead() {
    # Rate-limited Telegram DM: the log channel MUST NOT die silently.
    local now last
    now=$(date +%s)
    last=$(cat "$ALERT_STAMP" 2>/dev/null || echo 0)
    if [ $((now - last)) -lt 21600 ]; then
        return  # already alerted within 6h
    fi
    echo "$now" > "$ALERT_STAMP"
    local token
    token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$BOT_DIR/.env" | cut -d= -f2-)
    [ -z "$token" ] && return
    curl -s -m 15 "https://api.telegram.org/bot${token}/sendMessage" \
        -d chat_id="${LOGPULL_ALERT_CHAT_ID:-1379584180}" \
        --data-urlencode text="⚠️ Crystal Lab: Render CLI токен протух — стрим логов Render НЕ работает. Выполни 'render login'. (Wappi-канал логов работает независимо.)" \
        >/dev/null 2>&1
}

while true; do
    DATE=$(date +%Y-%m-%d)
    LOG_FILE="$LOG_DIR/render-$DATE.log"

    echo "=== Stream started at $(date) ===" >> "$LOG_FILE"

    # Stream logs until connection drops, then reconnect. Capture the tail so
    # we can detect auth death instead of silently writing error noise forever.
    OUT=$(/Users/admin/.local/bin/render logs -o text -r srv-d7d1u0reo5us7381mqc0 --tail 2>&1 | tee -a "$LOG_FILE" | tail -c 2000)

    if echo "$OUT" | grep -qiE "unauthorized|token is expired|run .render login."; then
        echo "=== AUTH DEAD at $(date) — alerting, retry in 5 min ===" >> "$LOG_FILE"
        alert_auth_dead
        sleep 300   # back off: no point hammering with a dead token
    else
        echo "=== Stream disconnected at $(date), reconnecting in 5s ===" >> "$LOG_FILE"
        sleep 5
    fi
done
