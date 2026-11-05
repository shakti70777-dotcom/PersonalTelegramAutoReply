import asyncio
import html
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
from aiogram.exceptions import TelegramBadRequest


# ==================================================
# CONFIGURATION
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

if OWNER_ID <= 0:
    raise RuntimeError("OWNER_ID environment variable is missing or invalid.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
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

admin_input_mode = {}


def load_settings():
    settings_data = DEFAULT_SETTINGS.copy()

    if not SETTINGS_FILE.exists():
        return settings_data

    try:
        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            saved_data = json.load(file)

        if isinstance(saved_data, dict):
            settings_data.update(saved_data)
            # Migrate settings created by earlier versions.
            if "reply_message" not in saved_data and "reply_text" in saved_data:
                settings_data["reply_message"] = saved_data["reply_text"]
            if "delay_seconds" not in saved_data and "delay" in saved_data:
                settings_data["delay_seconds"] = saved_data["delay"]

        if not isinstance(settings_data.get("keyword_replies"), dict):
            settings_data["keyword_replies"] = {}

        if settings_data.get("reply_mode") not in {"all", "keywords"}:
            settings_data["reply_mode"] = "all"

        if not isinstance(settings_data.get("enabled"), bool):
            settings_data["enabled"] = True

        try:
            delay = int(settings_data.get("delay_seconds", 0))
            settings_data["delay_seconds"] = max(0, min(delay, 3600))
        except (TypeError, ValueError):
            settings_data["delay_seconds"] = 0

        for counter in ("total_received", "total_replied"):
            try:
                settings_data[counter] = max(
                    0, int(settings_data.get(counter, 0))
                )
            except (TypeError, ValueError):
                settings_data[counter] = 0

        return settings_data

    except (json.JSONDecodeError, OSError):
        logger.exception("Could not load settings.json")
        return DEFAULT_SETTINGS.copy()


settings = load_settings()


def save_settings():
    try:
        temporary_file = SETTINGS_FILE.with_suffix(".tmp")

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)

        temporary_file.replace(SETTINGS_FILE)

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
                    callback_data="toggle_on",
                ),
                InlineKeyboardButton(
                    text="🔴 Turn OFF",
                    callback_data="toggle_off",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Set Reply Message",
                    callback_data="set_reply",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Select Language",
                    callback_data="set_language",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Reply Mode",
                    callback_data="reply_mode",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔑 Keyword Replies",
                    callback_data="manage_keywords",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏱ Reply Delay",
                    callback_data="set_delay",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👁 Preview Reply",
                    callback_data="preview_reply",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Statistics",
                    callback_data="show_stats",
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
                    callback_data="language_English",
                ),
                InlineKeyboardButton(
                    text="🇮🇳 Hindi",
                    callback_data="language_Hindi",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🇧🇩 Bengali",
                    callback_data="language_Bengali",
                ),
                InlineKeyboardButton(
                    text="🌍 Custom",
                    callback_data="language_Custom",
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
                    text="❌ Cancel",
                    callback_data="cancel_input",
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


# ==================================================
# ADMIN HELPERS
# ==================================================

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID


def admin_status_text():
    status = "🟢 ON" if settings["enabled"] else "🔴 OFF"

    language = html.escape(str(settings["language"]))
    reply_mode = html.escape(str(settings["reply_mode"]).title())
    delay = html.escape(str(settings["delay_seconds"]))

    return (
        "⚙️ <b>AUTO-REPLY ADMIN PANEL</b>\n\n"
        f"📡 Status: <b>{status}</b>\n"
        f"🌐 Language: <b>{language}</b>\n"
        f"🎯 Reply Mode: <b>{reply_mode}</b>\n"
        f"⏱ Delay: <b>{delay} seconds</b>\n\n"
        "Select an option below:"
    )


async def show_admin_panel(message: Message):
    await message.answer(
        admin_status_text(),
        reply_markup=admin_panel_keyboard(),
    )


async def safe_edit_message(
    message: Message,
    text: str,
    reply_markup=None,
):
    if message is None:
        return

    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return
        raise


def clear_admin_input(user_id: int):
    admin_input_mode.pop(user_id, None)
    # ==================================================
# START & COMMANDS
# ==================================================

@router.message(CommandStart())
async def start_command(message: Message):
    if message.from_user is None:
        return

    clear_admin_input(message.from_user.id)

    await message.answer(
        "👋 Welcome to <b>24x7 Reply Assistant</b>!\n\n"
        "This bot can automatically reply to messages sent to this bot.\n\n"
        "Use /help to see available commands."
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "<b>Available Commands</b>\n\n"
        "/start — Start the bot\n"
        "/help — Show help\n"
        "/admin — Open admin panel\n"
        "/on — Enable auto-reply\n"
        "/off — Disable auto-reply\n"
        "/setreply — Change auto-reply message\n"
        "/setdelay — Set reply delay\n"
        "/addkeyword — Add a keyword reply\n"
        "/delkeyword — Delete a keyword reply\n"
        "/cancel — Cancel current input"
    )


@router.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user is None:
        return

    clear_admin_input(message.from_user.id)

    if not is_admin(message.from_user.id):
        await message.answer("⛔ You are not authorized to use the admin panel.")
        return

    await show_admin_panel(message)


@router.message(Command("on"))
async def enable_command(message: Message):
    if message.from_user is None or not is_admin(message.from_user.id):
        return

    clear_admin_input(message.from_user.id)
    settings["enabled"] = True
    save_settings()

    await message.answer("✅ Auto-reply is now ON.")


@router.message(Command("off"))
async def disable_command(message: Message):
    if message.from_user is None or not is_admin(message.from_user.id):
        return

    clear_admin_input(message.from_user.id)
    settings["enabled"] = False
    save_settings()

    await message.answer("⏸️ Auto-reply is now OFF.")


@router.message(Command("cancel"))
async def cancel_command(message: Message):
    if message.from_user is None:
        return

    clear_admin_input(message.from_user.id)

    if is_admin(message.from_user.id):
        await message.answer(
            "❌ Input cancelled.",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await message.answer("Input cancelled.")


@router.message(Command("setreply"))
async def setreply_command(message: Message):
    if message.from_user is None or not is_admin(message.from_user.id):
        return

    clear_admin_input(message.from_user.id)
    admin_input_mode[message.from_user.id] = "reply"

    await message.answer(
        "✍️ Send the new auto-reply message now:",
        reply_markup=back_keyboard()
    )


@router.message(Command("setdelay"))
async def setdelay_command(message: Message):
    if message.from_user is None or not is_admin(message.from_user.id):
        return

    clear_admin_input(message.from_user.id)
    admin_input_mode[message.from_user.id] = "delay_seconds"

    await message.answer(
        "⏱️ Send the reply delay in seconds.\n"
        "Enter a number from 0 to 3600:",
        reply_markup=back_keyboard()
    )


@router.message(Command("addkeyword"))
async def addkeyword_command(message: Message):
    if message.from_user is None or not is_admin(message.from_user.id):
        return

    clear_admin_input(message.from_user.id)
    admin_input_mode[message.from_user.id] = "add_keyword"

    await message.answer(
        "🔑 Send the keyword and reply in this format:\n\n"
        "<code>keyword | reply message</code>\n\n"
        "Example:\n"
        "<code>price | Please contact support for pricing.</code>",
        reply_markup=back_keyboard()
    )


@router.message(Command("delkeyword"))
async def delkeyword_command(message: Message):
    if message.from_user is None or not is_admin(message.from_user.id):
        return

    clear_admin_input(message.from_user.id)
    admin_input_mode[message.from_user.id] = "delete_keyword"

    await message.answer(
        "🗑️ Send the exact keyword you want to delete:",
        reply_markup=back_keyboard()
    )


# ==================================================
# ADMIN PANEL CALLBACKS
# ==================================================

@router.callback_query(F.data == "admin_home")
async def admin_home_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            admin_status_text(),
            reply_markup=admin_panel_keyboard()
        )


@router.callback_query(F.data == "cancel_input")
async def cancel_input_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer("Input cancelled.")

    if callback.message:
        await safe_edit_message(
            callback.message,
            "❌ Input cancelled.\n\n" + admin_status_text(),
            reply_markup=admin_panel_keyboard()
        )


@router.callback_query(F.data == "toggle_on")
async def toggle_on_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    settings["enabled"] = True
    save_settings()
    await callback.answer("Auto-reply enabled.")

    if callback.message:
        await safe_edit_message(
            callback.message,
            admin_status_text(),
            reply_markup=admin_panel_keyboard()
        )


@router.callback_query(F.data == "toggle_off")
async def toggle_off_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    settings["enabled"] = False
    save_settings()
    await callback.answer("Auto-reply disabled.")

    if callback.message:
        await safe_edit_message(
            callback.message,
            admin_status_text(),
            reply_markup=admin_panel_keyboard()
        )


@router.callback_query(F.data == "set_reply")
async def set_reply_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    admin_input_mode[callback.from_user.id] = "reply"
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            "✍️ Send your new auto-reply message:",
            reply_markup=back_keyboard()
        )


