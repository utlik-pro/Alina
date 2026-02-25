# 🔧 Testing Troubleshooting Guide

Common problems and solutions when running tests.

---

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Test Execution Errors](#test-execution-errors)
3. [Database Problems](#database-problems)
4. [Async Test Issues](#async-test-issues)
5. [Import Errors](#import-errors)
6. [Coverage Problems](#coverage-problems)
7. [Performance Issues](#performance-issues)

---

## Installation Issues

### Problem: `pytest` command not found

**Symptoms:**
```bash
$ pytest
bash: pytest: command not found
```

**Solution:**
```bash
# Make sure you're in virtual environment
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows

# Install pytest
pip install pytest pytest-asyncio pytest-cov
```

### Problem: Module import errors after install

**Symptoms:**
```
ModuleNotFoundError: No module named 'pytest_asyncio'
```

**Solution:**
```bash
# Install all test dependencies
pip install -r requirements.txt

# Or install missing package
pip install pytest-asyncio
```

### Problem: Wrong Python version

**Symptoms:**
```
ERROR: Python 3.7 is not supported
```

**Solution:**
```bash
# Check Python version
python --version

# Should be 3.13+ (project requirement)
# Update Python or use correct version
python3.13 -m pytest
```

---

## Test Execution Errors

### Problem: `TypeError: 'service_type' is an invalid keyword`

**Symptoms:**
```python
TypeError: 'service_type' is an invalid keyword argument for Booking
```

**Cause:** Using wrong field name (documentation vs actual code mismatch)

**Solution:**
```python
# ❌ Wrong
booking = Booking(
    service_type="Body massage",  # Wrong field!
    service_duration=60            # Wrong field!
)

# ✅ Correct
booking = Booking(
    service_name="Body massage",   # Correct!
    duration=60                     # Correct!
)
```

**How to verify:** Check model definition
```bash
grep "class Booking" database/models.py -A 20
```

### Problem: `TypeError: takes X arguments but Y were given`

**Symptoms:**
```python
TypeError: get_or_create_context() takes 2 positional arguments but 3 were given
```

**Cause:** Wrong method signature

**Solution:**
```python
# ❌ Wrong
context = dialog_manager.get_or_create_context(user_id, "username")

# ✅ Correct
context = dialog_manager.get_or_create_context(user_id)
```

**How to verify:** Check function definition
```bash
grep "def get_or_create_context" dialog_context.py
```

### Problem: `AssertionError` with no message

**Symptoms:**
```
AssertionError
assert 0.0 == 23.0
```

**Cause:** Assertion without error message

**Solution:**
```python
# ❌ Bad - unclear failure
assert booking.vat_amount == 23.0

# ✅ Good - clear message
assert booking.vat_amount == 23.0, \
    f"Expected VAT 23.0, got {booking.vat_amount}"
```

---

## Database Problems

### Problem: Database locked

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Cause:** Using real database instead of in-memory

**Solution:**
```python
# ✅ Always use in-memory for tests
@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")  # Note :memory:
    # ...
```

### Problem: Tables not created

**Symptoms:**
```
sqlalchemy.exc.OperationalError: no such table: bookings
```

**Cause:** Forgot to create tables in fixture

**Solution:**
```python
@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")

    # Don't forget this!
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    return Session()
```

### Problem: Data persists between tests

**Symptoms:**
- Tests pass individually but fail when run together
- Random test failures

**Cause:** Sharing database instance

**Solution:**
```python
# ❌ Bad - shared database
db = create_database()  # Global

def test_1():
    client = Client(id=1)  # Affects test_2!
    db.add(client)

def test_2():
    client = db.query(Client).filter_by(id=1).first()
    assert client is None  # FAILS!

# ✅ Good - fresh database per test
@pytest.fixture
def db():
    """New database each test"""
    return create_in_memory_database()

def test_1(db):
    client = Client(id=1)
    db.add(client)

def test_2(db):  # Fresh database!
    clients = db.query(Client).all()
    assert len(clients) == 0  # PASSES
```

---

## Async Test Issues

### Problem: `TypeError: object MagicMock can't be used in await`

**Symptoms:**
```python
TypeError: object MagicMock can't be used in 'await' expression
```

**Cause:** Using `MagicMock` instead of `AsyncMock` for async methods

**Solution:**
```python
# ❌ Wrong
from unittest.mock import MagicMock

message.answer = MagicMock()
await message.answer("text")  # ERROR!

# ✅ Correct
from unittest.mock import AsyncMock

message.answer = AsyncMock()
await message.answer("text")  # Works!
```

### Problem: Test hangs forever

**Symptoms:**
- Test never completes
- Need to Ctrl+C to stop

**Cause:** Async function not awaited

**Solution:**
```python
# ❌ Wrong - not awaited
@pytest.mark.asyncio
async def test_something():
    result = some_async_function()  # Missing await!
    assert result == expected

# ✅ Correct
@pytest.mark.asyncio
async def test_something():
    result = await some_async_function()  # Awaited!
    assert result == expected
```

### Problem: `RuntimeError: no running event loop`

**Symptoms:**
```
RuntimeError: no running event loop
```

**Cause:** Missing `@pytest.mark.asyncio` decorator

**Solution:**
```python
# ❌ Wrong - no decorator
async def test_something():
    await async_function()

# ✅ Correct
@pytest.mark.asyncio  # Don't forget!
async def test_something():
    await async_function()
```

### Problem: `asyncio_mode` configuration error

**Symptoms:**
```
PytestConfigWarning: Unknown config option: asyncio_mode
```

**Cause:** pytest-asyncio not installed

**Solution:**
```bash
pip install pytest-asyncio
```

---

## Import Errors

### Problem: `ModuleNotFoundError: No module named 'database'`

**Symptoms:**
```
ModuleNotFoundError: No module named 'database'
```

**Cause:** Running tests from wrong directory

**Solution:**
```bash
# ❌ Wrong
cd tests
pytest  # Can't find parent modules!

# ✅ Correct
cd /path/to/project/root
pytest tests/
```

### Problem: Circular import

**Symptoms:**
```
ImportError: cannot import name 'X' from partially initialized module
```

**Cause:** Circular dependency in imports

**Solution:**
- Move import inside function
- Reorganize module structure
- Use `from __future__ import annotations` for type hints

```python
# ❌ Can cause circular import
from module_a import ClassA

class ClassB:
    def method(self) -> ClassA:
        pass

# ✅ Better
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from module_a import ClassA

class ClassB:
    def method(self) -> ClassA:
        pass
```

---

## Coverage Problems

### Problem: Coverage shows 0% for all files

**Symptoms:**
```
Name       Stmts   Miss  Cover
------------------------------
bot.py       358    358     0%
```

**Cause:** Running tests but not actually exercising code

**Solution:**
1. Check if tests are actually passing
2. Verify tests import and use the modules
3. Check coverage config in `pytest.ini`

```bash
# Run with verbose coverage
pytest --cov=. --cov-report=term-missing -v
```

### Problem: Tests in coverage report

**Symptoms:**
```
tests/test_something.py    100    0   100%
```

**Cause:** Tests included in coverage (shouldn't be)

**Solution:**
Add to `pytest.ini`:
```ini
[coverage:run]
omit =
    */tests/*
    */test_*.py
```

### Problem: Can't open HTML coverage report

**Symptoms:**
- `htmlcov/index.html` doesn't exist

**Cause:** Didn't generate HTML report

**Solution:**
```bash
# Generate HTML report
pytest --cov=. --cov-report=html

# Open in browser
open htmlcov/index.html  # macOS
```

---

## Performance Issues

### Problem: Tests are too slow

**Symptoms:**
- Unit tests take >1 second each
- Full suite takes >5 minutes

**Causes & Solutions:**

**1. Using real database**
```python
# ❌ Slow - real database
engine = create_engine("sqlite:///test.db")

# ✅ Fast - in-memory
engine = create_engine("sqlite:///:memory:")
```

**2. Making real API calls**
```python
# ❌ Slow - real API
response = openai.chat.completions.create(...)

# ✅ Fast - mock
response = mock_openai.chat.completions.create(...)
```

**3. Not using parametrize**
```python
# ❌ Slow - many similar tests
def test_cash_350(): ...
def test_cash_460(): ...
def test_transfer_350(): ...

# ✅ Fast - one parametrized test
@pytest.mark.parametrize("price,method,vat", [
    (350, "cash", 0),
    (460, "cash", 0),
    (350, "transfer", 17.5),
])
def test_payment(price, method, vat): ...
```

**4. Running all tests when you need one**
```bash
# ❌ Slow - all tests
pytest

# ✅ Fast - specific test
pytest tests/unit/test_vat_calculation.py::test_cash_payment_no_vat
```

---

## Common Pytest Flags

### Problem: Don't know which flags to use

**Solution:** Use these common combinations:

```bash
# Quick feedback (fast tests only)
pytest -m "not slow" -x

# Debugging failed test
pytest tests/test_file.py::test_name -v -s --tb=long

# Coverage report
pytest --cov=. --cov-report=html --cov-report=term-missing

# Parallel execution (faster)
pytest -n auto

# Stop on first failure
pytest -x

# Show local variables in traceback
pytest -l

# Re-run only failed tests
pytest --lf

# Run last failed, then all
pytest --ff
```

---

## Debugging Techniques

### 1. Use print debugging

```python
def test_something():
    print(f"DEBUG: value = {value}")  # Won't show normally
    assert value == expected
```

Run with `-s`:
```bash
pytest -s tests/test_file.py
```

### 2. Use PDB debugger

```python
def test_something():
    import pdb; pdb.set_trace()  # Breakpoint
    # Execution will pause here
    result = function_under_test()
```

Or run with `--pdb`:
```bash
pytest --pdb  # Drops into debugger on failure
```

### 3. Use verbose output

```bash
pytest -vv  # Extra verbose
pytest --tb=long  # Full traceback
```

### 4. Isolate the problem

```bash
# Run just one test
pytest tests/test_file.py::test_specific

# Run just one class
pytest tests/test_file.py::TestClass

# Run just one marker
pytest -m unit
```

### 5. Check test setup

```bash
# Show fixture setup/teardown
pytest --setup-show
```

---

## Getting Help

### 1. Check error message carefully

- Read the full traceback
- Note the exact error type
- Check which line failed

### 2. Search this guide

Use Ctrl+F to search for error message

### 3. Check pytest documentation

```bash
pytest --help
pytest --markers  # Show available markers
pytest --fixtures  # Show available fixtures
```

### 4. Enable debug mode

Add to `pytest.ini`:
```ini
[pytest]
log_cli = true
log_cli_level = DEBUG
```

### 5. Create minimal reproduction

Create smallest possible test that shows the problem:

```python
def test_minimal():
    """Smallest test showing the problem"""
    # Just enough code to reproduce issue
    pass
```

---

## Prevention Checklist

Before running tests:

- [ ] Virtual environment activated?
- [ ] All dependencies installed?
- [ ] Running from project root?
- [ ] Database using `:memory:`?
- [ ] Async tests have `@pytest.mark.asyncio`?
- [ ] Using `AsyncMock` for async methods?
- [ ] Fixtures cleaning up properly?
- [ ] Tests independent (no shared state)?

---

## Still Having Problems?

1. **Check examples**: Look at working tests in `tests/` directory
2. **Read methodology**: See `TESTING_METHODOLOGY.md` for patterns
3. **Check source code**: Verify actual field names and signatures
4. **Run one test**: Isolate the problem to single test
5. **Use debugger**: Add breakpoints and inspect state

**Common mistakes:**
- Wrong field names (check models)
- Wrong method signatures (check source)
- Missing `await` for async
- Using `MagicMock` instead of `AsyncMock`
- Not using in-memory database
- Tests not isolated

---

**Last Updated**: 2025-11-24
**Need more help?** Check `TESTING_METHODOLOGY.md` for detailed examples!
