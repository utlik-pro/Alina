"""
Unit tests for VAT calculation logic

Tests the Booking.calculate_total() method from database/models.py
"""
import pytest
from database.models import Booking, Client
from prices import get_price


class TestVATCalculation:
    """Test suite for VAT calculation"""

    @pytest.mark.unit
    @pytest.mark.vat
    def test_cash_payment_no_vat(self, in_memory_db):
        """
        Cash payment should have NO VAT

        Given: Booking with cash payment, base_price=350
        When: calculate_total() is called
        Then: vat_amount=0, total_price=350
        """
        # Create client
        client = Client(
            telegram_id="123",
            name="Test User"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("body_massage_60")

        # Create booking with cash payment
        booking = Booking(
            client_id=client.id,
            service_name="Body massage",
            duration=60,
            base_price=base_price,
            payment_method="cash",
            status="confirmed",
        )

        # Calculate total
        booking.calculate_total()

        # Assertions
        assert booking.vat_amount == 0.0, "Cash payment should have no VAT"
        assert booking.total_price == base_price, "Total should equal base price for cash"
        assert booking.base_price == base_price, "Base price should remain unchanged"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_transfer_payment_with_5_percent_vat(self, in_memory_db):
        """
        Transfer payment should add 5% VAT

        Given: Booking with transfer payment, base_price=480 (Body 90min)
        When: calculate_total() is called
        Then: vat_amount=24, total_price=504
        """
        client = Client(
            telegram_id="456",
            name="Test User 2"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("body_massage_90")
        expected_vat = round(base_price * 0.05, 2)
        expected_total = round(base_price + expected_vat, 2)

        booking = Booking(
            client_id=client.id,
            service_name="Body massage",
            duration=90,
            base_price=base_price,
            payment_method="transfer",
            status="confirmed",
        )

        booking.calculate_total()

        assert booking.vat_amount == expected_vat, f"VAT should be {expected_vat} AED (5% of {base_price}), got {booking.vat_amount}"
        assert booking.total_price == expected_total, f"Total should be {expected_total} AED, got {booking.total_price}"
        assert booking.base_price == base_price, "Base price should remain unchanged"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_bank_payment_with_vat(self, in_memory_db):
        """
        Bank payment (alternative name for transfer) should add 5% VAT
        """
        client = Client(
            telegram_id="789",
            name="Test User 3"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("face_massage")

        booking = Booking(
            client_id=client.id,
            service_name="Face massage",
            duration=50,
            base_price=base_price,
            payment_method="bank",  # Alternative to "transfer"
            status="confirmed",
        )

        booking.calculate_total()

        expected_vat = round(base_price * 0.05, 2)  # 18.50
        expected_total = round(base_price + expected_vat, 2)  # 388.50

        assert booking.vat_amount == expected_vat, f"VAT should be {expected_vat} AED"
        assert booking.total_price == expected_total, f"Total should be {expected_total} AED"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_combo_service_cash_no_vat(self, in_memory_db):
        """
        Combo service (Body + Face) with cash should have no VAT

        Given: Combo booking, base_price=650, cash payment
        When: calculate_total() is called
        Then: vat_amount=0, total_price=650
        """
        client = Client(
            telegram_id="111",
            name="Test User 4"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("body_face_combo")

        booking = Booking(
            client_id=client.id,
            service_name="Body + Face massage",
            duration=85,
            base_price=base_price,
            payment_method="cash",
            status="confirmed",
        )

        booking.calculate_total()

        assert booking.vat_amount == 0.0, "Combo with cash should have no VAT"
        assert booking.total_price == base_price, "Total should equal base price"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_combo_service_transfer_with_vat(self, in_memory_db):
        """
        Combo service (Body + Face) with transfer should add 5% VAT

        Given: Combo booking, base_price=650, transfer payment
        When: calculate_total() is called
        Then: vat_amount=32.50, total_price=682.50
        """
        client = Client(
            telegram_id="222",
            name="Test User 5"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("body_face_combo")

        booking = Booking(
            client_id=client.id,
            service_name="Body + Face massage",
            duration=85,
            base_price=base_price,
            payment_method="transfer",
            status="confirmed",
        )

        booking.calculate_total()

        expected_vat = round(base_price * 0.05, 2)  # 32.50
        expected_total = round(base_price + expected_vat, 2)  # 682.50

        assert booking.vat_amount == expected_vat, f"VAT should be {expected_vat} AED"
        assert booking.total_price == expected_total, f"Total should be {expected_total} AED"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_vat_rate_override(self, in_memory_db):
        """
        Test custom VAT rate (if different from 5%)

        Given: Booking with custom vat_rate
        When: calculate_total() is called
        Then: VAT calculated with custom rate
        """
        client = Client(
            telegram_id="333",
            name="Test User 6"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("body_massage_60")

        booking = Booking(
            client_id=client.id,
            service_name="Body massage",
            duration=60,
            base_price=base_price,
            payment_method="transfer",
            vat_rate=0.10,  # 10% instead of 5%
            status="confirmed",
        )

        booking.calculate_total()

        expected_vat = round(base_price * 0.10, 2)  # 35.00
        expected_total = round(base_price + expected_vat, 2)  # 385.00

        assert booking.vat_amount == expected_vat, f"VAT should use custom rate: {expected_vat} AED"
        assert booking.total_price == expected_total, f"Total with 10% VAT: {expected_total} AED"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_zero_price_booking(self, in_memory_db):
        """
        Test edge case: booking with zero base price

        Given: Booking with base_price=0
        When: calculate_total() is called
        Then: vat_amount=0, total_price=0
        """
        client = Client(
            telegram_id="444",
            name="Test User 7"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        booking = Booking(
            client_id=client.id,
            service_name="Free session",
            duration=30,
            base_price=0.0,
            payment_method="transfer",
            status="confirmed",
        )

        booking.calculate_total()

        assert booking.vat_amount == 0.0, "Zero price should have zero VAT"
        assert booking.total_price == 0.0, "Total should be zero"

    @pytest.mark.unit
    @pytest.mark.vat
    @pytest.mark.parametrize("base_price,payment_method,expected_vat,expected_total", [
        (get_price("body_massage_60"), "cash", 0.0, get_price("body_massage_60")),
        (get_price("body_massage_60"), "transfer", round(get_price("body_massage_60") * 0.05, 2), round(get_price("body_massage_60") * 1.05, 2)),
        (get_price("body_massage_90"), "cash", 0.0, get_price("body_massage_90")),
        (get_price("body_massage_90"), "transfer", round(get_price("body_massage_90") * 0.05, 2), round(get_price("body_massage_90") * 1.05, 2)),
        (get_price("body_face_combo"), "cash", 0.0, get_price("body_face_combo")),
        (get_price("body_face_combo"), "transfer", round(get_price("body_face_combo") * 0.05, 2), round(get_price("body_face_combo") * 1.05, 2)),
        (get_price("face_massage"), "cash", 0.0, get_price("face_massage")),
        (get_price("face_massage"), "transfer", round(get_price("face_massage") * 0.05, 2), round(get_price("face_massage") * 1.05, 2)),
    ])
    def test_vat_calculation_parametrized(
        self,
        in_memory_db,
        base_price,
        payment_method,
        expected_vat,
        expected_total
    ):
        """
        Parametrized test for various price/payment combinations

        Tests multiple scenarios in a single test function
        """
        client = Client(
            telegram_id="555",
            name="Param Test User"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        booking = Booking(
            client_id=client.id,
            service_name="Test service",
            duration=60,
            base_price=base_price,
            payment_method=payment_method,
            status="confirmed",
        )

        booking.calculate_total()

        assert booking.vat_amount == expected_vat, \
            f"VAT mismatch for {base_price} AED {payment_method}: expected {expected_vat}, got {booking.vat_amount}"

        assert booking.total_price == expected_total, \
            f"Total mismatch for {base_price} AED {payment_method}: expected {expected_total}, got {booking.total_price}"

    @pytest.mark.unit
    @pytest.mark.vat
    def test_recalculate_after_payment_method_change(self, in_memory_db):
        """
        Test VAT recalculation when payment method changes

        Given: Booking initially with cash (no VAT)
        When: Payment method changed to transfer and calculate_total() called again
        Then: VAT should be recalculated
        """
        client = Client(
            telegram_id="666",
            name="Test User 8"
        )
        in_memory_db.add(client)
        in_memory_db.commit()

        base_price = get_price("body_massage_90")
        expected_vat = round(base_price * 0.05, 2)
        expected_total = round(base_price + expected_vat, 2)

        booking = Booking(
            client_id=client.id,
            service_name="Body massage",
            duration=90,
            base_price=base_price,
            payment_method="cash",
            status="confirmed",
        )

        # Initial calculation (cash)
        booking.calculate_total()
        assert booking.total_price == base_price, f"Initial total should be {base_price} (no VAT)"

        # Change to transfer
        booking.payment_method = "transfer"
        booking.calculate_total()

        assert booking.vat_amount == expected_vat, "VAT should be added after changing to transfer"
        assert booking.total_price == expected_total, "Total should include VAT after method change"
