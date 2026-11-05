# ============================================================
# PERSONAL TELEGRAM AUTO REPLY
# PART 1/4 — IMPORTS, CONFIGURATION & AI HELPER
# ============================================================

import os
import re
import time
import json
import asyncio
import logging

from collections import defaultdict
from typing import Optional

from aiohttp import web

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
from aiogram.exceptions import TelegramConflictError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from openai import AsyncOpenAI


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("PersonalTelegramAutoReply")


# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================

def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Required environment variable is missing: {name}"
        )

    return value


def get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise RuntimeError(
            f"Environment variable {name} must be an integer."
        )


API_ID = get_int_env("API_ID", 0)

if API_ID <= 0:
    raise RuntimeError("API_ID must be a positive integer.")

API_HASH = get_required_env("API_HASH")
SESSION_STRING = get_required_env("SESSION_STRING")

OPENAI_API_KEY = get_required_env("OPENAI_API_KEY")

# Use a model name supported by your OpenAI API account.
AI_MODEL = os.getenv("AI_MODEL", "gpt-6-luna").strip()

BOT_TOKEN = get_required_env("BOT_TOKEN")

OWNER_ID = get_int_env("OWNER_ID", 0)

if OWNER_ID <= 0:
    raise RuntimeError("OWNER_ID must be a positive integer.")

OFFICIAL_CHANNEL = os.getenv(
    "OFFICIAL_CHANNEL",
    "https://t.me/Trusted_Money_India",
).strip()

REPLY_COOLDOWN_SECONDS = get_int_env(
    "REPLY_COOLDOWN_SECONDS",
    60,
)

PORT = get_int_env("PORT", 10000)

if REPLY_COOLDOWN_SECONDS < 0:
    raise RuntimeError(
        "REPLY_COOLDOWN_SECONDS cannot be negative."
    )

if not AI_MODEL:
    raise RuntimeError("AI_MODEL cannot be empty.")


# ============================================================
# CLIENTS
# ============================================================

telegram_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
)

admin_bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    ),
)

admin_dp = Dispatcher()


# ============================================================
# GLOBAL SETTINGS
# ============================================================

# These settings are currently in memory.
# They reset when the Render service restarts.

auto_reply_enabled = True
ai_reply_enabled = True

DEFAULT_INSTRUCTIONS = """
You are an intelligent, helpful Telegram assistant.

Respond naturally to ordinary conversations and general questions.
Do not restrict replies to greetings or a small list of predefined phrases.

Reply in the language used by the sender:
- If the sender writes in English, reply in English.
- If the sender writes in Bengali, reply in Bengali.
- If the sender uses another language, try to reply in that language.

Be accurate, polite, clear, and concise.
Never invent facts, app details, links, or verification claims.

When a question is about a specific earning app, the app lookup
system in the later code parts will handle official-channel checking.
Do not claim an app is verified unless the channel lookup confirms it.
""".strip()

ai_instructions = DEFAULT_INSTRUCTIONS

# Stores recent conversation messages for each Telegram user.
user_history = defaultdict(list)

# Stores the most recent reply time for each user.
last_replied = {}

# Prevents simultaneous processing of messages from the same user.
sender_locks = {}

MAX_HISTORY_MESSAGES = 8

# Used later by the official-channel app lookup system.
CHANNEL_POST_SCAN_LIMIT = 300


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(text: Optional[str]) -> str:
    """
    Normalize text for matching and routing.
    """
    if not text:
        return ""

    text = text.casefold().strip()
    text = re.sub(r"\s+", " ", text)

    return text


def get_sender_lock(sender_id: int) -> asyncio.Lock:
    """
    Return a lock dedicated to the specified sender.
    """
    lock = sender_locks.get(sender_id)

    if lock is None:
        lock = asyncio.Lock()
        sender_locks[sender_id] = lock

    return lock


def cooldown_is_over(sender_id: int) -> bool:
    """
    Return True if the sender's cooldown has expired.
    """
    last_reply_time = last_replied.get(sender_id, 0)

    return (
        time.time() - last_reply_time
        >= REPLY_COOLDOWN_SECONDS
    )


def record_reply_time(sender_id: int) -> None:
    """
    Record the time when a reply was sent.
    """
    last_replied[sender_id] = time.time()


# ============================================================
# AI CLIENT
# ============================================================

ai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    timeout=45.0,
    max_retries=2,
)


