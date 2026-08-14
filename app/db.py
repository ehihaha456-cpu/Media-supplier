
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from .config import MONGO_URI, MONGO_DB, DEFAULT_STORAGE_LIMIT, DEFAULT_INTERVAL_MINUTES

client = None
db = None

async def init_db():
    global client, db
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is not configured")
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[MONGO_DB]
    await db.settings.update_one(
        {"_id": "settings"},
        {"$setOnInsert": {
            "storage_limit": DEFAULT_STORAGE_LIMIT,
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "protect_content": True,
            "caption": "",
            "buttons": [],
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    await db.media.create_index("received_at")
    await db.users.create_index("user_id", unique=True)
    await db.chats.create_index("chat_id", unique=True)

async def get_settings():
    return await db.settings.find_one({"_id": "settings"})

async def update_settings(data: dict):
    data["updated_at"] = datetime.now(timezone.utc)
    await db.settings.update_one({"_id": "settings"}, {"$set": data}, upsert=True)

async def add_user(user_id: int):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

async def set_user_active(user_id: int, active: bool):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"active": active, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

async def active_users():
    return db.users.find({"active": True})

async def upsert_chat(chat_id: int, chat_type: str, title: str = "", active: bool = True):
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "chat_id": chat_id,
            "chat_type": chat_type,
            "title": title or "",
            "active": active,
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

async def active_chats():
    return db.chats.find({"active": True})

async def save_media(media_doc: dict):
    media_doc["received_at"] = datetime.now(timezone.utc)
    await db.media.insert_one(media_doc)
    settings = await get_settings()
    limit = max(1, int(settings.get("storage_limit", DEFAULT_STORAGE_LIMIT)))
    count = await db.media.count_documents({})
    if count > limit:
        old = await db.media.find({}).sort("received_at", 1).limit(count - limit).to_list(length=count - limit)
        if old:
            await db.media.delete_many({"_id": {"$in": [x["_id"] for x in old]}})

async def latest_media():
    return await db.media.find({}).sort("received_at", -1).limit(1).to_list(length=1)
