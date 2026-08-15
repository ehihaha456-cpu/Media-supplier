
import asyncio
import logging
import threading
from flask import Flask
from .bot import build_application, initialize

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
app = Flask(__name__)

_application = None
_loop = None
_ready = threading.Event()
_error = None

def _runner():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()

def _start_bot():
    global _application, _loop, _error
    try:
        _loop = asyncio.new_event_loop()
        threading.Thread(target=_runner, daemon=True, name="telegram-loop").start()
        _application = build_application()

        async def boot():
            await _application.initialize()
            await _application.start()
            await _application.updater.start_polling(
                allowed_updates=["message", "callback_query", "my_chat_member", "channel_post"],
                drop_pending_updates=False,
            )
            await initialize(_application)
            log.info("Telegram polling + media delivery started")

        asyncio.run_coroutine_threadsafe(boot(), _loop).result(timeout=90)
        _ready.set()
    except Exception as exc:
        _error = repr(exc)
        log.exception("Telegram bot startup failed")

threading.Thread(target=_start_bot, daemon=True, name="telegram-bootstrap").start()

@app.get("/")
def root():
    return "Auto Media Delivery Bot is running", 200

@app.get("/health")
def health():
    return {
        "status": "ok" if _ready.is_set() else "starting",
        "telegram_polling": _ready.is_set(),
        "error": _error,
    }, 200 if _ready.is_set() else 503
