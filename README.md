# Auto Media Delivery Bot — Render Web Service V5

This build uses a Render Web Service with a Telegram webhook.

Render:
- Service: Web Service
- Build: `pip install -r requirements.txt`
- Start: `gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:$PORT app.web:app`

Environment:
- BOT_TOKEN
- MONGO_URI
- MONGO_DB=auto_media_bot
- OWNER_IDS=<numeric Telegram user ID>
- WEBHOOK_SECRET=<optional random secret>
- DEFAULT_STORAGE_LIMIT=20
- DEFAULT_INTERVAL_MINUTES=60

After deployment:
1. Open `https://YOUR-RENDER-DOMAIN/health` and confirm ready=true.
2. Open `https://YOUR-RENDER-DOMAIN/webhook-info` and confirm a non-empty Telegram webhook URL and no recent webhook error.
3. Send `/start` to the bot.
4. Owner can send `/diag` to check MongoDB/media/source state.
