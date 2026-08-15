from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from .config import MONGO_URI, MONGO_DB, DEFAULT_STORAGE_LIMIT, DEFAULT_INTERVAL_MINUTES

client = None
db = None


def now():
    return datetime.now(timezone.utc)


async def init_db():
    global client, db
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is not configured")
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[MONGO_DB]
    await client.admin.command("ping")

    await db.settings.update_one(
        {"_id": "settings"},
        {"$setOnInsert": {
            "storage_limit": DEFAULT_STORAGE_LIMIT,
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "protect_content": True,
            "caption": "",
            "buttons": [],
            "source_chat_id": None,
            "updated_at": now(),
        }},
        upsert=True,
    )
    await db.media.create_index("seq", unique=True)
    await db.media.create_index("received_at")
    await db.users.create_index("user_id", unique=True)
    await db.chats.create_index("chat_id", unique=True)


async def get_settings():
    return await db.settings.find_one({"_id": "settings"})


async def update_settings(data: dict):
    data["updated_at"] = now()
    await db.settings.update_one({"_id": "settings"}, {"$set": data}, upsert=True)


async def add_user(user_id: int):
    oldest = await db.media.find_one({}, sort=[("seq", 1)])
    cursor = oldest["seq"] if oldest else None
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True, "updated_at": now(), "next_seq": cursor, "next_send_at": now()}},
        upsert=True,
    )


async def activate_user(user_id: int):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        await add_user(user_id)
        return
    oldest = await db.media.find_one({}, sort=[("seq", 1)])
    cursor = user.get("next_seq")
    if cursor is None or (oldest and cursor < oldest["seq"]):
        cursor = oldest["seq"] if oldest else None
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"active": True, "next_seq": cursor, "next_send_at": now(), "updated_at": now()}},
    )


async def deactivate_user(user_id: int):
    await db.users.update_one({"user_id": user_id}, {"$set": {"active": False, "updated_at": now()}})


async def active_users_due(at=None):
    at = at or now()
    return db.users.find({"active": True, "next_send_at": {"$lte": at}})


async def get_user(user_id: int):
    return await db.users.find_one({"user_id": user_id})


async def update_user_cursor(user_id: int, next_seq, next_send_at):
    await db.users.update_one({"user_id": user_id}, {"$set": {"next_seq": next_seq, "next_send_at": next_send_at, "updated_at": now()}})


async def upsert_chat(chat_id: int, chat_type: str, title: str = "", active: bool = True):
    existing = await db.chats.find_one({"chat_id": chat_id})
    insert_values = {"delivery_enabled": True, "next_seq": None, "next_send_at": now()}
    if not existing:
        oldest = await db.media.find_one({}, sort=[("seq", 1)])
        if oldest:
            insert_values["next_seq"] = oldest["seq"]
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"chat_id": chat_id, "chat_type": chat_type, "title": title or "", "active": active, "updated_at": now()},
         "$setOnInsert": insert_values},
        upsert=True,
    )


async def set_chat_delivery(chat_id: int, enabled: bool):
    await db.chats.update_one({"chat_id": chat_id}, {"$set": {"delivery_enabled": enabled, "updated_at": now()}})


async def active_chats_due(at=None):
    at = at or now()
    return db.chats.find({"active": True, "delivery_enabled": True, "next_send_at": {"$lte": at}})


async def update_chat_cursor(chat_id: int, next_seq, next_send_at):
    await db.chats.update_one({"chat_id": chat_id}, {"$set": {"next_seq": next_seq, "next_send_at": next_send_at, "updated_at": now()}})


async def list_chats():
    return await db.chats.find({"active": True}).sort("updated_at", -1).to_list(length=100)


async def save_media(kind: str, file_id: str):
    last = await db.media.find_one({}, sort=[("seq", -1)])
    seq = (last["seq"] + 1) if last else 1
    await db.media.insert_one({"seq": seq, "kind": kind, "file_id": file_id, "received_at": now()})

    settings = await get_settings()
    limit = max(1, int(settings.get("storage_limit", DEFAULT_STORAGE_LIMIT)))
    docs = await db.media.find({}, {"_id": 1, "seq": 1}).sort("seq", -1).to_list(length=limit + 1000)
    if len(docs) > limit:
        remove = docs[limit:]
        await db.media.delete_many({"_id": {"$in": [x["_id"] for x in remove]}})

    oldest = await db.media.find_one({}, sort=[("seq", 1)])
    if oldest:
        # Users/chats that were waiting for deleted media continue from the oldest retained item.
        await db.users.update_many({"next_seq": {"$lt": oldest["seq"]}}, {"$set": {"next_seq": oldest["seq"]}})
        await db.chats.update_many({"next_seq": {"$lt": oldest["seq"]}}, {"$set": {"next_seq": oldest["seq"]}})
    return seq


async def get_media_by_seq(seq: int):
    return await db.media.find_one({"seq": seq})


async def latest_media():
    return await db.media.find_one({}, sort=[("seq", -1)])


async def oldest_media():
    return await db.media.find_one({}, sort=[("seq", 1)])


async def media_count():
    return await db.media.count_documents({})


async def set_source_chat(chat_id: int):
    await update_settings({"source_chat_id": chat_id})
    await db.chats.update_one({"chat_id": chat_id}, {"$set": {"delivery_enabled": False}})


async def get_source_chat_id():
    s = await get_settings()
    return s.get("source_chat_id") if s else None


async def clear_source_chat():
    await update_settings({"source_chat_id": None})