# ============================================================
# AI CONVERSATION HELPER
# ============================================================

async def generate_ai_reply(
    sender_id: int,
    incoming_text: str,
) -> str:
    """
    Generate a conversational AI reply using recent user history.
    """

    incoming_text = (incoming_text or "").strip()

    if not incoming_text:
        return "Please send a text message so I can help."

    if not ai_reply_enabled:
        return ""

    history = user_history[sender_id]

    # Keep only the latest configured number of messages.
    history = history[-MAX_HISTORY_MESSAGES:]

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

    try:
        response = await ai_client.chat.completions.create(
    model=AI_MODEL,
    messages=messages,
        )
        )

        reply_text = (
            response.choices[0].message.content or ""
        ).strip()

        if not reply_text:
            reply_text = (
                "Sorry, I couldn't prepare a response. "
                "Please try again."
            )

        # Save the current user message and AI response.
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

        # Keep history bounded to avoid unlimited growth.
        user_history[sender_id] = history[
            -(MAX_HISTORY_MESSAGES * 2):
        ]

        return reply_text

    except Exception:
        logger.exception(
            "AI reply generation failed for sender_id=%s",
            sender_id,
        )

        return (
            "Sorry, I'm temporarily unable to generate a reply. "
            "Please try again shortly."
        )


# ============================================================
# END OF PART 1/4
# ============================================================
# ============================================================
# PERSONAL TELEGRAM AUTO REPLY
# PART 2/4 — APP DETECTION & OFFICIAL CHANNEL LOOKUP
# ============================================================


# ============================================================
# APP LOOKUP MESSAGES
# ============================================================

APP_NOT_FOUND_MESSAGE = (
    "ℹ️ This app is not listed on our official channel "
    "(@Trusted_Money_India). I don't have verified details "
    "or a verified registration link for it."
)

APP_LISTED_MESSAGE = (
    "✅ Listed on our official channel. Please review the "
    "complete details and registration link above."
)

CHANNEL_CHECK_ERROR_MESSAGE = (
    "⚠️ I couldn't check our official channel right now "
    "because of a temporary technical issue. "
    "Please try again shortly."
)

NO_RECENT_APP_POST_MESSAGE = (
    "ℹ️ I couldn't find a suitable recent app listing on "
    "our official channel. I won't invent app details or links."
)


# ============================================================
# APP-RELATED WORDS
# ============================================================

APP_TERMS = {
    "app",
    "application",
    "earning",
    "earn",
    "withdraw",
    "withdrawal",
    "payment",
    "reward",
    "rewards",
    "task",
    "tasks",
    "registration",
    "register",
    "referral",
    "refer",
    "verified",
    "verification",
    "listed",
    "listing",
    "income",
    "money",
}


# These phrases clearly ask for a general app recommendation/listing.
GENERIC_APP_REQUEST_PATTERNS = [
    r"\b( suggest|recommend|show|find|share|give)\b.*\b(apps?|earning apps?|"
    r"verified apps?|trusted apps?|earning websites?)\b",
    r"\b(any|some|latest|new|recent)\b.*\b(apps?|earning apps?|"
    r"verified apps?|trusted apps?)\b",
    r"\b(apps?|earning apps?|verified apps?|trusted apps?)\b.*"
    r"\b(available|listed|verified|latest|new|recent)\b",
    r"\bshow\s+me\s+(an?\s+)?(earning\s+)?app\b",
]


# Explicitly conversational phrases should never be treated as app names.
COMMON_CONVERSATION_PATTERNS = [
    r"^(hi|hello|hey|hii+|helo+)[!. ]*$",
    r"^(good morning|good afternoon|good evening|good night)[!. ]*$",
    r"^(how are you|how r u|how are u)[?! .]*$",
    r"^(what's up|whats up|sup)[?! .]*$",
    r"^(thank you|thanks|thank u|thx)[!. ]*$",
    r"^(ok|okay|alright|sure|yes|no|yeah|yep|nope)[!. ]*$",
    r"^(bye|goodbye|see you|see ya)[!. ]*$",
    r"^(who are you|what are you|what can you do)[?! .]*$",
    r"^(help|please help)[!. ]*$",
]


