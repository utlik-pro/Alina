"""Read-only calendar reconciliation. Never retry, repair or mark a booking paid."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re


def _phone(value):
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('00'):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith('05'):
        digits = '971' + digits[1:]
    return digits if len(digits) >= 9 else None


def _payment(value):
    value = str(value or '').lower()
    if value in ('transfer', 'bank_transfer'):
        return 'bank_transfer'
    return value if value in ('cash', 'card') else None


def _money(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


async def check_calendar_record(attempt, booking, yclients, expected=None):
    result = {"operation": attempt.operation_key, "booking_id": attempt.booking_id,
              "record_id": attempt.yclients_id, "state": "needs_review", "checks": {},
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "payment_scope": "Payment terms and paid_full flag; bank receipt is not verified."}
    checks = result['checks']

    def compare(field, actual, wanted):
        checks[field] = ('unknown' if actual is None or wanted is None else
                         'match' if actual == wanted else 'mismatch')

    if booking is None or booking.booking_date is None:
        result["reason"] = "Local booking or expected date is missing."
        return result
    recovered = not attempt.yclients_id
    try:
        if recovered:
            candidates = await yclients.find_operation_candidates(
                attempt.operation_key, booking.booking_date.strftime("%Y-%m-%d"))
            if candidates is None:
                result.update(state="unverified", reason="Operation search unavailable or incomplete.")
                return result
            if len(candidates) != 1:
                result["reason"] = "Operation search has zero or multiple matches; review before retry."
                return result
            record = candidates[0]
            if not record.get("id"):
                result["reason"] = "Operation match has no record ID."
                return result
            result["record_id"] = str(record["id"])
        else:
            record = await yclients.get_record(attempt.yclients_id)
    except Exception:
        record = None
    if not isinstance(record, dict) or not record:
        result.update(state="unverified", reason="Calendar record unavailable; absence is not proven.")
        return result
    if str(record.get("id")) != str(result["record_id"]):
        result["reason"] = "Calendar returned a different record ID."
        return result
    if record.get("deleted") in (True, 1, '1', 'true'):
        result.update(state="mismatch", reason="Calendar record is deleted.")
        return result
    active = record.get('deleted')
    compare('record_active', not bool(active) if isinstance(active, (bool, int)) and active in (0, 1) else None, True)
    compare('local_record_id', str(getattr(booking, 'yclients_appointment_id', None) or '') or None,
            str(result['record_id']))
    expected = expected or {}
    try:
        # This salon writes UAE wall-clock times with +03:00 in YClients.
        actual_date = datetime.fromisoformat(record["datetime"]).replace(tzinfo=None)
        wanted_date = (datetime.fromisoformat(expected['datetime']).replace(tzinfo=None)
                       if expected.get('datetime') else booking.booking_date.replace(tzinfo=None))
        compare('datetime', actual_date, wanted_date)
        compare('duration', int(record['seance_length']),
                int(expected.get('duration_seconds') or int(booking.duration) * 60))
    except (KeyError, TypeError, ValueError):
        checks['schedule'] = 'unknown'
    # Do not guess staff/service IDs from names or today's changing catalogue.
    compare('staff', str(record.get('staff_id') or (record.get('staff') or {}).get('id') or '') or None,
            str(expected.get('staff_id') or '') or None)
    services = record.get('services')
    actual_ids = sorted(str(s['id']) for s in services if isinstance(s, dict) and s.get('id')) if isinstance(services, list) else None
    compare('services', actual_ids, sorted(map(str, expected['service_ids'])) if expected.get('service_ids') else None)
    client = record.get('client') or {}
    compare('phone', _phone(client.get('phone')), _phone(expected.get('client_phone')))
    normalize = lambda text: ' '.join(str(text or '').casefold().split()) or None
    compare('client_name', normalize(client.get('name')), normalize(expected.get('client_name')))
    comment = str(record.get('comment') or '')
    compare('operation_marker', f'[operation:{attempt.operation_key}]' in comment, True if expected else None)
    method = re.search(r'\bPayment:\s*(cash|bank transfer|card)\b', comment, re.I)
    actual_method = method.group(1).lower().replace(' ', '_') if method else None
    compare('payment_method', actual_method, _payment(expected.get('payment_method')))
    wanted_vat = {'cash': 'tax free', 'bank_transfer': '+5% vat'}.get(_payment(expected.get('payment_method')))
    payment_line = re.search(r'\bPayment:([^\n]*?)(?:\.\s|$)', comment, re.I)
    compare('vat_terms', wanted_vat in payment_line.group(1).lower() if wanted_vat and payment_line else None,
            True if wanted_vat else None)
    prices = [_money(s.get('cost')) if isinstance(s, dict) else None for s in services] if isinstance(services, list) and services else []
    actual_price = sum(prices, Decimal(0)) if prices and all(p is not None for p in prices) else None
    compare('base_price', actual_price, _money(expected.get('base_price')))
    # Never confuse a payment method written in a comment with actual payment.
    paid = record.get('paid_full')
    paid = bool(paid) if isinstance(paid, (bool, int)) and paid in (0, 1) else None
    status = getattr(booking, 'payment_status', None)
    compare('payment_status', paid, True if status == 'paid' else False if status == 'pending' else None)
    mismatches = [k for k, v in checks.items() if v == 'mismatch']
    unknown = [k for k, v in checks.items() if v == 'unknown']
    if mismatches:
        result.update(state='mismatch', reason='Different fields: ' + ', '.join(mismatches))
    elif checks.get('schedule') == 'unknown':
        result.update(state='unverified', reason='Calendar date or duration is missing/invalid.')
    elif unknown:
        result.update(state='needs_review', reason='Unverified fields: ' + ', '.join(unknown))
    else:
        result.update(state='recovered_matches' if recovered else 'matches',
                      reason='Calendar fields match the saved request and local payment status.')
    result['recovered'] = recovered
    return result
