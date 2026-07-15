"""Database services for Crystal Lab booking system"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import select, update, func, desc, delete
from sqlalchemy.orm import selectinload
from loguru import logger

from .models import Client, Message, Booking, DialogSession, Package, MasterAccount, WaitingList
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
        area: Optional[str] = None,
        preferred_therapist: Optional[str] = None,
        avoid_therapist: Optional[str] = None,
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
            if area:
                client.area = area
            if preferred_therapist:
                client.preferred_therapist = preferred_therapist
            if avoid_therapist:
                client.avoid_therapist = avoid_therapist
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
            client.area = None
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

    # ── Scheduler / reminder support ──────────────────────────────────

    async def get_due_for_confirmation(self, target_date) -> List[Dict[str, Any]]:
        """Confirmed bookings on `target_date` (a date) that have not yet
        received a day-before confirmation. Returns plain dicts with the
        client contact info the scheduler needs (no detached-ORM access).
        """
        day_start = datetime(target_date.year, target_date.month, target_date.day)
        day_end = day_start + timedelta(days=1)
        async with self.db.session() as session:
            result = await session.execute(
                select(Booking, Client)
                .join(Client, Booking.client_id == Client.id)
                .where(
                    Booking.status == "confirmed",
                    Booking.booking_date >= day_start,
                    Booking.booking_date < day_end,
                    Booking.confirmation_sent_at.is_(None),
                )
            )
            return [self._booking_row_to_dict(b, c) for b, c in result.all()]

    # Default session length (minutes) used to estimate a session's END
    # time when a booking has no explicit duration.
    DEFAULT_SESSION_MINUTES = 90

    async def get_due_for_survey(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Confirmed bookings whose session has ENDED (within the last 24h)
        and that have not yet received a post-session survey.

        We filter on the session's end time (start + duration), not its start,
        so the "hope you enjoyed your session" message never lands mid-massage.
        """
        now = now or datetime.utcnow()
        window_start = now - timedelta(hours=24)
        async with self.db.session() as session:
            result = await session.execute(
                select(Booking, Client)
                .join(Client, Booking.client_id == Client.id)
                .where(
                    Booking.status == "confirmed",
                    Booking.booking_date < now,          # started
                    Booking.booking_date >= window_start,
                    Booking.survey_sent_at.is_(None),
                )
            )
            rows = [self._booking_row_to_dict(b, c) for b, c in result.all()]

        due = []
        for r in rows:
            start = r.get("booking_date")
            if not start:
                continue
            mins = r.get("duration") or self.DEFAULT_SESSION_MINUTES
            if start + timedelta(minutes=mins) <= now:   # session has ended
                due.append(r)
        return due

    async def mark_confirmation_sent(self, booking_id: int) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking_id)
                .values(confirmation_sent_at=datetime.utcnow())
            )

    async def mark_survey_sent(self, booking_id: int) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking_id)
                .values(survey_sent_at=datetime.utcnow())
            )

    async def apply_penalty(self, booking_id: int, amount: float, reason: str) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking_id)
                .values(penalty_amount=amount, penalty_reason=reason[:500])
            )
            logger.info(f"Penalty {amount} AED applied to booking {booking_id}: {reason}")

    async def get_latest_active_booking(self, telegram_id: str) -> Optional[Dict[str, Any]]:
        """The client's SOONEST upcoming confirmed booking.

        Cancel/reschedule should act on the next appointment, not the
        furthest-future one, and never on an already-finished session. We
        allow a 2h grace after start (so a client can cancel a booking that
        just began) but exclude long-past rows.
        """
        uae_now = datetime.utcnow() + timedelta(hours=4)
        lower_bound = uae_now - timedelta(hours=2)
        async with self.db.session() as session:
            client = (await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )).scalar_one_or_none()
            if not client:
                return None
            result = await session.execute(
                select(Booking)
                .where(
                    Booking.client_id == client.id,
                    Booking.status == "confirmed",
                    Booking.booking_date >= lower_bound,
                )
                .order_by(Booking.booking_date.asc())  # soonest first
                .limit(1)
            )
            b = result.scalar_one_or_none()
            return self._booking_row_to_dict(b, client) if b else None

    async def get_active_bookings(self, telegram_id: str):
        """ALL upcoming confirmed bookings, soonest first. Used to match a
        cancel/reschedule to the booking the client actually means (by the
        old date/time they mention) instead of guessing the soonest one."""
        uae_now = datetime.utcnow() + timedelta(hours=4)
        lower_bound = uae_now - timedelta(hours=2)
        async with self.db.session() as session:
            client = (await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )).scalar_one_or_none()
            if not client:
                return []
            rows = (await session.execute(
                select(Booking)
                .where(
                    Booking.client_id == client.id,
                    Booking.status == "confirmed",
                    Booking.booking_date >= lower_bound,
                )
                .order_by(Booking.booking_date.asc())
            )).scalars().all()
            return [self._booking_row_to_dict(b, client) for b in rows]

    async def count_active_bookings(self, telegram_id: str) -> int:
        """How many upcoming confirmed bookings the client has. When >1, a bare
        'cancel'/'reschedule' is ambiguous (get_latest_active_booking would pick
        the soonest, possibly the wrong one) and the caller should disambiguate.
        """
        uae_now = datetime.utcnow() + timedelta(hours=4)
        lower_bound = uae_now - timedelta(hours=2)
        async with self.db.session() as session:
            client = (await session.execute(
                select(Client).where(Client.telegram_id == telegram_id)
            )).scalar_one_or_none()
            if not client:
                return 0
            rows = (await session.execute(
                select(Booking.id).where(
                    Booking.client_id == client.id,
                    Booking.status == "confirmed",
                    Booking.booking_date >= lower_bound,
                )
            )).all()
            return len(rows)

    async def set_yclients_id(self, booking_id: int, yclients_id) -> None:
        """Persist the YClients record id after a confirmed sync — cancel and
        reschedule mutate YClients directly and need this to target the record."""
        async with self.db.session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking_id)
                .values(yclients_appointment_id=str(yclients_id),
                        updated_at=datetime.utcnow())
            )

    async def set_rescheduled(self, old_id: int, new_id: int) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == old_id)
                .values(status="rescheduled", rescheduled_to=new_id,
                        updated_at=datetime.utcnow())
            )

    @staticmethod
    def _booking_row_to_dict(b: Booking, c: Client) -> Dict[str, Any]:
        # telegram_id is "wappi_<phone>" for the WhatsApp path
        phone = c.phone
        if not phone and c.telegram_id and c.telegram_id.startswith("wappi_"):
            phone = c.telegram_id.replace("wappi_", "", 1)
        return {
            "booking_id": b.id,
            "telegram_id": c.telegram_id,
            "phone": phone,
            "client_name": c.name,
            "client_id": c.id,
            "total_bookings": c.total_bookings,
            "service_name": b.service_name,
            "duration": b.duration,
            "booking_date": b.booking_date,
            "therapist_name": b.therapist_name,
            "area": b.area,
            "base_price": b.base_price,
            "total_price": b.total_price,
            "payment_method": b.payment_method,
            "location_details": c.location_details,
            "location_latitude": c.location_latitude,
            "location_longitude": c.location_longitude,
            "package_id": b.package_id,
            "yclients_appointment_id": b.yclients_appointment_id,
        }


