"""
Example Unit Test - Copy this template for new unit tests

This example demonstrates:
- AAA pattern (Arrange-Act-Assert)
- Using fixtures for test data
- Parametrized tests
- Clear documentation
"""
import pytest
from database.models import Booking, Client


class TestVATCalculationExample:
    """
    Example test suite for VAT calculation

    Use this as a template when writing new unit tests for isolated functions.
    """

    @pytest.mark.unit
    @pytest.mark.vat
    def test_cash_payment_has_no_vat(self, in_memory_db):
        """
        Test that cash payments do not include VAT

        GIVEN: A booking with cash payment method and base_price=350
        WHEN: calculate_total() is called
        THEN: vat_amount should be 0.0 and total_price should equal base_price
        """
        # ========== ARRANGE ==========
        # Create test client
        client = Client(
            telegram_id="123456789",
            name="Test User"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        # Create test booking with cash payment
        booking = Booking(
            client_id=client.id,
            service_name="Body massage",
            duration=60,
            base_price=350.0,
            payment_method="cash",
            status="confirmed",
        )

        # ========== ACT ==========
        # Execute the function under test
        booking.calculate_total()

        # ========== ASSERT ==========
        # Verify expected outcomes
        assert booking.vat_amount == 0.0, \
            "Cash payment should have no VAT"

        assert booking.total_price == 350.0, \
            f"Total should equal base price for cash, got {booking.total_price}"

        assert booking.base_price == 350.0, \
            "Base price should remain unchanged"

        print("✅ TEST PASSED: Cash payment has no VAT")


    @pytest.mark.unit
    @pytest.mark.vat
    def test_transfer_payment_adds_5_percent_vat(self, in_memory_db):
        """
        Test that bank transfer payments add 5% VAT

        GIVEN: A booking with transfer payment method and base_price=460
        WHEN: calculate_total() is called
        THEN: vat_amount should be 23.0 (5% of 460) and total should be 483.0
        """
        # ========== ARRANGE ==========
        client = Client(
            telegram_id="987654321",
            name="Transfer Test User"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        booking = Booking(
            client_id=client.id,
            service_name="Body massage",
            duration=90,
            base_price=460.0,
            payment_method="transfer",
            status="confirmed",
        )

        # ========== ACT ==========
        booking.calculate_total()

        # ========== ASSERT ==========
        expected_vat = 23.0  # 5% of 460
        expected_total = 483.0  # 460 + 23

        assert booking.vat_amount == expected_vat, \
            f"VAT should be {expected_vat} AED (5% of 460), got {booking.vat_amount}"

        assert booking.total_price == expected_total, \
            f"Total should be {expected_total} AED, got {booking.total_price}"

        assert booking.payment_method == "transfer", \
            "Payment method should be transfer"

        print("✅ TEST PASSED: Transfer payment adds 5% VAT")


    @pytest.mark.unit
    @pytest.mark.vat
    @pytest.mark.parametrize("base_price,payment_method,expected_vat,expected_total", [
        # (base_price, payment_method, expected_vat, expected_total)
        (350.0, "cash", 0.0, 350.0),         # Body 60min - cash
        (350.0, "transfer", 17.5, 367.5),   # Body 60min - transfer
        (460.0, "cash", 0.0, 460.0),         # Body 90min - cash
        (460.0, "transfer", 23.0, 483.0),   # Body 90min - transfer
        (590.0, "cash", 0.0, 590.0),         # Combo - cash
        (590.0, "transfer", 29.5, 619.5),   # Combo - transfer
    ])
    def test_vat_calculation_multiple_scenarios(
        self,
        in_memory_db,
        base_price,
        payment_method,
        expected_vat,
        expected_total
    ):
        """
        Parametrized test covering multiple price/payment combinations

        This single test function runs 6 different test cases!

        Benefits of parametrized tests:
        - Compact code (6 tests in 1 function)
        - Easy to add new scenarios
        - Shared test logic
        - Clear test data table
        """
        # ========== ARRANGE ==========
        client = Client(
            telegram_id="param_test_123",
            name="Parametrized Test User"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        booking = Booking(
            client_id=client.id,
            service_name="Test Service",
            duration=60,
            base_price=base_price,
            payment_method=payment_method,
            status="confirmed",
        )

        # ========== ACT ==========
        booking.calculate_total()

        # ========== ASSERT ==========
        assert booking.vat_amount == expected_vat, \
            f"VAT mismatch for {base_price} AED {payment_method}: " \
            f"expected {expected_vat}, got {booking.vat_amount}"

        assert booking.total_price == expected_total, \
            f"Total mismatch for {base_price} AED {payment_method}: " \
            f"expected {expected_total}, got {booking.total_price}"

        print(f"✅ TEST PASSED: {base_price} AED {payment_method} → {expected_total} AED")


# ==================== HOW TO RUN THIS EXAMPLE ====================
#
# Run all tests in this file:
#   pytest docs/testing/examples/unit_test_example.py
#
# Run only VAT tests:
#   pytest docs/testing/examples/unit_test_example.py -m vat
#
# Run specific test:
#   pytest docs/testing/examples/unit_test_example.py::TestVATCalculationExample::test_cash_payment_has_no_vat
#
# Run with verbose output:
#   pytest docs/testing/examples/unit_test_example.py -v
#
# Run with print statements visible:
#   pytest docs/testing/examples/unit_test_example.py -s
#
# ==================================================================


# ==================== KEY TAKEAWAYS ====================
#
# 1. AAA PATTERN: Always structure tests as Arrange → Act → Assert
#
# 2. CLEAR NAMES: Test name should describe what is being tested
#    ✅ Good: test_cash_payment_has_no_vat
#    ❌ Bad: test_vat, test_1
#
# 3. DOCUMENTATION: Every test should have a docstring explaining:
#    - What is being tested
#    - GIVEN (initial state)
#    - WHEN (action)
#    - THEN (expected result)
#
# 4. ASSERTIONS WITH MESSAGES: Always include error messages
#    ✅ Good: assert x == 5, f"Expected 5, got {x}"
#    ❌ Bad: assert x == 5
#
# 5. USE FIXTURES: Don't create database connections in tests
#    ✅ Good: def test_something(in_memory_db):
#    ❌ Bad: def test_something(): db = create_db()
#
# 6. PARAMETRIZE: Use @pytest.mark.parametrize for multiple similar tests
#    - Reduces code duplication
#    - Makes test data visible
#    - Easy to add new cases
#
# 7. MARKERS: Use pytest markers to categorize tests
#    @pytest.mark.unit - Unit test
#    @pytest.mark.vat - VAT-related test
#    @pytest.mark.slow - Slow test
#
# 8. ISOLATION: Each test should be independent
#    - Don't rely on other tests
#    - Don't share state between tests
#    - Use fixtures for clean setup/teardown
#
# =======================================================
