
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
    # storage_limit is a per-recipient visible-message limit, not a source-library limit.
    # The source library must retain every captured media item.
    await db.media.create_index("seq", unique=True)
    await db.media.create_index("file_id", unique=True)
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
    docs = await db.media.find({}, {"seq": 1, "_id": 0}).sort("seq", 1).to_list(length=5000)
    return [int(x["seq"]) for x in docs]

async def _prepare_recipient(collection, field, value):
    available = await _available_seqs()
    if not available:
        return None

    available_set = set(available)
    doc = await collection.find_one({field: value})
    old_queue = [int(x) for x in (doc.get("delivery_queue", []) if doc else [])]
    old_pos = int(doc.get("queue_pos", 0)) if doc else 0
    old_pos = max(0, min(old_pos, len(old_queue)))

    # Keep the current cycle intact. If a source media disappeared manually,
    # remove it and repair the cursor.
    removed_before = sum(1 for x in old_queue[:old_pos] if x not in available_set)
    queue = [x for x in old_queue if x in available_set]
    pos = max(0, old_pos - removed_before)
    pos = min(pos, len(queue))

    # Once every media in the source library has been delivered for this
    # recipient, create a brand-new random permutation and start again.
    if not queue or pos >= len(queue):
        queue = available[:]
        random.shuffle(queue)
        pos = 0
    else:
        # Media uploaded during a running cycle is added once to that cycle.
        used = set(queue)
        remaining = queue[pos:]
        for seq in available:
            if seq not in used:
                remaining.insert(random.randint(0, len(remaining)), seq)
                used.add(seq)
        queue = queue[:pos] + remaining

    await collection.update_one(
        {field: value},
        {"$set": {
            "delivery_queue": queue,
            "queue_pos": pos,
            "cycle_size": len(queue),
            "updated_at": now(),
        }},
        upsert=True,
    )
    return queue, pos


async def _peek_for(collection, field, value):
    prepared = await _prepare_recipient(collection, field, value)
    if not prepared:
        return None
    queue, pos = prepared
    if pos >= len(queue):
        return None
    return await db.media.find_one({"seq": queue[pos]})

async def _advance_for(collection, field, value, seq):
    doc = await collection.find_one({field: value})
    if not doc:
        return
    queue = [int(x) for x in doc.get("delivery_queue", [])]
    pos = int(doc.get("queue_pos", 0))
    if pos < len(queue) and int(queue[pos]) == int(seq):
        await collection.update_one(
            {field: value},
            {"$set": {"queue_pos": pos + 1, "updated_at": now()}},
        )

async def push_sent_message_id(collection, field, value, message_id, limit):
    doc = await collection.find_one({field: value}, {"sent_message_ids": 1})
    ids = list(doc.get("sent_message_ids", [])) if doc else []
    ids.append(int(message_id))
    old_ids = ids[:-limit] if len(ids) > limit else []
    ids = ids[-limit:]
    await collection.update_one(
        {field: value},
        {"$set": {"sent_message_ids": ids, "updated_at": now()}},
        upsert=True,
    )
    return old_ids

async def push_user_sent_message_id(user_id, message_id, limit):
    return await push_sent_message_id(db.users, "user_id", user_id, message_id, limit)

async def push_chat_sent_message_id(chat_id, message_id, limit):
    return await push_sent_message_id(db.chats, "chat_id", chat_id, message_id, limit)

async def add_user(user_id):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "active": True, "updated_at": now()},
         "$setOnInsert": {"delivery_queue": [], "queue_pos": 0, "next_send_at": now()}},
        upsert=True,
    )

async def activate_user(user_id):
    await add_user(user_id)
    await db.users.update_one({"user_id": user_id},
        {"$set": {"active": True, "next_send_at": now(), "updated_at": now()}})

async def deactivate_user(user_id):
    await db.users.update_one({"user_id": user_id},
        {"$set": {"active": False, "updated_at": now()}})

async def active_users_due(at=None):
    at = at or now()
    return db.users.find({"active": True, "next_send_at": {"$lte": at}})

async def update_user_schedule(user_id, next_send_at):
    await db.users.update_one({"user_id": user_id},
        {"$set": {"next_send_at": next_send_at, "updated_at": now()}})

async def next_user_media(user_id):
    return await _peek_for(db.users, "user_id", user_id)

async def advance_user_media(user_id, seq):
    await _advance_for(db.users, "user_id", user_id, seq)

async def update_user_cursor(user_id, next_seq, next_send_at):
    # Compatibility for older code paths.
    await db.update_user_schedule(user_id, next_send_at)

async def upsert_chat(chat_id, chat_type, title="", active=True):
    await db.chats.update_one(
        {"chat_id": chat_id},
        {"$set": {"chat_id": chat_id, "chat_type": chat_type,
                  "title": title or "", "active": active, "updated_at": now()},
         "$setOnInsert": {"delivery_enabled": True, "delivery_queue": [],
                          "queue_pos": 0, "next_send_at": now()}},
        upsert=True)

async def set_chat_delivery(chat_id, enabled):
    await db.chats.update_one({"chat_id": chat_id},
        {"$set": {"delivery_enabled": bool(enabled), "next_send_at": now(), "updated_at": now()}})

async def active_chats_due(at=None):
    at = at or now()
    return db.chats.find({"active": True, "delivery_enabled": True,
                          "next_send_at": {"$lte": at}})

async def update_chat_schedule(chat_id, next_send_at):
    await db.chats.update_one({"chat_id": chat_id},
        {"$set": {"next_send_at": next_send_at, "updated_at": now()}})

async def next_chat_media(chat_id):
    return await _peek_for(db.chats, "chat_id", chat_id)

async def advance_chat_media(chat_id, seq):
    await _advance_for(db.chats, "chat_id", chat_id, seq)

async def update_chat_cursor(chat_id, next_seq, next_send_at):
    await db.update_chat_schedule(chat_id, next_send_at)

async def list_chats():
    return await db.chats.find({"active": True}).sort("updated_at", -1).to_list(length=100)

async def save_media(kind, file_id):
    # Keep ALL source media. The admin limit applies only to bot-sent
    # messages visible in each recipient chat.
    existing = await db.media.find_one({"file_id": file_id})
    if existing:
        return existing.get("seq")

    last = await db.media.find_one({}, sort=[("seq", -1)])
    seq = (int(last["seq"]) + 1) if last else 1
    await db.media.insert_one({
        "seq": seq,
        "kind": kind,
        "file_id": file_id,
        "received_at": now(),
    })
    return seq


async def trim_to_limit(limit):
    limit = max(1, int(limit))
    docs = await db.media.find({}, {"_id": 1, "seq": 1}).sort("seq", -1).to_list(length=limit + 5000)
    if len(docs) > limit:
        await db.media.delete_many({"_id": {"$in": [d["_id"] for d in docs[limit:]]}})

async def get_media_by_seq(seq):
    return await db.media.find_one({"seq": int(seq)})

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
