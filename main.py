import asyncio
import logging
import os
import re
import time

from aiohttp import web
from openai import AsyncOpenAI
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    ChannelPrivateError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

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

OFFICIAL_CHANNEL = os.getenv(
    "OFFICIAL_CHANNEL",
    "Trusted_Money_India",
).strip().lstrip("@")

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

official_channel_entity = None


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
# OFFICIAL CHANNEL HELPERS
# =====================================================

async def get_official_channel():
    global official_channel_entity

    if official_channel_entity is not None:
        return official_channel_entity

    official_channel_entity = await telegram_client.get_entity(
        OFFICIAL_CHANNEL
    )

    return official_channel_entity


def normalize_text(text):
    text = (text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_generic_earning_app_request(text):
    normalized = normalize_text(text)

    generic_patterns = [
        r"\bany\s+earning\s+apps?\b",
        r"\bany\s+apps?\s+to\s+earn\b",
        r"\bsuggest\s+(?:me\s+)?(?:an?\s+)?earning\s+apps?\b",
        r"\brecommend\s+(?:me\s+)?(?:an?\s+)?earning\s+apps?\b",
        r"\bfind\s+(?:me\s+)?(?:an?\s+)?earning\s+apps?\b",
        r"\bshow\s+(?:me\s+)?(?:some\s+)?earning\s+apps?\b",
        r"\blatest\s+earning\s+apps?\b",
        r"\bearning\s+apps?\b",
        r"\bapps?\s+to\s+earn\s+money\b",
        r"\bmake\s+money\s+apps?\b",
        r"\bearn\s+money\s+apps?\b",
        r"\bearning\s+application\b",
        r"\bearning\s+applications\b",
    ]

    if any(re.search(pattern, normalized) for pattern in generic_patterns):
        specific_lookup_patterns = [
            r"\bis\s+.+\s+real\s+or\s+fake\b",
            r"\bis\s+.+\s+legit\b",
            r"\bis\s+.+\s+genuine\b",
            r"\bcheck\s+.+\s+app\b",
            r"\bsearch\s+.+\s+app\b",
            r"\bfind\s+.+\s+app\b",
        ]

        if any(
            re.search(pattern, normalized)
            for pattern in specific_lookup_patterns
        ):
            return False

        return True

    return False


def extract_specific_app_name(text):
    original = (text or "").strip()
    normalized = normalize_text(original)

    if not normalized:
        return None

    generic_phrases = [
        "any earning app",
        "any earning apps",
        "earning app",
        "earning apps",
        "latest earning apps",
        "apps to earn money",
        "earn money apps",
        "make money apps",
        "earning application",
        "earning applications",
    ]

    if any(phrase in normalized for phrase in generic_phrases):
        if is_generic_earning_app_request(original):
            return None

    patterns = [
        r"^(?:is|are)\s+(.+?)\s+(?:app\s+)?(?:real\s+or\s+fake|legit|genuine|trusted|verified)\??$",
        r"^(?:check|search|find)\s+(.+?)(?:\s+app|\s+application)?$",
        r"^(?:tell\s+me\s+about|what\s+about|info\s+about|details\s+about)\s+(.+?)(?:\s+app|\s+application)?$",
        r"^(.+?)\s+(?:app|application)\s+(?:real\s+or\s+fake|legit|genuine|trusted|verified)\??$",
        r"^(.+?)\s+(?:app|application)\s+(?:details|info|review|payment|withdrawal)\??$",
        r"^(.+?)\s+(?:app|application)\??$",
    ]

    for pattern in patterns:
        match = re.match(pattern, normalized)

        if match:
            app_name = match.group(1).strip()
            app_name = re.sub(
                r"\b(?:please|kindly|bro|brother|tell|me|about|check|search|find)\b",
                " ",
                app_name,
            )
            app_name = re.sub(r"\s+", " ", app_name).strip()

            if app_name and app_name not in {
                "earning",
                "earn money",
                "make money",
                "money earning",
                "any",
                "some",
            }:
                return app_name

    return None


def post_contains_app_name(post_text, app_name):
    normalized_post = normalize_text(post_text)
    normalized_name = normalize_text(app_name)

    if not normalized_post or not normalized_name:
        return False

    return normalized_name in normalized_post


def is_suitable_earning_post(post_text):
    normalized = normalize_text(post_text)

    earning_keywords = [
        "earning",
        "earn",
        "income",
        "reward",
        "rewards",
        "task",
        "tasks",
        "payment",
        "paid",
        "withdraw",
        "withdrawal",
        "cash",
        "money",
        "app",
        "application",
        "refer",
        "referral",
    ]

    return any(keyword in normalized for keyword in earning_keywords)


# =====================================================
# OFFICIAL CHANNEL SEARCH AND FORWARDING
# =====================================================

async def search_specific_app_post(app_name):
    channel = await get_official_channel()

    async for message in telegram_client.iter_messages(
        channel,
        limit=200,
    ):
        post_text = message.raw_text or ""

        if post_contains_app_name(post_text, app_name):
            return channel, message

    return channel, None


async def search_generic_earning_post():
    channel = await get_official_channel()

    async for message in telegram_client.iter_messages(
        channel,
        limit=150,
    ):
        post_text = message.raw_text or ""

        if is_suitable_earning_post(post_text):
            return channel, message

    return channel, None


async def forward_original_post(event, channel, channel_message):
    await telegram_client.forward_messages(
        entity=event.chat_id,
        messages=channel_message,
        from_peer=channel,
    )


async def handle_specific_app_request(event, app_name):
    try:
        channel, channel_message = await search_specific_app_post(app_name)

        if channel_message:
            await forward_original_post(
                event,
                channel,
                channel_message,
            )

            await event.respond(
                f"I found a post mentioning '{app_name}' on the official channel. "
                "The original post is forwarded above. Please check the post "
                "for the available details.",
                link_preview=False,
            )

            logger.info(
                "Forwarded official channel post for app: %s",
                app_name,
            )
            return True

        await event.respond(
            f"I could not find '{app_name}' on the official channel "
            f"https://t.me/{OFFICIAL_CHANNEL}. "
            "It is not listed there, so I cannot verify it using the official channel.",
            link_preview=False,
        )

        logger.info(
            "App not found on official channel: %s",
            app_name,
        )
        return True

    except (
        ChannelPrivateError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    ):
        logger.exception("Cannot access the official channel")

        await event.respond(
            "I could not access the official channel to check this app. "
            "I cannot verify it right now.",
            link_preview=False,
        )
        return True

    except Exception:
        logger.exception("Specific app channel search failed")

        await event.respond(
            "I could not complete the official channel search right now. "
            "Please try again later.",
            link_preview=False,
        )
        return True


async def handle_generic_earning_request(event):
    try:
        channel, channel_message = await search_generic_earning_post()

        if channel_message:
            await forward_original_post(
                event,
                channel,
                channel_message,
            )

            await event.respond(
                "Here is an earning-related post from the official channel. "
                "Please check the original post for its details.",
                link_preview=False,
            )

            logger.info("Forwarded a generic earning-related channel post")
            return True

        await event.respond(
            "I could not find a suitable earning-app post on the official channel "
            f"https://t.me/{OFFICIAL_CHANNEL}.",
            link_preview=False,
        )

        logger.info("No suitable earning post found in official channel")
        return True

    except (
        ChannelPrivateError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    ):
        logger.exception("Cannot access the official channel")

        await event.respond(
            "I could not access the official channel to find an earning app. "
            "Please try again later.",
            link_preview=False,
        )
        return True

    except Exception:
        logger.exception("Generic earning app channel search failed")

        await event.respond(
            "I could not search the official channel right now. "
            "Please try again later.",
            link_preview=False,
        )
        return True


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

        last_replied[user_id] = current_time

        try:
            specific_app_name = extract_specific_app_name(incoming_text)

            if specific_app_name:
                handled = await handle_specific_app_request(
                    event,
                    specific_app_name,
                )

                if handled:
                    return

            if is_generic_earning_app_request(incoming_text):
                handled = await handle_generic_earning_request(event)

                if handled:
                    return

            reply_text = await generate_ai_reply(
                user_id=user_id,
                incoming_text=incoming_text,
            )

        except Exception:
            logger.exception("Message processing failed")
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
