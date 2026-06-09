"""Reminder scheduler for Crystal Lab (FR-3.1, FR-4.x).

A single asyncio background loop (same pattern as FollowUpService) that:

1. Day-before confirmations — for every confirmed booking happening
   tomorrow, send the client a WhatsApp confirmation between 11:00 and
   12:00 UAE time, exactly once.

2. Post-session follow-up — after a session's time has passed, send a
   "how was it?" survey plus the right next-step offer:
     - package client, last session  → renewal offer
     - package client, sessions left  → "book your next session"
     - brand-new client (1 booking)   → package offer
     - returning client               → "book your next session"
   Also decrements a package session and marks the booking completed.

All timestamps in the DB are naive UAE local time (UTC+4), so the
scheduler works in UAE local time throughout.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional
from loguru import logger

from services.follow_up import FollowUpService
from prices import get_price

UAE_OFFSET = timedelta(hours=4)


def now_uae() -> datetime:
    """Current naive UAE local time (UTC+4, no DST)."""
    return datetime.utcnow() + UAE_OFFSET


# ── Post-session message templates (English — bot replies in English) ──
SURVEY_TEMPLATE = (
    "Hi {name}! Hope you enjoyed your session today 😊 "
    "How did you like your {service} dear? 🌹"
)
NEXT_SESSION_OFFER = "Would you like to book your next session dear? 🌹"


def _package_offer() -> str:
    body10 = get_price("body_massage_60") * 10
    try:
        # If a discounted 10-session package exists in prices, prefer it.
        from prices import SERVICE_CATALOG
        pkg = SERVICE_CATALOG.get("body_pkg_10")
        if pkg:
            return (
                "By the way dear, we have special packages 🌹\n"
                f"10 sessions for {pkg['price']:.0f} AED — great value! "
                "Would you be interested? 😊"
            )
    except Exception:
        pass
    return (
        "By the way dear, we have special packages that save you money 🌹 "
        "Would you be interested in hearing about them? 😊"
    )


def _renewal_offer() -> str:
    return (
        "Hi dear! That was the last session from your package 🌹 "
        "Would you like to renew it? We can offer the same or a different "
        "package option 😊"
    )


def _sessions_left_offer(remaining: int) -> str:
    return (
        f"You have {remaining} session(s) left in your package dear 🌹 "
        "Would you like to book your next one? 😊"
    )


class ReminderScheduler:
    """Background scheduler for day-before confirmations and post-session
    follow-ups.
    """

    def __init__(
        self,
        booking_service,
        send_message: Callable[[str, str], Awaitable[None]],
        package_service=None,
        notification_service=None,
        check_interval: int = 900,  # 15 min
        confirm_window=(11, 12),    # UAE hours [start, end)
    ):
        """
        Args:
            booking_service: database BookingService
            send_message: async fn(phone, text) — sends WhatsApp to client
            package_service: optional database PackageService
            notification_service: optional admin notifier
            check_interval: loop period in seconds
            confirm_window: (start_hour, end_hour) UAE window for day-before
        """
        self.booking_service = booking_service
        self.send_message = send_message
        self.package_service = package_service
        self.notification_service = notification_service
        self.check_interval = check_interval
        self.confirm_window = confirm_window
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"Reminder scheduler started (every {self.check_interval}s, "
            f"confirm window {self.confirm_window[0]:02d}:00–{self.confirm_window[1]:02d}:00 UAE)"
        )

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Reminder scheduler stopped")

    async def _loop(self):
        while self._running:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"Reminder scheduler error: {e}", exc_info=True)
            await asyncio.sleep(self.check_interval)

    async def run_once(self, current: Optional[datetime] = None):
        """One scheduler tick. Exposed (not private) so tests can call it
        with an injected `current` UAE time.
        """
        current = current or now_uae()
        await self._send_day_before(current)
        await self._send_post_session(current)

    # ── FR-3.1 day-before confirmations ───────────────────────────────
    async def _send_day_before(self, current: datetime):
        start_h, end_h = self.confirm_window
        in_window = start_h <= current.hour < end_h
        # Catch-up: bookings made for tomorrow AFTER the window closed, or a
        # Render restart/deploy that spanned the window, would otherwise never
        # get a confirmation. Re-send (only the still-unconfirmed ones — it's
        # idempotent via confirmation_sent_at) through the afternoon/evening,
        # but never at night.
        catchup = end_h <= current.hour < 21
        if not (in_window or catchup):
            return

        target_date = (current + timedelta(days=1)).date()
        due = await self.booking_service.get_due_for_confirmation(target_date)
        if not due:
            return
        logger.info(f"Day-before: {len(due)} confirmation(s) due for {target_date}")

        for b in due:
            phone = b.get("phone")
            if not phone:
                continue
            location = b.get("location_details") or ""
            msg = FollowUpService.format_day_before_confirmation(
                service_name=b["service_name"],
                booking_date=b["booking_date"],
                location_details=location,
            )
            try:
                await self.send_message(phone, msg)
                await self.booking_service.mark_confirmation_sent(b["booking_id"])
                logger.info(
                    f"Day-before confirmation sent → {phone} (booking {b['booking_id']})"
                )
            except Exception as e:
                logger.error(f"Day-before send failed for {phone}: {e}")

    # ── FR-4.x post-session follow-up ─────────────────────────────────
    async def _send_post_session(self, current: datetime):
        due = await self.booking_service.get_due_for_survey(current)
        if not due:
            return
        logger.info(f"Post-session: {len(due)} survey(s) due")

        for b in due:
            phone = b.get("phone")
            if not phone:
                # still mark so we don't loop forever on a phoneless row
                await self.booking_service.mark_survey_sent(b["booking_id"])
                continue

            # Claim the booking BEFORE any side effect: stamping survey_sent_at
            # first means a transient WhatsApp failure or an overlapping tick
            # can't double-send the survey or double-consume a package session.
            await self.booking_service.mark_survey_sent(b["booking_id"])

            name = (b.get("client_name") or "dear").split(" ")[0]
            try:
                # 1) the survey itself
                await self.send_message(
                    phone,
                    SURVEY_TEMPLATE.format(name=name, service=b["service_name"]),
                )

                # 2) the next-step offer (consumes a package session if linked)
                offer = await self._build_offer(b)
                if offer:
                    await asyncio.sleep(0.4)
                    await self.send_message(phone, offer)

                # 3) complete the booking
                await self.booking_service.update_booking_status(
                    b["booking_id"], "completed"
                )
                logger.info(
                    f"Post-session survey sent → {phone} (booking {b['booking_id']})"
                )
            except Exception as e:
                logger.error(f"Post-session send failed for {phone}: {e}")

    async def _build_offer(self, b: dict) -> Optional[str]:
        """Pick the right next-step offer for a finished session."""
        # Package session → decrement and offer accordingly
        if b.get("package_id") and self.package_service:
            consumed = await self.package_service.consume_session(b["package_id"])
            if consumed:
                if consumed.get("is_last"):
                    return _renewal_offer()
                return _sessions_left_offer(consumed["sessions_remaining"])

        # New client (this was their first booking) → package offer
        total = b.get("total_bookings") or 0
        if total <= 1:
            return _package_offer()

        # Returning client → simple next-session nudge
        return NEXT_SESSION_OFFER
