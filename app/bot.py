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


def is_owner(uid):
    return uid in OWNER_IDS


def protected_markup(settings):
    buttons = settings.get("buttons", [])
    if not buttons:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["text"], url=b["url"])] for b in buttons])


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
    await db.activate_user(update.effective_user.id)
    s = await db.get_settings()
    await update.effective_message.reply_text(
        "👋 Welcome!\n\nYour automatic media delivery is active.",
        reply_markup=main_keyboard(s) if is_owner(update.effective_user.id) else None,
    )

    oldest = await db.oldest_media()
    if oldest:
        try:
            await send_media(context.bot, update.effective_user.id, oldest, s)
            await db.update_user_cursor(update.effective_user.id, oldest["seq"] + 1, db.now() + timedelta(minutes=int(s.get("interval_minutes", 60))))
        except Exception:
            log.exception("Initial media delivery failed")


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
    s = await db.get_settings()
    new = not bool(s.get("delivery_enabled", True))
    await db.set_delivery_enabled(new)
    await q.answer("Auto delivery " + ("ON" if new else "OFF"))
    s = await db.get_settings()
    await q.edit_message_text("🛠 Admin Panel", reply_markup=main_keyboard(s))


async def test_send(update, context):
    q = update.callback_query
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
    s = await db.get_settings()
    await q.edit_message_text("⚙️ Settings", reply_markup=settings_keyboard(s))


async def editor_page(update, context):
    q = update.callback_query
    s = await db.get_settings()
    caption = s.get("caption") or "(empty)"
    buttons = s.get("buttons", [])
    text = f"✏️ Caption & Buttons\n\nCaption:\n{caption[:700]}\n\nButtons: {len(buttons)}"
    await q.edit_message_text(text, reply_markup=editor_keyboard())


async def home(update, context):
    q = update.callback_query
    s = await db.get_settings()
    await q.edit_message_text("🛠 Admin Panel", reply_markup=main_keyboard(s))


async def toggle_protect(update, context):
    q = update.callback_query
    s = await db.get_settings()
    await db.update_settings({"protect_content": not bool(s.get("protect_content", True))})
    await q.answer("Protection updated")
    await settings_page(q, context)


async def clear_caption(update, context):
    q = update.callback_query
    await db.update_settings({"caption": ""})
    await q.answer("Caption cleared")
    await editor_page(q, context)


async def clear_buttons(update, context):
    q = update.callback_query
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
    await q.edit_message_text("Send the maximum media count (example: 10 or 20).\n\nUse /cancel to cancel.")
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
        # Trigger trimming by re-saving settings and removing excess records.
        docs = await db.db.media.find({}, {"_id": 1, "seq": 1}).sort("seq", -1).to_list(length=n + 1000)
        if len(docs) > n:
            await db.db.media.delete_many({"_id": {"$in": [d["_id"] for d in docs[n:]]}})
        await update.effective_message.reply_text(f"✅ Storage limit set to {n}.", reply_markup=main_keyboard())
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
    text = (update.effective_message.text or "").strip()
    if "|" not in text:
        await update.effective_message.reply_text("❌ Format: Button Text | https://example.com")
        return WAIT_BUTTON
    label, url = [x.strip() for x in text.split("|", 1)]
    if not label or len(label) > 64 or not url.startswith(("https://", "http://", "tg://")):
        await update.effective_message.reply_text("❌ Invalid button text or URL.")
        return WAIT_BUTTON
    s = await db.get_settings()
    buttons = list(s.get("buttons", []))
    if len(buttons) >= 20:
        await update.effective_message.reply_text("❌ Maximum 20 buttons reached.")
        return ConversationHandler.END
    buttons.append({"text": label, "url": url})
    await db.update_settings({"buttons": buttons})
    await update.effective_message.reply_text("✅ Button added.", reply_markup=main_keyboard())
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.pop("editor_action", None)
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_keyboard() if is_owner(update.effective_user.id) else None)
    return ConversationHandler.END


async def manage_buttons(update, context):
    q = update.callback_query
    s = await db.get_settings()
    buttons = s.get("buttons", [])
    if not buttons:
        await q.answer("No buttons")
        await editor_page(q, context)
        return
    await q.edit_message_text("🗑 Tap a button to remove it:", reply_markup=button_manage_keyboard(buttons))


async def delete_button(update, context):
    q = update.callback_query
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
    media = await db.latest_media()
    if not media:
        await q.answer("No media available yet", show_alert=True)
        return
    s = await db.get_settings()
    await q.answer()
    await send_media(context.bot, q.message.chat_id, media, s)


async def library(update, context):
    q = update.callback_query
    count = await db.media_count()
    oldest = await db.oldest_media()
    latest = await db.latest_media()
    s = await db.get_settings()
    text = f"📦 Media Library\n\nStored: {count}/{s.get('storage_limit')}\n"
    if oldest:
        text += f"Oldest sequence: {oldest['seq']}\nLatest sequence: {latest['seq']}"
    else:
        text += "No media uploaded yet."
    await q.edit_message_text(text, reply_markup=main_keyboard())


