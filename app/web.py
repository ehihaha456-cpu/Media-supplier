
import os
import asyncio
from flask import Flask, request
from telegram import Update
from .bot import build_application

app = Flask(__name__)
application = None
_loop = None

def init_bot():
    global application, _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    application = build_application()
    _loop.run_until_complete(application.initialize())
    _loop.run_until_complete(application.start())
    public_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not public_url:
        raise RuntimeError("RENDER_EXTERNAL_URL is not available")
    _loop.run_until_complete(application.bot.set_webhook(
        url=f"{public_url}/telegram/webhook",
        allowed_updates=Update.ALL_TYPES,
    ))

init_bot()

@app.get("/")
def health():
    return "Auto Media Delivery Bot is running", 200

@app.get("/health")
def health_check():
    return {"status": "ok"}, 200

@app.post("/telegram/webhook")
def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        asyncio.run_coroutine_threadsafe(application.update_queue.put(update), _loop)
        return "ok", 200
    except Exception as e:
        return {"error": str(e)}, 400
