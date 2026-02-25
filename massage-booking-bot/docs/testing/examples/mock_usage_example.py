"""
Example Mock Usage - How to use test mocks effectively

This example demonstrates:
- TelegramMessageBuilder usage
- TelegramBotMock usage
- OpenAIMock usage
- Best practices for mocking
"""
import pytest
from datetime import datetime
from tests.helpers.telegram_mock import (
    TelegramMessageBuilder,
    TelegramBotMock,
    create_conversation_flow
)
from tests.helpers.openai_mock import OpenAIMock, create_booking_agent_mock


# ==================== TELEGRAM MESSAGE BUILDER ====================

def test_telegram_message_builder_basic():
    """
    Example: Creating simple mock Telegram message

    TelegramMessageBuilder uses the Builder pattern for fluent API
    """
    # Create message with just text
    message = TelegramMessageBuilder(user_id=123) \
        .with_text("Hello, bot!") \
        .build()

    # Verify message properties
    assert message.from_user.id == 123
    assert message.text == "Hello, bot!"
    assert message.chat.id == 123

    # Message has async methods for responding
    # (these are AsyncMock objects, so they work in async context)
    assert hasattr(message, 'answer')
    assert hasattr(message, 'reply')

    print("✅ Basic TelegramMessageBuilder works")


def test_telegram_message_builder_with_location():
    """
    Example: Creating message with GPS location
    """
    message = TelegramMessageBuilder(user_id=456) \
        .with_text("I'm here") \
        .with_location(latitude=25.2048, longitude=55.2708) \
        .build()

    # Verify location data
    assert message.location is not None
    assert message.location.latitude == 25.2048
    assert message.location.longitude == 55.2708

    print("✅ Location message builder works")


def test_telegram_message_builder_custom_timestamp():
    """
    Example: Creating message with specific timestamp
    """
    custom_time = datetime(2025, 1, 1, 12, 0, 0)

    message = TelegramMessageBuilder(user_id=789) \
        .with_text("New Year message") \
        .with_timestamp(custom_time) \
        .build()

    assert message.date == custom_time

    print("✅ Custom timestamp works")


def test_create_conversation_flow():
    """
    Example: Creating multiple messages quickly

    Useful for testing conversation sequences
    """
    messages = create_conversation_flow(
        user_id=123,
        messages=["Body massage", "60 minutes", "Cash"]
    )

    assert len(messages) == 3
    assert messages[0].text == "Body massage"
    assert messages[1].text == "60 minutes"
    assert messages[2].text == "Cash"

    # All messages from same user
    assert all(msg.from_user.id == 123 for msg in messages)

    print("✅ Conversation flow creation works")


# ==================== TELEGRAM BOT MOCK ====================

@pytest.mark.asyncio
async def test_telegram_bot_mock_tracking_messages():
    """
    Example: Using TelegramBotMock to track sent messages

    TelegramBotMock records all messages sent during test
    """
    bot_mock = TelegramBotMock()

    # Send some messages
    await bot_mock.send_message(chat_id=123, text="Hello!")
    await bot_mock.send_message(chat_id=123, text="How can I help?")
    await bot_mock.send_message(chat_id=456, text="Different chat")

    # Verify tracking
    assert bot_mock.get_message_count() == 3

    # Get last message
    assert bot_mock.get_last_message_text() == "Different chat"

    # Get messages to specific chat
    chat_123_messages = bot_mock.get_messages_to_chat(123)
    assert len(chat_123_messages) == 2
    assert chat_123_messages[0]["text"] == "Hello!"

    print("✅ TelegramBotMock tracking works")


@pytest.mark.asyncio
async def test_telegram_bot_mock_send_location():
    """
    Example: Tracking location messages
    """
    bot_mock = TelegramBotMock()

    # Send location
    await bot_mock.send_location(
        chat_id=123,
        latitude=25.2048,
        longitude=55.2708
    )

    # Verify
    assert len(bot_mock.locations_sent) == 1
    location_msg = bot_mock.locations_sent[0]

    assert location_msg["chat_id"] == 123
    assert location_msg["latitude"] == 25.2048
    assert location_msg["longitude"] == 55.2708

    print("✅ Location sending works")


@pytest.mark.asyncio
async def test_telegram_bot_mock_clear_history():
    """
    Example: Clearing message history between tests
    """
    bot_mock = TelegramBotMock()

    # Send messages
    await bot_mock.send_message(chat_id=123, text="Message 1")
    await bot_mock.send_message(chat_id=123, text="Message 2")

    assert bot_mock.get_message_count() == 2

    # Clear history
    bot_mock.clear_history()

    # Verify cleared
    assert bot_mock.get_message_count() == 0
    assert len(bot_mock.messages_sent) == 0

    print("✅ Clear history works")


# ==================== OPENAI MOCK ====================

@pytest.mark.asyncio
async def test_openai_mock_basic_response():
    """
    Example: Using OpenAIMock with custom responses
    """
    openai_mock = OpenAIMock()

    # Add custom response
    openai_mock.add_response("hello", "Hi there! How can I help you today?")

    # Make API call
    response = await openai_mock.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello bot"}]
    )

    # Verify response
    content = response.choices[0].message.content
    assert "Hi there" in content

    print("✅ Basic OpenAI mock works")


