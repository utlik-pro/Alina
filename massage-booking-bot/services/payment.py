"""Payment handling for Crystal Lab (scaffold).

Crystal Lab currently takes payment two ways:
- Cash on site (tax-free) — no online step needed.
- Bank transfer (+5% VAT) — client is sent bank details; admin reconciles.

This module centralizes:
- the bank-details message shown to transfer clients,
- a status helper to mark a booking paid,
- a stubbed online-payment-link creator for when a provider
  (Stripe / Telr / Network International) is chosen.

To enable online payments you (the user) need to decide on a provider
and supply its API keys; `create_payment_link` is where that plugs in.
"""

from __future__ import annotations

from typing import Optional
from loguru import logger

from config import config


def bank_details_message(amount_aed: Optional[float] = None) -> str:
    """Client-facing bank-transfer instructions."""
    details = config.PAYMENT_BANK_DETAILS
    head = "For bank transfer, please use these details dear 🌹\n\n"
    amount_line = f"\n\nAmount: {amount_aed:.2f} AED (incl. 5% VAT)" if amount_aed else ""
    if details:
        return head + details + amount_line
    # Not configured yet — admin will send details manually.
    return (
        "For bank transfer our admin will share the bank details with you "
        "shortly dear 🌹" + amount_line
    )


async def create_payment_link(booking_id: int, amount_aed: float) -> Optional[str]:
    """Create an online payment link (STUB).

    Returns None until a provider is configured. When PAYMENT_LINK_BASE is
    set we return a naive link so the rest of the flow can be wired/tested;
    swap this body for the real provider SDK call when chosen.
    """
    base = config.PAYMENT_LINK_BASE
    if not base:
        logger.info(f"[payment stub] no provider configured for booking {booking_id}")
        return None
    return f"{base.rstrip('/')}/pay?booking={booking_id}&amount={amount_aed:.2f}"


class PaymentService:
    """Thin DB helper for payment status."""

    def __init__(self, booking_service):
        self.booking_service = booking_service

    async def mark_paid(self, booking_id: int) -> None:
        from sqlalchemy import update
        from database.models import Booking
        async with self.booking_service.db.session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking_id)
                .values(payment_status="paid")
            )
        logger.info(f"Booking {booking_id} marked paid")
