# bot/handlers.py
# This module contains the BotHandlers class, which defines and registers
# all the command, message, and query handlers for the bot.

import asyncio
import logging
from datetime import datetime
from typing import Optional

from telebot.async_telebot import AsyncTeleBot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputTextMessageContent,
    ReactionTypeEmoji,
    InlineQueryResultArticle,
)
from telebot.apihelper import ApiTelegramException

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter, UserFormatter, URLParser
from bot.utils import format_duration, CallbackDataManager
from bot.summarizer import AISummarizer

logger = logging.getLogger(__name__)


class BotHandlers:
    def __init__(
        self,
        bot: AsyncTeleBot,
        github_api: GitHubAPI,
        db_manager: DatabaseManager,
        summarizer: Optional[AISummarizer],
    ):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.summarizer = summarizer
        self._last_settings_message_id = {}

    def register_handlers(self):
        # Register all command and query handlers, protected by the owner filter.

        # --- Register the test log command ---
        self.bot.message_handler(is_owner=True, commands=["testlog"])(self.handle_test_log)

        # Main Commands
        self.bot.message_handler(is_owner=True, commands=["start", "help"])(self.handle_help)
        self.bot.message_handler(is_owner=True, commands=["status"])(self.handle_status)
        
        self.bot.message_handler(is_owner=True, commands=["settings"])(self.handle_settings)
        # Central callback handler for all interactive buttons     
        self.bot.callback_query_handler(is_owner=True, func=lambda call: call.data)(self.handle_callback_query)
        
        # Token Management
        self.bot.message_handler(is_owner=True, commands=["settoken"])(self.handle_set_token)
        self.bot.message_handler(is_owner=True, commands=["removetoken"])(self.handle_remove_token)

        # Monitoring & Settings
        self.bot.message_handler(is_owner=True, commands=["pause", "resume"])(self.handle_pause_resume)
        self.bot.message_handler(is_owner=True, commands=["setinterval"])(self.handle_set_interval)
        self.bot.message_handler(is_owner=True, commands=["digest"])(self.handle_digest_command)

        # Destination Management (grouped into a single router function)
        self.bot.message_handler(is_owner=True, commands=["add_dest", "remove_dest", "list_dests"])(self.handle_destinations)

        # Inline Mode
        self.bot.inline_handler(is_owner=True, func=lambda query: True)(self.handle_inline_query)

        self.bot.message_handler(is_owner=True, content_types=['text'])(self.handle_text_message)

        
    async def handle_help(self, message: Message):
        # Handles the /start and /help command.
        help_text = f"👋 **Hi, {message.from_user.first_name}!**\n\n"
        help_text += """
📖 *Available Commands*

*Core Controls:*
`/settoken <TOKEN>` - Saves your GitHub Token.
`/removetoken` - Deletes your token.
`/status` - Shows bot status.
`/pause` | `/resume` - Pause/Resume monitoring.
`/testlog` - Sends a test message to the log channel.

*Settings:*
`/setinterval <seconds>` - Sets check interval.
`/digest <daily|weekly|off>` - Set notification mode.

*Destinations:*
`/add_dest [ID]` - Adds a destination.
`/remove_dest <ID|me>` - Removes a destination.
`/list_dests` - Shows all destinations.
"""
        try:
            # Kept your working effect ID for the help message.
            await self.bot.reply_to(
                message, help_text, parse_mode="Markdown", message_effect_id="5046509860389126442"
            )
        except Exception as e:
            logger.warning(f"Could not send message with effect, sending normally. Error: {e}")
            await self.bot.reply_to(message, help_text, parse_mode="Markdown")

    # --- test log command ---
    async def handle_test_log(self, message: Message):
        """Sends a test error message to the configured log channel."""
        if not config.LOG_CHANNEL_ID:
            await self.bot.reply_to(message, "The `LOG_CHANNEL_ID` is not configured in your `.env` file.")
            return

        try:
            logger.error("This is a test error message sent via the /testlog command.")
            await self.bot.reply_to(message, "✅ A test error log has been sent log channel.")
        except Exception as e:
            await self.bot.reply_to(message, f"❌ Failed to send test log. Error: {e}")

    # --- Settings Menu Logic ---

    async def handle_settings(self, message: Message):
        """Entry point for the /settings command."""
        await self._send_settings_menu(message.chat.id)

    async def handle_callback_query(self, call: CallbackQuery):
        """Central router for all button clicks."""
        data = CallbackDataManager.get_callback_data(call.data)
        if not data:
            await self.bot.answer_callback_query(call.id, "Menu expired. Use /settings again.")
            try: await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            return
        
        action = data.get('action')
        await self.bot.answer_callback_query(call.id)

        # Route actions based on callback data
        if action == 'main_menu':
            await self._send_settings_menu(call.message.chat.id, call.message.message_id, is_edit=True)
        elif action == 'toggle_pause':
            await self.db_manager.set_monitoring_paused(not await self.db_manager.is_monitoring_paused())
            await self._send_settings_menu(call.message.chat.id, call.message.message_id, is_edit=True)
        elif action == 'open_digest_menu':
            await self._send_digest_submenu(call.message.chat.id, call.message.message_id)
        elif action == 'set_digest_mode':
            await self.db_manager.update_digest_mode(data.get('mode'))
            await self._send_settings_menu(call.message.chat.id, call.message.message_id, is_edit=True)
        elif action == 'open_interval_menu':
            await self._send_interval_submenu(call.message.chat.id, call.message.message_id)
        elif action == 'set_interval':
            await self.db_manager.update_monitor_interval(data.get('seconds'))
            await self._send_interval_submenu(call.message.chat.id, call.message.message_id)
        elif action == 'open_dest_menu':
            await self._send_destinations_submenu(call.message.chat.id, call.message.message_id)
        elif action == 'open_add_dest_prompt':
            await self.db_manager.set_bot_state('awaiting_destination')
            await self.bot.edit_message_text("Please send the new destination ID:", call.message.chat.id, call.message.message_id, reply_markup=None)
        elif action == 'confirm_remove_dest':
            await self._send_confirm_remove_dest(call.message.chat.id, call.message.message_id, data.get('target_id'))
        elif action == 'execute_remove_dest':
            await self.db_manager.remove_destination(data.get('target_id'))
            await self._send_destinations_submenu(call.message.chat.id, call.message.message_id)
        elif action == 'confirm_remove_token':
            await self._send_confirm_remove_token(call.message.chat.id, call.message.message_id)
        elif action == 'execute_remove_token':
            await self.db_manager.remove_token()
            await self.bot.edit_message_text("✅ Token removed. The bot will now stop functioning.", call.message.chat.id, call.message.message_id, reply_markup=None)
        elif action == 'close':
             await self.bot.delete_message(call.message.chat.id, call.message.message_id)
             self._last_settings_message_id.pop(call.message.chat.id, None)

    async def handle_text_message(self, message: Message):
        """Handles stateful text inputs and default reactions."""
        bot_state = await self.db_manager.get_bot_state()
        if bot_state and bot_state.get('state') == 'awaiting_destination':
            await self._handle_destination_input(message)

    async def _handle_destination_input(self, message: Message):
        """Processes the received text as a new destination ID."""
        target_id_str = message.text.strip()
        
        if target_id_str.startswith('-'):
            try:
                test_msg = await self.bot.send_message(target_id_str, "✅ Bot permission test...")
                await self.bot.delete_message(test_msg.chat.id, test_msg.message_id)
            except ApiTelegramException as e:
                await self.bot.reply_to(message, f"❌ Failed to add destination.\n*Reason:* `{e.description}`")
                await self.db_manager.clear_bot_state(); return
        
        await self.db_manager.add_destination(target_id_str)
        await self.db_manager.clear_bot_state()
        await self.bot.delete_message(message.chat.id, message.message_id)
        conf_msg = await self.bot.send_message(message.chat.id, f"✅ Destination `{target_id_str}` added. Re-opening settings...")
        await asyncio.sleep(2)
        await self.bot.delete_message(conf_msg.chat.id, conf_msg.message_id)
        await self._send_settings_menu(message.chat.id)

    async def _send_or_edit_menu(self, chat_id, text, keyboard, message_id=None, is_edit=False):
        """Helper function to safely send or edit a menu message."""
        try:
            if is_edit and message_id:
                await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
            else:
                last_msg_id = self._last_settings_message_id.get(chat_id)
                if last_msg_id:
                    try: await self.bot.delete_message(chat_id, last_msg_id)
                    except: pass
                sent_msg = await self.bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
                self._last_settings_message_id[chat_id] = sent_msg.message_id
        except ApiTelegramException as e:
            logger.warning(f"Could not edit/send settings menu for chat {chat_id}. Error: {e}")
            if is_edit:
                sent_msg = await self.bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="Markdown")
                self._last_settings_message_id[chat_id] = sent_msg.message_id

    async def _send_settings_menu(self, chat_id, message_id=None, is_edit=False):
        """Generates the main settings menu."""
        is_paused, digest_mode = await asyncio.gather(self.db_manager.is_monitoring_paused(), self.db_manager.get_digest_mode())
        text = "⚙️ **Bot Settings**\n"
        pause_text = "▶️ Resume" if is_paused else "⏸️ Pause"
        digest_text = f"🔔 Mode: {digest_mode.capitalize()}"

        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(InlineKeyboardButton(pause_text, callback_data=CallbackDataManager.create_callback_data('toggle_pause')),
                     InlineKeyboardButton(digest_text, callback_data=CallbackDataManager.create_callback_data('open_digest_menu')))
        keyboard.add(InlineKeyboardButton("⏱️ Set Interval", callback_data=CallbackDataManager.create_callback_data('open_interval_menu')),
                     InlineKeyboardButton("📍 Manage Destinations", callback_data=CallbackDataManager.create_callback_data('open_dest_menu')))
        keyboard.add(InlineKeyboardButton("🗑️ Remove Token", callback_data=CallbackDataManager.create_callback_data('confirm_remove_token')))
        keyboard.add(InlineKeyboardButton("Close Menu", callback_data=CallbackDataManager.create_callback_data('close')))
        await self._send_or_edit_menu(chat_id, text, keyboard, message_id, is_edit)

    async def _send_digest_submenu(self, chat_id, message_id):
        """Generates the digest settings sub-menu."""
        current_mode = await self.db_manager.get_digest_mode()
        text = "🔔 **Select Notification Mode**"
        modes = ['off', 'daily', 'weekly']
        buttons = [InlineKeyboardButton(f"✅ {m.capitalize()}" if m == current_mode else m.capitalize(), callback_data=CallbackDataManager.create_callback_data('set_digest_mode', {'mode': m})) for m in modes]
        keyboard = InlineKeyboardMarkup().row(*buttons)
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data=CallbackDataManager.create_callback_data('main_menu')))
        await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

    async def _send_interval_submenu(self, chat_id, message_id):
        """Generates the interval sub-menu with presets."""
        current_interval = await self.db_manager.get_monitor_interval() or config.MONITOR_INTERVAL_SECONDS
        text = f"⏱️ **Select Check Interval**\n_Current: {format_duration(current_interval)}_"
        presets = {"5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
        keyboard = InlineKeyboardMarkup(row_width=3)
        buttons = [InlineKeyboardButton(f"✅ {label}" if seconds == current_interval else label, callback_data=CallbackDataManager.create_callback_data('set_interval', {'seconds': seconds})) for label, seconds in presets.items()]
        keyboard.add(*buttons)
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data=CallbackDataManager.create_callback_data('main_menu')))
        await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")
        
    async def _send_destinations_submenu(self, chat_id, message_id):
        """Generates the destination management sub-menu."""
        destinations = await self.db_manager.get_all_destinations()
        text = "📍 **Manage Destinations**"
        keyboard = InlineKeyboardMarkup(row_width=1)
        if not destinations:
            text += "\nNo destinations configured."
        for dest in destinations:
            display_text = f"❌ {dest}" + (" (Your DM)" if dest == str(chat_id) else "")
            callback_data = CallbackDataManager.create_callback_data('confirm_remove_dest', {'target_id': dest})
            keyboard.add(InlineKeyboardButton(display_text, callback_data=callback_data))
        keyboard.add(InlineKeyboardButton("➕ Add Destination", callback_data=CallbackDataManager.create_callback_data('open_add_dest_prompt')))
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data=CallbackDataManager.create_callback_data('main_menu')))
        await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

    async def _send_confirm_remove_dest(self, chat_id, message_id, target_id):
        """Shows confirmation before removing a destination."""
        text = f"Are you sure you want to remove this destination?\n`{target_id}`"
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(InlineKeyboardButton("Yes, Remove", callback_data=CallbackDataManager.create_callback_data('execute_remove_dest', {'target_id': target_id})),
                     InlineKeyboardButton("No, Cancel", callback_data=CallbackDataManager.create_callback_data('open_dest_menu')))
        await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

    async def _send_confirm_remove_token(self, chat_id, message_id):
        """Shows a strong confirmation before removing the token."""
        text = "⚠️ **ARE YOU SURE?**\n\nThis will delete your GitHub token. This action cannot be undone."
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(InlineKeyboardButton("❌ YES, DELETE IT", callback_data=CallbackDataManager.create_callback_data('execute_remove_token')),
                     InlineKeyboardButton("✅ No, Cancel", callback_data=CallbackDataManager.create_callback_data('main_menu')))
        await self.bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="Markdown")

    async def handle_status(self, message: Message):
        # Shows a detailed status of the bot's current state.
        if not await self.db_manager.token_exists():
            await self.bot.reply_to(message, "No GitHub token is set. Use `/settoken`.")
            return

        wait_msg = await self.bot.reply_to(message, "🔍 Fetching status...")
        try:
            # Gather all status data concurrently for speed.
            tasks = {
                "user": self.github_api.get_authenticated_user(),
                "rate_limit": self.github_api.get_rate_limit(),
                "destinations": self.db_manager.get_all_destinations(),
                "interval": self.db_manager.get_monitor_interval(),
                "is_paused": self.db_manager.is_monitoring_paused(),
                "last_error": self.db_manager.get_last_error(),
                "digest_mode": self.db_manager.get_digest_mode()
            }
            results = await asyncio.gather(*tasks.values())
            res = dict(zip(tasks.keys(), results))

            # Build the status message.
            status_text = "📊 *Bot Status*\n\n"
            if res.get('last_error'):
                status_text += f"⚠️ *LAST ERROR:*\n`{res['last_error']}`\n\n"

            monitoring_status = "Paused ⏸️" if res.get('is_paused') else "Active ✅"
            status_text += f"📢 *Monitoring:* `{monitoring_status}`\n"
            status_text += f"🔔 *Notification Mode:* `{res.get('digest_mode', 'off').capitalize()}`\n"
            
            if res.get('user'):
                status_text += f"👤 *GitHub Account:* `@{res['user'].get('login', 'N/A')}`\n"
            
            if res.get('rate_limit'):
                core = res['rate_limit'].get('resources', {}).get('core', {})
                status_text += f"📈 *API Limit:* `{core.get('remaining', 'N/A')}/{core.get('limit', 'N/A')}`\n"

            current_interval = res.get('interval') or config.MONITOR_INTERVAL_SECONDS
            status_text += f"⏱️ *Check Interval:* `{format_duration(current_interval)}`\n"
            status_text += f"📍 *Destinations:* `{len(res.get('destinations', []))}` configured."
            
            await self.bot.edit_message_text(status_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error fetching status: {e}", exc_info=True)
            await self.bot.edit_message_text("❌ An error occurred while fetching status.", wait_msg.chat.id, wait_msg.message_id)
            
    async def handle_set_token(self, message: Message):
        # Sets the GitHub token and performs initial setup.
        try:
            token = message.text.split(" ", 1)[1]
        except IndexError:
            await self.bot.reply_to(message, "Usage: `/settoken <your_token>`", parse_mode="Markdown"); return

        await self.db_manager.store_token(token)
        try:
            # Validate the token by fetching user data.
            user_data = await self.github_api.get_authenticated_user()
            if not user_data or 'login' not in user_data: raise GitHubAPIError(401, "Invalid token")
            
            # On success, reset error/pause states and set default destination.
            await self.db_manager.clear_last_error()
            await self.db_manager.set_monitoring_paused(False)
            username = user_data.get("login")
            await self.db_manager.add_destination(str(message.from_user.id))
            
            reply_text = f"✅ **Token validated!**\n\nConnected to: *@{username}*.\nYour DM is set as the default destination."
            await self.bot.reply_to(message, reply_text, parse_mode="Markdown")
        except GitHubAPIError:
            await self.db_manager.remove_token()
            await self.bot.reply_to(message, "❌ **Invalid Token.**", parse_mode="Markdown")
        finally:
            try: await self.bot.delete_message(message.chat.id, message.message_id)
            except Exception as e: logger.warning(f"Could not delete token message: {e}")

    async def handle_remove_token(self, message: Message):
        # Removes the user's token from the database.
        if await self.db_manager.token_exists():
            await self.db_manager.remove_token()
            await self.bot.reply_to(message, "✅ Your GitHub token has been removed.")
        else:
            await self.bot.reply_to(message, "ℹ️ No token was found to remove.")

    async def handle_pause_resume(self, message: Message):
        # A single router for /pause and /resume commands.
        command = message.text.split()[0]
        if command == '/pause':
            await self.db_manager.set_monitoring_paused(True)
            await self.bot.reply_to(message, "⏸️ Monitoring paused.")
        elif command == '/resume':
            await self.db_manager.set_monitoring_paused(False)
            await self.bot.reply_to(message, "▶️ Monitoring resumed.")
            
    async def handle_set_interval(self, message: Message):
        # Sets the monitoring interval.
        try:
            seconds = int(message.text.split(" ", 1)[1])
            if seconds < 60:
                await self.bot.reply_to(message, "❌ Minimum interval is 60 seconds."); return
            await self.db_manager.update_monitor_interval(seconds)
            await self.bot.reply_to(message, f"✅ Interval set to *{format_duration(seconds)}*.", parse_mode="Markdown")
        except (IndexError, ValueError):
            await self.bot.reply_to(message, "Usage: `/setinterval <seconds>`", parse_mode="Markdown")

    async def handle_digest_command(self, message: Message):
        # Handles setting the digest mode.
        try:
            mode = message.text.split(" ", 1)[1].lower()
            if mode not in ['daily', 'weekly', 'off']: raise ValueError()
            await self.db_manager.update_digest_mode(mode)
            reply_message = f"✅ Digest mode set to *{mode}*."
            if mode == 'off': reply_message = "✅ Instant notifications are now **ON**."
            await self.bot.reply_to(message, reply_message, parse_mode="Markdown")
        except (IndexError, ValueError):
            await self.bot.reply_to(message, "Usage: `/digest <daily|weekly|off>`", parse_mode="Markdown")

    async def handle_destinations(self, message: Message):
        # A single router for all destination-related commands.
        # Note: Using your custom command names.
        command = message.text.split()[0]
        
        if command == '/add_dest':
            if not await self.db_manager.token_exists(): await self.bot.reply_to(message, "Set token first."); return
            parts = message.text.split(" ", 1)
            target_id_str = str(message.from_user.id) if len(parts) == 1 else parts[1].strip()

            if target_id_str.startswith('-'):
                try:
                    test_msg = await self.bot.send_message(target_id_str, "✅ Bot permission test...")
                    await self.bot.delete_message(test_msg.chat.id, test_msg.message_id)
                except ApiTelegramException as e:
                    await self.bot.reply_to(message, f"❌ Failed: `{e.description}`\nMake sure I'm an admin."); return
            await self.db_manager.add_destination(target_id_str)
            await self.bot.reply_to(message, f"✅ Destination added: `{target_id_str}`", parse_mode="Markdown")
        
        elif command == '/remove_dest':
            try:
                arg = message.text.split(" ", 1)[1].strip().lower()
                target_id = str(message.from_user.id) if arg == 'me' else arg
                if await self.db_manager.remove_destination(target_id) > 0:
                    await self.bot.reply_to(message, f"✅ Destination removed: `{target_id}`", parse_mode="Markdown")
                else:
                    await self.bot.reply_to(message, f"❌ Not found: `{target_id}`", parse_mode="Markdown")
            except IndexError:
                await self.bot.reply_to(message, "Usage: `/remove_dest <ID|me>`", parse_mode="Markdown")
                
        elif command == '/list_dests':
            destinations = await self.db_manager.get_all_destinations()
            if not destinations: await self.bot.reply_to(message, "No destinations configured."); return
            text = "📋 *Configured Destinations:*\n\n"
            for i, dest in enumerate(destinations, 1):
                text += f"{i}. `{dest}` {'(Your DM)' if dest == str(message.from_user.id) else ''}\n"
            await self.bot.reply_to(message, text, parse_mode="Markdown")

    async def _show_inline_help(self, query: InlineQueryResultArticle):
        # Get bot info to use actual username
        bot_info = await self.bot.get_me()
        bot_username = bot_info.username
        # Shows a help message in inline mode.
        help_result = InlineQueryResultArticle(
            id="help",
            title="🤖 Bot Help",
            description="Usage: .repo owner/repo or .user username",
            input_message_content=InputTextMessageContent(
                message_text=f"*Usage:*\n`@{bot_username} .repo owner/repo`\n`@{bot_username} .user username`",
                parse_mode="Markdown"
            )
        )
        await self.bot.answer_inline_query(query.id, [help_result], cache_time=300)

    async def handle_inline_query(self, query: InlineQueryResultArticle):
        # Handles inline queries for repos and users.
        query_text = query.query.strip()
        if not query_text.startswith((".repo ", ".user ")):
            await self._show_inline_help(query); return
        results = []
        try:
            if query_text.startswith(".repo "):
                repo_input = query_text[6:]
                parsed = URLParser.parse_repo_input(repo_input)
                if parsed:
                    owner, repo_name = parsed
                    tasks = {"repo_data": self.github_api.get_repository(owner, repo_name), "languages": self.github_api.get_repository_languages(owner, repo_name),"latest_release": self.github_api.get_latest_release(owner, repo_name),"readme": self.github_api.get_readme(owner, repo_name)}
                    task_results = await asyncio.gather(*tasks.values())
                    res = dict(zip(tasks.keys(), task_results))
                    if res["repo_data"]:
                        ai_summary = None
                        if self.summarizer and res["readme"]: ai_summary = await self.summarizer.summarize_readme(res["readme"])
                        preview_text = RepoFormatter.format_repository_preview(res["repo_data"], res["languages"], res["latest_release"], ai_summary)
                        results.append(InlineQueryResultArticle(id=f"repo_{owner}_{repo_name}",title=f"📦 {owner}/{repo_name}",description=res["repo_data"].get("description", "")[:60],input_message_content=InputTextMessageContent(preview_text, parse_mode="HTML"),thumbnail_url=res["repo_data"].get("owner", {}).get("avatar_url")))
            elif query_text.startswith(".user "):
                username = query_text[6:]
                user_data = await self.github_api.get_user(username)
                if user_data:
                    info_text = UserFormatter.format_user_info(user_data)
                    results.append(InlineQueryResultArticle(id=f"user_{username}",title=f"👤 {user_data.get('name', username)}",description=f"@{username} - {user_data.get('bio', '')[:50]}",input_message_content=InputTextMessageContent(info_text, parse_mode="HTML"),thumbnail_url=user_data.get("avatar_url")))
            await self.bot.answer_inline_query(query.id, results, cache_time=10)
        except Exception as e:
            logger.error(f"Error handling inline query: {e}", exc_info=True)
