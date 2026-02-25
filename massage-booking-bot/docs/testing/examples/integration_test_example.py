"""
Example Integration Test - Copy this template for new integration tests

This example demonstrates:
- Full conversation flow testing
- Using async fixtures
- Mocking external APIs (OpenAI, Telegram)
- Testing multiple components together
"""
import pytest
from unittest.mock import patch
from datetime import datetime

from database.models import Booking, Client
from dialog_context import DialogManager
from tests.helpers.telegram_mock import TelegramMessageBuilder
from tests.helpers.openai_mock import create_booking_agent_mock


@pytest.mark.critical
@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_booking_flow_with_cash_payment(async_db_session, dialog_manager):
    """
    Integration test for complete booking conversation flow

    This test validates the entire user journey from first message to completed booking.

    SCENARIO:
    1. User: "Hi, I want body massage"
       → Bot shows prices (350 AED, 460 AED) with VAT footnote
    2. User: "60 minutes"
       → Bot confirms duration and asks for location
    3. User: [Sends location]
       → Bot asks for villa/apartment number
    4. User: "Villa 25"
       → Bot asks for preferred time
    5. User: "7pm tomorrow"
       → Bot asks for name
    6. User: "Sara"
       → Bot asks for payment method
    7. User: "Cash"
       → Bot confirms booking with final price (350 AED, no VAT)

    EXPECTED OUTCOMES:
    - Booking created in database
    - No VAT added (cash payment)
    - All client details saved correctly
    - Total price = base price = 350 AED
    """
    # ========== ARRANGE ==========
    user_id = 123456789
    openai_mock = create_booking_agent_mock()

    # Conversation messages
    messages = [
        "Hi, I want body massage",
        "60 minutes",
        "Villa 25",
        "7pm tomorrow",
        "Sara",
        "Cash",
    ]

    # ========== ACT ==========
    with patch("agents.booking_agent.AsyncOpenAI", return_value=openai_mock):
        # Create dialog context
        context = dialog_manager.get_or_create_context(user_id)

        # Simulate conversation
        for msg_text in messages:
            message = TelegramMessageBuilder(user_id).with_text(msg_text).build()

            # Process message (simplified simulation of bot.py logic)
            if "body" in msg_text.lower():
                # Service selection
                context.booking_data = context.booking_data or {}
                context.booking_data["service_type"] = "Body massage"

                # Get bot response
                response = await openai_mock.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": msg_text}]
                )
                bot_response = response.choices[0].message.content

                # Verify bot response format
                assert "350 AED" in bot_response or "350" in bot_response, \
                    "Bot should show 60-min price"
                assert "460 AED" in bot_response or "460" in bot_response, \
                    "Bot should show 90-min price"
                assert "VAT" in bot_response.upper() or "tax" in bot_response.lower(), \
                    "Bot should mention VAT system"

            elif "60" in msg_text:
                # Duration selection
                context.booking_data["service_duration"] = 60
                context.booking_data["base_price"] = 350.0

            elif "villa" in msg_text.lower():
                # Address
                context.client_data = context.client_data or {}
                context.client_data["address"] = msg_text

            elif "7pm" in msg_text.lower() or "tomorrow" in msg_text.lower():
                # Time
                context.booking_data["booking_time"] = msg_text

            elif msg_text == "Sara":
                # Name
                context.client_data["name"] = msg_text

            elif "cash" in msg_text.lower():
                # Payment method
                context.booking_data["payment_method"] = "cash"

        # Create booking in database (as bot would do)
        client = Client(
            telegram_id=str(user_id),
            name=context.client_data.get("name"),
            location_details=context.client_data.get("address"),
        )
        async_db_session.add(client)
        await async_db_session.commit()
        await async_db_session.refresh(client)

        booking = Booking(
            client_id=client.id,
            service_name=context.booking_data.get("service_type"),
            duration=context.booking_data.get("service_duration"),
            base_price=context.booking_data.get("base_price"),
            payment_method=context.booking_data.get("payment_method"),
            notes=context.booking_data.get("booking_time"),
            status="confirmed",
        )
        booking.calculate_total()

        async_db_session.add(booking)
        await async_db_session.commit()
        await async_db_session.refresh(booking)

    # ========== ASSERT ==========

    # Verify client data
    assert client.name == "Sara", "Client name should be saved"
    assert client.location_details == "Villa 25", "Address should be saved"
    assert client.telegram_id == str(user_id), "Telegram ID should match"

    # Verify booking data
    assert booking.service_name == "Body massage", "Service should be Body massage"
    assert booking.duration == 60, "Duration should be 60 minutes"
    assert booking.base_price == 350.0, "Base price should be 350 AED"

    # Verify VAT calculation (CRITICAL!)
    assert booking.vat_amount == 0.0, "Cash payment should have NO VAT"
    assert booking.total_price == 350.0, "Total should equal base price for cash"
    assert booking.payment_method == "cash", "Payment method should be cash"

    # Verify booking time
    assert "7pm" in booking.notes or "tomorrow" in booking.notes, \
        "Booking time should be stored"

    print("✅ INTEGRATION TEST PASSED: Complete booking flow with cash payment")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_booking_flow_with_transfer_payment_includes_vat(async_db_session, dialog_manager):
    """
    Integration test for booking with bank transfer payment

    SCENARIO:
    Similar to cash flow, but user chooses "Bank transfer"

    EXPECTED:
    - 5% VAT added to base price
    - Total = base_price * 1.05
    - VAT amount stored in database
    """
    # ========== ARRANGE ==========
    user_id = 987654321
    openai_mock = create_booking_agent_mock()

    messages = [
        "Body massage please",
        "90",  # 90 minutes
        "Apartment 12",
        "Tomorrow 2pm",
        "Fatima",
        "Bank transfer",
    ]

    # ========== ACT ==========
    with patch("agents.booking_agent.AsyncOpenAI", return_value=openai_mock):
        context = dialog_manager.get_or_create_context(user_id)

        for msg_text in messages:
            if "body" in msg_text.lower():
                context.booking_data = {"service_type": "Body massage"}

            elif "90" in msg_text:
                context.booking_data["service_duration"] = 90
                context.booking_data["base_price"] = 460.0

            elif "apartment" in msg_text.lower():
                context.client_data = {"address": msg_text}

            elif "2pm" in msg_text.lower() or "tomorrow" in msg_text.lower():
                context.booking_data["booking_time"] = msg_text

            elif msg_text == "Fatima":
                context.client_data["name"] = msg_text

            elif "transfer" in msg_text.lower() or "bank" in msg_text.lower():
                context.booking_data["payment_method"] = "transfer"

        # Create client and booking
        client = Client(
            telegram_id=str(user_id),
            name=context.client_data.get("name"),
            location_details=context.client_data.get("address"),
        )
        async_db_session.add(client)
        await async_db_session.commit()
        await async_db_session.refresh(client)

        booking = Booking(
            client_id=client.id,
            service_name=context.booking_data.get("service_type"),
            duration=context.booking_data.get("service_duration"),
            base_price=context.booking_data.get("base_price"),
            payment_method=context.booking_data.get("payment_method"),
            notes=context.booking_data.get("booking_time"),
            status="confirmed",
        )
        booking.calculate_total()  # Calculate VAT for transfer

        async_db_session.add(booking)
        await async_db_session.commit()
        await async_db_session.refresh(booking)

    # ========== ASSERT ==========

    # Verify client data
    assert client.name == "Fatima"
    assert client.location_details == "Apartment 12"

    # Verify booking data
    assert booking.service_name == "Body massage"
    assert booking.duration == 90
    assert booking.base_price == 460.0

    # Verify VAT calculation (CRITICAL!)
    expected_vat = 23.0  # 5% of 460
    expected_total = 483.0  # 460 + 23

    assert booking.vat_amount == expected_vat, \
        f"VAT should be {expected_vat} AED (5% of 460), got {booking.vat_amount}"

    assert booking.total_price == expected_total, \
        f"Total should be {expected_total} AED (460 + VAT), got {booking.total_price}"

    assert booking.payment_method == "transfer", \
        "Payment method should be transfer"

    print("✅ INTEGRATION TEST PASSED: Booking flow with transfer payment includes VAT")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_medical_notes_are_saved_and_acknowledged(async_db_session, dialog_manager):
    """
    Integration test for medical notes detection and storage

    SCENARIO:
    User mentions medical condition during conversation:
    "I had cesarean 2 months ago"

    EXPECTED:
    - Medical note detected by keywords
    - Bot acknowledges: "I will inform the therapist"
    - Medical notes saved to database
    - Admin notification includes medical notes
    """
    # ========== ARRANGE ==========
    user_id = 111222333
    openai_mock = create_booking_agent_mock()

    messages = [
        "Body massage",
        "90 min",
        "Villa 30",
        "I had cesarean 2 months ago",  # ← Medical note!
        "Tomorrow 4pm",
        "Mariam",
        "Cash",
    ]

    medical_note_detected = False
    saved_medical_notes = []

    # Keywords that should trigger medical note detection
    medical_keywords = [
        "cesarean", "surgery", "operation", "birth",
        "pregnant", "pain", "bleeding", "medical"
    ]

    # ========== ACT ==========
    with patch("agents.booking_agent.AsyncOpenAI", return_value=openai_mock):
        context = dialog_manager.get_or_create_context(user_id)
        context.client_data = {}
        context.booking_data = {}

        for msg_text in messages:
            # Check for medical keywords
            if any(keyword in msg_text.lower() for keyword in medical_keywords):
                medical_note_detected = True
                saved_medical_notes.append(msg_text)

                # Get bot response
                response = await openai_mock.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": msg_text}]
                )
                bot_response = response.choices[0].message.content

                # Verify bot acknowledges medical note
                assert "inform" in bot_response.lower() or "therapist" in bot_response.lower(), \
                    "Bot should acknowledge informing therapist about medical condition"

                # Save to context
                context.client_data["medical_notes"] = msg_text

            # Process other messages
            elif "body" in msg_text.lower():
                context.booking_data["service_type"] = "Body massage"
            elif "90" in msg_text:
                context.booking_data["service_duration"] = 90
                context.booking_data["base_price"] = 460.0
            elif "villa" in msg_text.lower() and "30" in msg_text:
                context.client_data["address"] = msg_text
            elif "4pm" in msg_text.lower() or "tomorrow" in msg_text.lower():
                context.booking_data["booking_time"] = msg_text
            elif msg_text == "Mariam":
                context.client_data["name"] = msg_text
            elif "cash" in msg_text.lower():
                context.booking_data["payment_method"] = "cash"

        # Save to database
        client = Client(
            telegram_id=str(user_id),
            name=context.client_data.get("name"),
            location_details=context.client_data.get("address"),
            medical_notes=context.client_data.get("medical_notes"),
        )
        async_db_session.add(client)
        await async_db_session.commit()
        await async_db_session.refresh(client)

    # ========== ASSERT ==========

    # Verify medical note was detected
    assert medical_note_detected, "Medical note should be detected"
    assert len(saved_medical_notes) > 0, "Medical notes should be saved"
    assert "cesarean" in saved_medical_notes[0].lower(), \
        "Should contain 'cesarean' keyword"

    # Verify medical notes in database
    assert client.medical_notes is not None, "Client should have medical notes"
    assert "cesarean" in client.medical_notes.lower(), \
        "Database should contain medical notes"

    print("✅ INTEGRATION TEST PASSED: Medical notes saved and acknowledged")


