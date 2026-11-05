import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ==================================================
# CONFIGURATION
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

if OWNER_ID <= 0:
    raise RuntimeError("OWNER_ID environment variable is missing or invalid.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

# ==================================================
# SETTINGS
# ==================================================

SETTINGS_FILE = Path("settings.json")

DEFAULT_SETTINGS = {
    "enabled": True,
    "language": "English",
    "reply_message": (
        "👋 Hello! Thanks for messaging me.\n\n"
        "I'm currently unavailable, but I'll reply as soon as possible. 😊"
    ),
    "reply_mode": "all",
    "delay_seconds": 0,
    "keyword_replies": {},
    "total_received": 0,
    "total_replied": 0,
}


def load_settings():
    if not SETTINGS_FILE.exists():
        return DEFAULT_SETTINGS.copy()

    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            saved = json.load(file)

        settings_data = DEFAULT_SETTINGS.copy()
        settings_data.update(saved)

        if not isinstance(settings_data.get("keyword_replies"), dict):
            settings_data["keyword_replies"] = {}

        return settings_data

    except (json.JSONDecodeError, OSError):
        logger.exception("Could not load settings.json")
        return DEFAULT_SETTINGS.copy()


settings = load_settings()

# Stores the next expected input from the admin
admin_input_mode = {}


def save_settings():
    try:
        with SETTINGS_FILE.open("w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
    except OSError:
        logger.exception("Could not save settings.json")


# ==================================================
# KEYBOARDS
# ==================================================

def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Turn ON",
                    callback_data="admin_enable",
                ),
                InlineKeyboardButton(
                    text="🔴 Turn OFF",
                    callback_data="admin_disable",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Set Reply Message",
                    callback_data="admin_set_reply",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Select Language",
                    callback_data="admin_language",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Reply Mode",
                    callback_data="admin_reply_mode",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔑 Keyword Replies",
                    callback_data="admin_keywords",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏱ Reply Delay",
                    callback_data="admin_delay",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👁 Preview Reply",
                    callback_data="admin_preview",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Statistics",
                    callback_data="admin_stats",
                ),
            ],
        ]
    )


def language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="lang_English",
                ),
                InlineKeyboardButton(
                    text="🇮🇳 Hindi",
                    callback_data="lang_Hindi",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇧🇩 Bengali",
                    callback_data="lang_Bengali",
                ),
                InlineKeyboardButton(
                    text="🌍 Custom",
                    callback_data="lang_Custom",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back to Admin Panel",
                    callback_data="admin_home",
                ),
            ],
        ]
    )


def reply_mode_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 Reply to All Messages",
                    callback_data="mode_all",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔑 Reply to Keywords Only",
                    callback_data="mode_keywords",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back to Admin Panel",
                    callback_data="admin_home",
                ),
            ],
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Back to Admin Panel",
                    callback_data="admin_home",
                ),
            ],
        ]
    )


# ==================================================
# ADMIN HELPERS
# ==================================================

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID


def admin_status_text():
    status = "🟢 ON" if settings["enabled"] else "🔴 OFF"

    return (
        "⚙️ <b>AUTO-REPLY ADMIN PANEL</b>\n\n"
        f"📡 Status: <b>{status}</b>\n"
        f"🌐 Language: <b>{settings['language']}</b>\n"
        f"🎯 Reply Mode: <b>{settings['reply_mode'].title()}</b>\n"
        f"⏱ Delay: <b>{settings['delay_seconds']} seconds</b>\n\n"
        "Select an option below:"
    )


async def show_admin_panel(message: Message):
    await message.answer(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


# ==================================================
# START & COMMANDS
# ==================================================

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "🤖 <b>24x7 Reply Assistant</b>\n\n"
        "This bot provides automatic replies.\n\n"
        "Use /help to see available commands."
    )


@router.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "📘 <b>Available Commands</b>\n\n"
        "/start — Start the bot\n"
        "/help — Show help\n"
        "/admin — Open Admin Panel"
    )