# Explicit app lookup requests.
SPECIFIC_APP_REQUEST_PATTERNS = [
    r"\b(is|are)\b.+\b(app|application)\b.+\b(verified|listed|trusted|official)\b",
    r"\b(app|application)\b.+\b(verified|listed|trusted|official)\b",
    r"\b(about|details|information|info|review)\b.+\b(app|application)\b",
    r"\b(does|do)\b.+\b(app|application)\b.+\b(pay|paying|earn|earning|withdraw)\b",
    r"\b(can|how)\b.+\b(app|application)\b.+\b(earn|earning|withdraw|payment)\b",
    r"\b(app|application)\b.+\b(payment|withdrawal|earning|reward|referral)\b",
]


# ============================================================
# CONVERSATION / APP INTENT DETECTION
# ============================================================

def is_common_conversation(text: str) -> bool:
    """
    Detect common conversational messages.
    These must go to normal AI conversation, not app lookup.
    """

    normalized = normalize_text(text)

    if not normalized:
        return True

    for pattern in COMMON_CONVERSATION_PATTERNS:
        if re.search(pattern, normalized):
            return True

    return False


def is_generic_app_request(text: str) -> bool:
    """
    Detect requests for a general/recent/verified app listing.
    """

    normalized = normalize_text(text)

    if not normalized or is_common_conversation(normalized):
        return False

    for pattern in GENERIC_APP_REQUEST_PATTERNS:
        if re.search(pattern, normalized):
            return True

    return False


def is_specific_app_request(text: str) -> bool:
    """
    Detect explicit requests about a particular app.

    Important:
    A short ordinary message is NOT automatically an app name.
    """

    normalized = normalize_text(text)

    if not normalized or is_common_conversation(normalized):
        return False

    has_app_term = any(
        term in normalized.split()
        for term in APP_TERMS
    )

    if not has_app_term:
        return False

    for pattern in SPECIFIC_APP_REQUEST_PATTERNS:
        if re.search(pattern, normalized):
            return True

    # Example: "XYZ app" or "XYZ earning app"
    # This is considered an app-related query, but not every
    # short standalone word is treated as an app name.
    if re.search(
        r"\b[\w.-]+\s+(earning\s+)?(app|application)\b",
        normalized,
    ):
        return True

    return False


# ============================================================
# APP NAME EXTRACTION
# ============================================================

APP_QUERY_PREFIXES = [
    "is ",
    "are ",
    "tell me about ",
    "what about ",
    "what is ",
    "details of ",
    "details about ",
    "information about ",
    "info about ",
    "review ",
    "check ",
    "find ",
    "search ",
    "show ",
    "please check ",
    "please find ",
]

APP_QUERY_SUFFIXES = [
    " app",
    " application",
    " earning app",
    " earning application",
    " is it verified",
    " is it listed",
    " verified",
    " listed",
    " trusted",
    " official",
    " details",
    " information",
    " info",
    " review",
    " payment proof",
    " withdrawal",
    " earning",
]