async def status(update, context):
    q = update.callback_query
    s = await db.get_settings()
    users = await db.db.users.count_documents({"active": True})
    chats = await db.db.chats.count_documents({"active": True, "delivery_enabled": True})
    media = await db.media_count()
    source = s.get("source_chat_id") or "Not set"
    text = (
        "📊 Bot Status\n\n"
        f"Active users: {users}\n"
        f"Active delivery chats: {chats}\n"
        f"Stored media: {media}/{s.get('storage_limit')}\n"
        f"Interval: {s.get('interval_minutes')} min\n"
        f"Protection: {'ON' if s.get('protect_content') else 'OFF'}\n"
        f"Source chat: {source}"
    )
    await q.edit_message_text(text, reply_markup=main_keyboard())


async def users_page(update, context):
    q = update.callback_query
    total = await db.db.users.count_documents({})
    active = await db.db.users.count_documents({"active": True})
    await q.edit_message_text(f"👥 Users\n\nTotal users: {total}\nActive delivery: {active}", reply_markup=main_keyboard())


async def chats_page(update, context):
    q = update.callback_query
    chats = await db.list_chats()
    if not chats:
        await q.edit_message_text("💬 No groups/channels found yet. Add the bot to a group/channel first.", reply_markup=main_keyboard())
        return
    await q.edit_message_text("💬 Groups & Channels\n\nTap a chat to turn automatic delivery ON/OFF.", reply_markup=chat_keyboard(chats))


async def toggle_chat(update, context):
    q = update.callback_query
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
    chats = await db.list_chats()
    await q.edit_message_text("🎯 Select the source group/channel. Media posted there will be captured automatically.", reply_markup=source_keyboard(chats))


async def set_source(update, context):
    q = update.callback_query
    chat_id = int(q.data.split(":", 1)[1])
    await db.set_source_chat(chat_id)
    await q.answer("Source saved")
    await settings_page(q, context)


async def clear_source(update, context):
    q = update.callback_query
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
    if not update.effective_chat or not update.effective_message:
        return
    source_id = await db.get_source_chat_id()
    if source_id is None or update.effective_chat.id != source_id:
        return
    msg = update.effective_message
    if msg.video:
        await db.save_media("video", msg.video.file_id)
        log.info("Captured video from source chat %s", update.effective_chat.id)
    elif msg.photo:
        await db.save_media("photo", msg.photo[-1].file_id)
        log.info("Captured photo from source chat %s", update.effective_chat.id)
    elif msg.document:
        # Store only document media; text files etc. are ignored.
        if msg.document.mime_type and (msg.document.mime_type.startswith("video/") or msg.document.mime_type.startswith("image/")):
            await db.save_media("document", msg.document.file_id)


async def deliver_one(bot, target_type, target_id, cursor, settings):
    oldest = await db.oldest_media()
    if not oldest:
        return None, None
    if cursor is None or cursor < oldest["seq"]:
        cursor = oldest["seq"]
    media = await db.get_media_by_seq(cursor)
    if not media:
        # Cursor may point to a deleted gap; jump to oldest retained media.
        cursor = oldest["seq"]
        media = oldest
    await send_media(bot, target_id, media, settings)
    return media["seq"] + 1, db.now() + timedelta(minutes=int(settings.get("interval_minutes", 60)))


async def delivery_loop(application):
    while True:
        try:
            settings = await db.get_settings()
            if not bool(settings.get("delivery_enabled", True)):
                await asyncio.sleep(10)
                continue
            interval = max(1, int(settings.get("interval_minutes", 60)))
            at = db.now()

            async for user in db.active_users_due(at):
                try:
                    nxt, due = await deliver_one(application.bot, "user", user["user_id"], user.get("next_seq"), settings)
                    if due:
                        await db.update_user_cursor(user["user_id"], nxt, due)
                except Exception as e:
                    log.warning("User %s delivery failed: %s", user.get("user_id"), e)
                    await db.update_user_cursor(user["user_id"], user.get("next_seq"), at + timedelta(minutes=interval))

            async for chat in db.active_chats_due(at):
                try:
                    nxt, due = await deliver_one(application.bot, "chat", chat["chat_id"], chat.get("next_seq"), settings)
                    if due:
                        await db.update_chat_cursor(chat["chat_id"], nxt, due)
                except Exception as e:
                    log.warning("Chat %s delivery failed: %s", chat.get("chat_id"), e)
                    await db.update_chat_cursor(chat["chat_id"], chat.get("next_seq"), at + timedelta(minutes=interval))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Delivery loop error")
        await asyncio.sleep(10)


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
    return app
