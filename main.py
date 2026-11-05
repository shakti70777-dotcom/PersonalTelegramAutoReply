import asyncio
import logging
import os
import time

from aiohttp import web
from openai import AsyncOpenAI
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


# =====================================================
# CONFIGURATION
# =====================================================

API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
SESSION_STRING = os.getenv("SESSION_STRING", "").strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "gpt-6-luna").strip()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = os.getenv("OWNER_ID", "").strip()

PORT = int(os.getenv("PORT", "10000"))
REPLY_COOLDOWN_SECONDS = int(
    os.getenv("REPLY_COOLDOWN_SECONDS", "60")
)

DEFAULT_INSTRUCTIONS = (
    "You are an AI assistant replying on behalf of the Telegram account owner. "
    "Answer the sender's message naturally, politely, and accurately. "
    "Reply in the same language as the sender whenever possible. "
    "Keep replies reasonably concise. "
    "Do not invent personal information, promises, or facts about the owner. "
    "If you do not know something, say so honestly."
)


# =====================================================
# LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("personal_ai_auto_reply")


# =====================================================
# VALIDATE ENVIRONMENT
# =====================================================

required_variables = {
    "API_ID": API_ID,
    "API_HASH": API_HASH,
    "SESSION_STRING": SESSION_STRING,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "BOT_TOKEN": BOT_TOKEN,
    "OWNER_ID": OWNER_ID,
}

for variable_name, variable_value in required_variables.items():
    if not variable_value:
        raise RuntimeError(
            f"Required environment variable is missing: {variable_name}"
        )

try:
    API_ID = int(API_ID)
    OWNER_ID = int(OWNER_ID)
except ValueError:
    raise RuntimeError("API_ID and OWNER_ID must be numeric.")


# =====================================================
# CLIENTS
# =====================================================

telegram_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
)

control_bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher()

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
)


# =====================================================
# SETTINGS
# =====================================================

auto_reply_enabled = True
ai_reply_enabled = True
ai_instructions = DEFAULT_INSTRUCTIONS

last_replied = {}
user_history = {}

MAX_HISTORY_MESSAGES = 8


# =====================================================
# ADMIN KEYBOARD
# =====================================================

def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Auto Reply ON",
                    callback_data="auto_on",
                ),
                InlineKeyboardButton(
                    text="🔴 Auto Reply OFF",
                    callback_data="auto_off",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🤖 AI Reply ON",
                    callback_data="ai_on",
                ),
                InlineKeyboardButton(
                    text="⛔ AI Reply OFF",
                    callback_data="ai_off",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Status",
                    callback_data="status",
                ),
            ],
        ]
    )


def get_status_text():
    auto_status = "ON 🟢" if auto_reply_enabled else "OFF 🔴"
    ai_status = "ON 🟢" if ai_reply_enabled else "OFF 🔴"

    return (
        "⚙️ <b>Personal AI Auto Reply Control</b>\n\n"
        f"Auto Reply: <b>{auto_status}</b>\n"
        f"AI Reply: <b>{ai_status}</b>\n"
        f"AI Model: <code>{AI_MODEL}</code>\n"
        f"Cooldown: <b>{REPLY_COOLDOWN_SECONDS}s</b>"
    )


# =====================================================
# OWNER CHECK
# =====================================================

def is_owner(user_id):
    return user_id == OWNER_ID


# =====================================================
# CONTROL BOT COMMANDS
# =====================================================

