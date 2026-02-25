"""
Telegram API mock helpers for testing
"""
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock


class TelegramMessageBuilder:
    """
    Builder for creating mock Telegram messages

    Usage:
        message = TelegramMessageBuilder(user_id=123).with_text("Hello").build()
    """

    def __init__(self, user_id: int = 123456789, username: str = "test_user"):
        self.user_id = user_id
        self.username = username
        self.chat_id = user_id
        self.message_id = 1
        self.text_content = "Test message"
        self.location_data = None
        self.timestamp = datetime.now()

    def with_text(self, text: str):
        """Set message text"""
        self.text_content = text
        return self

    def with_location(self, latitude: float, longitude: float):
        """Set location data"""
        self.location_data = {
            "latitude": latitude,
            "longitude": longitude,
        }
        return self

    def with_message_id(self, message_id: int):
        """Set message ID"""
        self.message_id = message_id
        return self

    def with_timestamp(self, timestamp: datetime):
        """Set message timestamp"""
        self.timestamp = timestamp
        return self

    def build(self) -> MagicMock:
        """Build and return mock message object"""
        message = MagicMock()

        # User data
        message.from_user = MagicMock()
        message.from_user.id = self.user_id
        message.from_user.username = self.username
        message.from_user.first_name = self.username.capitalize()
        message.from_user.last_name = "Test"
        message.from_user.is_bot = False

        # Chat data
        message.chat = MagicMock()
        message.chat.id = self.chat_id
        message.chat.type = "private"

        # Message data
        message.message_id = self.message_id
        message.date = self.timestamp
        message.text = self.text_content

        # Location data (if provided)
        if self.location_data:
            message.location = MagicMock()
            message.location.latitude = self.location_data["latitude"]
            message.location.longitude = self.location_data["longitude"]
        else:
            message.location = None

        # Mock async methods
        message.answer = AsyncMock(
            return_value=self._create_response_message(self.message_id + 100)
        )
        message.reply = AsyncMock(
            return_value=self._create_response_message(self.message_id + 100)
        )
        message.edit_text = AsyncMock(return_value=message)

        return message

    def _create_response_message(self, message_id: int) -> MagicMock:
        """Create a mock response message"""
        response = MagicMock()
        response.message_id = message_id
        response.text = "Bot response"
        response.date = datetime.now()
        return response


class TelegramBotMock:
    """
    Mock Telegram Bot instance for testing

    Usage:
        bot_mock = TelegramBotMock()
        await bot_mock.send_message(chat_id=123, text="Hello")
        assert bot_mock.messages_sent == 1
    """

    def __init__(self):
        self.messages_sent = []
        self.locations_sent = []
        self.edits_made = []
        self._message_id_counter = 1000

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup=None,
        **kwargs
    ) -> MagicMock:
        """Mock send_message method"""
        message = MagicMock()
        message.message_id = self._message_id_counter
        message.chat = MagicMock()
        message.chat.id = chat_id
        message.text = text
        message.date = datetime.now()

        self.messages_sent.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "message_id": message.message_id,
            "timestamp": datetime.now(),
        })

        self._message_id_counter += 1
        return message

    async def send_location(
        self,
        chat_id: int,
        latitude: float,
        longitude: float,
        **kwargs
    ) -> MagicMock:
        """Mock send_location method"""
        message = MagicMock()
        message.message_id = self._message_id_counter
        message.chat = MagicMock()
        message.chat.id = chat_id
        message.location = MagicMock()
        message.location.latitude = latitude
        message.location.longitude = longitude

        self.locations_sent.append({
            "chat_id": chat_id,
            "latitude": latitude,
            "longitude": longitude,
            "message_id": message.message_id,
        })

        self._message_id_counter += 1
        return message

    async def edit_message_text(
        self,
        text: str,
        chat_id: int,
        message_id: int,
        parse_mode: Optional[str] = None,
        **kwargs
    ) -> MagicMock:
        """Mock edit_message_text method"""
        self.edits_made.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "new_text": text,
            "parse_mode": parse_mode,
        })

        message = MagicMock()
        message.message_id = message_id
        message.text = text
        return message

    def get_last_message_text(self) -> Optional[str]:
        """Get text of last sent message"""
        if self.messages_sent:
            return self.messages_sent[-1]["text"]
        return None

    def get_message_count(self) -> int:
        """Get total count of messages sent"""
        return len(self.messages_sent)

    def get_messages_to_chat(self, chat_id: int) -> list:
        """Get all messages sent to specific chat"""
        return [msg for msg in self.messages_sent if msg["chat_id"] == chat_id]

    def clear_history(self):
        """Clear all sent messages history"""
        self.messages_sent.clear()
        self.locations_sent.clear()
        self.edits_made.clear()


def create_conversation_flow(user_id: int, messages: list[str]) -> list[MagicMock]:
    """
    Create a series of mock messages simulating a conversation

    Args:
        user_id: Telegram user ID
        messages: List of message texts

    Returns:
        List of mock message objects

    Usage:
        messages = create_conversation_flow(123, ["Body", "60", "Cash"])
    """
    builder = TelegramMessageBuilder(user_id=user_id)
    mock_messages = []

    for i, text in enumerate(messages):
        message = builder.with_text(text).with_message_id(i + 1).build()
        mock_messages.append(message)

    return mock_messages
