import asyncio
import logging
import os
import time

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession


# ==============================
# CONFIGURATION
# ==============================

API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

AUTO_REPLY_TEXT = os.getenv(
    "AUTO_REPLY_TEXT",
    "👋 Hello! Thanks for messaging me.\n\n"
    "I'm currently unavailable, but I'll reply as soon as possible. 😊"
)

REPLY_COOLDOWN_SECONDS = int(
    os.getenv("REPLY_COOLDOWN_SECONDS", "3600")
)

PORT = int(os.getenv("PORT", "10000"))


# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("personal_auto_reply")


# ==============================
# VALIDATE ENVIRONMENT
# ==============================

if not API_ID:
    raise RuntimeError("API_ID environment variable is missing.")

if not API_HASH:
    raise RuntimeError("API_HASH environment variable is missing.")

if not SESSION_STRING:
    raise RuntimeError("SESSION_STRING environment variable is missing.")

try:
    API_ID = int(API_ID)
except ValueError:
    raise RuntimeError("API_ID must be a number.")


# ==============================
# TELETHON CLIENT
# ==============================

client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
)

last_replied = {}


# ==============================
# AUTO-REPLY HANDLER
# ==============================

@client.on(events.NewMessage(incoming=True))
async def auto_reply_handler(event):
    try:
        # Only reply to private chats
        if not event.is_private:
            return

        # Ignore messages sent by bots
        sender = await event.get_sender()
        if sender and getattr(sender, "bot", False):
            return

        # Ignore empty messages
        if not event.raw_text:
            return

        # Avoid replying to the same person repeatedly
        user_id = event.sender_id
        current_time = time.time()

        previous_reply = last_replied.get(user_id, 0)

        if current_time - previous_reply < REPLY_COOLDOWN_SECONDS:
            return

        await event.reply(AUTO_REPLY_TEXT)
        last_replied[user_id] = current_time

        logger.info("Auto-replied to private user ID %s", user_id)

    except Exception:
        logger.exception("Auto-reply handler failed")


# ==============================
# HEALTH CHECK SERVER
# ==============================

async def health_check(request):
    return web.Response(text="Personal Telegram Auto Reply is running.")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )

    await site.start()
    logger.info("Health server started on port %s", PORT)

    return runner


# ==============================
# MAIN
# ==============================

async def main():
    runner = None

    try:
        runner = await start_web_server()

        logger.info("Connecting personal Telegram account...")
        await client.start()

        me = await client.get_me()

        logger.info(
            "Personal auto-reply is active for account ID %s",
            me.id,
        )

        await client.run_until_disconnected()

    finally:
        if runner:
            await runner.cleanup()

        if client.is_connected():
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
