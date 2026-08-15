from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_keyboard(settings=None):
    enabled = True if not settings else bool(settings.get("delivery_enabled", True))
    state = "ON" if enabled else "OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Auto Delivery: {state}", callback_data="toggle_delivery")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"), InlineKeyboardButton("✏️ Editor", callback_data="editor")],
        [InlineKeyboardButton("👥 Users", callback_data="users"), InlineKeyboardButton("💬 Groups & Channels", callback_data="chats")],
        [InlineKeyboardButton("📦 Media Library", callback_data="library"), InlineKeyboardButton("📊 Status", callback_data="status")],
        [InlineKeyboardButton("🧪 Send Test", callback_data="test_send")],
    ])


def settings_keyboard(s):
    protect = "ON" if s.get("protect_content") else "OFF"
    source = "Set" if s.get("source_chat_id") else "Not set"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🛡 Protection: {protect}", callback_data="toggle_protect")],
        [InlineKeyboardButton(f"📦 Storage limit: {s.get('storage_limit')}", callback_data="set_storage")],
        [InlineKeyboardButton(f"⏱ Send interval: {s.get('interval_minutes')} min", callback_data="set_interval")],
        [InlineKeyboardButton(f"🎯 Source group: {source}", callback_data="source_menu")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])


def editor_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set Caption", callback_data="set_caption")],
        [InlineKeyboardButton("🧹 Clear Caption", callback_data="clear_caption")],
        [InlineKeyboardButton("🔘 Add Button", callback_data="add_button")],
        [InlineKeyboardButton("🗑 Manage Buttons", callback_data="manage_buttons")],
        [InlineKeyboardButton("👀 Preview Latest", callback_data="preview")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])


def source_keyboard(chats):
    rows = []
    for c in chats[:20]:
        title = (c.get("title") or str(c["chat_id"]))[:28]
        icon = "📢" if c.get("chat_type") == "channel" else "👥"
        rows.append([InlineKeyboardButton(f"{icon} {title}", callback_data=f"set_source:{c['chat_id']}")])
    rows.append([InlineKeyboardButton("➕ Set from group command", callback_data="source_help")])
    rows.append([InlineKeyboardButton("❌ Clear source", callback_data="clear_source")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def chat_keyboard(chats):
    rows = []
    for c in chats[:30]:
        enabled = c.get("delivery_enabled", True)
        icon = "📢" if c.get("chat_type") == "channel" else "👥"
        state = "ON" if enabled else "OFF"
        title = (c.get("title") or str(c["chat_id"]))[:22]
        rows.append([InlineKeyboardButton(f"{icon} {title} · {state}", callback_data=f"toggle_chat:{c['chat_id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def button_manage_keyboard(buttons):
    rows = []
    for i, b in enumerate(buttons):
        rows.append([InlineKeyboardButton(f"🗑 {b['text'][:35]}", callback_data=f"delete_button:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="editor")])
    return InlineKeyboardMarkup(rows)
