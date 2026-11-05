import asyncio
import logging
import os
import re
import time
from collections import defaultdict

from aiohttp import web
from openai import AsyncOpenAI

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import RPCError

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest


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

OFFICIAL_CHANNEL = os.getenv(
    "OFFICIAL_CHANNEL",
    "Trusted_Money_India"
).strip()

if OFFICIAL_CHANNEL.startswith("https://t.me/"):
    OFFICIAL_CHANNEL = OFFICIAL_CHANNEL.rstrip("/").split("/")[-1]

OFFICIAL_CHANNEL = OFFICIAL_CHANNEL.lstrip("@")

PORT = int(os.getenv("PORT", "10000"))

REPLY_COOLDOWN_SECONDS = int(
    os.getenv("REPLY_COOLDOWN_SECONDS", "0")
)


# =====================================================
# DEFAULT AI INSTRUCTIONS
# =====================================================

DEFAULT_INSTRUCTIONS = (
    "You are an AI assistant replying on behalf of the Telegram account owner. "
    "Always reply in the same language used by the incoming sender. "
    "If the sender writes in Bengali, reply in Bengali. "
    "If the sender writes in English, reply in English. "
    "If the sender writes in Hindi, reply in Hindi. "
    "For other languages, reply in the sender's language whenever possible. "
    "Do not translate the conversation into English unless the sender asks. "
    "Reply naturally, politely, and accurately. "
    "Keep replies reasonably concise. "
    "Never invent personal information, payment claims, app details, "
    "registration links, or verification claims. "
    "App information must come only from the official channel lookup system."
)


# =====================================================
# APP RESPONSE TEXTS
# =====================================================

APP_NOT_FOUND_TEXT = (
    "ℹ️ This app is not verified or listed on our official channel. "
    "I can share its details only after it is published there."
)

APP_FOUND_TEXT = (
    "✅ Listed on our official channel. "
    "Please review the complete details and registration link above."
)

CHANNEL_CHECK_FAILED_TEXT = (
    "⚠️ I couldn't check the official channel right now. "
    "Please try again in a little while."
)

GENERIC_APP_INTRO = (
    "📌 Here's an app post from our official channel. "
    "Please review its name and complete details below."
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
# VALIDATE ENVIRONMENT VARIABLES
# =====================================================

required_variables = {
    "API_ID": API_ID,
    "API_HASH": API_HASH,
    "SESSION_STRING": SESSION_STRING,
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "BOT_TOKEN": BOT_TOKEN,
    "OWNER_ID": OWNER_ID,
    "OFFICIAL_CHANNEL": OFFICIAL_CHANNEL,
}

for variable_name, variable_value in required_variables.items():
    if not variable_value:
        raise RuntimeError(
            f"Required environment variable is missing: {variable_name}"
        )

try:
    API_ID = int(API_ID)
    OWNER_ID = int(OWNER_ID)
except ValueError as exc:
    raise RuntimeError(
        "API_ID and OWNER_ID must be numeric."
    ) from exc

if PORT < 1 or PORT > 65535:
    raise RuntimeError("PORT must be between 1 and 65535.")

if REPLY_COOLDOWN_SECONDS < 0:
    raise RuntimeError(
        "REPLY_COOLDOWN_SECONDS cannot be negative."
    )


# =====================================================
# TELEGRAM AND OPENAI CLIENTS
# =====================================================

telegram_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
)

control_bot = Bot(token=BOT_TOKEN)

dispatcher = Dispatcher()

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)


# =====================================================
# BOT SETTINGS
# =====================================================

auto_reply_enabled = True
ai_reply_enabled = True

ai_instructions = DEFAULT_INSTRUCTIONS

last_replied = {}

user_history = defaultdict(list)

MAX_HISTORY_MESSAGES = 8

CHANNEL_POST_SCAN_LIMIT = 300

sender_locks = {}


# =====================================================
# ADMIN PANEL KEYBOARD
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


# =====================================================
# ADMIN STATUS
# =====================================================

def get_status_text():
    auto_status = "ON 🟢" if auto_reply_enabled else "OFF 🔴"
    ai_status = "ON 🟢" if ai_reply_enabled else "OFF 🔴"

    return (
        "⚙️ <b>Personal AI Auto Reply Control</b>\n\n"
        f"Auto Reply: <b>{auto_status}</b>\n"
        f"AI Reply: <b>{ai_status}</b>\n"
        f"AI Model: <code>{AI_MODEL}</code>\n"
        f"Cooldown: <b>{REPLY_COOLDOWN_SECONDS}s</b>\n"
        f"Official channel: <code>@{OFFICIAL_CHANNEL}</code>"
    )


# =====================================================
# SAFE ADMIN MESSAGE EDIT
# =====================================================

