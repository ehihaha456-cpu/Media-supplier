# Auto Media Delivery Bot — Complete Web Service

## Features
- Telegram webhook + Render Web Service
- Source group/channel selection from Admin Panel or `/setsource`
- Stores only Telegram `file_id` + metadata in MongoDB
- Configurable media storage limit (1–1000; e.g. 10 or 20)
- Oldest retained media is automatically removed when the limit is exceeded
- `/start` activates automatic delivery; `/stop` disables it
- Each user receives the retained media sequentially, one media per configured interval
- Groups/channels receive the same sequential delivery when bot is added
- Group/channel delivery can be toggled from Admin Panel
- Caption editor
- Inline URL button editor with remove controls
- Preview latest media
- Telegram content protection ON/OFF (`protect_content`)
- Status and media library pages
- Optional webhook secret

## Render Web Service
Build Command:
`pip install -r requirements.txt`

Start Command:
`gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT app.web:app`

Required environment variables:
- `BOT_TOKEN`
- `MONGO_URI`
- `MONGO_DB=auto_media_bot`
- `OWNER_IDS=<numeric Telegram user ID>`
- `WEBHOOK_SECRET=<random secret>`
- `DEFAULT_STORAGE_LIMIT=20`
- `DEFAULT_INTERVAL_MINUTES=60`

Render supplies `PORT` and `RENDER_EXTERNAL_URL` automatically.

## Source group
Option 1: Add the bot to the source group, then send `/setsource` there as the owner.
Option 2: Open `/admin` → Settings → Source group and select a group/channel the bot knows.

For channels, the bot must be an administrator with permission to post/read the required channel updates. For source groups, the bot must be able to receive group messages (BotFather privacy settings may need adjustment depending on how the group is configured).

## Protection
The bot sends messages with Telegram's `protect_content` flag when protection is ON. Telegram controls the exact client behavior; no bot can guarantee protection against recording with another device.