def extract_app_name(text: str) -> str:
    """
    Extract a likely app name from an explicit app-related query.

    Examples:
        "Is XYZ app verified?" -> "XYZ"
        "Tell me about XYZ earning app" -> "XYZ"
        "XYZ app details" -> "XYZ"
    """

    value = (text or "").strip()

    if not value:
        return ""

    value = re.sub(r"[?!.,:;]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    normalized = value.casefold()

    # Remove common question prefixes.
    for prefix in APP_QUERY_PREFIXES:
        if normalized.startswith(prefix):
            value = value[len(prefix):].strip()
            normalized = value.casefold()
            break

    # Remove common app-related suffixes.
    for suffix in sorted(
        APP_QUERY_SUFFIXES,
        key=len,
        reverse=True,
    ):
        if normalized.endswith(suffix):
            value = value[:-len(suffix)].strip()
            normalized = value.casefold()
            break

    # Remove leftover conversational/question wording.
    value = re.sub(
        r"^(please\s+)?(check|find|search|tell me about|what about)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    value = re.sub(
        r"\s+(is it|is this|verified|listed|trusted|official)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    value = re.sub(r"\s+", " ", value).strip(" -")

    return value


# ============================================================
# OFFICIAL CHANNEL RESOLUTION
# ============================================================

async def get_official_channel():
    """
    Resolve the configured official Telegram channel.

    Raises an exception if Telegram cannot resolve/access it.
    The caller must distinguish this from an app not being found.
    """

    channel_reference = OFFICIAL_CHANNEL.strip()

    if not channel_reference:
        raise RuntimeError("OFFICIAL_CHANNEL is not configured.")

    return await telegram_client.get_entity(channel_reference)


# ============================================================
# CHANNEL POST MATCHING
# ============================================================

def get_channel_message_text(message) -> str:
    """
    Return searchable text from a channel post.
    Supports text and media captions.
    """

    text = getattr(message, "raw_text", None)

    if not text:
        text = getattr(message, "message", None)

    return (text or "").strip()


def normalize_app_name_for_match(app_name: str) -> str:
    """
    Normalize app names for channel matching.
    """

    normalized = normalize_text(app_name)

    normalized = re.sub(
        r"[^a-z0-9\u0980-\u09ff]+",
        " ",
        normalized,
    )

    return re.sub(r"\s+", " ", normalized).strip()


def app_name_matches_post(app_name: str, post_text: str) -> bool:
    """
    Check whether the requested app name appears in a channel post.
    """

    normalized_app = normalize_app_name_for_match(app_name)
    normalized_post = normalize_app_name_for_match(post_text)

    if not normalized_app or not normalized_post:
        return False

    # Exact normalized phrase match.
    if normalized_app in normalized_post:
        return True

    # For multi-word names, require all meaningful name tokens.
    app_tokens = normalized_app.split()

    if len(app_tokens) >= 2:
        return all(token in normalized_post.split() for token in app_tokens)

    return False


# ============================================================
# SEARCH OFFICIAL CHANNEL FOR A SPECIFIC APP
# ============================================================

async def find_app_post(app_name: str):
    """
    Search only the configured official channel.

    Returns:
        Telegram Message if found
        None if search completed but no matching post exists

    Raises:
        Exception if the channel cannot be checked
    """

    if not app_name:
        return None

    channel = await get_official_channel()

    async for message in telegram_client.iter_messages(
        channel,
        limit=CHANNEL_POST_SCAN_LIMIT,
    ):
        post_text = get_channel_message_text(message)

        if not post_text:
            continue

        if app_name_matches_post(app_name, post_text):
            return message

    return None


# ============================================================
# FORWARD ORIGINAL CHANNEL POST
# ============================================================

async def forward_channel_post(
    sender_id: int,
    channel_message,
) -> bool:
    """
    Forward the complete original channel post to the sender.

    Telethon forwarding preserves the original post's text/media
    instead of rebuilding it from extracted text.
    """

    try:
        channel = await get_official_channel()

        await telegram_client.forward_messages(
            entity=event.chat_id,
            messages=channel_message,
            from_peer=channel,
        )

        await event.respond(
            reply_text,
            link_preview=False,
        )

        return True

    except Exception:
        logger.exception("Error while forwarding channel post")
        return False

# ============================================================
# HANDLE SPECIFIC APP LOOKUP
# ============================================================

async def handle_specific_app_lookup(
    sender_id: int,
    incoming_text: str,
) -> None:
    """
    Check a specific app only against the official channel.
    """

    app_name = extract_app_name(incoming_text)

    if not app_name:
        await telegram_client.send_message(
            sender_id,
            (
                "Please send the app's name clearly so I can "
                "check it on our official channel."
            ),
            link_preview=False,
        )
        return

    try:
        channel_message = await find_app_post(app_name)

    except Exception:
        logger.exception(
            "Official channel lookup failed for app=%r",
            app_name,
        )

        await telegram_client.send_message(
            sender_id,
            CHANNEL_CHECK_ERROR_MESSAGE,
            link_preview=False,
        )
        return

    if channel_message is None:
        await telegram_client.send_message(
            sender_id,
            APP_NOT_FOUND_MESSAGE,
            link_preview=False,
        )
        return

    forwarded = await forward_channel_post(
        sender_id,
        channel_message,
    )

    if not forwarded:
        await telegram_client.send_message(
            sender_id,
            CHANNEL_CHECK_ERROR_MESSAGE,
            link_preview=False,
        )


# ============================================================
# GENERIC APP REQUEST MATCHING
# ============================================================

GENERIC_APP_POST_KEYWORDS = {
    "earning",
    "app",
    "application",
    "reward",
    "rewards",
    "task",
    "tasks",
    "payment",
    "withdrawal",
    "referral",
    "register",
    "registration",
    "income",
}


def is_likely_app_listing_post(post_text: str) -> bool:
    """
    Basic filter to avoid forwarding unrelated channel posts.
    """

    normalized = normalize_text(post_text)

    if not normalized:
        return False

    words = set(re.findall(r"\b[\w]+\b", normalized))

    return len(words.intersection(GENERIC_APP_POST_KEYWORDS)) >= 2


async def find_recent_app_post():
    """
    Find a recent app-related post in the official channel.

    Returns:
        Telegram Message if a suitable post is found
        None if no suitable post is found

    Raises:
        Exception if channel access/search fails
    """

    channel = await get_official_channel()

    async for message in telegram_client.iter_messages(
        channel,
        limit=CHANNEL_POST_SCAN_LIMIT,
    ):
        post_text = get_channel_message_text(message)

        if not post_text:
            continue

        if is_likely_app_listing_post(post_text):
            return message

    return None


# ============================================================
# HANDLE GENERIC APP REQUEST
# ============================================================

async def handle_generic_app_request(
    sender_id: int,
) -> None:
    """
    Forward a suitable recent app listing from the official channel.
    Never fabricate a listing.
    """

    try:
        channel_message = await find_recent_app_post()

    except Exception:
        logger.exception(
            "Official channel search failed for generic app request."
        )

        await telegram_client.send_message(
            sender_id,
            CHANNEL_CHECK_ERROR_MESSAGE,
            link_preview=False,
        )
        return

    if channel_message is None:
        await telegram_client.send_message(
            sender_id,
            NO_RECENT_APP_POST_MESSAGE,
            link_preview=False,
        )
        return

    forwarded = await forward_channel_post(
        sender_id,
        channel_message,
    )

    if not forwarded:
        await telegram_client.send_message(
            sender_id,
            CHANNEL_CHECK_ERROR_MESSAGE,
            link_preview=False,
        )


# ============================================================
# END OF PART 2/4
# ============================================================
# ============================================================
# PERSONAL TELEGRAM AUTO REPLY
# PART 3/4 — PERSONAL MESSAGE HANDLER
# ============================================================


# ============================================================
# PERSONAL MESSAGE HANDLER
# ============================================================

@telegram_client.on(events.NewMessage(incoming=True))
async def personal_message_handler(event):
    """
    Handle incoming private messages sent to the connected
    personal Telegram account.
    """

    try:
        # Only handle private conversations.
        if not event.is_private:
            return

        # Ignore messages sent by the connected account.
        if event.out:
            return

        sender_id = event.sender_id

        if not sender_id:
            return

        incoming_text = (event.raw_text or "").strip()

        # Ignore empty text messages.
        if not incoming_text:
            return

        # ----------------------------------------------------
        # AUTO REPLY MASTER SWITCH
        # ----------------------------------------------------

        if not auto_reply_enabled:
            logger.info(
                "Auto Reply is OFF. Ignoring sender_id=%s",
                sender_id,
            )
            return

        # ----------------------------------------------------
        # PER-SENDER LOCK
        # ----------------------------------------------------

        lock = get_sender_lock(sender_id)

        async with lock:

            # ------------------------------------------------
            # COOLDOWN
            # ------------------------------------------------

            if not cooldown_is_over(sender_id):
                logger.info(
                    "Cooldown active for sender_id=%s",
                    sender_id,
                )
                return

            # ------------------------------------------------
            # ROUTING 1: GENERAL APP RECOMMENDATION
            # ------------------------------------------------

            if is_generic_app_request(incoming_text):

                await handle_generic_app_request(sender_id)

                record_reply_time(sender_id)
                return

            # ------------------------------------------------
            # ROUTING 2: SPECIFIC APP LOOKUP
            # ------------------------------------------------

            if is_specific_app_request(incoming_text):

                await handle_specific_app_lookup(
                    sender_id,
                    incoming_text,
                )

                record_reply_time(sender_id)
                return

            # ------------------------------------------------
            # ROUTING 3: NORMAL AI CONVERSATION
            # ------------------------------------------------

            if not ai_reply_enabled:
                logger.info(
                    "AI Reply is OFF. Ignoring sender_id=%s",
                    sender_id,
                )
                return

            reply_text = await generate_ai_reply(
                sender_id=sender_id,
                incoming_text=incoming_text,
            )

            if not reply_text:
                return

            await telegram_client.send_message(
                entity=sender_id,
                message=reply_text,
                link_preview=False,
            )

            record_reply_time(sender_id)

            logger.info(
                "AI reply sent successfully to sender_id=%s",
                sender_id,
            )

    except Exception:
        logger.exception(
            "Unexpected error in personal_message_handler"
        )


# ============================================================
# END OF PART 3/4
# ============================================================
# ============================================================
# PERSONAL TELEGRAM AUTO REPLY
# PART 4/4 — ADMIN PANEL, HEALTH CHECK & STARTUP
# ============================================================

import html


# ============================================================
# ADMIN PANEL STATE
# ============================================================

awaiting_admin_instructions = False


# ============================================================
# ADMIN KEYBOARD
# ============================================================

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """
    Build the admin control panel keyboard.
    """

    auto_reply_label = (
        "🟢 Auto Reply: ON"
        if auto_reply_enabled
        else "🔴 Auto Reply: OFF"
    )

    ai_reply_label = (
        "🟢 AI Reply: ON"
        if ai_reply_enabled
        else "🔴 AI Reply: OFF"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=auto_reply_label,
                    callback_data="admin_toggle_auto",
                )
            ],
            [
                InlineKeyboardButton(
                    text=ai_reply_label,
                    callback_data="admin_toggle_ai",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Status",
                    callback_data="admin_status",
                ),
                InlineKeyboardButton(
                    text="📝 Instructions",
                    callback_data="admin_instructions",
                ),
            ],
        ]
    )


