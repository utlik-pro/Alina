# 🔧 Pytest Fixtures Guide

Complete guide to using fixtures in the massage booking bot tests.

---

## What are Fixtures?

**Fixtures** are reusable test components that:
- Set up test data
- Provide mock objects
- Create database connections
- Clean up after tests

**Benefits:**
- ✅ Reduce code duplication
- ✅ Consistent test setup
- ✅ Automatic cleanup
- ✅ Easy to maintain

---

## Available Fixtures

### 📦 Database Fixtures

#### `in_memory_db` - Synchronous Database

**Use when:** Testing simple database operations without async

**Example:**
```python
def test_create_client(in_memory_db):
    client = Client(telegram_id="123", name="Test")
    in_memory_db.add(client)
    in_memory_db.commit()

    assert client.id is not None
```

**Features:**
- In-memory SQLite (fast!)
- Automatic table creation
- Automatic cleanup
- Synchronous operations

#### `async_db_session` - Asynchronous Database

**Use when:** Testing async code (handlers, services)

**Example:**
```python
@pytest.mark.asyncio
async def test_create_booking(async_db_session):
    client = Client(telegram_id="123", name="Test")
    async_db_session.add(client)
    await async_db_session.commit()
    await async_db_session.refresh(client)

    assert client.id is not None
```

**Features:**
- Async SQLite with aiosqlite
- For testing async functions
- Auto cleanup after test

---

### 💬 Dialog Context Fixtures

#### `dialog_context` - Single Context Instance

**Use when:** Testing context state transitions

**Example:**
```python
def test_context_state_change(dialog_context):
    dialog_context.state = "consulting"
    assert dialog_context.state == "consulting"

    dialog_context.booking_data = {"service": "Body"}
    assert "service" in dialog_context.booking_data
```

**Features:**
- Fresh context each test
- Pre-configured user_id
- Clean state

#### `dialog_manager` - Manager Instance

**Use when:** Testing manager-level operations

**Example:**
```python
def test_create_multiple_contexts(dialog_manager):
    context1 = dialog_manager.get_or_create_context(123)
    context2 = dialog_manager.get_or_create_context(456)

    assert context1.user_id != context2.user_id
    assert len(dialog_manager.contexts) == 2
```

**Features:**
- Manages multiple contexts
- Clears state between tests
- Singleton pattern

---

### 📱 Telegram Mock Fixtures

#### `mock_telegram_message` - Message Object

**Use when:** Testing message handlers

**Example:**
```python
@pytest.mark.asyncio
async def test_message_handler(mock_telegram_message):
    mock_telegram_message.text = "Body massage"

    # Test handler
    await handle_message(mock_telegram_message)

    # Verify response sent
    mock_telegram_message.answer.assert_called_once()
```

**Features:**
- Pre-configured user/chat data
- AsyncMock for async methods
- Customizable properties

#### `mock_bot` - Bot Instance

**Use when:** Testing bot.send_message() calls

**Example:**
```python
@pytest.mark.asyncio
async def test_notification(mock_bot):
    await send_admin_notification(mock_bot, "New booking!")

    mock_bot.send_message.assert_called_with(
        chat_id=admin_chat_id,
        text="New booking!"
    )
```

**Features:**
- Tracks all sent messages
- AsyncMock methods
- Verifiable interactions

---

### 🤖 OpenAI Mock Fixtures

#### `mock_openai_client` - AI Client

**Use when:** Testing conversation flows

**Example:**
```python
@pytest.mark.asyncio
async def test_ai_response(mock_openai_client):
    response = await mock_openai_client.chat.completions.create(
        messages=[{"role": "user", "content": "Body massage"}]
    )

    content = response.choices[0].message.content
    assert "350 AED" in content
```

**Features:**
- Pre-configured responses
- Pattern matching
- No real API calls

---

### 📊 Data Fixtures

#### `sample_client_data` - Client Dictionary

**Use when:** Creating test clients

**Example:**
```python
def test_client_creation(sample_client_data):
    client = Client(**sample_client_data)
    assert client.name == sample_client_data["name"]
```

**Contents:**
```python
{
    "telegram_id": 123456789,
    "name": "Test User",
    "location_lat": 25.2048,
    "location_long": 55.2708,
    "address": "Villa 25"
}
```

#### `sample_booking_data_cash` - Cash Booking

**Use when:** Creating test bookings without VAT

**Example:**
```python
def test_cash_booking(sample_booking_data_cash):
    booking = Booking(**sample_booking_data_cash)
    assert booking.payment_method == "cash"
    assert booking.base_price == 350.0
```

#### `sample_booking_data_transfer` - Transfer Booking

**Use when:** Creating test bookings with VAT

**Example:**
```python
def test_transfer_booking(sample_booking_data_transfer):
    booking = Booking(**sample_booking_data_transfer)
    assert booking.payment_method == "transfer"
    assert booking.base_price == 460.0
```

---

## Creating Custom Fixtures

### Basic Fixture

```python
# In conftest.py
@pytest.fixture
def my_test_data():
    """My custom test data"""
    return {
        "key": "value",
        "number": 42
    }

# In test file
def test_something(my_test_data):
    assert my_test_data["number"] == 42
```

### Fixture with Setup/Teardown

```python
@pytest.fixture
def temp_file():
    """Create temporary file"""
    # Setup
    file = open("temp.txt", "w")
    file.write("test data")
    file.close()

    yield "temp.txt"  # Provide to test

    # Teardown
    import os
    os.remove("temp.txt")
```

