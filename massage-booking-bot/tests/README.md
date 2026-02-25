# 🧪 Tests Directory

Internal documentation for test structure and development.

---

## 📁 Directory Structure

```
tests/
├── README.md                          # This file
├── __init__.py                        # Test package initialization
├── conftest.py                        # Pytest fixtures and configuration (15 fixtures)
│
├── test_critical_scenarios.py        # 6 critical integration tests
│   ├── test_body_60_cash_no_vat
│   ├── test_body_90_transfer_with_vat
│   ├── test_message_buffering_three_quick_messages
│   ├── test_medical_notes_detection
│   ├── test_short_answers_recognition
│   └── test_combo_body_face
│
├── unit/                              # Unit tests directory
│   ├── __init__.py
│   └── test_vat_calculation.py       # 16 VAT calculation tests
│
├── integration/                       # Integration tests directory
│   └── __init__.py
│
└── helpers/                           # Test utilities and mocks
    ├── __init__.py
    ├── telegram_mock.py              # TelegramMessageBuilder, TelegramBotMock
    └── openai_mock.py                # OpenAIMock, create_booking_agent_mock()
```

---

## 🚀 Quick Start

### Running Tests

```bash
# All tests
pytest

# Only unit tests
pytest tests/unit/

# Only critical scenarios
pytest -m critical

# Specific test file
pytest tests/unit/test_vat_calculation.py

# With coverage report
pytest --cov=. --cov-report=html
```

### Writing a New Test

1. **Choose test type**: Unit or Integration?
2. **Use appropriate fixture**: `in_memory_db` or `async_db_session`
3. **Follow AAA pattern**: Arrange → Act → Assert
4. **Add markers**: `@pytest.mark.unit`, `@pytest.mark.critical`, etc.

---

## 🏗️ Available Fixtures

### Database Fixtures

#### `in_memory_db` (sync)
```python
def test_something(in_memory_db):
    """Use for simple unit tests"""
    client = Client(telegram_id="123", name="Test")
    in_memory_db.add(client)
    in_memory_db.commit()
```

#### `async_db_session` (async)
```python
@pytest.mark.asyncio
async def test_something(async_db_session):
    """Use for async integration tests"""
    client = Client(telegram_id="123", name="Test")
    async_db_session.add(client)
    await async_db_session.commit()
```

### Dialog Context Fixtures

#### `dialog_context`
```python
def test_something(dialog_context):
    """Fresh DialogContext instance"""
    dialog_context.state = "consulting"
    assert dialog_context.state == "consulting"
```

#### `dialog_manager`
```python
def test_something(dialog_manager):
    """DialogManager with clean state"""
    context = dialog_manager.get_or_create_context(user_id=123)
    # Use context...
```

### Mock Fixtures

#### `mock_telegram_message`
```python
def test_handler(mock_telegram_message):
    """Mock Telegram message with AsyncMock methods"""
    mock_telegram_message.text = "Hello"
    await mock_telegram_message.answer("Response")
```

#### `mock_bot`
```python
async def test_bot_send(mock_bot):
    """Mock Bot instance for testing send_message"""
    await mock_bot.send_message(chat_id=123, text="Hello")
    mock_bot.send_message.assert_called_once()
```

#### `mock_openai_client`
```python
async def test_ai_response(mock_openai_client):
    """Mock OpenAI client with predefined responses"""
    response = await mock_openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Body massage"}]
    )
    assert "350 AED" in response.choices[0].message.content
```

### Data Fixtures

#### `sample_client_data`
```python
def test_client(sample_client_data):
    """Pre-defined client data dictionary"""
    client = Client(**sample_client_data)
```

#### `sample_booking_data_cash` / `sample_booking_data_transfer`
```python
def test_booking(sample_booking_data_cash):
    """Pre-defined booking data for cash/transfer payments"""
    booking = Booking(**sample_booking_data_cash)
```

---

## 📝 Test Templates

### Unit Test Template

```python
import pytest
from database.models import Booking, Client


class TestMyFeature:
    """Test suite for MyFeature"""

    @pytest.mark.unit
    def test_feature_with_expected_input(self, in_memory_db):
        """
        GIVEN: [Initial state]
        WHEN: [Action performed]
        THEN: [Expected result]
        """
        # Arrange
        client = Client(telegram_id="123", name="Test User")
        in_memory_db.add(client)
        in_memory_db.commit()

        # Act
        result = client.some_method()

        # Assert
        assert result == expected_value

    @pytest.mark.unit
    def test_feature_with_edge_case(self, in_memory_db):
        """Test edge case behavior"""
        # Arrange
        # ...

        # Act
        # ...

        # Assert
        # ...
```

