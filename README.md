# Auto Media Delivery Bot

Telegram bot that:
- Watches one configured source group for video/photo/document media.
- Keeps only the newest N media items in MongoDB (default 20; configurable from admin settings).
- Sends the newest media on a configurable interval to `/start` users.
- Sends the newest media to groups/channels where the bot is added.
- Supports configurable caption and inline URL buttons.
- Supports Telegram content protection on messages sent by the bot.

## Setup

1. Create a Telegram bot with BotFather.
2. Create a MongoDB Atlas database.
3. Set environment variables from `.env.example`.
4. Deploy as a Render Worker or run locally.
5. Add the bot to the source group.
6. Set the source group ID in the bot's runtime configuration (currently `source_chat_id` in `bot_data`; the next revision will expose this in the admin panel).
7. Add the bot to destination groups/channels. For channels, make the bot an administrator with permission to post.
8. Use `/admin` to configure storage, interval, protection, caption and buttons.

## Important
Telegram content protection is enforced by Telegram and applies to messages sent by the bot with `protect_content=True`. It cannot guarantee protection against a separate device recording the screen.
