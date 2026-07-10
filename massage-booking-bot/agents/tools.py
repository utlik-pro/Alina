"""OpenAI tool-use schema for the booking agent.

The agent generates a natural-language reply AND, on confirmation,
calls the `book_appointment` tool with structured fields. The caller
reads those fields directly instead of parsing them back out of the
free-text reply.

Why: free-text parsing has 4+ known failure modes (day-of-week
disambiguation, 24h/12h, silent "tomorrow" default, year rollover)
and each edge case is a real YClients mis-booking. Structured output
eliminates them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

BOOK_APPOINTMENT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "book_appointment",
        "description": (
            "Call this ONLY when the client has confirmed a specific "
            "service, date, and time AND you are sending the final "
            "confirmation message (the one with ✅). Do NOT call this "
            "while still negotiating slots, price, or payment method. "
            "Every field must be concrete — no placeholders, no 'TBD'."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "service", "duration_minutes", "date", "time",
                "area", "payment_method", "client_name", "base_price_aed",
            ],
            "properties": {
                "service": {
                    "type": "string",
                    "description": (
                        "Service name as it appears in the price list, "
                        "e.g. 'body_massage', 'face_massage', "
                        "'lymphatic_drainage', 'russian_manicure'. "
                        "Use English snake_case."
                    ),
                },
                "duration_minutes": {
                    "type": "integer",
                    # 25/40/50 cover short face services (facial massage is
                    # 50 min); 150 = Japanese mani+pedi combo (2.5h); 180 =
                    # Russian mani+pedi combo (3h) and nail extensions (2.5-3h).
                    # Without these the schema truncated services to a wrong
                    # length, writing the wrong seance_length to YClients.
                    "enum": [25, 30, 40, 45, 50, 60, 75, 80, 90, 120, 150, 180],
                    "description": "Session length in minutes.",
                },
                "date": {
                    "type": "string",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    "description": (
                        "ISO date YYYY-MM-DD in UAE local time. "
                        "Must be today or later, within 60 days."
                    ),
                },
                "time": {
                    "type": "string",
                    "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    "description": "24h time HH:MM in UAE local time.",
                },
                "area": {
                    "type": "string",
                    "enum": ["abu_dhabi", "al_ain", "dubai"],
                    "description": "Service area the therapist works in.",
                },
                "master_id": {
                    "type": ["integer", "null"],
                    "description": (
                        "YClients staff_id of the chosen therapist if "
                        "one was explicitly picked. Null means any "
                        "available therapist in the area."
                    ),
                },
                "master_name": {
                    "type": ["string", "null"],
                    "description": (
                        "Therapist first name as shown to the client, "
                        "e.g. 'Elena'. Null if not yet chosen."
                    ),
                },
                "payment_method": {
                    "type": "string",
                    "enum": ["cash", "bank_transfer"],
                    "description": (
                        "Cash = tax-free; bank_transfer = +5% VAT."
                    ),
                },
                "client_name": {
                    "type": "string",
                    "description": (
                        "Name the client gave. Required — we must know "
                        "who to put on the record."
                    ),
                },
                "client_phone": {
                    "type": ["string", "null"],
                    "description": (
                        "WhatsApp number if the client shared one "
                        "separately from the message metadata. Null "
                        "means use the phone the webhook came from."
                    ),
                },
                "base_price_aed": {
                    "type": "number",
                    "description": (
                        "Quoted price in AED before VAT. Must match "
                        "the price list."
                    ),
                },
                "address": {
                    "type": ["string", "null"],
                    "description": (
                        "Free-text address / area description the "
                        "client shared. Null if they only sent GPS."
                    ),
                },
                "notes": {
                    "type": ["string", "null"],
                    "description": (
                        "Short free-text: medical info the client "
                        "mentioned (pregnancy, cesarean, pain, etc.) "
                        "or any special request. Null if none."
                    ),
                },
            },
        },
    },
}


@dataclass
class BookingCall:
    """Parsed arguments from a book_appointment tool call.

    Fields mirror the JSON schema. Optional fields default to None so
    callers can treat the object as a simple data holder.
    """

    service: str
    duration_minutes: int
    date: str              # YYYY-MM-DD
    time: str              # HH:MM
    area: str              # abu_dhabi | al_ain | dubai
    payment_method: str    # cash | bank_transfer
    client_name: str
    base_price_aed: float
    master_id: Optional[int] = None
    master_name: Optional[str] = None
    client_phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None

    @classmethod
    def from_tool_args(cls, args: Dict[str, Any]) -> "BookingCall":
        """Build from the JSON object OpenAI returns in tool_calls[].function.arguments."""
        return cls(
            service=str(args["service"]),
            duration_minutes=int(args["duration_minutes"]),
            date=str(args["date"]),
            time=str(args["time"]),
            area=str(args["area"]),
            payment_method=str(args["payment_method"]),
            client_name=str(args["client_name"]),
            # Required in the schema, but stay defensive: a missing/blank price
            # must not raise KeyError and drop the whole booking mid-turn.
            base_price_aed=float(args.get("base_price_aed") or 0),
            master_id=_opt_int(args.get("master_id")),
            master_name=_opt_str(args.get("master_name")),
            client_phone=_opt_str(args.get("client_phone")),
            address=_opt_str(args.get("address")),
            notes=_opt_str(args.get("notes")),
        )


def _opt_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


CANCEL_APPOINTMENT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cancel_appointment",
        "description": (
            "Call this ONLY when the client clearly wants to CANCEL an "
            "existing confirmed appointment (not reschedule). Always try "
            "to capture their reason. If they only hinted at cancelling, "
            "ask first — don't call the tool until they confirm."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["reason", "confirmed"],
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "The client's stated reason for cancelling, verbatim "
                        "or paraphrased. Empty string if they gave none."
                    ),
                },
                "confirmed": {
                    "type": "boolean",
                    "description": (
                        "Set true ONLY when the client has EXPLICITLY confirmed "
                        "they want to cancel (e.g. answered 'yes, cancel' after "
                        "you offered to reschedule). Set false if they merely "
                        "hinted, asked about cancelling, or are undecided — in "
                        "that case the booking is NOT cancelled."
                    ),
                },
                "master_en_route": {
                    "type": ["boolean", "null"],
                    "description": (
                        "True if the therapist has already left / is on the "
                        "way (admin context). Null/false otherwise."
                    ),
                },
            },
        },
    },
}

RESCHEDULE_APPOINTMENT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "reschedule_appointment",
        "description": (
            "Call this when the client wants to MOVE an existing confirmed "
            "appointment to a new date/time (and has given the new slot). "
            "Do NOT call while still negotiating the new time."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["new_date", "new_time"],
            "properties": {
                "new_date": {
                    "type": "string",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                    "description": "New ISO date YYYY-MM-DD in UAE local time.",
                },
                "new_time": {
                    "type": "string",
                    "pattern": r"^([01]\d|2[0-3]):[0-5]\d$",
                    "description": "New 24h time HH:MM in UAE local time.",
                },
                "reason": {
                    "type": ["string", "null"],
                    "description": "Optional reason for the reschedule.",
                },
            },
        },
    },
}


@dataclass
class CancelCall:
    """Parsed arguments from a cancel_appointment tool call."""

    reason: str = ""
    confirmed: bool = False
    master_en_route: bool = False

    @classmethod
    def from_tool_args(cls, args: Dict[str, Any]) -> "CancelCall":
        return cls(
            reason=_opt_str(args.get("reason")) or "",
            confirmed=bool(args.get("confirmed") or False),
            master_en_route=bool(args.get("master_en_route") or False),
        )


@dataclass
class RescheduleCall:
    """Parsed arguments from a reschedule_appointment tool call."""

    new_date: str          # YYYY-MM-DD
    new_time: str          # HH:MM
    reason: Optional[str] = None

    @classmethod
    def from_tool_args(cls, args: Dict[str, Any]) -> "RescheduleCall":
        return cls(
            new_date=str(args["new_date"]),
            new_time=str(args["new_time"]),
            reason=_opt_str(args.get("reason")),
        )


@dataclass
class AgentActions:
    """Container for any structured action the agent emitted this turn.

    Backward-friendly: callers that only care about bookings read
    `.booking_call`. Cancel/reschedule are additive.
    """

    booking_call: Optional[BookingCall] = None
    cancel_call: Optional[CancelCall] = None
    reschedule_call: Optional[RescheduleCall] = None


# All tools the booking agent may call.
BOOKING_TOOLS: List[Dict[str, Any]] = [
    BOOK_APPOINTMENT_TOOL,
    CANCEL_APPOINTMENT_TOOL,
    RESCHEDULE_APPOINTMENT_TOOL,
]
