"""Конфигурация приложения Crystal Lab Booking Bot"""

import os
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

class Config:
    """Класс конфигурации приложения"""

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./crystal_lab.db"
    )

    # Telegram Group для уведомлений
    ADMIN_GROUP_CHAT_ID: Optional[str] = os.getenv("ADMIN_GROUP_CHAT_ID")

    # Настройки приложения
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Настройки агентов
    RESPONSE_TIMEOUT: int = int(os.getenv("RESPONSE_TIMEOUT", "30"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

    # Redis (for message buffering)
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")

    # Mock режимы (для MVP без интеграций)
    MOCK_YCLIENTS: bool = os.getenv("MOCK_YCLIENTS", "True").lower() == "true"
    MOCK_WHATSAPP: bool = os.getenv("MOCK_WHATSAPP", "True").lower() == "true"

    # YClients API
    YCLIENTS_PARTNER_TOKEN: Optional[str] = os.getenv("YCLIENTS_PARTNER_TOKEN")
    YCLIENTS_USER_TOKEN: Optional[str] = os.getenv("YCLIENTS_USER_TOKEN")
    YCLIENTS_COMPANY_ID: Optional[str] = os.getenv("YCLIENTS_COMPANY_ID")
    YCLIENTS_LOGIN: Optional[str] = os.getenv("YCLIENTS_LOGIN")
    YCLIENTS_PASSWORD: Optional[str] = os.getenv("YCLIENTS_PASSWORD")

    # WhatsApp Business Cloud API
    WHATSAPP_ACCESS_TOKEN: Optional[str] = os.getenv("WHATSAPP_ACCESS_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "crystal_lab_verify_2026")
    WHATSAPP_APP_SECRET: Optional[str] = os.getenv("WHATSAPP_APP_SECRET")

    # WhatsApp server settings
    WHATSAPP_WEBHOOK_PORT: int = int(os.getenv("WHATSAPP_WEBHOOK_PORT", "8000"))

    # Render / Webhook mode
    RENDER: bool = os.getenv("RENDER", "false").lower() == "true"
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    PORT: int = int(os.getenv("PORT", "10000"))
    RENDER_EXTERNAL_URL: str = os.getenv("RENDER_EXTERNAL_URL", "")

    # ManyChat
    MANYCHAT_API_KEY: Optional[str] = os.getenv("MANYCHAT_API_KEY")
    MANYCHAT_WEBHOOK_SECRET: str = os.getenv("MANYCHAT_WEBHOOK_SECRET", "")

    @classmethod
    def validate(cls) -> bool:
        """Проверка наличия обязательных переменных"""
        if not cls.TELEGRAM_BOT_TOKEN:
            print("❌ TELEGRAM_BOT_TOKEN не установлен!")
            print("   Получите токен у @BotFather в Telegram")
            return False

        if not cls.OPENAI_API_KEY:
            print("❌ OPENAI_API_KEY не установлен!")
            print("   Получите ключ на https://platform.openai.com/api-keys")
            return False

        print("✅ Конфигурация валидна")
        print(f"   Модель: {cls.OPENAI_MODEL}")
        print(f"   Mock YClients: {cls.MOCK_YCLIENTS}")
        print(f"   Mock WhatsApp: {cls.MOCK_WHATSAPP}")
        return True


# Создаем экземпляр конфигурации
config = Config()
