
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_keyboard(is_owner=False):
    rows = [
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("✏️ Caption & Buttons", callback_data="editor")],
        [InlineKeyboardButton("📦 Media Library", callback_data="library")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("📊 Status", callback_data="status")])
    return InlineKeyboardMarkup(rows)

def settings_keyboard(settings):
    protect = "ON" if settings.get("protect_content") else "OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🛡 Protection: {protect}", callback_data="toggle_protect")],
        [InlineKeyboardButton(
            f"📦 Storage: {settings.get('storage_limit', 20)}",
            callback_data="set_storage"
        )],
        [InlineKeyboardButton(
            f"⏱ Interval: {settings.get('interval_minutes', 60)} min",
            callback_data="set_interval"
        )],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])

def editor_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Set Caption", callback_data="set_caption")],
        [InlineKeyboardButton("🔘 Add Button", callback_data="add_button")],
        [InlineKeyboardButton("🗑 Clear Buttons", callback_data="clear_buttons")],
        [InlineKeyboardButton("👀 Preview", callback_data="preview")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])
