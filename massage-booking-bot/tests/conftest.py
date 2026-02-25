"""
Pytest configuration and fixtures for massage booking bot tests
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Base, Client, Booking, Message, DialogSession
from dialog_context import DialogManager, DialogContext
from prices import get_price


# ==================== Database Fixtures ====================

@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
async def async_db_session():
    """Create async in-memory database session"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()


# ==================== Dialog Context Fixtures ====================

@pytest.fixture
def dialog_context():
    """Create fresh DialogContext for testing"""
    user_id = 123456789
    context = DialogContext(user_id=user_id)
    return context


@pytest.fixture
def dialog_manager():
    """Create DialogManager instance with clean state"""
    manager = DialogManager()
    manager.contexts.clear()  # Clear any existing contexts
    return manager


# ==================== Telegram Mock Fixtures ====================

@pytest.fixture
def mock_telegram_message():
    """Create mock Telegram message object"""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.from_user.username = "test_user"
    message.from_user.first_name = "Test"
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.message_id = 1
    message.date = datetime.now()
    message.text = "Test message"

    # Mock answer method
    message.answer = AsyncMock(return_value=MagicMock(message_id=2))
    message.reply = AsyncMock(return_value=MagicMock(message_id=2))

    return message


@pytest.fixture
def mock_telegram_location():
    """Create mock Telegram location object"""
    location = MagicMock()
    location.latitude = 25.2048
    location.longitude = 55.2708
    return location


@pytest.fixture
def mock_bot():
    """Create mock Telegram Bot instance"""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=100))
    bot.send_location = AsyncMock(return_value=MagicMock(message_id=101))
    return bot


# ==================== OpenAI Mock Fixtures ====================

@pytest.fixture
def mock_openai_response():
    """Create mock OpenAI API response"""
    def create_response(content: str):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = content
        response.usage = MagicMock()
        response.usage.total_tokens = 150
        return response
    return create_response


@pytest.fixture
def mock_openai_client(mock_openai_response):
    """Create mock OpenAI client with typical responses"""
    client = AsyncMock()

    async def mock_create(*args, **kwargs):
        messages = kwargs.get("messages", [])
        last_message = messages[-1]["content"] if messages else ""

        # Simulate GPT responses based on user input
        if "body" in last_message.lower():
            return mock_openai_response(
                f"Hello dear! Body massage is a great choice. "
                f"We offer 60 minutes ({get_price('body_massage_60'):,.0f} AED) or 90 minutes ({get_price('body_massage_90'):,.0f} AED). "
                f"We work with VAT system. Additional 5% if you pay by transfer. "
                f"Cash payment - tax free. Which duration would you prefer?"
            )
        elif "60" in last_message or "90" in last_message:
            return mock_openai_response(
                "Perfect! Please share your location so I can find you."
            )
        elif "cash" in last_message.lower():
            return mock_openai_response(
                f"Great! Your total is {get_price('body_massage_60'):,.0f} AED. Looking forward to seeing you!"
            )
        elif "transfer" in last_message.lower() or "bank" in last_message.lower():
            return mock_openai_response(
                f"Perfect! Your total is {get_price('body_massage_60') * 1.05:,.2f} AED ({get_price('body_massage_60'):,.0f} AED + 5% VAT). "
                f"I'll send you payment details."
            )
        elif "cesarean" in last_message.lower() or "surgery" in last_message.lower():
            return mock_openai_response(
                "Okay dear, thank you for letting me know. "
                "I will inform the therapist about your medical history."
            )
        else:
            return mock_openai_response(
                "Thank you! Could you please provide more details?"
            )

    client.chat.completions.create = mock_create
    return client


# ==================== Service Fixtures ====================

@pytest.fixture
def mock_notification_service():
    """Mock notification service"""
    service = AsyncMock()
    service.send_booking_notification = AsyncMock(return_value=True)
    service.send_admin_alert = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_yclients_service():
    """Mock YClients service"""
    service = AsyncMock()
    service.create_booking = AsyncMock(return_value={"id": "test_booking_123"})
    service.get_available_slots = AsyncMock(return_value=["14:00", "15:00", "16:00"])
    return service


# ==================== Test Data Fixtures ====================

@pytest.fixture
def sample_client_data():
    """Sample client data for testing"""
    return {
        "telegram_id": 123456789,
        "username": "test_user",
        "name": "Sara",
        "location_lat": 25.2048,
        "location_long": 55.2708,
        "address": "Villa 25",
        "medical_notes": None,
    }


@pytest.fixture
def sample_booking_data_cash():
    """Sample booking data with cash payment (no VAT)"""
    return {
        "service_type": "Body massage",
        "service_duration": 60,
        "base_price": get_price('body_massage_60'),
        "vat_amount": 0.0,
        "total_price": get_price('body_massage_60'),
        "payment_method": "cash",
        "booking_time": "7pm tomorrow",
    }


@pytest.fixture
def sample_booking_data_transfer():
    """Sample booking data with transfer payment (with VAT)"""
    _base = get_price('body_massage_90')
    _vat = round(_base * 0.05, 2)
    return {
        "service_type": "Body massage",
        "service_duration": 90,
        "base_price": _base,
        "vat_amount": _vat,
        "total_price": _base + _vat,
        "payment_method": "transfer",
        "booking_time": "2pm tomorrow",
    }


@pytest.fixture
def sample_booking_data_combo():
    """Sample booking data for combo service (Body + Face)"""
    return {
        "service_type": "Body + Face massage",
        "service_duration": 85,
        "base_price": get_price('body_face_combo'),
        "vat_amount": 0.0,  # Cash payment
        "total_price": get_price('body_face_combo'),
        "payment_method": "cash",
        "booking_time": "10am tomorrow",
    }


# ==================== Environment Fixtures ====================

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables for testing"""
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "test_token_123",
        "OPENAI_API_KEY": "test_openai_key",
        "OPENAI_MODEL": "gpt-4o-mini",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "ADMIN_GROUP_CHAT_ID": "test_admin_group",
        "DEBUG": "True",
        "MOCK_YCLIENTS": "True",
        "MOCK_WHATSAPP": "True",
    }):
        yield


# ==================== Time Control Fixtures ====================

@pytest.fixture
def freeze_time():
    """Fixture to control time for buffering tests"""
    class TimeController:
        def __init__(self):
            self.current_time = datetime.now()

        def advance(self, seconds: float):
            """Advance time by specified seconds"""
            from datetime import timedelta
            self.current_time += timedelta(seconds=seconds)
            return self.current_time

    return TimeController()


# ==================== Async Event Loop Fixture ====================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