@router.callback_query(F.data == "set_language")
async def set_language_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            "🌐 Choose a language label:",
            reply_markup=language_keyboard()
        )


@router.callback_query(F.data.startswith("language_"))
async def language_select_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    language = callback.data.replace("language_", "", 1)
    settings["language"] = language
    save_settings()
    await callback.answer("Language label updated.")

    if callback.message:
        await safe_edit_message(
            callback.message,
            "🌐 Language label saved.\n\n"
            "Note: this setting changes the label only; it does not automatically translate messages.\n\n"
            + admin_status_text(),
            reply_markup=admin_panel_keyboard()
        )


@router.callback_query(F.data == "reply_mode")
async def reply_mode_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            "⚙️ Choose the auto-reply mode:",
            reply_markup=reply_mode_keyboard()
        )


@router.callback_query(F.data.startswith("mode_"))
async def reply_mode_select_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    mode = callback.data.replace("mode_", "", 1)

    if mode not in ("all", "keywords"):
        await callback.answer("Invalid mode.", show_alert=True)
        return

    settings["reply_mode"] = mode
    save_settings()
    await callback.answer("Reply mode updated.")

    if callback.message:
        await safe_edit_message(
            callback.message,
            admin_status_text(),
            reply_markup=admin_panel_keyboard()
        )


