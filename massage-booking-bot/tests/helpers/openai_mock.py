"""
OpenAI API mock helpers for testing
"""
from typing import Optional, Callable
from unittest.mock import MagicMock

from prices import get_price


class OpenAIMock:
    """
    Mock OpenAI client for testing

    Usage:
        openai_mock = OpenAIMock()
        openai_mock.add_response("body", "Hello dear! Body massage is great...")
        response = await openai_mock.chat.completions.create(messages=[...])
    """

    def __init__(self):
        self.responses = {}
        self.default_response = "Thank you! Could you please provide more details?"
        self.call_history = []
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create_completion

    def add_response(self, trigger: str, response: str):
        """
        Add a response that will be returned when trigger is found in user message

        Args:
            trigger: Keyword to look for in user message (case-insensitive)
            response: Text to return when trigger is found
        """
        self.responses[trigger.lower()] = response

    def add_response_function(self, trigger: str, func: Callable[[str], str]):
        """
        Add a function that generates response dynamically

        Args:
            trigger: Keyword to look for in user message
            func: Function that takes user message and returns response
        """
        self.responses[trigger.lower()] = func

    def set_default_response(self, response: str):
        """Set default response when no trigger matches"""
        self.default_response = response

    async def _create_completion(self, *args, **kwargs):
        """Mock create method for chat completions"""
        messages = kwargs.get("messages", [])
        model = kwargs.get("model", "gpt-4o-mini")
        temperature = kwargs.get("temperature", 0.7)

        # Get last user message
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        last_message = user_messages[-1]["content"] if user_messages else ""

        # Record call for testing
        self.call_history.append({
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "user_message": last_message,
        })

        # Find matching response
        response_text = self._find_response(last_message)

        # Create mock response object
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = response_text
        response.choices[0].finish_reason = "stop"

        response.usage = MagicMock()
        response.usage.prompt_tokens = len(last_message) // 4
        response.usage.completion_tokens = len(response_text) // 4
        response.usage.total_tokens = response.usage.prompt_tokens + response.usage.completion_tokens

        response.model = model
        response.id = f"chatcmpl-test-{len(self.call_history)}"

        return response

    def _find_response(self, user_message: str) -> str:
        """Find matching response for user message"""
        user_message_lower = user_message.lower()

        # Check each trigger
        for trigger, response in self.responses.items():
            if trigger in user_message_lower:
                # If response is a function, call it
                if callable(response):
                    return response(user_message)
                return response

        # Return default if no match
        return self.default_response

    def get_call_count(self) -> int:
        """Get number of times API was called"""
        return len(self.call_history)

    def get_last_call(self) -> Optional[dict]:
        """Get details of last API call"""
        if self.call_history:
            return self.call_history[-1]
        return None

    def clear_history(self):
        """Clear call history"""
        self.call_history.clear()


def create_booking_agent_mock():
    """
    Create pre-configured OpenAI mock for booking agent scenarios

    Returns:
        OpenAIMock configured with typical booking responses
    """
    mock = OpenAIMock()

    # Service selection responses
    # IMPORTANT: "both" must come before "body massage" and "face massage"
    # because _find_response checks triggers in insertion order
    mock.add_response(
        "both",
        f"Hello dear! Body + Face combo is our special package. "
        f"85 minutes total for {get_price('body_face_combo'):,.0f} AED. "
        f"We work with VAT system. Additional 5% if you pay by transfer. "
        f"Cash payment - tax free. Would you like to book?"
    )

    mock.add_response(
        "body massage",
        f"Hello dear! Body massage is a great choice. "
        f"We offer 60 minutes ({get_price('body_massage_60'):,.0f} AED) or 90 minutes ({get_price('body_massage_90'):,.0f} AED). "
        f"We work with VAT system. Additional 5% if you pay by transfer. "
        f"Cash payment - tax free. Which duration would you prefer?"
    )

    mock.add_response(
        "face massage",
        f"Hello dear! Face massage is wonderful for relaxation. "
        f"We offer 50 minutes session for {get_price('face_massage'):,.0f} AED. "
        f"We work with VAT system. Additional 5% if you pay by transfer. "
        f"Cash payment - tax free. Would you like to proceed?"
    )

    # Duration responses
    def duration_response(msg: str):
        if "60" in msg:
            return "Perfect choice! 60 minutes body massage. Please share your location so I can find you dear."
        elif "90" in msg:
            return "Excellent! 90 minutes body massage for deeper relaxation. Please share your location."
        return "What duration would you prefer?"

    mock.add_response("60", duration_response)
    mock.add_response("90", duration_response)

    # Location responses
    mock.add_response(
        "villa",
        "Thank you! What is your villa number?"
    )

    mock.add_response(
        "apartment",
        "Thank you! What is your apartment number?"
    )

    # Time/slot responses
    mock.add_response(
        "tomorrow",
        "What time works best for you tomorrow dear?"
    )

    mock.add_response(
        "pm",
        "Great! What name should I put for the booking?"
    )

    # Payment responses
    mock.add_response(
        "cash",
        "Perfect! Cash payment - no additional VAT. Your total is {price} AED. Looking forward to seeing you!"
    )

    mock.add_response(
        "transfer",
        "Perfect! Bank transfer - your total is {price_with_vat} AED (including 5% VAT). I'll send payment details."
    )

    mock.add_response(
        "bank",
        "Perfect! Bank transfer - your total is {price_with_vat} AED (including 5% VAT). I'll send payment details."
    )

    # Medical notes response
    mock.add_response(
        "cesarean",
        "Okay dear, thank you for letting me know. I will inform the therapist about your cesarean. "
        "We will use gentle techniques to ensure your comfort and safety."
    )

    mock.add_response(
        "surgery",
        "Thank you for sharing that dear. I will inform the therapist about your surgery. "
        "We'll make sure to adjust the massage accordingly."
    )

    return mock
