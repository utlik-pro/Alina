"""Database services for Crystal Lab booking system"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, func, desc, delete
from sqlalchemy.orm import selectinload
from loguru import logger

from .models import Client, Message, Booking, DialogSession, Package
from .db import Database


class ClientService:
    """Service for client operations"""

    def __init__(self, db: Database):
        self.db = db

    async def get_or_create_client(self, telegram_id: str) -> Client:
        """Get existing client or create new one"""
        async with self.db.session() as session:
            # Try to find existing client
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one_or_none()

            if client:
                logger.info(f"Found existing client: {client.id} (telegram_id={telegram_id})")
                return client

            # Create new client
            client = Client(telegram_id=telegram_id)
            session.add(client)
            await session.flush()
            logger.info(f"Created new client: {client.id} (telegram_id={telegram_id})")
            return client

    async def update_client(
        self,
        telegram_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        location_latitude: Optional[float] = None,
        location_longitude: Optional[float] = None,
        location_details: Optional[str] = None,
        medical_notes: Optional[str] = None,
    ) -> Client:
        """Update client information"""
        async with self.db.session() as session:
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one()

            if name:
                client.name = name
            if phone:
                client.phone = phone
            if location_latitude is not None:
                client.location_latitude = location_latitude
            if location_longitude is not None:
                client.location_longitude = location_longitude
            if location_details:
                client.location_details = location_details
            if medical_notes:
                # Append to existing medical notes
                if client.medical_notes:
                    client.medical_notes += f"\n[{datetime.utcnow().strftime('%Y-%m-%d')}] {medical_notes}"
                else:
                    client.medical_notes = f"[{datetime.utcnow().strftime('%Y-%m-%d')}] {medical_notes}"

            client.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated client {client.id}")
            return client

    async def reset_client(self, telegram_id: str) -> None:
        """Reset client data (name, location) for fresh start. Keeps medical notes."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one_or_none()
            if not client:
                return
            client.name = None
            client.location_latitude = None
            client.location_longitude = None
            client.location_details = None
            client.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Reset client data for {telegram_id}")

    async def get_client_stats(self, telegram_id: str) -> Dict[str, Any]:
        """Get client statistics"""
        async with self.db.session() as session:
            result = await session.execute(
                select(Client)
                .where(Client.telegram_id == telegram_id)
                .options(selectinload(Client.bookings))
            )
            client = result.scalar_one()

            completed_bookings = sum(1 for b in client.bookings if b.status == "completed")
            total_spent = sum(
                b.total_price for b in client.bookings
                if b.status == "completed" and b.total_price
            )

            return {
                "client_id": client.id,
                "name": client.name,
                "total_bookings": client.total_bookings,
                "completed_bookings": completed_bookings,
                "total_spent": total_spent,
                "is_vip": client.is_vip,
                "created_at": client.created_at,
            }


