import os
import asyncio
from telethon import TelegramClient, events

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

client = TelegramClient(
    "auto_reply_session",
    API_ID,
    API_HASH
)

AUTO_REPLY = (
    "👋 Hello! Thanks for messaging me.\n"
    "I'm currently unavailable, but I'll reply when I'm back. 😊"
)

@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    # Ignore messages from bots and groups
    if event.is_group or event.sender.bot:
        return

    # Ignore messages from yourself
    if event.out:
        return

    await event.reply(AUTO_REPLY)

async def main():
    if not API_ID or not API_HASH:
        raise ValueError("API_ID and API_HASH are required.")

    await client.start()
    print("✅ Personal Auto-Reply is running!")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
