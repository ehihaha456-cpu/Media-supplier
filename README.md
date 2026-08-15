# Auto Media Delivery Bot V7

## Intended flow
1. Configure one source group/channel with `/setsource`.
2. New media posted after the bot is connected is stored by Telegram file_id.
3. Storage limit is configurable (10, 20, etc.). When a new item exceeds the limit, the oldest retained item is removed automatically.
4. Users who press `/start` receive the retained media in sequence at the configured interval.
5. Groups/channels where the bot is added are registered automatically; `/enablechat` can explicitly enable one.
6. Caption, inline buttons and Telegram content protection are applied to every delivered media message.
7. Channel posts are captured with ChannelPostHandler.

## Important Telegram limitation
The standard Telegram Bot API does NOT provide a method for a bot to read the complete historical message/media history of a group or channel. Therefore, media that existed BEFORE the bot received/processed the messages cannot be automatically imported by a normal bot.

To seed older media, repost/forward/copy those media into the configured source after the bot is running, or use a separate MTProto user-account importer (which is a different architecture).

## Render
Build:
`pip install -r requirements.txt`

Start:
`gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:$PORT app.web:app`
