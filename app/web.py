import os
import asyncio
import threading
from flask import Flask, request
from telegram import Update
from .bot import build_application, initialize
from .config import WEBHOOK_SECRET

app = Flask(__name__)
application = None
loop = None
ready = threading.Event()


def loop_runner():
    asyncio.set_event_loop(loop)
    loop.run_forever()


def startup():
    global application, loop
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop_runner, daemon=True, name="telegram-loop").start()
    application = build_application()
    fut = asyncio.run_coroutine_threadsafe(application.initialize(), loop)
    fut.result(timeout=60)
    fut = asyncio.run_coroutine_threadsafe(initialize(application), loop)
    fut.result(timeout=60)

    public_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not public_url:
        raise RuntimeError("RENDER_EXTERNAL_URL is not available")
    kwargs = {
        "url": f"{public_url}/telegram/webhook",
        "allowed_updates": Update.ALL_TYPES,
        "drop_pending_updates": False,
    }
    if WEBHOOK_SECRET:
        kwargs["secret_token"] = WEBHOOK_SECRET
    fut = asyncio.run_coroutine_threadsafe(application.bot.set_webhook(**kwargs), loop)
    fut.result(timeout=60)
    fut = asyncio.run_coroutine_threadsafe(application.start(), loop)
    fut.result(timeout=60)
    ready.set()


startup()


@app.get("/")
def health():
    return "Auto Media Delivery Bot is running", 200


@app.get("/health")
def health_check():
    return {"status": "ok", "ready": ready.is_set()}, 200


@app.get("/webhook-info")
def webhook_info():
    try:
        info = asyncio.run_coroutine_threadsafe(application.bot.get_webhook_info(), loop).result(timeout=15)
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
    if not ready.is_set():
        return "starting", 503
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != WEBHOOK_SECRET:
            return "forbidden", 403
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        asyncio.run_coroutine_threadsafe(application.update_queue.put(update), loop)
        return "ok", 200
    except Exception as e:
        return {"error": str(e)}, 400
