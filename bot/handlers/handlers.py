# bot/handlers/handlers.py
# This module contains the main BotHandlers class, which delegates
# tasks to more specialized handlers.

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from telebot.async_telebot import AsyncTeleBot
from telebot.types import (
    Message,
    CallbackQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)

# --- Import the new SettingsHandler ---
from .settings_handler import SettingsHandler

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter, UserFormatter, URLParser
from bot.utils import format_duration
from bot.summarizer import AISummarizer

if TYPE_CHECKING:
    from bot.scheduler import DigestScheduler

logger = logging.getLogger(__name__)

class BotHandlers:
    def __init__(
        self,
        bot: AsyncTeleBot,
        github_api: GitHubAPI,
        db_manager: DatabaseManager,
        summarizer: Optional[AISummarizer],
        scheduler: "DigestScheduler",
    ):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.summarizer = summarizer
        self.scheduler = scheduler
        self.settings_handler = SettingsHandler(bot, db_manager, scheduler)

    def register_handlers(self):
        # Register all command and query handlers
        self.settings_handler.register_handlers()
        
        # Register main commands handled by this class
        self.bot.message_handler(is_owner=True, commands=["start", "help"])(self.handle_help)
        self.bot.message_handler(is_owner=True, commands=["status"])(self.handle_status)
        self.bot.message_handler(is_owner=True, commands=["testlog"])(self.handle_test_log)
        
        # Register Token Management commands
        self.bot.message_handler(is_owner=True, commands=["settoken"])(self.handle_set_token)
        self.bot.message_handler(is_owner=True, commands=["removetoken"])(self.handle_remove_token)
        
        # Register Destination Management commands
        self.bot.message_handler(is_owner=True, commands=["add_dest"])(self.handle_add_destination)
        self.bot.message_handler(is_owner=True, commands=["remove_dest"])(self.handle_remove_destination)
        self.bot.message_handler(is_owner=True, commands=["list_dests"])(self.handle_list_destinations)

        # Register Inline Query Handler
        self.bot.inline_handler(is_owner=True, func=lambda query: True)(self.handle_inline_query)

    async def handle_help(self, message: Message):
        """Handles the /start and /help command with a complete command list."""
        help_text = f"👋 **Hi, {message.from_user.first_name}!**\n\n"
        help_text += """
📖 *Available Commands*

*Token Management:*
`/settoken <TOKEN>` - Saves your GitHub Token.
`/removetoken` - Deletes your currently stored token.

*Core & Status:*
`/status` - Shows a detailed summary of the bot's current status.
`/settings` - Opens the interactive menu to configure the bot.
`/testlog` - Sends a test message to the log channel.

*Destination Management:*
`/add_dest <ID>` - Adds a channel/group/topic ID for notifications.
`/remove_dest <ID|me>` - Removes a notification destination.
`/list_dests` - Lists all configured destinations.
"""
        try:
            await self.bot.reply_to(message, help_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Could not send help message: {e}")
            await self.bot.reply_to(message, help_text, parse_mode="Markdown")

    async def handle_test_log(self, message: Message):
        # --- Sends a test error message to the configured log channel ---
        if not config.LOG_CHANNEL_ID:
            await self.bot.reply_to(message, "The `LOG_CHANNEL_ID` is not configured.")
            return
        try:
            logger.error("This is a test error message sent via the /testlog command.")
            await self.bot.reply_to(message, "✅ A test error log has been sent to the log channel.")
        except Exception as e:
            await self.bot.reply_to(message, f"❌ Failed to send test log. Error: {e}")

    async def handle_status(self, message: Message):
        # --- Shows a detailed status of the bot's current state ---
        # --- This function remains here as it depends on many components ---
        if not await self.db_manager.token_exists():
            await self.bot.reply_to(message, "No GitHub token is set. Use `/settoken`.")
            return

        wait_msg = await self.bot.reply_to(message, "🔍 Fetching status...")
        try:
            tasks = {
                "user": self.github_api.get_authenticated_user(),
                "rate_limit": self.github_api.get_rate_limit(),
                "destinations": self.db_manager.get_all_destinations(),
                "interval": self.db_manager.get_monitor_interval(),
                "is_paused": self.db_manager.is_monitoring_paused(),
                "last_error": self.db_manager.get_last_error(),
                "digest_mode": self.db_manager.get_digest_mode(),
                "queue_count": self.db_manager.get_digest_queue_count()
            }
            results = await asyncio.gather(*tasks.values())
            res = dict(zip(tasks.keys(), results))

            next_run_info = "Not scheduled"
            if self.scheduler and self.scheduler.scheduler.running:
                jobs = self.scheduler.scheduler.get_jobs()
                if jobs:
                    next_run_time = min((job.next_run_time for job in jobs if job.next_run_time), default=None)
                    if next_run_time:
                        next_run_info = next_run_time.strftime('%A, %Y-%m-%d at %H:%M:%S %Z')

            status_text = "📊 *Bot Status*\n\n"
            if res.get('last_error'):
                status_text += f"⚠️ *LAST ERROR:*\n`{res['last_error']}`\n\n"

            monitoring_status = "Paused ⏸️" if res.get('is_paused') else "Active ✅"
            status_text += f"📢 *Monitoring:* `{monitoring_status}`\n"
            digest_mode = res.get('digest_mode', 'off').capitalize()
            status_text += f"🔔 *Notification Mode:* `{digest_mode}`\n"
            if digest_mode != 'Off':
                status_text += f"📦 *Items in Queue:* `{res.get('queue_count', 0)}`\n"
                status_text += f"🗓️ *Next Digest:* `{next_run_info}`\n"
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
        # --- Sets the GitHub token and performs initial setup ---
        try:
            token = message.text.split(" ", 1)[1]
        except IndexError:
            await self.bot.reply_to(message, "Usage: `/settoken <your_token>`", parse_mode="Markdown"); return

        await self.db_manager.store_token(token)
        try:
            user_data = await self.github_api.get_authenticated_user()
            if not user_data or 'login' not in user_data: raise GitHubAPIError(401, "Invalid token")
            
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

    # --- NEW TOKEN MANAGEMENT METHOD ---
    async def handle_remove_token(self, message: Message):
        """Removes the GitHub token and pauses monitoring."""
        await self.db_manager.remove_token()
        await self.db_manager.set_monitoring_paused(True) # Pause monitoring for safety
        reply_text = (
            "🗑️ **Token Removed.**\n\n"
            "All monitoring has been paused. Use `/settoken` to add a new one."
        )
        await self.bot.reply_to(message, reply_text, parse_mode="Markdown")
        
    # --- NEW DESTINATION MANAGEMENT METHODS ---
    async def handle_add_destination(self, message: Message):
        """Adds a new notification destination after verifying it."""
        try:
            target_id = message.text.split(" ", 1)[1]
            if not (target_id.startswith('-') or target_id.replace('/', '').isnumeric()):
                 raise ValueError("Invalid ID format.")
        except (IndexError, ValueError):
            await self.bot.reply_to(
                message, 
                "Usage: `/add_dest <ID>`\n"
                "Example for a channel: `/add_dest -100123456789`\n"
                "Example for a topic: `/add_dest -100123456789/4`",
                parse_mode="Markdown"
            )
            return

        wait_msg = await self.bot.reply_to(message, f"Verifying destination `{target_id}`...")
        try:
            chat_id_str, thread_id = (target_id.split('/')[0], int(target_id.split('/')[1])) if '/' in target_id else (target_id, None)
            test_msg = await self.bot.send_message(chat_id_str, "✅ Verification successful.", message_thread_id=thread_id)
            await self.bot.delete_message(chat_id_str, test_msg.message_id)
            
            await self.db_manager.add_destination(target_id)
            await self.bot.edit_message_text(f"✅ Destination `{target_id}` added successfully!", wait_msg.chat.id, wait_msg.message_id, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Failed to verify destination {target_id}: {e}")
            error_text = (
                f"❌ **Failed to add destination.**\n\n"
                f"Please ensure the bot is a member of the chat/channel and has permission to send messages."
            )
            await self.bot.edit_message_text(error_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="Markdown")

    async def handle_remove_destination(self, message: Message):
        """Removes a notification destination."""
        try:
            target_id_str = message.text.split(" ", 1)[1]
            if target_id_str.lower() == 'me':
                target_id = str(message.from_user.id)
            else:
                target_id = target_id_str
        except IndexError:
            await self.bot.reply_to(message, "Usage: `/remove_dest <ID|me>`", parse_mode="Markdown")
            return
            
        rows_affected = await self.db_manager.remove_destination(target_id)
        if rows_affected > 0:
            await self.bot.reply_to(message, f"✅ Destination `{target_id}` removed.", parse_mode="Markdown")
        else:
            await self.bot.reply_to(message, f"❌ Destination `{target_id}` not found.", parse_mode="Markdown")

    async def handle_list_destinations(self, message: Message):
        """Lists all configured notification destinations."""
        destinations = await self.db_manager.get_all_destinations()
        if not destinations:
            await self.bot.reply_to(message, "There are no notification destinations configured.")
            return

        text = "📍 *Configured Notification Destinations:*\n\n"
        text += "\n".join([f"`{dest}`" for dest in destinations])
        await self.bot.reply_to(message, text, parse_mode="Markdown")
    
    async def handle_inline_query(self, query: InlineQueryResultArticle):
        # --- This function remains here for now ---
        query_text = query.query.strip()
        if not query_text.startswith((".repo ", ".user ")):
            # In a real implementation, you would call a help function for inline mode here
            return
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