class MessageService:
    """Service for message operations"""

    def __init__(self, db: Database):
        self.db = db

    async def save_message(
        self,
        telegram_id: str,
        role: str,
        content: str,
        telegram_message_id: Optional[int] = None,
    ) -> Message:
        """Save a message to database"""
        async with self.db.session() as session:
            # Get client
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one()

            # Create message
            message = Message(
                client_id=client.id,
                role=role,
                content=content,
                telegram_message_id=telegram_message_id,
            )
            session.add(message)
            await session.flush()
            logger.debug(f"Saved {role} message for client {client.id}")
            return message

    async def get_recent_messages(
        self,
        telegram_id: str,
        limit: int = 20,
    ) -> List[Message]:
        """Get recent messages for a client"""
        async with self.db.session() as session:
            # Get client
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one()

            # Get recent messages
            result = await session.execute(
                select(Message)
                .where(Message.client_id == client.id)
                .order_by(desc(Message.created_at))
                .limit(limit)
            )
            messages = result.scalars().all()
            return list(reversed(messages))  # Return in chronological order

    async def get_conversation_history(
        self,
        telegram_id: str,
    ) -> List[Dict[str, str]]:
        """Get conversation history formatted for AI"""
        messages = await self.get_recent_messages(telegram_id)
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    async def clear_history(self, telegram_id: str) -> int:
        """Delete all messages for a client. Returns count of deleted messages."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one_or_none()
            if not client:
                return 0

            result = await session.execute(
                delete(Message).where(Message.client_id == client.id)
            )
            logger.info(f"Cleared {result.rowcount} messages for client {telegram_id}")
            return result.rowcount


class DialogSessionService:
    """Service for dialog session operations"""

    def __init__(self, db: Database):
        self.db = db

    async def get_or_create_session(self, telegram_id: str) -> DialogSession:
        """Get active session or create new one"""
        async with self.db.session() as session:
            # Try to find active session
            result = await session.execute(
                select(DialogSession)
                .where(
                    DialogSession.telegram_id == telegram_id,
                    DialogSession.is_active == True,
                )
                .order_by(desc(DialogSession.started_at))
            )
            dialog_session = result.scalar_one_or_none()

            if dialog_session:
                return dialog_session

            # Create new session
            dialog_session = DialogSession(telegram_id=telegram_id)
            session.add(dialog_session)
            await session.flush()
            logger.info(f"Created new dialog session for {telegram_id}")
            return dialog_session

    async def update_session_state(
        self,
        telegram_id: str,
        state: str,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> DialogSession:
        """Update session state"""
        async with self.db.session() as session:
            result = await session.execute(
                select(DialogSession)
                .where(
                    DialogSession.telegram_id == telegram_id,
                    DialogSession.is_active == True,
                )
                .order_by(desc(DialogSession.started_at))
                .limit(1)
            )
            dialog_session = result.scalar_one_or_none()
            if not dialog_session:
                return None

            dialog_session.state = state
            dialog_session.last_activity_at = datetime.utcnow()

            if context_data:
                dialog_session.context_data = context_data

            await session.flush()
            return dialog_session

    async def end_session(self, telegram_id: str):
        """End active session"""
        async with self.db.session() as session:
            await session.execute(
                update(DialogSession)
                .where(
                    DialogSession.telegram_id == telegram_id,
                    DialogSession.is_active == True,
                )
                .values(is_active=False, ended_at=datetime.utcnow())
            )
            logger.info(f"Ended dialog session for {telegram_id}")

    async def mark_as_lost_client(self, telegram_id: str):
        """Mark session as lost client"""
        async with self.db.session() as session:
            await session.execute(
                update(DialogSession)
                .where(
                    DialogSession.telegram_id == telegram_id,
                    DialogSession.is_active == True,
                )
                .values(is_lost_client=True)
            )
            logger.warning(f"Marked {telegram_id} as lost client")

    async def get_lost_clients(self, inactive_minutes: int = 60) -> List[DialogSession]:
        """Find lost clients (inactive > X minutes, not confirmed)"""
        threshold = datetime.utcnow() - timedelta(minutes=inactive_minutes)

        async with self.db.session() as session:
            result = await session.execute(
                select(DialogSession)
                .where(
                    DialogSession.is_active == True,
                    DialogSession.is_lost_client == False,
                    DialogSession.state.in_(["consulting", "collecting_location", "selecting_slot"]),
                    DialogSession.last_activity_at < threshold,
                )
            )
            return list(result.scalars().all())


class BookingService:
    """Service for booking operations"""

    def __init__(self, db: Database):
        self.db = db

    async def create_booking(
        self,
        telegram_id: str,
        service_name: str,
        duration: Optional[int] = None,
        base_price: Optional[float] = None,
        booking_date: Optional[datetime] = None,
        payment_method: Optional[str] = "cash",
    ) -> Booking:
        """Create a new booking"""
        async with self.db.session() as session:
            # Get client
            result = await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )
            client = result.scalar_one()

            # Create booking
            booking = Booking(
                client_id=client.id,
                service_name=service_name,
                duration=duration,
                base_price=base_price,
                booking_date=booking_date,
                payment_method=payment_method,
            )

            if base_price:
                booking.calculate_total()

            session.add(booking)
            await session.flush()
            logger.info(f"Created booking {booking.id} for client {client.id}: {service_name} on {booking_date}, payment: {payment_method}, total: {booking.total_price} AED")
            return booking

    async def update_booking_status(
        self,
        booking_id: int,
        status: str,
        notes: Optional[str] = None,
    ) -> Booking:
        """Update booking status"""
        async with self.db.session() as session:
            result = await session.execute(
                select(Booking).where(Booking.id == booking_id)
            )
            booking = result.scalar_one()

            booking.status = status
            booking.updated_at = datetime.utcnow()

            if notes:
                booking.notes = notes

            if status == "completed":
                booking.completed_at = datetime.utcnow()
                # Update client total bookings
                client = await session.get(Client, booking.client_id)
                client.total_bookings += 1

            elif status == "cancelled":
                booking.cancelled_at = datetime.utcnow()

            await session.flush()
            logger.info(f"Updated booking {booking.id} status to {status}")
            return booking
