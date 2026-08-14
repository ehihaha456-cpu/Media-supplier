
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters, ChatMemberHandler
)
from .config import BOT_TOKEN, OWNER_IDS
from . import db
from .keyboards import main_keyboard, settings_keyboard, editor_keyboard

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

WAIT_CAPTION, WAIT_BUTTON = range(2)

def owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        await db.add_user(update.effective_user.id)
    await update.message.reply_text(
        "Auto Media Delivery Bot is active.\n\n"
        "You will receive the latest media according to the configured schedule.",
        reply_markup=main_keyboard(owner(update.effective_user.id))
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update.effective_user.id):
        return
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=main_keyboard(True))

async def settings_page(update, context):
    s = await db.get_settings()
    await update.callback_query.edit_message_text("⚙️ Media Settings", reply_markup=settings_keyboard(s))

async def editor_page(update, context):
    await update.callback_query.edit_message_text("✏️ Caption & Button Editor", reply_markup=editor_keyboard())

async def toggle_protect(update, context):
    s = await db.get_settings()
    await db.update_settings({"protect_content": not bool(s.get("protect_content"))})
    await settings_page(update, context)

async def ask_caption(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Send the new caption as your next message.\nUse /cancel to cancel.")
    return WAIT_CAPTION

async def save_caption(update, context):
    if not owner(update.effective_user.id):
        return ConversationHandler.END
    await db.update_settings({"caption": update.message.text or ""})
    await update.message.reply_text("✅ Caption saved.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def ask_button(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "Send the button in this format:\n"
        "Button Text | https://example.com\n\n"
        "Use /cancel to cancel."
    )
    return WAIT_BUTTON

async def save_button(update, context):
    if not owner(update.effective_user.id):
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    if "|" not in text:
        await update.message.reply_text("❌ Invalid format. Use: Button Text | https://example.com")
        return WAIT_BUTTON
    label, url = [x.strip() for x in text.split("|", 1)]
    if not label or not url.startswith(("http://", "https://", "tg://")):
        await update.message.reply_text("❌ Invalid button. Use a valid URL.")
        return WAIT_BUTTON
    s = await db.get_settings()
    buttons = list(s.get("buttons", []))
    buttons.append({"text": label[:64], "url": url[:512]})
    await db.update_settings({"buttons": buttons})
    await update.message.reply_text("✅ Button added.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("Cancelled.", reply_markup=main_keyboard(owner(update.effective_user.id)))
    return ConversationHandler.END

async def clear_buttons(update, context):
    await db.update_settings({"buttons": []})
    await update.callback_query.answer("Buttons cleared")
    await editor_page(update, context)

async def preview(update, context):
    q = update.callback_query
    await q.answer()
    media = await db.latest_media()
    if not media:
        await q.message.reply_text("No media available for preview.")
        return
    s = await db.get_settings()
    markup = None
    if s.get("buttons"):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(x["text"], url=x["url"])]
            for x in s["buttons"]
        ])
    m = media[0]
    caption = s.get("caption", "")
    kwargs = {"caption": caption, "reply_markup": markup, "protect_content": bool(s.get("protect_content"))}
    if m["kind"] == "video":
        await q.message.reply_video(m["file_id"], **kwargs)
    elif m["kind"] == "photo":
        await q.message.reply_photo(m["file_id"], **kwargs)
    elif m["kind"] == "document":
        await q.message.reply_document(m["file_id"], **kwargs)

async def library(update, context):
    q = update.callback_query
    await q.answer()
    media = await db.latest_media()
    if not media:
        text = "📦 Media Library\n\nNo media stored."
    else:
        text = f"📦 Media Library\n\nLatest media: {media[0]['kind']}\nStored limit is controlled from Settings."
    await q.edit_message_text(text, reply_markup=main_keyboard(owner(q.from_user.id)))

async def status(update, context):
    q = update.callback_query
    await q.answer()
    s = await db.get_settings()
    media_count = await db.db.media.count_documents({}) if db.db is not None else 0
    text = (
        "📊 Status\n\n"
        f"Stored media: {media_count}\n"
        f"Storage limit: {s.get('storage_limit')}\n"
        f"Interval: {s.get('interval_minutes')} minutes\n"
        f"Protection: {'ON' if s.get('protect_content') else 'OFF'}"
    )
    await q.edit_message_text(text, reply_markup=main_keyboard(True))

