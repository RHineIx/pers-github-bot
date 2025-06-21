# bot/handlers/settings_handler.py
# This module contains the SettingsHandler class, which manages
# all the logic for the interactive settings menu.

import asyncio
import logging
from typing import TYPE_CHECKING

from telebot.async_telebot import AsyncTeleBot
from telebot.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telebot.apihelper import ApiTelegramException

from config import config
from bot.database import DatabaseManager
from bot.utils import format_duration, CallbackDataManager

if TYPE_CHECKING:
    from bot.scheduler import DigestScheduler

logger = logging.getLogger(__name__)


class SettingsHandler:
    def __init__(
        self,
        bot: AsyncTeleBot,
        db_manager: DatabaseManager,
        scheduler: "DigestScheduler",
    ):
        # --- Store necessary components ---
        self.bot = bot
        self.db_manager = db_manager
        self.scheduler = scheduler
        self._last_settings_message_id = {}

    def register_handlers(self):
        # --- Register all handlers managed by this class ---
        self.bot.message_handler(is_owner=True, commands=["settings"])(
            self.handle_settings
        )
        self.bot.callback_query_handler(is_owner=True, func=lambda call: True)(
            self.handle_callback_query
        )

    async def handle_settings(self, message: Message):
        # --- Entry point for the /settings command ---
        await self._send_settings_menu(message.chat.id)

    async def handle_callback_query(self, call: CallbackQuery):
        # --- Central router for all button clicks from the settings menu ---
        data = CallbackDataManager.get_callback_data(call.data)
        if not data:
            await self.bot.answer_callback_query(
                call.id, "Menu expired. Use /settings again."
            )
            try:
                await self.bot.delete_message(
                    call.message.chat.id, call.message.message_id
                )
            except:
                pass
            return

        action = data.get("action")
        # --- Answer the callback to remove the "loading" state on the button ---
        await self.bot.answer_callback_query(call.id)

        # --- Route actions based on callback data ---
        if action == "main_menu":
            await self._send_settings_menu(
                call.message.chat.id, call.message.message_id, is_edit=True
            )
        elif action == "toggle_pause":
            await self.db_manager.set_monitoring_paused(
                not await self.db_manager.is_monitoring_paused()
            )
            await self._send_settings_menu(
                call.message.chat.id, call.message.message_id, is_edit=True
            )
        elif action == "toggle_ai_features":
            await self.db_manager.set_ai_features_enabled(
                not await self.db_manager.are_ai_features_enabled()
            )
            await self._send_settings_menu(
                call.message.chat.id, call.message.message_id, is_edit=True
            )
        elif action == "toggle_ai_media_selection":
            await self.db_manager.set_ai_media_selection_enabled(
                not await self.db_manager.is_ai_media_selection_enabled()
            )
            await self._send_settings_menu(
                call.message.chat.id, call.message.message_id, is_edit=True
            )
        elif action == "open_digest_menu":
            await self._send_digest_submenu(
                call.message.chat.id, call.message.message_id
            )
        elif action == "set_digest_mode":
            await self.db_manager.update_digest_mode(data.get("mode"))
            await self._send_settings_menu(
                call.message.chat.id, call.message.message_id, is_edit=True
            )
        elif action == "open_interval_menu":
            await self._send_interval_submenu(
                call.message.chat.id, call.message.message_id
            )
        elif action == "set_interval":
            await self.db_manager.update_monitor_interval(data.get("seconds"))
            await self._send_interval_submenu(
                call.message.chat.id, call.message.message_id
            )
        elif action == "close":
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            self._last_settings_message_id.pop(call.message.chat.id, None)
        # --- Note: We will move other handlers like destination/token management here later if needed ---

    async def _send_or_edit_menu(
        self, chat_id, text, keyboard, message_id=None, is_edit=False
    ):
        # --- Helper function to safely send or edit a menu message ---
        try:
            if is_edit and message_id:
                await self.bot.edit_message_text(
                    text,
                    chat_id,
                    message_id,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            else:
                # --- Delete the previous settings message if it exists ---
                last_msg_id = self._last_settings_message_id.get(chat_id)
                if last_msg_id:
                    try:
                        await self.bot.delete_message(chat_id, last_msg_id)
                    except:
                        pass
                sent_msg = await self.bot.send_message(
                    chat_id, text, reply_markup=keyboard, parse_mode="Markdown"
                )
                self._last_settings_message_id[chat_id] = sent_msg.message_id
        except ApiTelegramException as e:
            logger.warning(
                f"Could not edit/send settings menu for chat {chat_id}. Error: {e}"
            )
            if is_edit:
                # --- If editing fails, send a new message ---
                sent_msg = await self.bot.send_message(
                    chat_id, text, reply_markup=keyboard, parse_mode="Markdown"
                )
                self._last_settings_message_id[chat_id] = sent_msg.message_id

    async def _send_settings_menu(self, chat_id, message_id=None, is_edit=False):
        # --- Generates the main settings menu ---
        is_paused, digest_mode, ai_enabled, ai_media_select_enabled = (
            await asyncio.gather(
                self.db_manager.is_monitoring_paused(),
                self.db_manager.get_digest_mode(),
                self.db_manager.are_ai_features_enabled(),
                self.db_manager.is_ai_media_selection_enabled(),
            )
        )
        text = "⚙️ **Bot Settings**\n"
        pause_text = "▶️ Resume" if is_paused else "⏸️ Pause"
        digest_text = f"🔔 Mode: {digest_mode.capitalize()}"
        ai_text = "🧠 AI Features: ON" if ai_enabled else "🧠 AI Features: OFF"
        ai_media_text = (
            "🖼️ AI Media Select: ON"
            if ai_media_select_enabled
            else "🖼️ AI Media Select: OFF"
        )

        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton(
                pause_text,
                callback_data=CallbackDataManager.create_callback_data("toggle_pause"),
            ),
            InlineKeyboardButton(
                digest_text,
                callback_data=CallbackDataManager.create_callback_data(
                    "open_digest_menu"
                ),
            ),
        )
        keyboard.add(
            InlineKeyboardButton(
                ai_text,
                callback_data=CallbackDataManager.create_callback_data(
                    "toggle_ai_features"
                ),
            ),
            InlineKeyboardButton(
                ai_media_text,
                callback_data=CallbackDataManager.create_callback_data(
                    "toggle_ai_media_selection"
                ),
            ),
        )
        keyboard.add(
            InlineKeyboardButton(
                "⏱️ Set Interval",
                callback_data=CallbackDataManager.create_callback_data(
                    "open_interval_menu"
                ),
            )
        )
        # --- We will add destination and token management buttons later ---
        keyboard.add(
            InlineKeyboardButton(
                "Close Menu",
                callback_data=CallbackDataManager.create_callback_data("close"),
            )
        )
        await self._send_or_edit_menu(chat_id, text, keyboard, message_id, is_edit)

    async def _send_digest_submenu(self, chat_id, message_id):
        # --- Generates the digest settings sub-menu ---
        current_mode = await self.db_manager.get_digest_mode()
        text = "🔔 **Select Notification Mode**"
        modes = ["off", "daily", "weekly"]
        buttons = [
            InlineKeyboardButton(
                f"✅ {m.capitalize()}" if m == current_mode else m.capitalize(),
                callback_data=CallbackDataManager.create_callback_data(
                    "set_digest_mode", {"mode": m}
                ),
            )
            for m in modes
        ]
        keyboard = InlineKeyboardMarkup().row(*buttons)
        keyboard.add(
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=CallbackDataManager.create_callback_data("main_menu"),
            )
        )
        await self.bot.edit_message_text(
            text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
        )

    async def _send_interval_submenu(self, chat_id, message_id):
        # --- Generates the interval sub-menu with presets ---
        current_interval = (
            await self.db_manager.get_monitor_interval()
            or config.STARS_MONITOR_INTERVAL
        )
        text = f"⏱️ **Select Check Interval**\n_Current: {format_duration(current_interval)}_"
        presets = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
        }
        keyboard = InlineKeyboardMarkup(row_width=3)
        buttons = [
            InlineKeyboardButton(
                f"✅ {label}" if seconds == current_interval else label,
                callback_data=CallbackDataManager.create_callback_data(
                    "set_interval", {"seconds": seconds}
                ),
            )
            for label, seconds in presets.items()
        ]
        keyboard.add(*buttons)
        keyboard.add(
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=CallbackDataManager.create_callback_data("main_menu"),
            )
        )
        await self.bot.edit_message_text(
            text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown"
        )
