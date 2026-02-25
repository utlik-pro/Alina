"""Database models for Crystal Lab booking system"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Boolean, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Client(Base):
    """Модель клиента"""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    location_latitude = Column(Float, nullable=True)
    location_longitude = Column(Float, nullable=True)
    location_details = Column(String(500), nullable=True)  # Villa/Apartment number
    medical_notes = Column(Text, nullable=True)
    preferred_therapist = Column(String(255), nullable=True)
    total_bookings = Column(Integer, default=0)
    is_vip = Column(Boolean, default=False)
    tags = Column(JSON, nullable=True)  # ["regular", "package_buyer", etc.]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    bookings = relationship("Booking", back_populates="client", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="client", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Client(id={self.id}, telegram_id={self.telegram_id}, name={self.name})>"


class Message(Base):
    """Модель сообщения в диалоге"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    telegram_message_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    client = relationship("Client", back_populates="messages")

    def __repr__(self):
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"<Message(id={self.id}, role={self.role}, content='{preview}')>"


class Booking(Base):
    """Модель бронирования"""
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    # Service details
    service_name = Column(String(255), nullable=False)
    duration = Column(Integer, nullable=True)  # minutes

    # Scheduling
    booking_date = Column(DateTime, nullable=True)
    therapist_name = Column(String(255), nullable=True)

    # Pricing
    base_price = Column(Float, nullable=True)
    vat_rate = Column(Float, default=0.05)
    vat_amount = Column(Float, nullable=True)
    total_price = Column(Float, nullable=True)
    payment_method = Column(String(50), nullable=True)  # "cash" or "transfer"

    # Status
    status = Column(String(50), default="draft", index=True)
    # draft, confirmed, in_progress, completed, cancelled

    # Notes
    notes = Column(Text, nullable=True)
    cancellation_reason = Column(String(500), nullable=True)

    # External integration
    yclients_appointment_id = Column(String(255), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    # Relationships
    client = relationship("Client", back_populates="bookings")

    def __repr__(self):
        return f"<Booking(id={self.id}, service={self.service_name}, status={self.status})>"

    def calculate_total(self):
        """
        Calculate total price with VAT based on payment method.

        - Cash payment: NO VAT (total = base_price)
        - Bank transfer: +5% VAT (total = base_price * 1.05)
        """
        if self.base_price is not None:
            if self.payment_method == "cash":
                # Cash payment - NO VAT
                self.vat_amount = 0.0
                self.total_price = round(self.base_price, 2)
            else:
                # Bank transfer or default - WITH VAT
                vat_rate = self.vat_rate if self.vat_rate is not None else 0.05
                self.vat_amount = round(self.base_price * vat_rate, 2)
                self.total_price = round(self.base_price + self.vat_amount, 2)


class DialogSession(Base):
    """Модель сессии диалога (для tracking контекста)"""
    __tablename__ = "dialog_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String(50), nullable=False, index=True)
    state = Column(String(50), default="initial")
    # initial, consulting, collecting_location, selecting_slot, confirming, completed

    context_data = Column(JSON, nullable=True)  # Полный контекст диалога
    is_active = Column(Boolean, default=True, index=True)
    is_lost_client = Column(Boolean, default=False)  # Flag для "потеряшек"

    started_at = Column(DateTime, default=datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    ended_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<DialogSession(id={self.id}, telegram_id={self.telegram_id}, state={self.state})>"


class Package(Base):
    """Модель пакета услуг"""
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    package_type = Column(String(100), nullable=False)  # "4_sessions", "8_sessions", etc.
    sessions_total = Column(Integer, nullable=False)
    sessions_used = Column(Integer, default=0)
    sessions_remaining = Column(Integer, nullable=False)

    base_price = Column(Float, nullable=False)
    vat_amount = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    purchased_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # Usually 90 days from purchase
    is_active = Column(Boolean, default=True, index=True)

    # Relationships
    client = relationship("Client")

    def __repr__(self):
        return f"<Package(id={self.id}, type={self.package_type}, remaining={self.sessions_remaining})>"
