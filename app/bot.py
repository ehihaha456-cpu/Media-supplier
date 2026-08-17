import asyncio
import logging
from datetime import timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, ContextTypes, ConversationHandler, filters
from . import db
from .config import BOT_TOKEN, OWNER_IDS
from .keyboards import main_keyboard, settings_keyboard, editor_keyboard, source_keyboard, chat_keyboard, button_manage_keyboard

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

WAIT_TEXT, WAIT_BUTTON = range(2)

# Prevent /start and the background delivery loop from claiming the same media concurrently.
_delivery_locks = {}
def _delivery_lock(key):
    if key not in _delivery_locks:
        _delivery_locks[key] = asyncio.Lock()
    return _delivery_locks[key]


def is_owner(uid):
    return uid in OWNER_IDS


def protected_markup(settings):
    buttons = settings.get("buttons", [])
    if not buttons:
        return None
    if buttons and isinstance(buttons[0], list):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(b["text"], url=b["url"]) for b in row]
            for row in buttons
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(b["text"], url=b["url"])]
        for b in buttons
    ])


async def send_media(bot, chat_id, media, settings):
    kwargs = {
        "caption": settings.get("caption", "")[:1024],
        "reply_markup": protected_markup(settings),
        "protect_content": bool(settings.get("protect_content", True)),
    }
    if media["kind"] == "video":
        return await bot.send_video(chat_id, media["file_id"], **kwargs)
    if media["kind"] == "photo":
        return await bot.send_photo(chat_id, media["file_id"], **kwargs)
    if media["kind"] == "document":
        return await bot.send_document(chat_id, media["file_id"], **kwargs)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_message:
        return
    uid = update.effective_user.id

    if is_owner(uid):
        settings = await db.get_settings()
        await update.effective_message.reply_text(
            "🛠 Admin Panel\n\nOwner account is excluded from automatic media delivery.",
            reply_markup=main_keyboard(settings),
        )
        return

    await db.activate_user(uid)
    settings = await db.get_settings()
    await update.effective_message.reply_text(
        "👋 Welcome!\n\nYour automatic media delivery is active."
    )

    if not bool(settings.get("delivery_enabled", True)):
        return

    async with _delivery_lock(("user", uid)):
        media = await db.next_user_media(uid)
        if not media:
            return
        try:
            await deliver_one(context.bot, uid, media, settings, target_kind="user")
            await db.advance_user_media(uid, media["seq"])
            interval = max(1, int(settings.get("interval_minutes", 60)))
            await db.update_user_schedule(uid, db.now() + timedelta(minutes=interval))
        except Exception:
            log.exception("Initial media delivery failed for user %s", uid)


async def stop(update, context):
    if update.effective_user:
        await db.deactivate_user(update.effective_user.id)
        await update.effective_message.reply_text("⏹ Automatic media delivery stopped. Use /start to enable it again.")



async def diag(update, context):
    if not is_owner(update.effective_user.id):
        return
    try:
        s = await db.get_settings()
        media = await db.media_count()
        source = s.get("source_chat_id") if s else None
        await update.effective_message.reply_text(
            "🔧 Diagnostics\n\n"
            f"MongoDB: connected\n"
            f"Stored media: {media}\n"
            f"Source chat: {source or 'Not set'}\n"
            f"Interval: {s.get('interval_minutes') if s else '-'} min\n"
            f"Protection: {'ON' if s and s.get('protect_content') else 'OFF'}"
        )
    except Exception as e:
        log.exception("Diagnostics failed")
        await update.effective_message.reply_text(f"❌ Diagnostics error: {e}")

async def admin(update, context):
    if not is_owner(update.effective_user.id):
        return
    s = await db.get_settings()
    await update.effective_message.reply_text("🛠 Admin Panel", reply_markup=main_keyboard(s))