# ============================================================
# ADMIN STATUS TEXT
# ============================================================

def get_admin_status_text() -> str:
    """
    Return current settings for the owner.
    """

    auto_status = "🟢 ON" if auto_reply_enabled else "🔴 OFF"
    ai_status = "🟢 ON" if ai_reply_enabled else "🔴 OFF"

    return (
        "<b>Personal Telegram Auto Reply</b>\n\n"
        f"<b>Auto Reply:</b> {auto_status}\n"
        f"<b>AI Reply:</b> {ai_status}\n"
        f"<b>Cooldown:</b> {REPLY_COOLDOWN_SECONDS} seconds\n"
        f"<b>AI Model:</b> <code>{html.escape(AI_MODEL)}</code>\n"
        f"<b>Official Channel:</b> "
        f"<code>{html.escape(OFFICIAL_CHANNEL)}</code>\n"
        f"<b>Users with history:</b> {len(user_history)}"
    )


# ============================================================
# ADMIN AUTHORIZATION
# ============================================================

def is_owner(user_id: Optional[int]) -> bool:
    """
    Allow admin actions only from the configured owner.
    """

    return user_id is not None and user_id == OWNER_ID


# ============================================================
# /admin COMMAND
# ============================================================

@admin_dp.message(Command("admin"))
async def admin_command(message: Message):
    """
    Open the admin panel.
    """

    if not is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ You are not authorized to use this panel.")
        return

    await message.answer(
        get_admin_status_text(),
        reply_markup=get_admin_keyboard(),
    )


