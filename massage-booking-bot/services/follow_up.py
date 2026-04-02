"""Follow-up service for Crystal Lab Booking Bot

Automatic follow-up messages for inactive clients ("потеряшки").
Also handles day-before booking confirmations and upselling.

Cultural context (from 22.11.2025 meeting):
- Arab clients respond well to frequent reminders
- They are often distracted and need nudges
- "Update us" phrase works well
- Suggesting available slots increases conversion
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Callable, Awaitable, Optional, Dict, Any
from loguru import logger

from dialog_context import dialog_manager
from services.lost_client_messages import get_lost_client_message_by_attempt
from prices import get_price


# Trial session follow-up for massage inquiries (5 min delay)
TRIAL_SESSION_MESSAGE = """Dear, we have trial session for new clients
(body 60 + face 20)
80 min = 350 AED 🌟

Share your location please dear and which day/time you prefer? 😊"""

TRIAL_SESSION_IMAGE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "trial_session.jpg")

# Keywords that indicate massage interest
MASSAGE_KEYWORDS = ["massage", "body", "face", "lymphatic", "deep tissue", "cupping", "relaxing"]

# Follow-up timing — default (initial stage)
FOLLOW_UP_DELAYS = [
    timedelta(minutes=5),    # 1st follow-up: 5 minutes (trial session for massage)
    timedelta(hours=1),      # 2nd: 1 hour
    timedelta(hours=4),      # 3rd: 4 hours
    timedelta(hours=24),     # 4th: next day
    timedelta(hours=48),     # 5th: 2 days
]

# Follow-up timing — when client is already selecting time/nearly booked (more aggressive)
FOLLOW_UP_DELAYS_BOOKING = [
    timedelta(minutes=10),   # 1st: 10 minutes — client was choosing time
    timedelta(hours=2),      # 2nd: 2 hours
    timedelta(hours=24),     # 3rd: next day
]

# States that indicate client is in active booking flow
BOOKING_FLOW_STATES = {"collecting_location", "selecting_slot", "location_received", "confirming"}

MAX_FOLLOW_UPS = 5

# Upselling recommendations based on booked service
# Prices loaded from prices.py (single source of truth)
def _build_upsell_recommendations():
    """Build upsell messages with dynamic prices from prices.py."""
    _p = get_price
    return {
        "Body massage": [
            f"Would you also like to add a face massage? Body + Face combo is just {_p('body_face_combo'):.0f} AED (saves 70 AED)! 🌹",
            "Many clients add head spa to their body massage session. Would you like that too?",
        ],
        "Face massage": [
            f"Would you like to combine with body massage? Body + Face combo is just {_p('body_face_combo'):.0f} AED 🌹",
            f"Our Deep Facial Cleansing ({_p('deep_facial_cleansing'):.0f} AED) is very popular - great results! Would you like to add it?",
        ],
        "Deep facial cleansing": [
            "Many clients add a face massage after cleansing for best results. Interested? 🌹",
        ],
        "Combo mani + pedi": [
            "Would you also like eyebrow lamination or eyelash lifting while you're at it? 🌹",
        ],
        "Eyelash extension": [
            f"Would you like to add eyebrow lamination as well? {_p('brow_lamination'):.0f} AED 🌹",
        ],
        "Eyebrow lamination": [
            f"Eyelash lifting pairs perfectly with brow lamination - combo just {_p('lash_brow_combo'):.0f} AED! 🌹",
        ],
    }

UPSELL_RECOMMENDATIONS = _build_upsell_recommendations()

# Day-before confirmation template
DAY_BEFORE_TEMPLATE = """Hi dear! Just a reminder about your appointment tomorrow:

🛎️ {service_name}
📅 {date}
⏰ {time}
📍 {location}

Please confirm - are we still on? 🌹

