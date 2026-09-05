"""Read-only calendar checks. Never repair or repeat a write automatically."""
from datetime import datetime


async def check_calendar_record(attempt, booking, yclients):
    result = {"operation": attempt.operation_key, "booking_id": attempt.booking_id,
              "record_id": attempt.yclients_id, "state": "needs_review"}
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
                result["reason"] = "Operation search has zero or multiple matches; manual review required before retry."
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
    if not record:
        result.update(state="unverified", reason="Calendar record unavailable; absence is not proven.")
        return result
    if str(record.get("id")) != str(result["record_id"]):
        result["reason"] = "Calendar returned a different record ID."
        return result
    if record.get("deleted"):
        result.update(state="mismatch", reason="Calendar record is deleted.")
        return result
    try:
        # YClients stores the salon's wall clock with +03:00; compare that
        # wall clock, matching the convention used by create_booking.
        actual = datetime.fromisoformat(record["datetime"]).replace(tzinfo=None)
        expected = booking.booking_date.replace(tzinfo=None)
        duration = int(record["seance_length"])
        expected_duration = int(booking.duration) * 60
    except (KeyError, TypeError, ValueError):
        result.update(state="unverified", reason="Calendar date or duration is missing/invalid.")
        return result
    if actual != expected or duration != expected_duration:
        result.update(state="mismatch", reason="Calendar date/time or duration differs from the local booking.")
        return result
    result.update(state="recovered_schedule_matches" if recovered else "schedule_matches", reason="Record ID, date/time and duration match; service, payment and contact still require review.")
    return result