@pytest.mark.asyncio
async def test_openai_mock_multiple_triggers():
    """
    Example: Multiple response patterns
    """
    openai_mock = OpenAIMock()

    # Add multiple responses
    openai_mock.add_response("body", "Body massage is great! 350 AED for 60 min.")
    openai_mock.add_response("face", "Face massage is relaxing! 370 AED for 50 min.")
    openai_mock.add_response("both", "Combo package! 590 AED for 110 min.")

    # Test each trigger
    response1 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "I want body massage"}]
    )
    assert "350 AED" in response1.choices[0].message.content

    response2 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "I want face massage"}]
    )
    assert "370 AED" in response2.choices[0].message.content

    response3 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "I want both"}]
    )
    assert "590 AED" in response3.choices[0].message.content

    print("✅ Multiple triggers work")


@pytest.mark.asyncio
async def test_openai_mock_call_tracking():
    """
    Example: Tracking API calls

    OpenAIMock records all API calls for verification
    """
    openai_mock = OpenAIMock()
    openai_mock.add_response("test", "Response")

    # Make calls
    await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "First message"}]
    )
    await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "Second message"}]
    )

    # Verify call count
    assert openai_mock.get_call_count() == 2

    # Get last call details
    last_call = openai_mock.get_last_call()
    assert last_call["user_message"] == "Second message"

    # Check history
    assert len(openai_mock.call_history) == 2

    print("✅ Call tracking works")


@pytest.mark.asyncio
async def test_openai_mock_default_response():
    """
    Example: Using default response for unmatched messages
    """
    openai_mock = OpenAIMock()

    # Set custom default
    openai_mock.set_default_response("I don't understand. Can you rephrase?")

    # Add specific response
    openai_mock.add_response("hello", "Hi!")

    # Test matched trigger
    response1 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "Hello"}]
    )
    assert "Hi!" in response1.choices[0].message.content

    # Test unmatched trigger (should use default)
    response2 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "Random message"}]
    )
    assert "don't understand" in response2.choices[0].message.content

    print("✅ Default response works")


@pytest.mark.asyncio
async def test_create_booking_agent_mock():
    """
    Example: Using pre-configured booking agent mock

    create_booking_agent_mock() returns OpenAI mock with
    responses for typical booking scenarios
    """
    openai_mock = create_booking_agent_mock()

    # Test service selection
    response = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "Body massage"}]
    )
    content = response.choices[0].message.content

    # Should include pricing and VAT info
    assert "350 AED" in content or "350" in content  # 60 min price
    assert "460 AED" in content or "460" in content  # 90 min price
    assert "VAT" in content.upper() or "tax" in content.lower()

    print("✅ Booking agent mock works")


@pytest.mark.asyncio
async def test_openai_mock_dynamic_response():
    """
    Example: Using function for dynamic responses

    Instead of static string, can use function that
    generates response based on user message
    """
    openai_mock = OpenAIMock()

    # Dynamic response function
    def price_response(user_message):
        if "60" in user_message:
            return "60 minutes costs 350 AED"
        elif "90" in user_message:
            return "90 minutes costs 460 AED"
        return "What duration would you like?"

    openai_mock.add_response_function("price", price_response)

    # Test dynamic responses
    response1 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "What's the price for 60 min?"}]
    )
    assert "350 AED" in response1.choices[0].message.content

    response2 = await openai_mock.chat.completions.create(
        messages=[{"role": "user", "content": "What's the price for 90 min?"}]
    )
    assert "460 AED" in response2.choices[0].message.content

    print("✅ Dynamic response function works")


# ==================== BEST PRACTICES ====================

def test_mock_best_practices_summary():
    """
    Summary of mock best practices

    DO:
    ✅ Use mocks to isolate tests from external dependencies
    ✅ Use builders for creating complex test objects
    ✅ Track mock interactions for verification
    ✅ Clear mock state between tests
    ✅ Use fixtures to create reusable mocks

    DON'T:
    ❌ Make real API calls in tests (slow, expensive, unreliable)
    ❌ Share mock state between tests (causes flaky tests)
    ❌ Mock everything (some things should be tested for real)
    ❌ Create overly complex mocks (keep them simple)
    """
    print("""
    ==================== MOCK BEST PRACTICES ====================

    1. ISOLATION
       Mock external dependencies (APIs, databases, network)
       Keep tests fast and reliable

    2. BUILDERS
       Use builder pattern for complex objects
       Makes test code readable and maintainable

    3. VERIFICATION
       Track mock calls to verify behavior
       Assert on interactions, not just outputs

    4. FIXTURES
       Create reusable mocks in conftest.py
       Reduce boilerplate in individual tests

    5. CLARITY
       Mock behavior should be obvious
       Don't make tests harder to understand

    6. BALANCE
       Don't over-mock (test some real code)
       Don't under-mock (avoid external dependencies)

    =============================================================
    """)


# ==================== HOW TO RUN THESE EXAMPLES ====================
#
# Run all mock examples:
#   pytest docs/testing/examples/mock_usage_example.py
#
# Run specific example:
#   pytest docs/testing/examples/mock_usage_example.py::test_telegram_message_builder_basic
#
# Run with output visible:
#   pytest docs/testing/examples/mock_usage_example.py -s
#
# ====================================================================
