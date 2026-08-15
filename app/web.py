import os
import asyncio
import threading
from flask import Flask, request
from telegram import Update
from .bot import build_application

app = Flask(__name__)
application = None
_loop = None
_ready = threading.Event()

def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()

def init_bot():
    global application, _loop
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_run_loop, name="telegram-event-loop", daemon=True).start()
    application = build_application()

    async def startup():
        await application.initialize()
        await application.start()
        public_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
        if not public_url:
            raise RuntimeError("RENDER_EXTERNAL_URL is not available")
        await application.bot.set_webhook(
            url=f"{public_url}/telegram/webhook",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )

    asyncio.run_coroutine_threadsafe(startup(), _loop).result(timeout=60)
    _ready.set()

init_bot()

@app.get("/")
def health():
    return "Auto Media Delivery Bot is running", 200

@app.get("/health")
def health_check():
    return {"status": "ok"}, 200

@app.get("/webhook-info")
def webhook_info():
    try:
        info = asyncio.run_coroutine_threadsafe(
            application.bot.get_webhook_info(), _loop
        ).result(timeout=15)
        return {
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_message": info.last_error_message,
            "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
        }, 200
    except Exception as e:
        return {"error": str(e)}, 500

@app.post("/telegram/webhook")
def telegram_webhook():
    if not _ready.is_set():
        return {"error": "bot is starting"}, 503
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        asyncio.run_coroutine_threadsafe(
            application.update_queue.put(update), _loop
        )
        return "ok", 200
    except Exception as e:
        return {"error": str(e)}, 400