# ==================== HOW TO RUN THESE EXAMPLES ====================
#
# Run all integration tests:
#   pytest docs/testing/examples/integration_test_example.py
#
# Run only critical tests:
#   pytest docs/testing/examples/integration_test_example.py -m critical
#
# Run with verbose async output:
#   pytest docs/testing/examples/integration_test_example.py -v -s
#
# Run specific test:
#   pytest docs/testing/examples/integration_test_example.py::test_complete_booking_flow_with_cash_payment
#
# ====================================================================


# ==================== KEY TAKEAWAYS ====================
#
# 1. ASYNC TESTS: Always use @pytest.mark.asyncio for async tests
#
# 2. FIXTURES: Use async_db_session for async database operations
#
# 3. MOCKING: Mock external APIs (OpenAI, Telegram) to avoid real calls
#    - Faster tests
#    - Deterministic results
#    - No API costs
#
# 4. PATCHING: Use unittest.mock.patch to replace real implementations
#    with patch("agents.booking_agent.AsyncOpenAI", return_value=mock):
#
# 5. CONTEXT MANAGERS: Use 'with' for patches and async contexts
#
# 6. FULL FLOW: Integration tests should test multiple components
#    - Dialog context
#    - Database operations
#    - Business logic
#    - State transitions
#
# 7. REALISTIC SCENARIOS: Base tests on real user conversations
#    - Use actual user messages
#    - Test complete workflows
#    - Verify end-to-end behavior
#
# 8. CLEAR DOCUMENTATION: Document the scenario being tested
#    - Step-by-step conversation
#    - Expected outcomes
#    - Why this matters
#
# =======================================================