### Integration Test Template

```python
import pytest
from unittest.mock import patch
from tests.helpers.telegram_mock import TelegramMessageBuilder
from tests.helpers.openai_mock import create_booking_agent_mock


@pytest.mark.critical
@pytest.mark.asyncio
async def test_full_conversation_flow(async_db_session, dialog_manager):
    """
    Test complete user conversation flow

    Scenario:
    - User: "Message 1"
    - Bot: Expected response 1
    - User: "Message 2"
    - Bot: Expected response 2

    Expected outcome:
    - [What should happen]
    """
    # Arrange
    user_id = 123456789
    openai_mock = create_booking_agent_mock()

    messages = [
        "First user message",
        "Second user message",
        "Third user message",
    ]

    # Act
    with patch("agents.booking_agent.AsyncOpenAI", return_value=openai_mock):
        context = dialog_manager.get_or_create_context(user_id)

        for msg_text in messages:
            message = TelegramMessageBuilder(user_id).with_text(msg_text).build()

            # Process message
            # ... your logic here

        # Create final booking
        client = Client(telegram_id=str(user_id), name="Test")
        async_db_session.add(client)
        await async_db_session.commit()

        booking = Booking(
            client_id=client.id,
            service_name="Test Service",
            duration=60,
            base_price=350.0,
            payment_method="cash",
            status="confirmed",
        )
        booking.calculate_total()

        async_db_session.add(booking)
        await async_db_session.commit()

    # Assert
    assert booking.total_price == 350.0
    assert booking.vat_amount == 0.0
```

### Parametrized Test Template

```python
@pytest.mark.unit
@pytest.mark.parametrize("input_value,expected_output", [
    ("60", 60),
    ("90", 90),
    ("1 hour", 60),
    ("1.5 hours", 90),
])
def test_duration_parsing(input_value, expected_output):
    """Test various duration input formats"""
    result = parse_duration(input_value)
    assert result == expected_output
```

---

## 🧰 Helper Utilities

### TelegramMessageBuilder

**Purpose**: Create mock Telegram messages with fluent API

**Usage**:
```python
from tests.helpers.telegram_mock import TelegramMessageBuilder

# Simple text message
message = TelegramMessageBuilder(user_id=123) \
    .with_text("Body massage") \
    .build()

# Message with location
message = TelegramMessageBuilder(user_id=123) \
    .with_location(latitude=25.2048, longitude=55.2708) \
    .build()

# Custom timestamp
from datetime import datetime
message = TelegramMessageBuilder(user_id=123) \
    .with_text("Hello") \
    .with_timestamp(datetime(2025, 1, 1, 12, 0, 0)) \
    .build()
```

**Available Methods**:
- `.with_text(text: str)` - Set message text
- `.with_location(latitude: float, longitude: float)` - Add location
- `.with_message_id(id: int)` - Set message ID
- `.with_timestamp(dt: datetime)` - Set timestamp
- `.build()` - Create the mock message object

### TelegramBotMock

**Purpose**: Mock Bot instance that tracks sent messages

**Usage**:
```python
from tests.helpers.telegram_mock import TelegramBotMock

bot_mock = TelegramBotMock()

# Send messages
await bot_mock.send_message(chat_id=123, text="Hello")
await bot_mock.send_location(chat_id=123, latitude=25.2, longitude=55.3)

# Verify
assert bot_mock.get_message_count() == 2
assert bot_mock.get_last_message_text() == "Hello"

# Get all messages to specific chat
messages = bot_mock.get_messages_to_chat(123)
assert len(messages) == 2
```

### OpenAIMock

**Purpose**: Mock OpenAI API without making real calls

**Usage**:
```python
from tests.helpers.openai_mock import OpenAIMock

# Create mock
openai_mock = OpenAIMock()

# Add custom responses
openai_mock.add_response("body", "Hello dear! Body massage is great...")
openai_mock.add_response("cash", "Perfect! Cash payment - no VAT.")

# Use in test
response = await openai_mock.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "I want body massage"}]
)

# Verify
assert "Body massage" in response.choices[0].message.content

# Check call history
assert openai_mock.get_call_count() == 1
last_call = openai_mock.get_last_call()
assert "body" in last_call["user_message"].lower()
```