# ============================================================
# /status COMMAND
# ============================================================

@admin_dp.message(Command("status"))
async def admin_status_command(message: Message):
    """
    Show current admin status.
    """

    if not is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Unauthorized.")
        return

    await message.answer(
        get_admin_status_text(),
        reply_markup=get_admin_keyboard(),
    )


# ============================================================
# TOGGLE AUTO REPLY
# ============================================================

@admin_dp.callback_query(F.data == "admin_toggle_auto")
async def admin_toggle_auto_callback(callback: CallbackQuery):
    """
    Toggle the master Auto Reply switch.
    """

    global auto_reply_enabled

    if not is_owner(callback.from_user.id):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    auto_reply_enabled = not auto_reply_enabled

    await callback.answer(
        "Auto Reply enabled."
        if auto_reply_enabled
        else "Auto Reply disabled."
    )

    if callback.message:
        await callback.message.edit_text(
            get_admin_status_text(),
            reply_markup=get_admin_keyboard(),
        )


# ============================================================
# TOGGLE AI REPLY
# ============================================================

@admin_dp.callback_query(F.data == "admin_toggle_ai")
async def admin_toggle_ai_callback(callback: CallbackQuery):
    """
    Toggle the AI Reply switch.
    """

    global ai_reply_enabled

    if not is_owner(callback.from_user.id):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    ai_reply_enabled = not ai_reply_enabled

    await callback.answer(
        "AI Reply enabled."
        if ai_reply_enabled
        else "AI Reply disabled."
    )

    if callback.message:
        await callback.message.edit_text(
            get_admin_status_text(),
            reply_markup=get_admin_keyboard(),
        )