async def set_storage(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Send storage limit as a number, e.g. 10 or 20.\nUse /cancel to cancel.")
    context.user_data["setting"] = "storage"
    return WAIT_CAPTION

async def set_interval(update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Send interval in minutes, e.g. 60.\nUse /cancel to cancel.")
    context.user_data["setting"] = "interval"
    return WAIT_CAPTION

async def save_setting_value(update, context):
    if not owner(update.effective_user.id):
        return ConversationHandler.END
    value = (update.message.text or "").strip()
    setting = context.user_data.pop("setting", None)
    if setting not in ("storage", "interval"):
        return await save_caption(update, context)
    try:
        n = int(value)
        if n < 1 or n > 100000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Enter a valid positive number.")
        return WAIT_CAPTION
    if setting == "storage":
        await db.update_settings({"storage_limit": n})
        await update.message.reply_text(f"✅ Storage limit set to {n}.", reply_markup=main_keyboard(True))
    else:
        await db.update_settings({"interval_minutes": n})
        await update.message.reply_text(f"✅ Auto-send interval set to {n} minutes.", reply_markup=main_keyboard(True))
    return ConversationHandler.END

async def source_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only configured source chat is accepted.
    source_id = context.application.bot_data.get("source_chat_id")
    if source_id is None or update.effective_chat.id != source_id:
        return
    msg = update.effective_message
    doc = None
    if msg.video:
        doc = {"kind": "video", "file_id": msg.video.file_id, "source_message_id": msg.message_id}
    elif msg.photo:
        doc = {"kind": "photo", "file_id": msg.photo[-1].file_id, "source_message_id": msg.message_id}
    elif msg.document:
        doc = {"kind": "document", "file_id": msg.document.file_id, "source_message_id": msg.message_id}
    if doc:
        await db.save_media(doc)
        log.info("Saved source media: %s", doc["kind"])

async def chat_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    if not cm:
        return
    chat = cm.chat
    new_status = cm.new_chat_member.status
    active = new_status in ("member", "administrator")
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
        await db.upsert_chat(chat.id, chat.type, chat.title or "", active=active)

async def deliver_job(context: ContextTypes.DEFAULT_TYPE):
    s = await db.get_settings()
    media = await db.latest_media()
    if not media:
        return
    m = media[0]
    markup = None
    if s.get("buttons"):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(x["text"], url=x["url"])]
            for x in s["buttons"]
        ])
    kwargs = {
        "caption": s.get("caption", ""),
        "reply_markup": markup,
        "protect_content": bool(s.get("protect_content")),
    }

    # Direct /start users
    async for u in db.active_users():
        try:
            if m["kind"] == "video":
                await context.bot.send_video(u["user_id"], m["file_id"], **kwargs)
            elif m["kind"] == "photo":
                await context.bot.send_photo(u["user_id"], m["file_id"], **kwargs)
            elif m["kind"] == "document":
                await context.bot.send_document(u["user_id"], m["file_id"], **kwargs)
        except Exception as e:
            log.warning("User delivery failed %s: %s", u["user_id"], e)

    # Groups/channels where the bot was added
    async for c in db.active_chats():
        try:
            if m["kind"] == "video":
                await context.bot.send_video(c["chat_id"], m["file_id"], **kwargs)
            elif m["kind"] == "photo":
                await context.bot.send_photo(c["chat_id"], m["file_id"], **kwargs)
            elif m["kind"] == "document":
                await context.bot.send_document(c["chat_id"], m["file_id"], **kwargs)
        except Exception as e:
            log.warning("Chat delivery failed %s: %s", c["chat_id"], e)
            if "chat not found" in str(e).lower() or "bot was kicked" in str(e).lower():
                await db.upsert_chat(c["chat_id"], c["chat_type"], c.get("title", ""), active=False)

async def reschedule_job(application):
    s = await db.get_settings()
    for job in application.job_queue.get_jobs_by_name("media_delivery"):
        job.schedule_removal()
    application.job_queue.run_repeating(
        deliver_job,
        interval=max(60, int(s.get("interval_minutes", 60)) * 60),
        first=10,
        name="media_delivery",
    )

async def on_post_init(application):
    await db.init_db()
    await reschedule_job(application)

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required")
    app = Application.builder().token(BOT_TOKEN).post_init(on_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_caption, pattern="^set_caption$"),
            CallbackQueryHandler(ask_button, pattern="^add_button$"),
            CallbackQueryHandler(set_storage, pattern="^set_storage$"),
            CallbackQueryHandler(set_interval, pattern="^set_interval$"),
        ],
        states={
            WAIT_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_setting_value)],
            WAIT_BUTTON: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_button)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(settings_page, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(editor_page, pattern="^editor$"))
    app.add_handler(CallbackQueryHandler(toggle_protect, pattern="^toggle_protect$"))
    app.add_handler(CallbackQueryHandler(clear_buttons, pattern="^clear_buttons$"))
    app.add_handler(CallbackQueryHandler(preview, pattern="^preview$"))
    app.add_handler(CallbackQueryHandler(library, pattern="^library$"))
    app.add_handler(CallbackQueryHandler(status, pattern="^status$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.edit_message_text("⚙️ Admin Panel", reply_markup=main_keyboard(owner(u.callback_query.from_user.id))), pattern="^home$"))

    app.add_handler(ChatMemberHandler(chat_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, source_media))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