@dispatcher.message(Command("start"))
async def start_command(message: Message):
    if not message.from_user:
        return

    if not is_owner(message.from_user.id):
        await message.answer("⛔ You are not authorized to use this panel.")
        return

    await message.answer(
        get_status_text(),
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


@dispatcher.message(Command("panel"))
async def panel_command(message: Message):
    if not message.from_user:
        return

    if not is_owner(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    await message.answer(
        get_status_text(),
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


@dispatcher.message(Command("instructions"))
async def instructions_command(message: Message):
    global ai_instructions

    if not message.from_user:
        return

    if not is_owner(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    new_instructions = message.text.partition(" ")[2].strip()

    if not new_instructions:
        await message.answer(
            "Send your instructions like this:\n\n"
            "/instructions Reply politely and briefly in English."
        )
        return

    ai_instructions = new_instructions

    await message.answer(
        "✅ AI instructions updated.\n\n"
        "New instructions will apply to future replies."
    )


# =====================================================
# CONTROL BOT BUTTON HANDLERS
# =====================================================

@dispatcher.callback_query(F.data == "auto_on")
async def auto_on_callback(callback: CallbackQuery):
    global auto_reply_enabled

    if not is_owner(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    auto_reply_enabled = True

    await callback.answer("Auto Reply enabled.")

    if callback.message:
        await callback.message.edit_text(
            get_status_text(),
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )


@dispatcher.callback_query(F.data == "auto_off")
async def auto_off_callback(callback: CallbackQuery):
    global auto_reply_enabled

    if not is_owner(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    auto_reply_enabled = False

    await callback.answer("Auto Reply disabled.")

    if callback.message:
        await callback.message.edit_text(
            get_status_text(),
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )


@dispatcher.callback_query(F.data == "ai_on")
async def ai_on_callback(callback: CallbackQuery):
    global ai_reply_enabled

    if not is_owner(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    ai_reply_enabled = True

    await callback.answer("AI Reply enabled.")

    if callback.message:
        await callback.message.edit_text(
            get_status_text(),
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )


@dispatcher.callback_query(F.data == "ai_off")
async def ai_off_callback(callback: CallbackQuery):
    global ai_reply_enabled

    if not is_owner(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    ai_reply_enabled = False

    await callback.answer("AI Reply disabled.")

    if callback.message:
        await callback.message.edit_text(
            get_status_text(),
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )


@dispatcher.callback_query(F.data == "status")
async def status_callback(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer("Status refreshed.")

    if callback.message:
        await callback.message.edit_text(
            get_status_text(),
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )


# =====================================================
# AI RESPONSE
# =====================================================

async def generate_ai_reply(user_id: int, incoming_text: str) -> str:
    history = user_history.get(user_id, [])

    messages = [
        {
            "role": "system",
            "content": ai_instructions,
        }
    ]

    messages.extend(history)

    messages.append(
        {
            "role": "user",
            "content": incoming_text,
        }
    )

    response = await openai_client.responses.create(
        model=AI_MODEL,
        input=messages,
    )

    reply_text = (response.output_text or "").strip()

    if not reply_text:
        raise RuntimeError("OpenAI returned an empty response.")

    history.append(
        {
            "role": "user",
            "content": incoming_text,
        }
    )

    history.append(
        {
            "role": "assistant",
            "content": reply_text,
        }
    )

    user_history[user_id] = history[-MAX_HISTORY_MESSAGES:]

    return reply_text


# =====================================================
# PERSONAL TELEGRAM AUTO-REPLY
# =====================================================

@telegram_client.on(events.NewMessage(incoming=True))
async def auto_reply_handler(event):
    try:
        if not event.is_private:
            return

        if not auto_reply_enabled:
            return

        if not ai_reply_enabled:
            return

        sender = await event.get_sender()

        if sender and getattr(sender, "bot", False):
            return

        incoming_text = (event.raw_text or "").strip()

        if not incoming_text:
            return

        user_id = event.sender_id

        if not user_id:
            return

        current_time = time.time()
        previous_reply = last_replied.get(user_id, 0)

        if current_time - previous_reply < REPLY_COOLDOWN_SECONDS:
            logger.info("Cooldown active for user ID %s", user_id)
            return

        # Mark before the API request to prevent duplicate simultaneous calls.
        last_replied[user_id] = current_time

        try:
            reply_text = await generate_ai_reply(
                user_id=user_id,
                incoming_text=incoming_text,
            )
        except Exception:
            logger.exception("AI response generation failed")
            last_replied.pop(user_id, None)
            return

        await event.reply(reply_text)

        logger.info("AI replied to private user ID %s", user_id)

    except Exception:
        logger.exception("Auto-reply handler failed")


# =====================================================
# HEALTH CHECK
# =====================================================

async def health_check(request):
    return web.Response(
        text="Personal AI Telegram Auto Reply is running."
    )


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


# =====================================================
# MAIN
# =====================================================

async def main():
    runner = None

    try:
        runner = await start_web_server()

        logger.info("Connecting personal Telegram account...")
        await telegram_client.start()

        me = await telegram_client.get_me()

        logger.info(
            "Personal Telegram connected. Account ID: %s",
            me.id,
        )

        logger.info("Starting Admin Control Bot polling...")

        await asyncio.gather(
            telegram_client.run_until_disconnected(),
            dispatcher.start_polling(
                control_bot,
                close_bot_session=False,
            ),
        )

    finally:
        if runner:
            await runner.cleanup()

        if telegram_client.is_connected():
            await telegram_client.disconnect()

        await control_bot.session.close()
        await openai_client.close()


if __name__ == "__main__":
    asyncio.run(main())
