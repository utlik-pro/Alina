"""
Терминальный чат с AI-ботом Crystal Lab.
Тестирование ответов без Telegram — пишешь как клиент, бот отвечает.

Запуск:
    python3.11 test_chat.py
"""

import asyncio
from openai import AsyncOpenAI
from config import config
from agents.booking_agent import BookingAgent
from dialog_context import dialog_manager

# Цвета для терминала
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


async def main():
    # Проверяем ключ
    if not config.OPENAI_API_KEY or config.OPENAI_API_KEY == "your_openai_api_key_here":
        print(f"{YELLOW}OpenAI API key не настроен в .env{RESET}")
        return

    agent = BookingAgent()
    user_id = "test_terminal_user"

    print(f"""
{BOLD}╔══════════════════════════════════════════════╗
║   Crystal Lab AI Bot — Тест в терминале      ║
║   Модель: {config.OPENAI_MODEL:<35}║
╚══════════════════════════════════════════════╝{RESET}

{GRAY}Пишите как клиент. Бот ответит как Алина.
Команды: /clear — сброс диалога, /quit — выход{RESET}
""")

    # История сообщений для GPT
    messages = [{"role": "system", "content": agent.system_prompt}]

    while True:
        try:
            user_input = input(f"{GREEN}Вы: {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{GRAY}Выход.{RESET}")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print(f"{GRAY}Выход.{RESET}")
            break

        if user_input == "/clear":
            messages = [{"role": "system", "content": agent.system_prompt}]
            dialog_manager.clear_context(user_id)
            print(f"{YELLOW}Диалог сброшен.{RESET}\n")
            continue

        # Добавляем сообщение клиента
        messages.append({"role": "user", "content": user_input})

        try:
            response = await agent.client.chat.completions.create(
                model=agent.model,
                messages=messages,
            )

            bot_reply = response.choices[0].message.content

            # Добавляем ответ в историю
            messages.append({"role": "assistant", "content": bot_reply})

            # Разбиваем по MESSAGE_SPLIT (как в реальном боте)
            parts = bot_reply.split("---MESSAGE_SPLIT---")
            for part in parts:
                part = part.strip()
                if part:
                    print(f"{CYAN}Бот: {part}{RESET}")

            # Показываем использование токенов
            usage = response.usage
            if usage:
                print(f"{GRAY}   [{usage.prompt_tokens} + {usage.completion_tokens} = {usage.total_tokens} tokens]{RESET}")

            print()

        except Exception as e:
            print(f"{YELLOW}Ошибка API: {e}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
