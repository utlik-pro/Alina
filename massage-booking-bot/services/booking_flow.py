"""End-to-end booking flow orchestrator for Crystal Lab

Connects the AI agent's booking intent with YClients API to:
1. Find or create client in YClients
2. Look up service/staff availability
3. Create booking in YClients
4. Create booking in local database
5. Send confirmation to client and admin group

Supports mock mode (MOCK_YCLIENTS=True) for development without API keys.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from loguru import logger

from config import config
from database.services import ClientService, BookingService
from services.yclients_api import YClientsClient
from prices import SERVICE_CATALOG as _PRICE_CATALOG


# ── Service catalog (built from prices.py — single source of truth) ───────────
# Maps service display names to {default_duration, default_price} for booking flow

def _build_service_catalog() -> Dict[str, Dict[str, Any]]:
    """Build service catalog from centralized prices.py."""
    # Map prices.py keys to service display names used in bot.py
    _KEY_TO_NAME = {
        "body_massage_60": "Body massage",
        "body_massage_90": "Body massage 90min",
        "body_face_combo": "Body + Face massage",
        "face_massage": "Face massage",
        "deep_facial_cleansing": "Deep facial cleansing",
        "carboxy_therapy": "Carboxy-therapy",
        "russian_combo": "Combo mani + pedi",
        "russian_mani": "Russian gelish manicure",
        "russian_pedi": "Russian gelish pedicure",
        "japanese_mani": "Japanese manicure",
        "japanese_pedi": "Japanese pedicure",
        "lash_ext_classic": "Eyelash extension classical volume",
        "lash_ext_2d": "Eyelash extension 2D volume",
        "lash_ext_russian": "Eyelash extension Russian volume",
        "lash_lifting": "Eyelash lifting",
        "brow_lamination": "Eyebrow lamination",
        "lash_brow_combo": "Eyebrow lamination + Eyelash lifting",
        "pmu_lips": "Permanent makeup lips",
        "pmu_eyebrows": "Permanent makeup eyebrows",
        "pmu_eyeliner": "Permanent makeup eyeliner",
        "wax_full_face": "Face waxing",
        "cupping": "Cupping",
        "neck_shoulders": "Neck/shoulders/back massage",
        "foot_reflexology": "Foot reflexology",
        "hair_makeup": "Hair and makeup",
        "hairstyle": "Hairstyle",
        "makeup": "Makeup",
    }
    catalog = {}
    for key, display_name in _KEY_TO_NAME.items():
        svc = _PRICE_CATALOG[key]
        catalog[display_name] = {
            "default_duration": svc["duration"],
            "default_price": svc["price"],
        }
    return catalog

SERVICE_CATALOG: Dict[str, Dict[str, Any]] = _build_service_catalog()


class BookingFlow:
    """Orchestrates the full booking process."""

    def __init__(
        self,
        client_service: ClientService,
        booking_service: BookingService,
        yclients_client: Optional[YClientsClient] = None,
    ):
        self.client_service = client_service
        self.booking_service = booking_service
        self.yclients = yclients_client
        self.mock_mode = config.MOCK_YCLIENTS

    async def check_availability(
        self,
        service_name: str,
        preferred_date: Optional[str] = None,
        staff_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Check available slots for a service.

        Args:
            service_name: Name of the service
            preferred_date: Date in YYYY-MM-DD format (defaults to tomorrow)
            staff_id: Preferred staff member ID

        Returns:
            {"available": True/False, "slots": [...], "staff": [...]}
        """
        if not preferred_date:
            preferred_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        if self.mock_mode:
            return self._mock_availability(service_name, preferred_date)

        if not self.yclients:
            logger.warning("YClients client not initialized")
            return {"available": True, "slots": [], "staff": [], "mock": True}

        try:
            availability = await self.yclients.check_availability(
                booking_date=preferred_date,
            )

            slots = []
            for staff_avail in availability:
                for time_slot in staff_avail.get("available_times", []):
                    slots.append({
                        "staff_id": staff_avail["staff_id"],
                        "staff_name": staff_avail["staff_name"],
                        "time": time_slot.get("time", ""),
                        "duration_sec": time_slot.get("seance_length", 3600),
                    })

            return {
                "available": len(slots) > 0,
                "date": preferred_date,
                "slots": slots,
                "staff": [s["staff_name"] for s in availability],
            }

        except Exception as e:
            logger.error(f"Failed to check YClients availability: {e}")
            return {"available": True, "slots": [], "error": str(e)}

    async def create_booking(
        self,
        telegram_id: str,
        service_name: str,
        booking_datetime: datetime,
        duration: Optional[int] = None,
        base_price: Optional[float] = None,
        payment_method: str = "cash",
        client_name: str = "",
        client_phone: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create a complete booking in both local DB and YClients.

        Returns:
            {"success": True, "booking_id": ..., "yclients_id": ..., ...}
        """
        # Resolve defaults from service catalog
        catalog = SERVICE_CATALOG.get(service_name, {})
        if duration is None:
            duration = catalog.get("default_duration", 60)
        if base_price is None:
            base_price = catalog.get("default_price", 350.0)

        result = {
            "success": False,
            "booking_id": None,
            "yclients_id": None,
            "service_name": service_name,
            "datetime": booking_datetime.isoformat(),
            "total_price": None,
        }

        # Step 1: Create booking in local database
        try:
            booking = await self.booking_service.create_booking(
                telegram_id=telegram_id,
                service_name=service_name,
                duration=duration,
                base_price=base_price,
                booking_date=booking_datetime,
                payment_method=payment_method,
            )
            await self.booking_service.update_booking_status(booking.id, "confirmed")
            result["booking_id"] = booking.id
            result["total_price"] = booking.total_price
            logger.info(f"Local booking {booking.id} created for {telegram_id}")
        except Exception as e:
            logger.error(f"Failed to create local booking: {e}")
            result["error"] = f"Database error: {e}"
            return result

        # Step 2: Create booking in YClients (if not mock)
        if not self.mock_mode and self.yclients:
            try:
                yclients_result = await self._create_yclients_booking(
                    service_name=service_name,
                    booking_datetime=booking_datetime,
                    client_name=client_name,
                    client_phone=client_phone,
                    notes=notes,
                )
                if yclients_result:
                    result["yclients_id"] = yclients_result.get("id")
                    # Update local booking with YClients ID
                    async with self.booking_service.db.session() as session:
                        from sqlalchemy import select
                        from database.models import Booking
                        stmt = select(Booking).where(Booking.id == booking.id)
                        res = await session.execute(stmt)
                        b = res.scalar_one()
                        b.yclients_appointment_id = str(result["yclients_id"])
                        await session.flush()

                    logger.info(f"YClients booking created: {result['yclients_id']}")
            except Exception as e:
                logger.error(f"YClients booking failed (local booking still valid): {e}")
                result["yclients_error"] = str(e)
        else:
            result["yclients_id"] = f"mock_{booking.id}"
            logger.info(f"Mock YClients booking for local booking {booking.id}")

        result["success"] = True
        return result

    async def cancel_booking(
        self,
        booking_id: int,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Cancel a booking in both local DB and YClients."""
        result = {"success": False, "booking_id": booking_id}

        try:
            booking = await self.booking_service.update_booking_status(
                booking_id, "cancelled", notes=reason
            )
            result["success"] = True

            # Cancel in YClients if we have the appointment ID
            if not self.mock_mode and self.yclients and booking.yclients_appointment_id:
                try:
                    await self.yclients.delete_booking(
                        int(booking.yclients_appointment_id)
                    )
                    logger.info(f"YClients booking {booking.yclients_appointment_id} cancelled")
                except Exception as e:
                    logger.error(f"Failed to cancel YClients booking: {e}")
                    result["yclients_error"] = str(e)

        except Exception as e:
            logger.error(f"Failed to cancel booking {booking_id}: {e}")
            result["error"] = str(e)

        return result

    async def _create_yclients_booking(
        self,
        service_name: str,
        booking_datetime: datetime,
        client_name: str = "",
        client_phone: str = "",
        notes: str = "",
    ) -> Optional[Dict]:
        """Create booking in YClients. Returns API response data."""
        if not self.yclients:
            return None

        # Ensure authenticated
        if not self.yclients.user_token:
            await self.yclients.authenticate()

        # Find client in YClients
        if client_phone:
            yclients_client = await self.yclients.find_or_create_client(
                phone=client_phone,
                name=client_name,
            )
        else:
            yclients_client = None

        # Get services from YClients and match by name
        services = await self.yclients.get_services()
        matched_service_ids = []
        for svc in services:
            if service_name.lower() in svc.get("title", "").lower():
                matched_service_ids.append(svc["id"])
                break

        if not matched_service_ids:
            logger.warning(f"No YClients service match for '{service_name}', using first service")
            if services:
                matched_service_ids = [services[0]["id"]]

        # Get available staff
        staff = await self.yclients.get_staff()
        staff_id = staff[0]["id"] if staff else 0

        # Create booking
        datetime_str = booking_datetime.strftime("%Y-%m-%dT%H:%M:%S")
        result = await self.yclients.create_booking(
            staff_id=staff_id,
            service_ids=matched_service_ids,
            booking_datetime=datetime_str,
            client_phone=client_phone or "unknown",
            client_name=client_name or "Client",
            comment=notes,
        )

        return result

    @staticmethod
    def _mock_availability(service_name: str, date: str) -> Dict[str, Any]:
        """Generate mock availability data."""
        return {
            "available": True,
            "date": date,
            "mock": True,
            "slots": [
                {"staff_name": "Anastasia", "time": "10:00", "duration_sec": 3600},
                {"staff_name": "Anastasia", "time": "12:00", "duration_sec": 3600},
                {"staff_name": "Anastasia", "time": "14:00", "duration_sec": 3600},
                {"staff_name": "Maria", "time": "11:00", "duration_sec": 3600},
                {"staff_name": "Maria", "time": "15:00", "duration_sec": 3600},
            ],
            "staff": ["Anastasia", "Maria"],
        }

    @staticmethod
    def format_availability_message(availability: Dict[str, Any]) -> str:
        """Format availability data into a readable message for the client."""
        if not availability.get("available"):
            return "Sorry dear, no slots available for that date. Would you like to try another day?"

        date = availability.get("date", "")
        slots = availability.get("slots", [])

        if not slots:
            return f"We have availability on {date}! What time works for you?"

        # Group by staff
        staff_slots: Dict[str, List[str]] = {}
        for slot in slots:
            name = slot.get("staff_name", "Therapist")
            time = slot.get("time", "")
            staff_slots.setdefault(name, []).append(time)

        lines = [f"Available slots for {date}:"]
        for name, times in staff_slots.items():
            times_str = ", ".join(times)
            lines.append(f"  {name}: {times_str}")

        return "\n".join(lines)
