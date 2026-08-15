
import os
import asyncio
import threading
import logging
from flask import Flask, request
from telegram import Update
from .bot import build_application, initialize
from .config import WEBHOOK_SECRET

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

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
    thread = threading.Thread(target=loop_runner, daemon=True, name="telegram-event-loop")
    thread.start()

    application = build_application()

    async def boot():
        await application.initialize()
        await initialize(application)
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

        await application.bot.set_webhook(**kwargs)
        await application.start()

    fut = asyncio.run_coroutine_threadsafe(boot(), loop)
    fut.result(timeout=90)
    ready.set()

    info = asyncio.run_coroutine_threadsafe(
        application.bot.get_webhook_info(), loop
    ).result(timeout=15)
    log.info(
        "Telegram webhook ready: url=%s pending=%s last_error=%s",
        info.url, info.pending_update_count, info.last_error_message
    )

startup()

@app.get("/")
def health():
    return "Auto Media Delivery Bot is running", 200

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "ready": ready.is_set(),
        "webhook": True,
    }, 200

@app.get("/webhook-info")
def webhook_info():
    try:
        info = asyncio.run_coroutine_threadsafe(
            application.bot.get_webhook_info(), loop
        ).result(timeout=15)
        return {
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_message": info.last_error_message,
            "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
        }, 200
    except Exception as e:
        log.exception("Webhook info failed")
        return {"error": str(e)}, 500

@app.post("/telegram/webhook")
def telegram_webhook():
    if not ready.is_set():
        return "starting", 503

    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if supplied != WEBHOOK_SECRET:
            log.warning("Telegram webhook rejected: bad secret")
            return "forbidden", 403

    try:
        payload = request.get_json(force=True)
        update = Update.de_json(payload, application.bot)

        # Let python-telegram-bot process the update itself.
        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            loop,
        )
        future.result(timeout=20)
        return "ok", 200
    except Exception as e:
        log.exception("Telegram update processing failed")
        return {"error": str(e)}, 500
