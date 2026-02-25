"""Менеджер контекста диалогов для Crystal Lab Booking Bot"""

from typing import Dict, List, Any, Optional
from datetime import datetime
from loguru import logger


class DialogContext:
    """Контекст одного диалога с клиентом"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.created_at = datetime.now()

        # История сообщений
        self.recent_messages: List[Dict[str, str]] = []

        # Собранные данные о клиенте
        self.client_data: Dict[str, Any] = {
            "name": None,
            "phone": None,
            "location": None,
            "location_details": None,  # villa/apartment number
            "preferred_therapist": None,
            "medical_notes": [],  # Важно для AI
        }

        # Данные текущего бронирования
        self.booking_data: Dict[str, Any] = {
            "service_type": None,  # body/face/combo
            "service_duration": None,  # 60/90/110 min
            "date": None,
            "time": None,
            "therapist_id": None,
            "status": "draft",  # draft/confirmed/cancelled
            "price": None,
            "total_with_vat": None,
        }

        # Состояние диалога
        self.state: str = "initial"  # initial/consulting/collecting_location/selecting_slot/confirming/completed
        self.last_question: Optional[str] = None

        # Метрики для "потеряшек"
        self.last_activity = datetime.now()
        self.message_count = 0
        self.has_location = False
        self.has_slot_proposal = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for compatibility - JSON serializable"""
        return {
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "recent_messages": self.recent_messages,
            "client_data": self.client_data,
            "booking_data": self.booking_data,
            "state": self.state,
            "last_question": self.last_question,
            "last_activity": self.last_activity.isoformat(),
            "message_count": self.message_count,
            "has_location": self.has_location,
            "has_slot_proposal": self.has_slot_proposal,
        }

    def get(self, key: str, default=None):
        """Dict-like get method for compatibility"""
        return getattr(self, key, default)


class DialogManager:
    """Менеджер для управления контекстами всех диалогов"""

    def __init__(self):
        self.contexts: Dict[int, DialogContext] = {}
        self.max_messages_history = 20  # Последние N сообщений

    def get_or_create_context(self, user_id: int) -> DialogContext:
        """Получить или создать контекст для пользователя"""
        if user_id not in self.contexts:
            logger.info(f"Создан новый контекст для пользователя {user_id}")
            self.contexts[user_id] = DialogContext(user_id)
        return self.contexts[user_id]

    def get_context(self, user_id: int) -> Optional[DialogContext]:
        """Get context without creating new one"""
        return self.contexts.get(user_id)

    def add_user_message(self, user_id: int, message: str) -> None:
        """Добавить сообщение пользователя в историю"""
        context = self.get_or_create_context(user_id)

        context.recent_messages.append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat()
        })

        context.message_count += 1
        context.last_activity = datetime.now()

        # Ограничиваем размер истории
        if len(context.recent_messages) > self.max_messages_history:
            context.recent_messages = context.recent_messages[-self.max_messages_history:]

    def add_bot_response(self, user_id: int, response: str, agent_name: str = "booking_agent") -> None:
        """Добавить ответ бота в историю"""
        context = self.get_or_create_context(user_id)

        context.recent_messages.append({
            "role": "assistant",
            "content": response,
            "agent": agent_name,
            "timestamp": datetime.now().isoformat()
        })

        # Ограничиваем размер истории
        if len(context.recent_messages) > self.max_messages_history:
            context.recent_messages = context.recent_messages[-self.max_messages_history:]

    def update_client_data(self, user_id: int, key: str, value: Any) -> None:
        """Обновить данные клиента"""
        context = self.get_or_create_context(user_id)

        if key in context.client_data:
            context.client_data[key] = value
            logger.info(f"Обновлены данные клиента {user_id}: {key} = {value}")

        # Особая обработка для медицинских заметок
        if key == "medical_note" and value:
            context.client_data["medical_notes"].append({
                "note": value,
                "timestamp": datetime.now().isoformat()
            })
            logger.warning(f"⚕️ Медицинская заметка для {user_id}: {value}")

    def update_booking_data(self, user_id: int, key: str, value: Any) -> None:
        """Обновить данные бронирования"""
        context = self.get_or_create_context(user_id)

        if key in context.booking_data:
            context.booking_data[key] = value
            logger.info(f"Обновлено бронирование {user_id}: {key} = {value}")

    def update_state(self, user_id: int, new_state: str) -> None:
        """Обновить состояние диалога"""
        context = self.get_or_create_context(user_id)
        old_state = context.state
        context.state = new_state
        logger.info(f"Состояние {user_id}: {old_state} → {new_state}")

    def get_context_for_agent(self, user_id: int) -> Dict[str, Any]:
        """Получить контекст в формате для AI агента"""
        context = self.get_or_create_context(user_id)

        return {
            "user_id": user_id,
            "recent_messages": context.recent_messages,
            "client_data": context.client_data,
            "booking_data": context.booking_data,
            "state": context.state,
            "last_question": context.last_question,
            "message_count": context.message_count,
            "has_location": context.has_location,
            "has_slot_proposal": context.has_slot_proposal,
        }

    def clear_context(self, user_id: int) -> None:
        """Очистить контекст пользователя"""
        if user_id in self.contexts:
            del self.contexts[user_id]
            logger.info(f"Контекст пользователя {user_id} очищен")

    def is_lost_client(self, user_id: int) -> bool:
        """Проверить, является ли клиент "потеряшкой" (не отвечает > 1 час)"""
        if user_id not in self.contexts:
            return False

        context = self.contexts[user_id]
        time_since_last_activity = (datetime.now() - context.last_activity).total_seconds()

        # Клиент "потерялся" если:
        # 1. Прошло > 1 часа с последнего сообщения
        # 2. Есть активное общение (> 2 сообщений)
        # 3. Нет подтвержденного бронирования
        return (
            time_since_last_activity > 3600 and
            context.message_count > 2 and
            context.booking_data["status"] != "confirmed"
        )

    def get_lost_clients(self) -> List[int]:
        """Получить список всех "потеряшек" для follow-up"""
        return [
            user_id for user_id in self.contexts.keys()
            if self.is_lost_client(user_id)
        ]


# Глобальный экземпляр менеджера
dialog_manager = DialogManager()