class MasterAccountService:
    """Service for MasterAccount (YClients staff ↔ Telegram chat mapping).

    Used by the masters-bot to store registrations and by the webhook
    to look up a chat_id for pushing booking notifications.
    """

    def __init__(self, db: Database):
        self.db = db

    async def get_by_staff_id(self, yclients_staff_id: int) -> Optional[MasterAccount]:
        """Return the registered master for a YClients staff_id, or None."""
        async with self.db.session() as session:
            result = await session.execute(
                select(MasterAccount).where(
                    MasterAccount.yclients_staff_id == yclients_staff_id,
                    MasterAccount.is_active == True,  # noqa: E712
                )
            )
            return result.scalar_one_or_none()

    async def get_by_chat_id(self, telegram_chat_id: str) -> Optional[MasterAccount]:
        """Return master by their Telegram chat_id (for self-service commands)."""
        async with self.db.session() as session:
            result = await session.execute(
                select(MasterAccount).where(
                    MasterAccount.telegram_chat_id == str(telegram_chat_id)
                )
            )
            return result.scalar_one_or_none()

    async def register(
        self,
        yclients_staff_id: int,
        staff_name: str,
        telegram_chat_id: str,
        telegram_username: Optional[str] = None,
    ) -> MasterAccount:
        """Create or reactivate a master account.

        If this chat_id already belongs to a different staff_id, we
        overwrite the binding (a master rejoining after YClients ID change).
        If this staff_id is already bound to a different chat_id, we
        migrate it to the new chat (master got a new Telegram account).
        """
        chat_id_str = str(telegram_chat_id)
        async with self.db.session() as session:
            # Existing binding by chat
            result = await session.execute(
                select(MasterAccount).where(
                    MasterAccount.telegram_chat_id == chat_id_str
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.yclients_staff_id = yclients_staff_id
                existing.staff_name = staff_name
                existing.telegram_username = telegram_username
                existing.is_active = True
                existing.registered_at = datetime.utcnow()
                await session.flush()
                logger.info(
                    f"MasterAccount reactivated: chat={chat_id_str} "
                    f"→ staff_id={yclients_staff_id} ({staff_name})"
                )
                return existing

            # Existing binding by staff_id — migrate
            result = await session.execute(
                select(MasterAccount).where(
                    MasterAccount.yclients_staff_id == yclients_staff_id
                )
            )
            by_staff = result.scalar_one_or_none()
            if by_staff:
                by_staff.telegram_chat_id = chat_id_str
                by_staff.telegram_username = telegram_username
                by_staff.staff_name = staff_name
                by_staff.is_active = True
                by_staff.registered_at = datetime.utcnow()
                await session.flush()
                logger.info(
                    f"MasterAccount migrated: staff_id={yclients_staff_id} "
                    f"→ new chat={chat_id_str}"
                )
                return by_staff

            account = MasterAccount(
                yclients_staff_id=yclients_staff_id,
                staff_name=staff_name,
                telegram_chat_id=chat_id_str,
                telegram_username=telegram_username,
                is_active=True,
            )
            session.add(account)
            await session.flush()
            logger.info(
                f"MasterAccount created: staff_id={yclients_staff_id} "
                f"({staff_name}) ↔ chat={chat_id_str}"
            )
            return account

    async def deactivate(self, telegram_chat_id: str) -> bool:
        """Mark a master inactive (they ran /unregister). Returns True if found."""
        async with self.db.session() as session:
            result = await session.execute(
                select(MasterAccount).where(
                    MasterAccount.telegram_chat_id == str(telegram_chat_id)
                )
            )
            account = result.scalar_one_or_none()
            if not account:
                return False
            account.is_active = False
            await session.flush()
            logger.info(f"MasterAccount deactivated: chat={telegram_chat_id}")
            return True

    async def mark_notified(self, yclients_staff_id: int) -> None:
        """Stamp last_notified_at after a successful push."""
        async with self.db.session() as session:
            await session.execute(
                update(MasterAccount)
                .where(MasterAccount.yclients_staff_id == yclients_staff_id)
                .values(last_notified_at=datetime.utcnow())
            )

    async def list_all(self, active_only: bool = True) -> List[MasterAccount]:
        """List all registered masters (for admin overview)."""
        async with self.db.session() as session:
            stmt = select(MasterAccount)
            if active_only:
                stmt = stmt.where(MasterAccount.is_active == True)  # noqa: E712
            stmt = stmt.order_by(MasterAccount.staff_name)
            result = await session.execute(stmt)
            return list(result.scalars().all())


class PackageService:
    """Service for client packages (абонементы 5x / 10x).

    Tracks sessions remaining, decrements on a completed session, and
    surfaces "last session → offer renewal" signals (FR-4.3/4.4).
    """

    def __init__(self, db: Database):
        self.db = db

    async def create_package(
        self,
        client_id: int,
        package_type: str,
        sessions_total: int,
        base_price: float,
        vat_amount: float = 0.0,
        total_price: Optional[float] = None,
        valid_days: int = 90,
    ) -> Dict[str, Any]:
        async with self.db.session() as session:
            pkg = Package(
                client_id=client_id,
                package_type=package_type,
                sessions_total=sessions_total,
                sessions_used=0,
                sessions_remaining=sessions_total,
                base_price=base_price,
                vat_amount=vat_amount,
                total_price=total_price if total_price is not None else base_price + vat_amount,
                expires_at=datetime.utcnow() + timedelta(days=valid_days),
                is_active=True,
            )
            session.add(pkg)
            await session.flush()
            logger.info(f"Package {pkg.id} created for client {client_id}: {package_type}")
            return self._to_dict(pkg)

    async def get_active_package(self, client_id: int) -> Optional[Dict[str, Any]]:
        """Active package with sessions left and not expired."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Package)
                .where(
                    Package.client_id == client_id,
                    Package.is_active == True,  # noqa: E712
                    Package.sessions_remaining > 0,
                    Package.expires_at > datetime.utcnow(),
                )
                .order_by(Package.expires_at)
                .limit(1)
            )
            pkg = result.scalar_one_or_none()
            return self._to_dict(pkg) if pkg else None

    async def consume_session(self, package_id: int) -> Optional[Dict[str, Any]]:
        """Decrement one session. Returns the updated package dict with an
        `is_last` flag set when no sessions remain after this one.
        """
        async with self.db.session() as session:
            pkg = await session.get(Package, package_id)
            if not pkg or pkg.sessions_remaining <= 0:
                return None
            pkg.sessions_used += 1
            pkg.sessions_remaining -= 1
            if pkg.sessions_remaining <= 0:
                pkg.is_active = False
            await session.flush()
            d = self._to_dict(pkg)
            d["is_last"] = pkg.sessions_remaining <= 0
            logger.info(
                f"Package {pkg.id}: consumed session, {pkg.sessions_remaining} left"
            )
            return d

    @staticmethod
    def _to_dict(pkg: Package) -> Dict[str, Any]:
        return {
            "id": pkg.id,
            "client_id": pkg.client_id,
            "package_type": pkg.package_type,
            "sessions_total": pkg.sessions_total,
            "sessions_used": pkg.sessions_used,
            "sessions_remaining": pkg.sessions_remaining,
            "total_price": pkg.total_price,
            "expires_at": pkg.expires_at,
            "is_active": pkg.is_active,
        }


class WaitingListService:
    """Service for the waiting list (FR-7.4)."""

    def __init__(self, db: Database):
        self.db = db

    async def add(
        self,
        client_id: int,
        service_name: Optional[str] = None,
        area: Optional[str] = None,
        preferred_date: Optional[str] = None,
        preferred_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self.db.session() as session:
            entry = WaitingList(
                client_id=client_id,
                service_name=service_name,
                area=area,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                status="active",
            )
            session.add(entry)
            await session.flush()
            logger.info(f"WaitingList entry {entry.id} added for client {client_id}")
            return {"id": entry.id, "client_id": client_id, "status": "active"}

    async def get_matches(
        self,
        area: Optional[str] = None,
        preferred_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Active waiting-list entries matching an area/date (a slot freed up)."""
        async with self.db.session() as session:
            stmt = (
                select(WaitingList, Client)
                .join(Client, WaitingList.client_id == Client.id)
                .where(WaitingList.status == "active")
            )
            if area:
                stmt = stmt.where(WaitingList.area == area)
            if preferred_date:
                stmt = stmt.where(WaitingList.preferred_date == preferred_date)
            stmt = stmt.order_by(WaitingList.created_at)
            result = await session.execute(stmt)
            rows = []
            for entry, client in result.all():
                phone = client.phone
                if not phone and client.telegram_id and client.telegram_id.startswith("wappi_"):
                    phone = client.telegram_id.replace("wappi_", "", 1)
                rows.append({
                    "id": entry.id,
                    "client_id": client.id,
                    "telegram_id": client.telegram_id,
                    "phone": phone,
                    "client_name": client.name,
                    "service_name": entry.service_name,
                    "area": entry.area,
                    "preferred_date": entry.preferred_date,
                    "preferred_time": entry.preferred_time,
                })
            return rows

    async def mark_notified(self, entry_id: int) -> None:
        async with self.db.session() as session:
            await session.execute(
                update(WaitingList)
                .where(WaitingList.id == entry_id)
                .values(status="notified", notified_at=datetime.utcnow())
            )