async def toggle_delivery(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    new = not bool(s.get("delivery_enabled", True))
    await db.set_delivery_enabled(new)
    await q.answer("Auto delivery " + ("ON" if new else "OFF"))
    s = await db.get_settings()
    await q.edit_message_text("🛠 Admin Panel", reply_markup=main_keyboard(s))


async def test_send(update, context):
    q = update.callback_query
    await q.answer()
    media = await db.latest_media()
    if not media:
        await q.answer("No media available", show_alert=True)
        return
    s = await db.get_settings()
    try:
        await send_media(context.bot, q.from_user.id, media, s)
        await q.answer("Test media sent")
    except Exception as e:
        await q.answer("Send failed", show_alert=True)
        log.exception("Test send failed: %s", e)


async def settings_page(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    await q.edit_message_text("⚙️ Settings", reply_markup=settings_keyboard(s))


async def editor_page(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    caption = s.get("caption") or "(empty)"
    buttons = s.get("buttons", [])
    text = f"✏️ Caption & Buttons\n\nCaption:\n{caption[:700]}\n\nButtons: {len(buttons)}"
    await q.edit_message_text(text, reply_markup=editor_keyboard())


async def home(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    await q.edit_message_text("🛠 Admin Panel", reply_markup=main_keyboard(s))


async def toggle_protect(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    await db.update_settings({"protect_content": not bool(s.get("protect_content", True))})
    await q.answer("Protection updated")
    await settings_page(q, context)


async def clear_caption(update, context):
    q = update.callback_query
    await q.answer()
    await db.update_settings({"caption": ""})
    await q.answer("Caption cleared")
    await editor_page(q, context)


async def clear_buttons(update, context):
    q = update.callback_query
    await q.answer()
    await db.update_settings({"buttons": []})
    await q.answer("Buttons cleared")
    await editor_page(q, context)


async def ask_caption(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["editor_action"] = "caption"
    await q.edit_message_text("Send the new caption now.\n\nUse /cancel to cancel.")
    return WAIT_TEXT


async def ask_storage(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["editor_action"] = "storage"
    await q.edit_message_text("Send the maximum number of bot media messages to keep visible in each user/group/channel chat (example: 10 or 20).\n\nThe source Media Library keeps ALL source media.\n\nUse /cancel to cancel.")
    return WAIT_TEXT


async def ask_interval(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["editor_action"] = "interval"
    await q.edit_message_text("Send the interval in minutes (example: 60). Minimum 1 minute.\n\nUse /cancel to cancel.")
    return WAIT_TEXT


async def ask_button(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["editor_action"] = "button"
    await q.edit_message_text("Send button as:\nButton Text | https://example.com\n\nUse /cancel to cancel.")
    return WAIT_BUTTON


async def save_text(update, context):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    action = context.user_data.pop("editor_action", None)
    text = (update.effective_message.text or "").strip()
    if action == "caption":
        if len(text) > 1024:
            await update.effective_message.reply_text("Caption is too long. Telegram media captions support up to 1024 characters.")
            return WAIT_TEXT
        await db.update_settings({"caption": text})
        await update.effective_message.reply_text("✅ Caption saved.", reply_markup=main_keyboard())
    elif action == "storage":
        try:
            n = int(text)
            if not 1 <= n <= 1000:
                raise ValueError
        except ValueError:
            await update.effective_message.reply_text("❌ Enter a number from 1 to 1000.")
            context.user_data["editor_action"] = "storage"
            return WAIT_TEXT
        await db.update_settings({"storage_limit": n})
        await update.effective_message.reply_text(
            f"✅ Chat media limit set to {n}.\n\n"
            "This only controls how many bot-sent media messages remain visible "
            "in each recipient chat. The source Media Library is not deleted.",
            reply_markup=main_keyboard(),
        )
    elif action == "interval":
        try:
            n = int(text)
            if not 1 <= n <= 10080:
                raise ValueError
        except ValueError:
            await update.effective_message.reply_text("❌ Enter a number from 1 to 10080 minutes.")
            context.user_data["editor_action"] = "interval"
            return WAIT_TEXT
        await db.update_settings({"interval_minutes": n})
        await update.effective_message.reply_text(f"✅ Send interval set to {n} minutes.", reply_markup=main_keyboard())
    return ConversationHandler.END


async def save_button(update, context):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    raw = (update.effective_message.text or "").strip()
    if not raw:
        await update.effective_message.reply_text("❌ Button input is empty.")
        return WAIT_BUTTON

    rows = []
    total = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        row = []
        for item in line.split("||"):
            item = item.strip()
            if "|" not in item:
                await update.effective_message.reply_text(
                    "❌ Format error.\n\n"
                    "Button Text | https://example.com\n\n"
                    "Same row:\n"
                    "Button 1 | URL1 || Button 2 | URL2"
                )
                return WAIT_BUTTON

            label, url = [x.strip() for x in item.split("|", 1)]
            if (
                not label or len(label) > 64 or
                not url.startswith(("https://", "http://", "tg://"))
            ):
                await update.effective_message.reply_text("❌ Invalid button text or URL.")
                return WAIT_BUTTON

            row.append({"text": label, "url": url})
            total += 1
            if total > 20:
                await update.effective_message.reply_text("❌ Maximum 20 buttons allowed.")
                return WAIT_BUTTON

        rows.append(row)

    if not rows:
        await update.effective_message.reply_text("❌ No buttons found.")
        return WAIT_BUTTON

    await db.update_settings({"buttons": rows})
    await update.effective_message.reply_text(
        f"✅ {total} button(s) saved in {len(rows)} row(s).",
        reply_markup=main_keyboard(await db.get_settings()),
    )
    return ConversationHandler.END

async def cancel(update, context):
    context.user_data.pop("editor_action", None)
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_keyboard() if is_owner(update.effective_user.id) else None)
    return ConversationHandler.END


async def manage_buttons(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    buttons = s.get("buttons", [])
    if not buttons:
        await q.answer("No buttons")
        await editor_page(q, context)
        return
    await q.edit_message_text("🗑 Tap a button to remove it:", reply_markup=button_manage_keyboard(buttons))


async def delete_button(update, context):
    q = update.callback_query
    await q.answer()
    try:
        idx = int(q.data.split(":", 1)[1])
    except Exception:
        await q.answer("Invalid")
        return
    s = await db.get_settings()
    buttons = list(s.get("buttons", []))
    if 0 <= idx < len(buttons):
        removed = buttons.pop(idx)
        await db.update_settings({"buttons": buttons})
        await q.answer(f"Removed: {removed['text'][:30]}")
    await manage_buttons(q, context)


async def preview(update, context):
    q = update.callback_query
    await q.answer()
    media = await db.latest_media()
    if not media:
        await q.answer("No media available yet", show_alert=True)
        return
    s = await db.get_settings()
    await q.answer()
    await send_media(context.bot, q.message.chat_id, media, s)


async def library(update, context):
    q = update.callback_query
    await q.answer()
    count = await db.media_count()
    oldest = await db.oldest_media()
    latest = await db.latest_media()
    s = await db.get_settings()
    limit = int(s.get("storage_limit", 10))
    text = (
        "📦 Media Library\n\n"
        f"Source media: {count}\n"
        f"Chat media limit: {limit}\n\n"
        "The source library keeps all captured media.\n"
    )
    if oldest:
        text += (
            f"Oldest sequence: {oldest['seq']}\n"
            f"Latest sequence: {latest['seq']}"
        )
    else:
        text += "No source media uploaded yet."
    await q.edit_message_text(text, reply_markup=main_keyboard())


async def status(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    users = await db.db.users.count_documents({"active": True})
    chats = await db.db.chats.count_documents({"active": True, "delivery_enabled": True})
    media = await db.media_count()
    source = s.get("source_chat_id") or "Not set"
    text = (
        "📊 Bot Status\n\n"
        f"Active users: {users}\n"
        f"Active delivery chats: {chats}\n"
        f"Source media: {media}\n"
        f"Interval: {s.get('interval_minutes')} min\n"
        f"Protection: {'ON' if s.get('protect_content') else 'OFF'}\n"
        f"Source chat: {source}"
    )
    await q.edit_message_text(text, reply_markup=main_keyboard())


async def users_page(update, context):
    q = update.callback_query
    await q.answer()
    total = await db.db.users.count_documents({})
    active = await db.db.users.count_documents({"active": True})
    await q.edit_message_text(f"👥 Users\n\nTotal users: {total}\nActive delivery: {active}", reply_markup=main_keyboard())


async def chats_page(update, context):
    q = update.callback_query
    await q.answer()
    chats = await db.list_chats()
    if not chats:
        await q.edit_message_text("💬 No groups/channels found yet. Add the bot to a group/channel first.", reply_markup=main_keyboard())
        return
    await q.edit_message_text("💬 Groups & Channels\n\nTap a chat to turn automatic delivery ON/OFF.", reply_markup=chat_keyboard(chats))


async def toggle_chat(update, context):
    q = update.callback_query
    await q.answer()
    chat_id = int(q.data.split(":", 1)[1])
    chat = await db.db.chats.find_one({"chat_id": chat_id})
    if not chat:
        await q.answer("Chat not found")
        return
    new = not chat.get("delivery_enabled", True)
    await db.set_chat_delivery(chat_id, new)
    await q.answer("Delivery " + ("ON" if new else "OFF"))
    await chats_page(q, context)


async def source_menu(update, context):
    q = update.callback_query
    await q.answer()
    chats = await db.list_chats()
    await q.edit_message_text("🎯 Select the source group/channel. Media posted there will be captured automatically.", reply_markup=source_keyboard(chats))


async def set_source(update, context):
    q = update.callback_query
    await q.answer()
    chat_id = int(q.data.split(":", 1)[1])
    await db.set_source_chat(chat_id)
    await q.answer("Source saved")
    await settings_page(q, context)


async def clear_source(update, context):
    q = update.callback_query
    await q.answer()
    await db.clear_source_chat()
    await q.answer("Source cleared")
    await settings_page(q, context)


async def source_help(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Add the bot to your source group, make sure it can see messages, then send /setsource in that group as the owner.\n\nThe bot will capture new videos/photos/documents from that group automatically.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="source_menu")]]))


async def setsource(update, context):
    if not is_owner(update.effective_user.id):
        return
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
        await update.effective_message.reply_text("Use /setsource inside the source group or channel.")
        return
    await db.upsert_chat(update.effective_chat.id, update.effective_chat.type, update.effective_chat.title or "", active=True)
    await db.set_source_chat(update.effective_chat.id)
    await update.effective_message.reply_text("✅ This chat is now the source. New media posted here will be stored automatically.")


async def enable_chat(update, context):
    if not update.effective_user or not is_owner(update.effective_user.id):
        return
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
        await update.effective_message.reply_text("Use /enablechat inside a group or channel.")
        return
    await db.upsert_chat(chat.id, chat.type, chat.title or "", active=True)
    await update.effective_message.reply_text(
        "✅ This group/channel is registered for automatic media delivery."
    )


async def chat_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    if not cm:
        return
    chat = cm.chat
    status = cm.new_chat_member.status
    active = status in ("member", "administrator")
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
        await db.upsert_chat(chat.id, chat.type, chat.title or "", active=active)


async def source_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not msg:
        return

    source_id = await db.get_source_chat_id()
    if source_id is None or chat.id != source_id:
        return

    if msg.video:
        seq = await db.save_media("video", msg.video.file_id)
        if seq:
            log.info("Captured video seq=%s from source %s", seq, chat.id)
    elif msg.photo:
        seq = await db.save_media("photo", msg.photo[-1].file_id)
        if seq:
            log.info("Captured photo seq=%s from source %s", seq, chat.id)
    elif msg.document:
        mime = msg.document.mime_type or ""
        if mime.startswith("video/") or mime.startswith("image/"):
            seq = await db.save_media("document", msg.document.file_id)
            if seq:
                log.info("Captured document seq=%s from source %s", seq, chat.id)


async def deliver_one(bot, target_id, media, settings, target_kind="user"):
    message = await send_media(bot, target_id, media, settings)

    # This limit is for messages visible in THIS recipient chat.
    # The source media library is never trimmed.
    limit = max(1, int(settings.get("storage_limit", 10)))

    if target_kind == "user":
        old_ids = await db.push_user_sent_message_id(
            target_id, message.message_id, limit
        )
    else:
        old_ids = await db.push_chat_sent_message_id(
            target_id, message.message_id, limit
        )

    for old_id in old_ids:
        try:
            await bot.delete_message(chat_id=target_id, message_id=old_id)
        except Exception:
            log.warning(
                "Could not delete old bot media message %s in chat %s",
                old_id, target_id
            )

    return message


async def _deliver_user(application, user, settings, at, interval):
    uid = user["user_id"]
    if is_owner(uid):
        return
    async with _delivery_lock(("user", uid)):
        media = await db.next_user_media(uid)
        if not media:
            await db.update_user_schedule(uid, at + timedelta(minutes=interval))
            return
        try:
            await deliver_one(application.bot, uid, media, settings, target_kind="user")
            await db.advance_user_media(uid, media["seq"])
        finally:
            await db.update_user_schedule(uid, at + timedelta(minutes=interval))


async def _deliver_chat(application, chat, settings, at, interval):
    chat_id = chat["chat_id"]
    async with _delivery_lock(("chat", chat_id)):
        media = await db.next_chat_media(chat_id)
        if not media:
            await db.update_chat_schedule(chat_id, at + timedelta(minutes=interval))
            return
        try:
            await deliver_one(application.bot, chat_id, media, settings, target_kind="chat")
            await db.advance_chat_media(chat_id, media["seq"])
        finally:
            await db.update_chat_schedule(chat_id, at + timedelta(minutes=interval))


async def delivery_loop(application):
    while True:
        try:
            settings = await db.get_settings()
            if not settings or not bool(settings.get("delivery_enabled", True)):
                await asyncio.sleep(5)
                continue

            at = db.now()
            interval = max(1, int(settings.get("interval_minutes", 60)))

            user_cursor = await db.active_users_due(at)
            async for user in user_cursor:
                try:
                    await _deliver_user(application, user, settings, at, interval)
                except Exception:
                    log.exception("User %s delivery failed", user.get("user_id"))

            chat_cursor = await db.active_chats_due(at)
            async for chat in chat_cursor:
                try:
                    await _deliver_chat(application, chat, settings, at, interval)
                except Exception:
                    log.exception("Chat %s delivery failed", chat.get("chat_id"))

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Delivery loop error")
        await asyncio.sleep(5)


async def initialize(application):
    await db.init_db()
    application.bot_data["delivery_task"] = asyncio.create_task(delivery_loop(application))


def build_application():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("diag", diag))
    app.add_handler(CommandHandler("setsource", setsource))
    app.add_handler(CommandHandler("enablechat", enable_chat))

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_caption, pattern="^set_caption$"),
            CallbackQueryHandler(ask_button, pattern="^add_button$"),
            CallbackQueryHandler(ask_storage, pattern="^set_storage$"),
            CallbackQueryHandler(ask_interval, pattern="^set_interval$"),
        ],
        states={
            WAIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_text)],
            WAIT_BUTTON: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_button)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(toggle_delivery, pattern="^toggle_delivery$"))
    app.add_handler(CallbackQueryHandler(test_send, pattern="^test_send$"))
    app.add_handler(CallbackQueryHandler(settings_page, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(editor_page, pattern="^editor$"))
    app.add_handler(CallbackQueryHandler(toggle_protect, pattern="^toggle_protect$"))
    app.add_handler(CallbackQueryHandler(clear_caption, pattern="^clear_caption$"))
    app.add_handler(CallbackQueryHandler(clear_buttons, pattern="^clear_buttons$"))
    app.add_handler(CallbackQueryHandler(manage_buttons, pattern="^manage_buttons$"))
    app.add_handler(CallbackQueryHandler(delete_button, pattern="^delete_button:"))
    app.add_handler(CallbackQueryHandler(preview, pattern="^preview$"))
    app.add_handler(CallbackQueryHandler(library, pattern="^library$"))
    app.add_handler(CallbackQueryHandler(status, pattern="^status$"))
    app.add_handler(CallbackQueryHandler(users_page, pattern="^users$"))
    app.add_handler(CallbackQueryHandler(chats_page, pattern="^chats$"))
    app.add_handler(CallbackQueryHandler(toggle_chat, pattern="^toggle_chat:"))
    app.add_handler(CallbackQueryHandler(source_menu, pattern="^source_menu$"))
    app.add_handler(CallbackQueryHandler(set_source, pattern="^set_source:"))
    app.add_handler(CallbackQueryHandler(clear_source, pattern="^clear_source$"))
    app.add_handler(CallbackQueryHandler(source_help, pattern="^source_help$"))
    app.add_handler(CallbackQueryHandler(home, pattern="^home$"))
    app.add_handler(ChatMemberHandler(chat_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, source_media))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POSTS, source_media))
    return app