### Fixture with Scope

```python
@pytest.fixture(scope="session")  # Created once per test session
def expensive_resource():
    # Setup expensive resource
    resource = create_expensive_thing()

    yield resource

    # Cleanup
    resource.cleanup()
```

**Scopes:**
- `function` - Default, per test
- `class` - Per test class
- `module` - Per test module
- `session` - Once per session

### Async Fixture

```python
@pytest.fixture
async def async_resource():
    """Async fixture"""
    resource = await create_async_resource()

    yield resource

    await resource.cleanup()
```

---

## Fixture Composition

Fixtures can use other fixtures:

```python
@pytest.fixture
def booking_with_client(in_memory_db):
    """Fixture that uses another fixture"""
    client = Client(telegram_id="123", name="Test")
    in_memory_db.add(client)
    in_memory_db.commit()

    booking = Booking(
        client_id=client.id,
        service_name="Body massage",
        base_price=350.0
    )
    in_memory_db.add(booking)
    in_memory_db.commit()

    return booking

# Use in test
def test_booking(booking_with_client):
    assert booking_with_client.client_id is not None
```

---

## Fixture Parameterization

Create multiple test cases from one fixture:

```python
@pytest.fixture(params=[
    ("cash", 0.0, 350.0),
    ("transfer", 17.5, 367.5),
])
def payment_scenario(request):
    """Different payment scenarios"""
    payment_method, vat, total = request.param
    return {
        "payment_method": payment_method,
        "expected_vat": vat,
        "expected_total": total
    }

def test_payment(payment_scenario):
    # This test runs TWICE - once per param
    booking = Booking(
        base_price=350.0,
        payment_method=payment_scenario["payment_method"]
    )
    booking.calculate_total()

    assert booking.vat_amount == payment_scenario["expected_vat"]
```

---

## Best Practices

### ✅ DO

1. **Keep fixtures simple**
   ```python
   @pytest.fixture
   def simple_client():
       return Client(telegram_id="123", name="Test")
   ```

2. **Use descriptive names**
   ```python
   # ✅ Good
   @pytest.fixture
   def booking_with_cash_payment():

   # ❌ Bad
   @pytest.fixture
   def data():
   ```

3. **Document fixtures**
   ```python
   @pytest.fixture
   def my_fixture():
       """
       Creates X for testing Y

       Returns: Z
       """
   ```

4. **Use appropriate scope**
   ```python
   @pytest.fixture(scope="module")  # Expensive setup
   def database_with_seed_data():
   ```

### ❌ DON'T

1. **Don't make fixtures too complex**
   ```python
   # ❌ Bad - too much logic
   @pytest.fixture
   def complex_fixture():
       # 50 lines of setup
       # Multiple objects
       # Complex relationships
   ```

2. **Don't share state between tests**
   ```python
   # ❌ Bad - mutable shared state
   shared_list = []

   @pytest.fixture
   def bad_fixture():
       return shared_list  # Will affect all tests!
   ```

3. **Don't forget cleanup**
   ```python
   # ❌ Bad - no cleanup
   @pytest.fixture
   def file_fixture():
       open("test.txt", "w").close()
       return "test.txt"
       # File left behind!

   # ✅ Good
   @pytest.fixture
   def file_fixture():
       filename = "test.txt"
       open(filename, "w").close()
       yield filename
       os.remove(filename)  # Cleanup
   ```

---

## Debugging Fixtures

### See which fixtures are available

```bash
pytest --fixtures
```

### See which fixtures a test uses

```bash
pytest --setup-show tests/test_vat_calculation.py::test_cash_payment_no_vat
```

### Print from fixture

```python
@pytest.fixture
def debug_fixture():
    print("Setup happening!")  # Will show with -s flag
    yield "data"
    print("Teardown happening!")
```

Run with:
```bash
pytest -s  # Show print output
```

---

## Common Patterns

### Pattern 1: Factory Fixture

```python
@pytest.fixture
def client_factory(in_memory_db):
    """Factory to create multiple clients"""
    def _create_client(telegram_id, name="Test"):
        client = Client(telegram_id=telegram_id, name=name)
        in_memory_db.add(client)
        in_memory_db.commit()
        return client

    return _create_client

# Use in test
def test_multiple_clients(client_factory):
    client1 = client_factory("123")
    client2 = client_factory("456")
    assert client1.id != client2.id
```

### Pattern 2: Conditional Fixture

```python
@pytest.fixture
def database(request):
    """Use different database based on marker"""
    if request.node.get_closest_marker("real_db"):
        return create_real_database()
    else:
        return create_in_memory_database()
```

### Pattern 3: Fixture with Finalizer

```python
@pytest.fixture
def resource(request):
    """Resource with cleanup finalizer"""
    res = create_resource()

    def cleanup():
        res.close()

    request.addfinalizer(cleanup)
    return res
```

---

## Summary

**Fixtures are your testing superpower!**

- 🎯 Use them to reduce boilerplate
- 🧹 They handle cleanup automatically
- 🔄 They make tests consistent
- 📦 They promote code reuse

**Remember:**
1. Keep fixtures simple
2. Use appropriate scope
3. Document what they provide
4. Clean up resources
5. Don't share mutable state

**See also:**
- [tests/conftest.py](../../tests/conftest.py) - All fixture definitions
- [Pytest docs](https://docs.pytest.org/en/stable/fixture.html) - Official documentation

---

**Last Updated**: 2025-11-24
