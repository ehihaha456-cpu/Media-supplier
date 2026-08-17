
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from .config import MONGO_URI, MONGO_DB, DEFAULT_STORAGE_LIMIT, DEFAULT_INTERVAL_MINUTES
import random

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

async def _available_seqs():
    docs = await db.media.find({}, {"seq": 1, "_id": 0}).sort("seq", 1).to_list(length=2000)
    return [int(x["seq"]) for x in docs]

async def _next_for(collection, field, value):
    available = await _available_seqs()
    if not available:
        return None

    doc = await collection.find_one({field: value})
    queue = [int(x) for x in (doc.get("delivery_queue", []) if doc else []) if int(x) in set(available)]
    pos = int(doc.get("queue_pos", 0)) if doc else 0
    pos = max(0, min(pos, len(queue)))

    if pos >= len(queue) or not queue:
        queue = available[:]
        random.shuffle(queue)
        pos = 0
    else:
        remaining = queue[pos:]
        used = set(queue)
        missing = [x for x in available if x not in used]
        for seq in missing:
            remaining.insert(random.randint(0, len(remaining)), seq)
        queue = queue[:pos] + remaining

    seq = queue[pos]
    media = await db.media.find_one({"seq": seq})
    if not media:
        return None

    await collection.update_one(
        {field: value},
        {"$set": {
            "delivery_queue": queue,
            "queue_pos": pos + 1,
            "updated_at": now(),
        }},
        upsert=True,
    )
    return media

async def add_user(user_id):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True, "updated_at": now()},
         "$setOnInsert": {"delivery_queue": [], "queue_pos": 0, "next_send_at": now()}},
        upsert=True,
    )

async def activate_user(user_id):
    await add_user(user_id)
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"active": True, "next_send_at": now(), "updated_at": now()}},
    )

async def deactivate_user(user_id):
    await db.users.update_one({"user_id": user_id}, {"$set": {"active": False, "updated_at": now()}})

async def active_users_due(at=None):
    at = at or now()
    return db.users.find({"active": True, "next_send_at": {"$lte": at}})

async def update_user_schedule(user_id, next_send_at):
    await db.users.update_one({"user_id": user_id}, {"$set": {"next_send_at": next_send_at, "updated_at": now()}})

async def next_user_media(user_id):
    return await _next_for(db.users, "user_id", user_id)

async def upsert_chat(chat_id, chat_type, title="", active=True):
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"chat_id": chat_id, "chat_type": chat_type, "title": title or "", "active": active, "updated_at": now()},
         "$setOnInsert": {"delivery_enabled": True, "delivery_queue": [], "queue_pos": 0, "next_send_at": now()}},
        upsert=True,
    )

async def set_chat_delivery(chat_id, enabled):
    await db.chats.update_one({"chat_id": chat_id}, {"$set": {"delivery_enabled": bool(enabled), "next_send_at": now(), "updated_at": now()}})

async def active_chats_due(at=None):
    at = at or now()
    return db.chats.find({"active": True, "delivery_enabled": True, "next_send_at": {"$lte": at}})

async def update_chat_schedule(chat_id, next_send_at):
    await db.chats.update_one({"chat_id": chat_id}, {"$set": {"next_send_at": next_send_at, "updated_at": now()}})

async def next_chat_media(chat_id):
    return await _next_for(db.chats, "chat_id", chat_id)

async def list_chats():
    return await db.chats.find({"active": True}).sort("updated_at", -1).to_list(length=100)

async def save_media(kind, file_id):
    if await db.media.find_one({"file_id": file_id}):
        return None
    last = await db.media.find_one({}, sort=[("seq", -1)])
    seq = (last["seq"] + 1) if last else 1
    await db.media.insert_one({"seq": seq, "kind": kind, "file_id": file_id, "received_at": now()})

    settings = await get_settings()
    limit = max(1, int(settings.get("storage_limit", DEFAULT_STORAGE_LIMIT)))
    docs = await db.media.find({}, {"_id": 1}).sort("seq", -1).to_list(length=limit + 1000)
    if len(docs) > limit:
        await db.media.delete_many({"_id": {"$in": [x["_id"] for x in docs[limit:]]}})
    return seq

async def trim_to_limit(limit):
    limit = max(1, int(limit))
    docs = await db.media.find({}, {"_id": 1}).sort("seq", -1).to_list(length=limit + 1000)
    if len(docs) > limit:
        await db.media.delete_many({"_id": {"$in": [x["_id"] for x in docs[limit:]]}})

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