async def safe_edit_admin_message(callback: CallbackQuery):
    if not callback.message:
        return

    try:
        await callback.message.edit_text(
            get_status_text(),
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )

    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return

        raise
        # =====================================================
# ADMIN COMMANDS
# =====================================================

@dispatcher.message(Command("start"))
async def start_command(message: Message):
    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:
        await message.answer("This bot is private.")
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

    if message.from_user.id != OWNER_ID:
        await message.answer(
            "You are not authorized to use this panel."
        )
        return

    await message.answer(
        get_status_text(),
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


@dispatcher.message(Command("status"))
async def status_command(message: Message):
    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:
        await message.answer(
            "You are not authorized to use this command."
        )
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

    if message.from_user.id != OWNER_ID:
        await message.answer(
            "You are not authorized to use this command."
        )
        return

    command_text = message.text or ""
    new_instructions = command_text.partition(" ")[2].strip()

    if not new_instructions:
        await message.answer(
            "Current AI instructions:\n\n"
            f"{ai_instructions}\n\n"
            "To update them, send:\n"
            "/instructions Your new instructions"
        )
        return

    ai_instructions = new_instructions

    await message.answer(
        "AI instructions updated successfully."
    )


# =====================================================
# ADMIN CALLBACKS
# =====================================================

@dispatcher.callback_query(
    lambda callback: callback.data in {
        "auto_on",
        "auto_off",
        "ai_on",
        "ai_off",
        "status",
    }
)
async def admin_callback_handler(callback: CallbackQuery):
    global auto_reply_enabled
    global ai_reply_enabled

    if not callback.from_user:
        await callback.answer()
        return

    if callback.from_user.id != OWNER_ID:
        await callback.answer(
            "You are not authorized.",
            show_alert=True,
        )
        return

    action = callback.data

    if action == "auto_on":
        auto_reply_enabled = True

    elif action == "auto_off":
        auto_reply_enabled = False

    elif action == "ai_on":
        ai_reply_enabled = True

    elif action == "ai_off":
        ai_reply_enabled = False

    await callback.answer()

    await safe_edit_admin_message(callback)


# =====================================================
# USER HISTORY
# =====================================================

def add_to_history(user_id: int, role: str, content: str):
    history = user_history[user_id]

    history.append(
        {
            "role": role,
            "content": content,
        }
    )

    if len(history) > MAX_HISTORY_MESSAGES:
        user_history[user_id] = history[-MAX_HISTORY_MESSAGES:]


def get_user_history(user_id: int):
    return list(user_history[user_id])


# =====================================================
# COOLDOWN
# =====================================================

def is_on_cooldown(user_id: int) -> bool:
    if REPLY_COOLDOWN_SECONDS == 0:
        return False

    last_time = last_replied.get(user_id, 0)

    return (
        time.time() - last_time
        < REPLY_COOLDOWN_SECONDS
    )


def update_last_replied(user_id: int):
    last_replied[user_id] = time.time()


# =====================================================
# TEXT NORMALIZATION
# =====================================================

def normalize_text(text: str) -> str:
    text = text.lower().strip()

    text = re.sub(
        r"https?://\S+",
        " ",
        text,
    )

    text = re.sub(
        r"[^a-z0-9\u0980-\u09ff]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# =====================================================
# COMMON CONVERSATION PHRASES
# =====================================================

COMMON_NON_APP_MESSAGES = {
    "hi",
    "hello",
    "hey",
    "how are you",
    "how r u",
    "what's up",
    "whats up",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "yes",
    "no",
    "hmm",
    "huh",
    "bye",
    "goodbye",
    "who are you",
    "are you there",
    "how is it going",
}


# =====================================================
# GENERIC APP REQUEST PHRASES
# =====================================================

APP_REQUEST_TERMS = (
    "earning app",
    "earning apps",
    "latest app",
    "latest earning app",
    "verified app",
    "verified earning app",
    "investing app",
    "investment app",
    "investment apps",
    "investing earning app",
    "app details",
    "apps details",
    "any app",
    "some app",
    "earn money app",
    "earn money apps",
)


def is_generic_app_request(text: str) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return False

    return any(
        normalize_text(term) in normalized
        for term in APP_REQUEST_TERMS
    )


# =====================================================
# COMMON CONVERSATION DETECTION
# =====================================================

def is_common_conversation(text: str) -> bool:
    normalized = normalize_text(text)

    normalized_phrases = {
        normalize_text(item)
        for item in COMMON_NON_APP_MESSAGES
    }

    return normalized in normalized_phrases


# =====================================================
# SPECIFIC APP NAME DETECTION
# =====================================================

def looks_like_specific_app_name(text: str) -> bool:
    """
    Detect standalone app names such as:
    PepsiCo
    Cash App
    EarnFast

    Avoid classifying ordinary conversational sentences as app names.
    """

    original = text.strip()
    normalized = normalize_text(original)

    if not normalized:
        return False

    if is_common_conversation(original):
        return False

    if is_generic_app_request(original):
        return False

    words = normalized.split()

    if len(words) > 4:
        return False

    conversation_starters = {
        "i",
        "you",
        "we",
        "they",
        "he",
        "she",
        "it",
        "what",
        "why",
        "when",
        "where",
        "who",
        "how",
        "can",
        "could",
        "would",
        "will",
        "please",
        "tell",
        "give",
        "show",
        "send",
        "do",
        "does",
        "did",
        "are",
        "is",
        "am",
        "have",
        "has",
    }

    if words and words[0] in conversation_starters:
        return False

    if len(normalized) > 60:
        return False

    return True
    # =====================================================
# OFFICIAL CHANNEL ENTITY
# =====================================================

_official_channel_entity = None


async def get_official_channel():
    global _official_channel_entity

    if _official_channel_entity is not None:
        return _official_channel_entity

    _official_channel_entity = await telegram_client.get_entity(
        OFFICIAL_CHANNEL
    )

    return _official_channel_entity


# =====================================================
# EXTRACT APP NAME FROM CHANNEL POST
# =====================================================

def get_post_text(post) -> str:
    text = getattr(post, "message", None)

    if not text:
        return ""

    return text.strip()


def get_post_search_text(post) -> str:
    text = get_post_text(post)

    if not text:
        return ""

    return normalize_text(text)


def app_name_matches_post(app_name: str, post) -> bool:
    query = normalize_text(app_name)
    post_text = get_post_search_text(post)

    if not query or not post_text:
        return False

    if query == post_text:
        return True

    if query in post_text.split():
        return True

    query_words = query.split()

    if len(query_words) > 1:
        return query in post_text

    return False


# =====================================================
# SEARCH OFFICIAL CHANNEL FOR A SPECIFIC APP
# =====================================================

async def find_channel_post(app_name: str):
    """
    Search only the configured official channel.
    Returns:
        ("found", message)
        ("not_found", None)
        ("error", None)
    """

    try:
        channel = await get_official_channel()

        async for post in telegram_client.iter_messages(
            channel,
            limit=CHANNEL_POST_SCAN_LIMIT,
        ):
            post_text = get_post_text(post)

            if not post_text:
                continue

            if app_name_matches_post(app_name, post):
                return "found", post

        return "not_found", None

    except Exception:
        logger.exception(
            "Official channel lookup failed for app: %s",
            app_name,
        )

        return "error", None


# =====================================================
# FIND A RECENT APP POST FOR GENERIC REQUESTS
# =====================================================

async def find_latest_channel_post():
    """
    Return the latest channel post with a caption.
    This is used for generic app requests such as:
    'latest earning app'
    'show me an app'
    """

    try:
        channel = await get_official_channel()

        async for post in telegram_client.iter_messages(
            channel,
            limit=CHANNEL_POST_SCAN_LIMIT,
        ):
            post_text = get_post_text(post)

            if post_text:
                return "found", post

        return "not_found", None

    except Exception:
        logger.exception(
            "Generic official channel lookup failed."
        )

        return "error", None


# =====================================================
# FORWARD ORIGINAL CHANNEL POST
# =====================================================

async def forward_original_channel_post(
    recipient_id: int,
    post,
):
    """
    Forward the original post from the connected personal account.
    Preserves original media and caption where Telegram allows it.
    """

    channel = await get_official_channel()

    await telegram_client.forward_messages(
        entity=recipient_id,
        messages=post.id,
        from_peer=channel,
    )


# =====================================================
# HANDLE SPECIFIC APP LOOKUP
# =====================================================

async def handle_specific_app_lookup(
    recipient_id: int,
    app_name: str,
):
    status, post = await find_channel_post(app_name)

    if status == "error":
        await telegram_client.send_message(
            recipient_id,
            CHANNEL_CHECK_FAILED_TEXT,
        )
        return

    if status == "not_found":
        await telegram_client.send_message(
            recipient_id,
            APP_NOT_FOUND_TEXT,
        )
        return

    try:
        await forward_original_channel_post(
            recipient_id,
            post,
        )

        await telegram_client.send_message(
            recipient_id,
            APP_FOUND_TEXT,
        )

    except Exception:
        logger.exception(
            "Failed to forward official channel post."
        )

        await telegram_client.send_message(
            recipient_id,
            CHANNEL_CHECK_FAILED_TEXT,
        )


# =====================================================
# HANDLE GENERIC APP REQUEST
# =====================================================

async def handle_generic_app_request(
    recipient_id: int,
):
    status, post = await find_latest_channel_post()

    if status == "error":
        await telegram_client.send_message(
            recipient_id,
            CHANNEL_CHECK_FAILED_TEXT,
        )
        return

    if status == "not_found":
        await telegram_client.send_message(
            recipient_id,
            APP_NOT_FOUND_TEXT,
        )
        return

    try:
        await telegram_client.send_message(
            recipient_id,
            GENERIC_APP_INTRO,
        )

        await forward_original_channel_post(
            recipient_id,
            post,
        )

    except Exception:
        logger.exception(
            "Failed to send generic app post."
        )

        await telegram_client.send_message(
            recipient_id,
            CHANNEL_CHECK_FAILED_TEXT,
        )
        # =====================================================
# OPENAI CONVERSATIONAL REPLY
# =====================================================

async def generate_ai_reply(sender_id: int, incoming_text: str) -> str:
    history = user_history[sender_id]

    messages = [
        {
            "role": "system",
            "content": ai_instructions or DEFAULT_INSTRUCTIONS,
        }
    ]

    messages.extend(history)
    messages.append({
        "role": "user",
        "content": incoming_text,
    })

    response = await asyncio.to_thread(
        openai_client.responses.create,
        model=AI_MODEL,
        input=messages,
    )

    reply_text = (response.output_text or "").strip()

    if not reply_text:
        raise ValueError("OpenAI returned an empty response.")

    history.append({
        "role": "user",
        "content": incoming_text,
    })
    history.append({
        "role": "assistant",
        "content": reply_text,
    })

    while len(history) > MAX_HISTORY_MESSAGES:
        history.pop(0)

    return reply_text


# =====================================================
# REPLY COOLDOWN CHECK
# =====================================================

def cooldown_is_over(sender_id: int) -> bool:
    last_reply_time = last_replied.get(sender_id, 0)

    return (
        time.time() - last_reply_time
        >= REPLY_COOLDOWN_SECONDS
    )

@telegram_client.on(events.NewMessage(incoming=True))
async def personal_message_handler(event):
    try:
        if not event.is_private:
            return

        if event.out:
            return

        sender_id = event.sender_id
        incoming_text = (event.raw_text or "").strip()

        if not sender_id or not incoming_text:
            return

        sender = await event.get_sender()

        if not sender or getattr(sender, "bot", False):
            return

        if not auto_reply_enabled:
            return

        lock = sender_locks.setdefault(sender_id, asyncio.Lock())

        async with lock:
            if not cooldown_is_over(sender_id):
                return

            # Generic app requests are handled using official-channel posts.
            if is_generic_app_request(incoming_text):
                await handle_generic_app_request(sender_id)
                last_replied[sender_id] = time.time()
                return

            # Specific app names are checked only against the official channel.
            if looks_like_specific_app_name(incoming_text):
                await handle_specific_app_lookup(sender_id, incoming_text)
                last_replied[sender_id] = time.time()
                return

            # Ordinary conversation uses OpenAI when AI replies are enabled.
            if not ai_reply_enabled:
                return

            if is_common_conversation(incoming_text):
                reply_text = await generate_ai_reply(
                    sender_id,
                    incoming_text,
                )
                await telegram_client.send_message(
                    sender_id,
                    reply_text,
                    link_preview=False,
                )
                settings["last_replied"][sender_id] = time.time()

    except Exception:
        logger.exception("Error while handling an incoming personal message.")


# =====================================================
# HEALTH CHECK WEB SERVER
# =====================================================

async def health_check(request):
    return web.Response(
        text="PersonalTelegramAutoReply is running!",
        status=200,
    )


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)

    await site.start()
    logger.info("Health server started on port %s.", port)

    return runner


# =====================================================
# APPLICATION STARTUP AND SHUTDOWN
# =====================================================

async def main():
    health_runner = None

    try:
        logger.info("Starting PersonalTelegramAutoReply...")

        await telegram_client.connect()

        if not await telegram_client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Check SESSION_STRING."
            )

        me = await telegram_client.get_me()
        logger.info(
            "Personal Telegram account connected. Account ID: %s",
            me.id,
        )

        health_runner = await start_health_server()

        logger.info("Starting admin control bot polling...")
        polling_task = asyncio.create_task(
            dispatcher.start_polling(control_bot)
        )

        logger.info("Personal Telegram auto-reply is ready.")

        try:
            await telegram_client.run_until_disconnected()
        finally:
            polling_task.cancel()

            try:
                await polling_task
            except asyncio.CancelledError:
                pass

    except Exception:
        logger.exception("Application startup or runtime error.")

    finally:
        if health_runner:
            await health_runner.cleanup()

        if telegram_client.is_connected():
            await telegram_client.disconnect()

        await control_bot.session.close()

        logger.info("PersonalTelegramAutoReply stopped.")


# =====================================================
# RUN APPLICATION
# =====================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user.")