If you need to reschedule, just let me know!"""


class FollowUpService:
    """Manages automatic follow-ups for inactive clients."""

    def __init__(
        self,
        send_message: Callable[[str, str], Awaitable[None]],
        notification_service=None,
        send_photo: Callable[[str, str, str], Awaitable[None]] = None,
    ):
        """
        Args:
            send_message: async function(user_id, text) to send message to client
            notification_service: NotificationService for admin alerts
            send_photo: async function(user_id, photo_path, caption) to send photo to client
        """
        self.send_message = send_message
        self.notification_service = notification_service
        self.send_photo = send_photo
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Track follow-up attempts per user: {user_id: {"count": N, "last_sent": datetime}}
        self.follow_up_state: Dict[str, Dict[str, Any]] = {}

    async def start(self, check_interval: int = 300):
        """Start the follow-up background loop.

        Args:
            check_interval: How often to check for inactive clients (seconds). Default 5 min.
        """
        self._running = True
        self._task = asyncio.create_task(self._loop(check_interval))
        logger.info(f"Follow-up service started (check every {check_interval}s)")

    async def stop(self):
        """Stop the follow-up background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Follow-up service stopped")

    async def _loop(self, interval: int):
        """Main background loop."""
        while self._running:
            try:
                await self._check_inactive_clients()
            except Exception as e:
                logger.error(f"Follow-up loop error: {e}")
            await asyncio.sleep(interval)

    async def _check_inactive_clients(self):
        """Check all active dialogs for inactive clients."""
        lost_clients = dialog_manager.get_lost_clients()

        for user_id in lost_clients:
            context = dialog_manager.get_context(user_id)
            if not context:
                continue

            # Skip completed or cancelled bookings
            if context.state in ("completed", "cancelled"):
                continue

            user_key = str(user_id)
            state = self.follow_up_state.get(user_key, {"count": 0, "last_sent": None})

            # Check if we've exhausted follow-ups
            if state["count"] >= MAX_FOLLOW_UPS:
                continue

            # Pick delay schedule based on booking stage
            is_booking_flow = context.state in BOOKING_FLOW_STATES
            delays = FOLLOW_UP_DELAYS_BOOKING if is_booking_flow else FOLLOW_UP_DELAYS

            # Check timing: should we send next follow-up?
            if state["count"] < len(delays):
                required_delay = delays[state["count"]]
            else:
                required_delay = delays[-1]  # Use last delay for any extra

            time_since_activity = datetime.now() - context.last_activity
            if time_since_activity < required_delay:
                continue

            # Check we haven't sent recently (min 10 min between follow-ups)
            if state["last_sent"] and (datetime.now() - state["last_sent"]) < timedelta(minutes=10):
                continue

            # Send follow-up
            attempt = state["count"] + 1

            # Check if client was asking about massage — send trial session offer
            is_massage_inquiry = self._is_massage_inquiry(context)

            if attempt == 1 and is_massage_inquiry and self.send_photo and os.path.exists(TRIAL_SESSION_IMAGE):
                message = TRIAL_SESSION_MESSAGE
                logger.info(f"Sending trial session follow-up with photo to user {user_id}")
            else:
                message = get_lost_client_message_by_attempt(attempt)
                logger.info(f"Sending follow-up #{attempt} to user {user_id}")

            try:
                if attempt == 1 and is_massage_inquiry and self.send_photo and os.path.exists(TRIAL_SESSION_IMAGE):
                    await self.send_photo(str(user_id), TRIAL_SESSION_IMAGE, message)
                else:
                    await self.send_message(str(user_id), message)

                # Update state
                self.follow_up_state[user_key] = {
                    "count": attempt,
                    "last_sent": datetime.now(),
                }

                # Notify admin on 3rd attempt
                if attempt >= 3 and self.notification_service:
                    client_name = context.client_data.get("name", f"User {user_id}")
                    logger.warning(f"Client {client_name} not responding after {attempt} follow-ups")

            except Exception as e:
                logger.error(f"Failed to send follow-up to {user_id}: {e}")

    @staticmethod
    def _is_massage_inquiry(context) -> bool:
        """Check if the client's conversation is about massage."""
        # Check recent messages for massage keywords
        recent = context.recent_messages if hasattr(context, 'recent_messages') else []
        for msg in recent:
            if msg.get("role") == "user":
                text = msg.get("content", "").lower()
                if any(kw in text for kw in MASSAGE_KEYWORDS):
                    return True
        # Check booking data
        service = ""
        if hasattr(context, 'booking_data'):
            service = (context.booking_data.get("service_type") or "").lower()
        elif hasattr(context, 'client_data'):
            pass
        if "massage" in service or "body" in service or "face" in service:
            return True
        # Default: treat as massage (most common service)
        return True

    def reset_follow_up(self, user_id):
        """Reset follow-up counter when client responds."""
        user_key = str(user_id)
        if user_key in self.follow_up_state:
            del self.follow_up_state[user_key]

    def get_upsell_message(self, service_name: str) -> Optional[str]:
        """Get upselling recommendation for a service."""
        for key, messages in UPSELL_RECOMMENDATIONS.items():
            if key.lower() in service_name.lower():
                import random
                return random.choice(messages)
        return None

    @staticmethod
    def format_day_before_confirmation(
        service_name: str,
        booking_date: datetime,
        location_details: str = "",
    ) -> str:
        """Format day-before booking confirmation message."""
        date_str = booking_date.strftime("%A, %B %d")
        time_str = booking_date.strftime("%I:%M %p")
        location = location_details if location_details else "Your location"

        return DAY_BEFORE_TEMPLATE.format(
            service_name=service_name,
            date=date_str,
            time=time_str,
            location=location,
        )
