
from datetime import datetime, timezone
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
            "delivery_enabled": True,
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

async def update_settings(data):
    data = dict(data)
    data["updated_at"] = now()
    await db.settings.update_one({"_id": "settings"}, {"$set": data}, upsert=True)

async def _oldest_seq():
    doc = await db.media.find_one({}, sort=[("seq", 1)])
    return doc["seq"] if doc else None

async def add_user(user_id):
    oldest = await _oldest_seq()
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "active": True,
            "updated_at": now(),
            "next_seq": oldest,
            "next_send_at": now(),
        }},
        upsert=True,
    )

async def activate_user(user_id):
    user = await db.users.find_one({"user_id": user_id})
    oldest = await _oldest_seq()
    if not user:
        await add_user(user_id)
        return

    cursor = user.get("next_seq")
    if oldest is not None and (cursor is None or cursor < oldest):
        cursor = oldest

    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "active": True,
            "next_seq": cursor,
            "next_send_at": now(),
            "updated_at": now(),
        }},
    )

async def deactivate_user(user_id):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"active": False, "updated_at": now()}},
    )

async def active_users_due(at=None):
    at = at or now()
    return db.users.find({
        "active": True,
        "next_send_at": {"$lte": at},
    })

async def update_user_cursor(user_id, next_seq, next_send_at):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "next_seq": next_seq,
            "next_send_at": next_send_at,
            "updated_at": now(),
        }},
    )

async def upsert_chat(chat_id, chat_type, title="", active=True):
    existing = await db.chats.find_one({"chat_id": chat_id})
    next_seq = await _oldest_seq() if not existing else None
    await db.chats.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "title": title or "",
                "active": active,
                "updated_at": now(),
            },
            "$setOnInsert": {
                "delivery_enabled": True,
                "next_seq": next_seq,
                "next_send_at": now(),
            },
        },
        upsert=True,
    )

async def set_chat_delivery(chat_id, enabled):
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "delivery_enabled": bool(enabled),
            "next_send_at": now(),
            "updated_at": now(),
        }},
    )

async def active_chats_due(at=None):
    at = at or now()
    return db.chats.find({
        "active": True,
        "delivery_enabled": True,
        "next_send_at": {"$lte": at},
    })

async def update_chat_cursor(chat_id, next_seq, next_send_at):
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "next_seq": next_seq,
            "next_send_at": next_send_at,
            "updated_at": now(),
        }},
    )

async def list_chats():
    return await db.chats.find({"active": True}).sort("updated_at", -1).to_list(length=100)

async def save_media(kind, file_id):
    # Avoid accidental duplicate storage of the same Telegram file_id.
    if await db.media.find_one({"file_id": file_id}):
        return None

    last = await db.media.find_one({}, sort=[("seq", -1)])
    seq = (last["seq"] + 1) if last else 1

    await db.media.insert_one({
        "seq": seq,
        "kind": kind,
        "file_id": file_id,
        "received_at": now(),
    })

    settings = await get_settings()
    limit = max(1, int(settings.get("storage_limit", DEFAULT_STORAGE_LIMIT)))

    docs = await db.media.find(
        {}, {"_id": 1, "seq": 1}
    ).sort("seq", -1).to_list(length=limit + 1000)

    if len(docs) > limit:
        remove_ids = [x["_id"] for x in docs[limit:]]
        await db.media.delete_many({"_id": {"$in": remove_ids}})

    oldest = await db.media.find_one({}, sort=[("seq", 1)])
    if oldest:
        await db.users.update_many(
            {"next_seq": {"$lt": oldest["seq"]}},
            {"$set": {"next_seq": oldest["seq"]}},
        )
        await db.chats.update_many(
            {"next_seq": {"$lt": oldest["seq"]}},
            {"$set": {"next_seq": oldest["seq"]}},
        )

    return seq

async def trim_to_limit(limit):
    limit = max(1, int(limit))
    docs = await db.media.find(
        {}, {"_id": 1, "seq": 1}
    ).sort("seq", -1).to_list(length=limit + 1000)
    if len(docs) > limit:
        await db.media.delete_many({
            "_id": {"$in": [d["_id"] for d in docs[limit:]]}
        })

    oldest = await db.media.find_one({}, sort=[("seq", 1)])
    if oldest:
        await db.users.update_many(
            {"next_seq": {"$lt": oldest["seq"]}},
            {"$set": {"next_seq": oldest["seq"]}},
        )
        await db.chats.update_many(
            {"next_seq": {"$lt": oldest["seq"]}},
            {"$set": {"next_seq": oldest["seq"]}},
        )

async def get_media_by_seq(seq):
    return await db.media.find_one({"seq": seq})

async def latest_media():
    return await db.media.find_one({}, sort=[("seq", -1)])

async def oldest_media():
    return await db.media.find_one({}, sort=[("seq", 1)])

async def media_count():
    return await db.media.count_documents({})

async def set_source_chat(chat_id):
    await update_settings({"source_chat_id": chat_id})

async def get_source_chat_id():
    s = await get_settings()
    return s.get("source_chat_id") if s else None

async def clear_source_chat():
    await update_settings({"source_chat_id": None})

async def set_delivery_enabled(enabled):
    await update_settings({"delivery_enabled": bool(enabled)})

async def get_delivery_enabled():
    s = await get_settings()
    return bool(s.get("delivery_enabled", True)) if s else True
