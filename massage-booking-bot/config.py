"""Конфигурация приложения Crystal Lab Booking Bot"""

import os
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

class Config:
    """Класс конфигурации приложения"""

    # Telegram Bot (client-facing: @crystal_lab_bot)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Telegram Bot for masters/therapists (separate bot: @crystal_lab_masters_bot)
    # When set, enables per-master booking notifications with address + Google Maps.
    MASTERS_BOT_TOKEN: Optional[str] = os.getenv("MASTERS_BOT_TOKEN")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4")

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

    # Wappi.pro (WhatsApp via QR-bound profile)
    WAPPI_TOKEN: Optional[str] = os.getenv("WAPPI_TOKEN")
    WAPPI_PROFILE_ID: Optional[str] = os.getenv("WAPPI_PROFILE_ID")
    WAPPI_WEBHOOK_SECRET: str = os.getenv("WAPPI_WEBHOOK_SECRET", "")
    # Attach promo/offer photos to WhatsApp replies. OFF by default (prod)
    # so the current test round stays text-only; flip to true when ready.
    WAPPI_SEND_PROMO_PHOTOS: bool = os.getenv("WAPPI_SEND_PROMO_PHOTOS", "false").lower() == "true"

    # Instagram (Meta Graph API) — entry point: IG DM → consult → WhatsApp CTA
    INSTAGRAM_ACCESS_TOKEN: Optional[str] = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    INSTAGRAM_VERIFY_TOKEN: str = os.getenv("INSTAGRAM_VERIFY_TOKEN", "crystal_lab_ig_2026")
    INSTAGRAM_APP_SECRET: Optional[str] = os.getenv("INSTAGRAM_APP_SECRET")
    # Default host = "Instagram API with Instagram Login" flavor (no FB Page).
    # For the Facebook-Login/Page-token flavor set https://graph.facebook.com/v23.0
    INSTAGRAM_GRAPH_BASE: str = os.getenv("INSTAGRAM_GRAPH_BASE", "https://graph.instagram.com/v23.0")
    # The WhatsApp number clients are funneled to (digits only, e.g. 9715XXXXXXXX)
    WHATSAPP_CTA_NUMBER: Optional[str] = os.getenv("WHATSAPP_CTA_NUMBER")

    # Driver / logistics notifications (Telegram chat id of the driver group)
    DRIVER_TELEGRAM_CHAT_ID: Optional[str] = os.getenv("DRIVER_TELEGRAM_CHAT_ID")

    # Payments — bank details shown to clients paying by transfer
    PAYMENT_BANK_DETAILS: Optional[str] = os.getenv("PAYMENT_BANK_DETAILS")
    # Optional online payment link / provider (Stripe/Telr/etc.) — stub for now
    PAYMENT_LINK_BASE: Optional[str] = os.getenv("PAYMENT_LINK_BASE")

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