@router.callback_query(F.data == "manage_keywords")
async def manage_keywords_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            "🔑 <b>Keyword Replies</b>\n\n"
            "Add keyword:\n"
            "<code>/addkeyword</code>\n\n"
            "Delete keyword:\n"
            "<code>/delkeyword</code>\n\n"
            "Use this format to add:\n"
            "<code>keyword | reply message</code>",
            reply_markup=back_keyboard()
        )


@router.callback_query(F.data == "set_delay")
async def set_delay_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    admin_input_mode[callback.from_user.id] = "delay_seconds"
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            "⏱️ Send the delay in seconds (0–3600):",
            reply_markup=back_keyboard()
        )


@router.callback_query(F.data == "preview_reply")
async def preview_reply_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer()

    preview_text = html.escape(str(settings.get("reply_message", DEFAULT_SETTINGS["reply_message"])))

    if callback.message:
        await safe_edit_message(
            callback.message,
            "👀 <b>Auto-reply Preview</b>\n\n"
            + (preview_text or "<i>No reply message configured.</i>"),
            reply_markup=back_keyboard()
        )


@router.callback_query(F.data == "show_stats")
async def show_stats_callback(callback: CallbackQuery):
    if callback.from_user is None or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return

    clear_admin_input(callback.from_user.id)
    await callback.answer()

    if callback.message:
        await safe_edit_message(
            callback.message,
            "📊 <b>Bot Statistics</b>\n\n"
            f"Messages received: {settings.get('total_received', 0)}\n"
            f"Replies sent: {settings.get('total_replied', 0)}",
            reply_markup=back_keyboard()
            
    )
        # ==================================================
# MESSAGE HANDLER
# ==================================================

