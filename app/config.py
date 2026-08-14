
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB = os.getenv("MONGO_DB", "auto_media_bot").strip()

# Telegram user ID(s), comma separated, allowed to open the admin panel.
OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip().isdigit()
}

DEFAULT_STORAGE_LIMIT = int(os.getenv("DEFAULT_STORAGE_LIMIT", "20"))
DEFAULT_INTERVAL_MINUTES = int(os.getenv("DEFAULT_INTERVAL_MINUTES", "60"))