# ============================================================
# STATUS BUTTON
# ============================================================

@admin_dp.callback_query(F.data == "admin_status")
async def admin_status_callback(callback: CallbackQuery):
    """
    Refresh status information.
    """

    if not is_owner(callback.from_user.id):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    await callback.answer("Status refreshed.")

    if callback.message:
        await callback.message.edit_text(
            get_admin_status_text(),
            reply_markup=get_admin_keyboard(),
        )


# ============================================================
# INSTRUCTIONS BUTTON
# ============================================================

@admin_dp.callback_query(F.data == "admin_instructions")
async def admin_instructions_callback(callback: CallbackQuery):
    """
    Ask the owner to send new AI instructions.
    """

    global awaiting_admin_instructions

    if not is_owner(callback.from_user.id):
        await callback.answer("Unauthorized.", show_alert=True)
        return

    awaiting_admin_instructions = True

    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "📝 Send the new AI instructions in your next message.\n\n"
            "The instructions will replace the current AI instructions."
        )


# ============================================================
# RECEIVE NEW ADMIN INSTRUCTIONS
# ============================================================

@admin_dp.message(F.text)
async def receive_admin_text(message: Message):
    """
    Receive new AI instructions from the owner.

    Other users' admin-bot messages are ignored.
    """

    global ai_instructions
    global awaiting_admin_instructions

    user_id = message.from_user.id if message.from_user else None

    if not is_owner(user_id):
        return

    if not awaiting_admin_instructions:
        return

    new_instructions = (message.text or "").strip()

    if not new_instructions:
        await message.answer(
            "⚠️ Instructions cannot be empty. Please send them again."
        )
        return

    if len(new_instructions) > 12000:
        await message.answer(
            "⚠️ Instructions are too long. Please keep them under "
            "12,000 characters."
        )
        return

    ai_instructions = new_instructions
    awaiting_admin_instructions = False

    await message.answer(
        "✅ AI instructions updated.\n\n"
        "The new instructions are now active.",
        reply_markup=get_admin_keyboard(),
    )


# ============================================================
# HEALTH CHECK
# ============================================================

async def health_check(request: web.Request) -> web.Response:
    """
    Render health endpoint.
    """

    return web.Response(
        text="PersonalTelegramAutoReply is running!",
        status=200,
    )


async def start_health_server():
    """
    Start the aiohttp health server for Render.
    """

    app = web.Application()

    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info(
        "Health server started on port %s",
        PORT,
    )

    return runner


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

async def main():
    """
    Start the personal Telegram client, admin bot, and health server.
    """

    health_runner = None

    try:
        logger.info("Starting PersonalTelegramAutoReply...")

        # Start the personal Telegram account.
        await telegram_client.start()

        logger.info(
            "Personal Telegram account connected."
        )

        # Start Render health endpoint.
        health_runner = await start_health_server()

        # Run the admin bot polling task.
        logger.info("Starting admin bot polling...")

        await admin_dp.start_polling(
            admin_bot,
            allowed_updates=admin_dp.resolve_used_update_types(),
        )

    except TelegramConflictError:
        logger.exception(
            "Admin bot polling conflict. "
            "Make sure another instance is not polling this bot."
        )

    except Exception:
        logger.exception(
            "Fatal error while running PersonalTelegramAutoReply."
        )

    finally:
        logger.info("Shutting down PersonalTelegramAutoReply...")

        # Stop the admin bot session.
        try:
            await admin_dp.stop_polling()
        except Exception:
            pass

        try:
            await admin_bot.session.close()
        except Exception:
            pass

        # Disconnect the personal Telegram account.
        try:
            if telegram_client.is_connected():
                await telegram_client.disconnect()
        except Exception:
            logger.exception(
                "Error while disconnecting personal Telegram client."
            )

        # Stop health server.
        if health_runner is not None:
            try:
                await health_runner.cleanup()
            except Exception:
                logger.exception(
                    "Error while stopping health server."
                )

        # Close OpenAI client.
        try:
            await ai_client.close()
        except Exception:
            logger.exception(
                "Error while closing OpenAI client."
            )

        logger.info(
            "PersonalTelegramAutoReply stopped."
        )


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info(
            "Application stopped manually."
        )

# ============================================================
# END OF PART 4/4
# ============================================================