@router.message(F.text)
async def text_message_handler(message: Message):
    if message.from_user is None or message.text is None:
        return

    user_id = message.from_user.id
    text = message.text.strip()

    # Ignore messages sent by bots
    if message.from_user.is_bot:
        return

    # Handle admin input
    if is_admin(user_id) and user_id in admin_input_mode:
        mode = admin_input_mode.get(user_id)

        if mode == "reply":
            settings["reply_message"] = text
            clear_admin_input(user_id)
            save_settings()

            await message.answer(
                "✅ Auto-reply message updated.",
                reply_markup=admin_panel_keyboard()
            )
            return

        if mode == "delay_seconds":
            try:
                delay = int(text)

                if not 0 <= delay <= 3600:
                    await message.answer(
                        "⚠️ Enter a number from 0 to 3600 seconds.",
                        reply_markup=back_keyboard()
                    )
                    return

                settings["delay_seconds"] = delay
                clear_admin_input(user_id)
                save_settings()

                await message.answer(
                    f"✅ Reply delay set to {delay} seconds.",
                    reply_markup=admin_panel_keyboard()
                )
            except ValueError:
                await message.answer(
                    "⚠️ Please enter a valid whole number from 0 to 3600.",
                    reply_markup=back_keyboard()
                )
            return

        if mode == "add_keyword":
            if "|" not in text:
                await message.answer(
                    "⚠️ Invalid format.\n\n"
                    "Use:\n<code>keyword | reply message</code>",
                    reply_markup=back_keyboard()
                )
                return

            keyword, reply_text = text.split("|", 1)
            keyword = keyword.strip().lower()
            reply_text = reply_text.strip()

            if not keyword or not reply_text:
                await message.answer(
                    "⚠️ Both keyword and reply message are required.",
                    reply_markup=back_keyboard()
                )
                return

            settings.setdefault("keyword_replies", {})[keyword] = reply_text
            clear_admin_input(user_id)
            save_settings()

            await message.answer(
                f"✅ Keyword reply added for: <code>{html.escape(keyword)}</code>",
                reply_markup=admin_panel_keyboard()
            )
            return

        if mode == "delete_keyword":
            keyword = text.lower()

            keyword_replies = settings.setdefault("keyword_replies", {})

            if keyword in keyword_replies:
                del keyword_replies[keyword]
                save_settings()
                result = f"✅ Deleted keyword: <code>{html.escape(keyword)}</code>"
            else:
                result = f"⚠️ Keyword not found: <code>{html.escape(keyword)}</code>"

            clear_admin_input(user_id)

            await message.answer(
                result,
                reply_markup=admin_panel_keyboard()
            )
            return

    # Auto-reply only in private chats
    if message.chat.type != "private":
        return

    # Do not auto-reply to the admin/owner
    if is_admin(user_id):
        return

    settings["total_received"] = settings.get("total_received", 0) + 1
    save_settings()

    # Auto-reply disabled
    if not settings.get("enabled", True):
        return

    reply_text = settings.get("reply_message", DEFAULT_SETTINGS["reply_message"])
    if not reply_text:
        return

    # Keyword mode
    if settings.get("reply_mode", "all") == "keywords":
        matched_reply = None
        keyword_replies = settings.get("keyword_replies", {})

        incoming_text = text.lower()

        for keyword, keyword_reply in keyword_replies.items():
            if keyword.lower() in incoming_text:
                matched_reply = keyword_reply
                break

        if matched_reply is None:
            return

        reply_text = matched_reply

    # Optional delay
    delay = settings.get("delay_seconds", 0)

    if delay:
        await asyncio.sleep(delay)

    try:
        await message.answer(reply_text, parse_mode=None)

        settings["total_replied"] = settings.get("total_replied", 0) + 1
        save_settings()

    except Exception:
        logger.exception("Failed to send auto-reply")


# ==================================================
# START BOT
# ==================================================

async def run_web_server():
    from aiohttp import web

    async def health_check(request):
        return web.Response(text="24x7 Reply Assistant is running!")

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Health server started on port %s", port)


async def main():
    logger.info("Starting 24x7 Reply Assistant...")

    try:
        await run_web_server()
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