@router.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    await show_admin_panel(message)


@router.message(Command("on"))
async def turn_on_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    settings["enabled"] = True
    save_settings()
    await message.answer("🟢 Auto-Reply enabled.")


@router.message(Command("off"))
async def turn_off_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    settings["enabled"] = False
    save_settings()
    await message.answer("🔴 Auto-Reply disabled.")


@router.message(Command("setreply"))
async def set_reply_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    new_reply = message.text.partition(" ")[2].strip()

    if not new_reply:
        admin_input_mode[message.from_user.id] = "reply"
        await message.answer(
            "💬 Send your new Auto-Reply message.",
            reply_markup=back_keyboard(),
        )
        return

    settings["reply_message"] = new_reply
    save_settings()
    await message.answer("✅ Auto-Reply message updated.")


@router.message(Command("setdelay"))
async def set_delay_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    value = message.text.partition(" ")[2].strip()

    if not value:
        admin_input_mode[message.from_user.id] = "delay"
        await message.answer(
            "⏱ Send delay in seconds (0–3600).",
            reply_markup=back_keyboard(),
        )
        return

    try:
        delay = int(value)
        if not 0 <= delay <= 3600:
            raise ValueError
    except ValueError:
        await message.answer("Enter a number between 0 and 3600.")
        return

    settings["delay_seconds"] = delay
    save_settings()
    await message.answer(f"✅ Reply delay set to {delay} seconds.")


@router.message(Command("addkeyword"))
async def add_keyword_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    content = message.text.partition(" ")[2].strip()

    if "|" not in content:
        await message.answer(
            "Use:\n<code>/addkeyword keyword | reply message</code>"
        )
        return

    keyword, reply = content.split("|", 1)
    keyword = keyword.strip().lower()
    reply = reply.strip()

    if not keyword or not reply:
        await message.answer("Keyword and reply message cannot be empty.")
        return

    settings["keyword_replies"][keyword] = reply
    save_settings()

    await message.answer(f"✅ Keyword reply saved for: <b>{keyword}</b>")


@router.message(Command("delkeyword"))
async def delete_keyword_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return

    keyword = message.text.partition(" ")[2].strip().lower()

    if not keyword:
        await message.answer("Use: <code>/delkeyword keyword</code>")
        return

    if keyword not in settings["keyword_replies"]:
        await message.answer("Keyword not found.")
        return

    del settings["keyword_replies"][keyword]
    save_settings()

    await message.answer(f"🗑 Keyword removed: <b>{keyword}</b>")


# ==================================================
# ADMIN PANEL CALLBACKS
# ==================================================

