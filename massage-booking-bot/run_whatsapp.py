"""Entry point for Crystal Lab WhatsApp Bot (FastAPI + uvicorn)"""

import uvicorn
from config import config


def main():
    print("Starting Crystal Lab WhatsApp Bot...")
    print(f"  Webhook port: {config.WHATSAPP_WEBHOOK_PORT}")
    print(f"  Phone Number ID: {config.WHATSAPP_PHONE_NUMBER_ID or 'NOT SET'}")
    print(f"  Verify Token: {config.WHATSAPP_VERIFY_TOKEN}")
    print()
    print("Webhook URL to register in Meta Business Suite:")
    print(f"  https://YOUR_DOMAIN:{config.WHATSAPP_WEBHOOK_PORT}/webhook")
    print()

    uvicorn.run(
        "whatsapp_bot:app",
        host="0.0.0.0",
        port=config.WHATSAPP_WEBHOOK_PORT,
        reload=config.DEBUG,
        log_level=config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