### create_booking_agent_mock()

**Purpose**: Pre-configured OpenAI mock for booking scenarios

**Usage**:
```python
from tests.helpers.openai_mock import create_booking_agent_mock

openai_mock = create_booking_agent_mock()

# Already configured with responses for:
# - "body massage" → pricing info
# - "face massage" → pricing info
# - "both" → combo pricing
# - "60" / "90" → duration confirmation
# - "cash" → cash payment confirmation
# - "transfer" / "bank" → transfer payment with VAT
# - "cesarean" / "surgery" → medical note acknowledgment

response = await openai_mock.chat.completions.create(
    messages=[{"role": "user", "content": "Body massage"}]
)
# Returns pre-configured response about body massage pricing
```

---

## ✅ Test Checklist

Before committing new tests, verify:

- [ ] **Test isolation**: Does not depend on other tests
- [ ] **Cleanup**: Database/context cleaned up automatically
- [ ] **Naming**: Test name describes what is tested
- [ ] **Documentation**: Docstring explains Given/When/Then
- [ ] **Markers**: Appropriate `@pytest.mark.*` decorators
- [ ] **AAA pattern**: Arrange → Act → Assert structure
- [ ] **Assertions**: Clear assertion messages
- [ ] **Fast**: Unit tests run in <100ms
- [ ] **Deterministic**: Same result every run
- [ ] **Pass**: Test actually passes locally

---

## 🎯 Test Markers

Use markers to categorize tests:

```python
@pytest.mark.unit          # Unit test (fast, isolated)
@pytest.mark.integration   # Integration test (slower, multiple components)
@pytest.mark.critical      # Critical scenario from QUICK_TEST checklist
@pytest.mark.vat           # VAT calculation test
@pytest.mark.buffering     # Message buffering test
@pytest.mark.slow          # Takes >1 second
@pytest.mark.asyncio       # Async test (required for async functions)
```

**Run specific markers**:
```bash
pytest -m unit              # Only unit tests
pytest -m "critical and vat"  # Critical VAT tests
pytest -m "not slow"        # Skip slow tests
```

---

## 🐛 Debugging Tests

### Print Debugging

```python
def test_something():
    print(f"Debug: value = {value}")  # Will show with pytest -s
    assert value == expected
```

Run with:
```bash
pytest -s  # Show print statements
```

### PDB Debugger

```python
def test_something():
    import pdb; pdb.set_trace()  # Breakpoint
    # Code after will pause for debugging
```

Run with:
```bash
pytest --pdb  # Drop into debugger on failure
```

### Verbose Output

```bash
pytest -v          # Verbose test names
pytest -vv         # Extra verbose
pytest --tb=long   # Full traceback
pytest --tb=short  # Short traceback
pytest -x          # Stop on first failure
```

### Coverage Analysis

```bash
# Generate HTML coverage report
pytest --cov=. --cov-report=html

# Open in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

---

## 📚 Additional Resources

- **Main Documentation**: `README_TESTING.md` - User-facing test documentation
- **Methodology**: `TESTING_METHODOLOGY.md` - How tests were created
- **Examples**: `docs/testing/examples/` - Copy-paste examples
- **pytest docs**: https://docs.pytest.org/
- **pytest-asyncio**: https://pytest-asyncio.readthedocs.io/

---

## 🤝 Contributing Tests

When adding new tests:

1. **Follow the templates** above
2. **Use existing fixtures** when possible
3. **Add new fixtures** to `conftest.py` if needed
4. **Document your test** with clear docstring
5. **Verify it passes**: `pytest tests/your_test.py`
6. **Check coverage**: `pytest --cov=module_you_tested`

---

## 📊 Current Test Status

Last updated: 2025-11-24

```
Total Tests:        23
Passing:            17 (74%)
Failing:             5 (22%)
Skipped:             1 (4%)

Coverage:
- database/models.py:     91% ✅
- database/services.py:   20% ⚠️
- dialog_context.py:      30% ⚠️
- bot.py:                  0% ❌

By Category:
- VAT Tests:        15/16 (94%) ✅
- Buffering:         1/1 (100%) ✅
- Critical Flows:    1/6 (17%) ⚠️
```

---

**Questions?** Check `TESTING_METHODOLOGY.md` or ask the team!