@router.callback_query(F.data == "admin_home")
async def admin_home_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin_enable")
async def enable_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    settings["enabled"] = True
    save_settings()

    await callback.answer("Auto-Reply enabled.")
    await callback.message.edit_text(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin_disable")
async def disable_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    settings["enabled"] = False
    save_settings()

    await callback.answer("Auto-Reply disabled.")
    await callback.message.edit_text(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin_set_reply")
async def set_reply_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    admin_input_mode[callback.from_user.id] = "reply"

    await callback.answer()
    await callback.message.answer(
        "💬 Send your new Auto-Reply message.\n\n"
        "Your next text message will be saved as the reply.",
        reply_markup=back_keyboard(),
    )


@router.callback_query(F.data == "admin_language")
async def language_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🌐 <b>Select Reply Language</b>",
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang_"))
async def language_select_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    language = callback.data.replace("lang_", "", 1)

    if language not in {"English", "Hindi", "Bengali", "Custom"}:
        await callback.answer("Invalid language.", show_alert=True)
        return

    settings["language"] = language
    save_settings()

    await callback.answer(f"Language set to {language}.")
    await callback.message.edit_text(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin_reply_mode")
async def reply_mode_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🎯 <b>Select Reply Mode</b>",
        reply_markup=reply_mode_keyboard(),
    )


@router.callback_query(F.data.startswith("mode_"))
async def mode_select_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    mode = callback.data.replace("mode_", "", 1)

    if mode not in {"all", "keywords"}:
        await callback.answer("Invalid reply mode.", show_alert=True)
        return

    settings["reply_mode"] = mode
    save_settings()

    await callback.answer("Reply mode updated.")
    await callback.message.edit_text(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin_keywords")
async def keywords_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(
        "🔑 <b>Keyword Replies</b>\n\n"
        "Add a keyword:\n"
        "<code>/addkeyword keyword | reply message</code>\n\n"
        "Example:\n"
        "<code>/addkeyword price | Please check our pricing details.</code>\n\n"
        "Delete a keyword:\n"
        "<code>/delkeyword keyword</code>",
        reply_markup=back_keyboard(),
    )


@router.callback_query(F.data == "admin_delay")
async def delay_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    admin_input_mode[callback.from_user.id] = "delay"

    await callback.answer()
    await callback.message.answer(
        "⏱ Send delay in seconds (0–3600).\n"
        "Send <code>0</code> for no delay.",
        reply_markup=back_keyboard(),
    )


@router.callback_query(F.data == "admin_preview")
async def preview_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(
        "👁 <b>Reply Preview</b>\n\n"
        + settings["reply_message"],
        reply_markup=back_keyboard(),
    )


@router.callback_query(F.data == "admin_stats")
async def stats_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(
        "📊 <b>Auto-Reply Statistics</b>\n\n"
        f"📩 Messages received: <b>{settings['total_received']}</b>\n"
        f"💬 Replies sent: <b>{settings['total_replied']}</b>",
        reply_markup=back_keyboard(),
    )


# ==================================================
# TEXT MESSAGE HANDLER
# ==================================================

@router.message(F.text)
async def text_message_handler(message: Message):
    if message.from_user is None:
        return

    user_id = message.from_user.id

    # Admin input handling
    if is_admin(user_id):
        mode = admin_input_mode.get(user_id)

        if mode == "reply":
            settings["reply_message"] = message.text
            save_settings()
            admin_input_mode.pop(user_id, None)

            await message.answer("✅ Auto-Reply message updated.")
            return

        if mode == "delay":
            try:
                delay = int(message.text.strip())

                if not 0 <= delay <= 3600:
                    raise ValueError

            except ValueError:
                await message.answer(
                    "❌ Invalid delay. Enter a number between 0 and 3600."
                )
                return

            settings["delay_seconds"] = delay
            save_settings()
            admin_input_mode.pop(user_id, None)

            await message.answer(
                f"✅ Reply delay set to {delay} seconds."
            )
            return

    # Auto-Reply only works in private chats
    if message.chat.type != "private":
        return

    # Ignore bot accounts
    if message.from_user.is_bot:
        return

    # Do not auto-reply to the owner
    if is_admin(user_id):
        return

    settings["total_received"] += 1

    if not settings["enabled"]:
        save_settings()
        return

    reply_text = None
    incoming_text = message.text.lower()

    if settings["reply_mode"] == "keywords":
        for keyword, keyword_reply in settings["keyword_replies"].items():
            if keyword.lower() in incoming_text:
                reply_text = keyword_reply
                break

        if reply_text is None:
            save_settings()
            return

    else:
        reply_text = settings["reply_message"]

    delay = settings["delay_seconds"]

    if delay > 0:
        await asyncio.sleep(delay)

    try:
        # Disable HTML parsing for user-defined reply text
        await message.answer(reply_text, parse_mode=None)
        settings["total_replied"] += 1
        save_settings()

    except Exception:
        logger.exception("Failed to send Auto-Reply")


# ==================================================
# START BOT
# ==================================================

async def main():
    logger.info("Starting 24x7 Reply Assistant...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
