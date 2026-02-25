"""Фразы для напоминаний потерявшимся клиентам (Lost Clients)

Основано на встрече с клиентом от 22.11.2025 и анализе реальных WhatsApp диалогов.

КУЛЬТУРНЫЙ КОНТЕКСТ:
- Арабские клиенты нормально относятся к частым напоминаниям
- Они рассеянные, им нужны напоминания
- Фраза "update us" работает хорошо
- Предложение свободных слотов повышает конверсию
"""

from typing import List
import random


# 10 вариантов фраз для пушей (меняющийся тон: friendly → более настойчивый)
LOST_CLIENT_MESSAGES = [
    # 1. Дружелюбный check-in
    "Hi dear! Just checking in - would you still like to book a massage? 😊",

    # 2. С предложением слотов
    "Hey! Just wanted to update you on our available slots for today/tomorrow. Any suitable for you?",

    # 3. Простой и прямой
    "Hello! We have some free time slots - interested? Let me know dear 🌹",

    # 4. С легким urgency
    "Hi! Are you still interested in booking? Update us please dear 😊",

    # 5. Follow-up
    "Hey dear! Following up on your booking request - would you like to proceed?",

    # 6. Приветливое приглашение
    "Hello! We'd love to have you - would you like to schedule a session? 🌹",

    # 7. Дружеское напоминание
    "Hi! Just a friendly reminder - we're here when you're ready to book dear 😊",

    # 8. Проверка интереса
    "Hey! Checking if you'd like to proceed with the booking? Let us know 🌹",

    # 9. С доступностью
    "Hello dear! We have availability today and tomorrow - any time work for you?",

    # 10. Финальный - более настойчивый
    "Hi! Let us know if you'd like to book - we're ready for you dear! Update us please 😊",
]


def get_random_lost_client_message() -> str:
    """
    Получить случайную фразу для напоминания.

    Returns:
        str: Случайная фраза из списка
    """
    return random.choice(LOST_CLIENT_MESSAGES)


def get_lost_client_message_with_slots(available_slots: List[str]) -> str:
    """
    Получить фразу с указанием доступных слотов.

    Args:
        available_slots: Список доступных времен (например: ["10:00 AM", "2:00 PM", "7:00 PM"])

    Returns:
        str: Сообщение с доступными слотами
    """
    if not available_slots:
        return get_random_lost_client_message()

    slots_text = " ".join(available_slots)

    messages_with_slots = [
        f"Hi dear! We have these slots available: {slots_text}\nAny suitable for you? 😊",
        f"Hello! Update on free slots: {slots_text}\nWould you like to book? 🌹",
        f"Hey dear! Available times: {slots_text}\nInterested? Let me know 😊",
        f"Hi! We can offer: {slots_text}\nAny of these work for you dear? 🌹",
    ]

    return random.choice(messages_with_slots)


def get_lost_client_message_by_attempt(attempt_number: int, available_slots: List[str] = None) -> str:
    """
    Получить фразу в зависимости от номера попытки.
    Тон становится более настойчивым с каждой попыткой.

    Args:
        attempt_number: Номер попытки (1, 2, 3, ...)
        available_slots: Опционально - доступные слоты

    Returns:
        str: Сообщение соответствующее номеру попытки
    """
    # Попытка 1-2: Дружелюбный тон
    if attempt_number <= 2:
        if available_slots:
            return get_lost_client_message_with_slots(available_slots)
        return LOST_CLIENT_MESSAGES[0]  # Самое дружелюбное

    # Попытка 3-5: Более настойчивый
    elif attempt_number <= 5:
        if available_slots:
            return get_lost_client_message_with_slots(available_slots)
        return LOST_CLIENT_MESSAGES[4]  # "Following up"

    # Попытка 6+: Финальные напоминания
    else:
        return LOST_CLIENT_MESSAGES[9]  # "Update us please" - наиболее настойчивое


# Примеры использования:
if __name__ == "__main__":
    print("=== 10 вариантов фраз для потеряшек ===\n")
    for i, msg in enumerate(LOST_CLIENT_MESSAGES, 1):
        print(f"{i}. {msg}\n")

    print("\n=== С доступными слотами ===\n")
    slots = ["10:00 AM", "2:00 PM", "7:00 PM"]
    print(get_lost_client_message_with_slots(slots))

    print("\n=== По номеру попытки ===\n")
    for attempt in [1, 3, 6]:
        print(f"Попытка {attempt}: {get_lost_client_message_by_attempt(attempt, slots)}\n")
