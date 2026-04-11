"""Скрипт запуска бота — polling (локально) или webhook (Render)"""

import os

if os.getenv("RENDER", "false").lower() == "true":
    # Webhook mode on Render — run via uvicorn
    import uvicorn
    from webhook_app import app  # noqa: F401

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
else:
    # Polling mode locally
    from bot import start_polling
    start_polling()
