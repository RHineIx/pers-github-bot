# In bot/handlers.py

import asyncio
import logging
from datetime import datetime
from telebot.async_telebot import AsyncTeleBot
from telebot.types import Message, InlineQueryResultArticle, InputTextMessageContent
from telebot.apihelper import ApiTelegramException
from bot.summarizer import AISummarizer
from typing import Optional

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter, UserFormatter, URLParser
from bot.utils import format_duration

logger = logging.getLogger(__name__)


class BotHandlers:
    # __init__ and register_handlers remain the same, but for completeness:
    def __init__(self, bot: AsyncTeleBot, github_api: GitHubAPI, db_manager: DatabaseManager, summarizer: Optional[AISummarizer]):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.summarizer = summarizer

    def register_handlers(self):
        """
        Registers all handlers with the TeleBot instance, protected by the IsOwnerFilter.
        """
        # Command Handlers
        self.bot.message_handler(is_owner=True, commands=["start", "help"])(self.handle_help)
        self.bot.message_handler(is_owner=True, commands=["settoken"])(self.handle_set_token)
        # ... (all other command handlers remain the same)
        self.bot.message_handler(is_owner=True, commands=["removetoken"])(self.handle_remove_token)
        self.bot.message_handler(is_owner=True, commands=["status"])(self.handle_status)
        self.bot.message_handler(is_owner=True, commands=["setinterval"])(self.handle_set_interval)
        self.bot.message_handler(is_owner=True, commands=["pause"])(self.handle_pause)
        self.bot.message_handler(is_owner=True, commands=["resume"])(self.handle_resume)
        self.bot.message_handler(is_owner=True, commands=["add_dest"])(self.handle_add_destination)
        self.bot.message_handler(is_owner=True, commands=["remove_dest"])(self.handle_remove_destination)
        self.bot.message_handler(is_owner=True, commands=["list_dests"])(self.handle_list_destinations)

        # Inline Mode Handler
        self.bot.inline_handler(is_owner=True, func=lambda query: True)(self.handle_inline_query)
        logger.info("All message and query handlers registered.")

    async def handle_help(self, message: Message):
        """Handles the /start and /help command, now with a custom message effect."""

        help_text = f"👋 **Hello, {message.from_user.first_name}!**\n\nHere are the available commands:\n\n"
        help_text += """
📖 *Available Commands*

*Core Controls:*
`/settoken <TOKEN>` - Securely saves your GitHub Token.
`/removetoken` - Deletes your token and all data.
`/status` - Shows bot status, API limit, and interval.
`/pause` - Temporarily stop checking for new stars.
`/resume` - Resume checking for new stars.

*Settings:*
`/setinterval <seconds>` - Sets the check interval (min 60s).

*Notification Destinations:*
`/add_destination <ID>` - Adds a channel/group ID.
`/remove_destination <ID>` - Removes a specific destination ID.
`/remove_destination me` - Removes your DM as a destination.
`/list_destinations` - Shows all configured destinations.
"""
        try:
            await self.bot.reply_to(
                message, 
                help_text, 
                parse_mode="Markdown",
                message_effect_id=5046509860389126442 # 🎉
            )
        except Exception as e:
            # Fallback to a normal message if the effect fails for any reason
            logger.warning(f"Could not send message with effect, sending normally. Error: {e}")
            await self.bot.reply_to(message, help_text, parse_mode="Markdown")
        
    async def handle_pause(self, message: Message):
        await self.db_manager.set_monitoring_paused(True)
        await self.bot.reply_to(message, "⏸️ Monitoring has been paused.", parse_mode="Markdown")

    async def handle_resume(self, message: Message):
        await self.db_manager.set_monitoring_paused(False)
        await self.bot.reply_to(message, "▶️ Monitoring has been resumed.", parse_mode="Markdown")

    async def handle_set_interval(self, message: Message):
        """Sets the monitoring interval with a user-friendly reply."""
        try:
            parts = message.text.split(" ", 1)
            if len(parts) < 2: await self.bot.reply_to(message, "Example: `/setinterval 300`"); return
            seconds = int(parts[1])
            min_interval = 60
            if seconds < min_interval: await self.bot.reply_to(message, f"❌ Minimum interval is {min_interval} seconds."); return
            
            await self.db_manager.update_monitor_interval(seconds)
            # --- Use the helper function for a better reply ---
            human_readable_duration = format_duration(seconds)
            await self.bot.reply_to(message, f"✅ Monitoring interval set to *{human_readable_duration}*.", parse_mode="Markdown")
        except ValueError: await self.bot.reply_to(message, "❌ Please enter a valid number.")
        except Exception as e: logger.error(f"Error in handle_set_interval: {e}"); await self.bot.reply_to(message, "An error occurred.")
    
    async def handle_set_token(self, message: Message):
        """Sets the token and clears any previous error state."""
        token = message.text.split(" ", 1)[-1]
        if token.startswith("/settoken"): await self.bot.reply_to(message, "Example: `/settoken ghp_...`"); return
        await self.db_manager.store_token(token)
        try:
            user_data = await self.github_api.get_authenticated_user()
            if not user_data or 'login' not in user_data: raise GitHubAPIError(401, "Invalid token")
            
            # --- Clear any past errors on successful token set ---
            await self.db_manager.clear_last_error()
            await self.db_manager.set_monitoring_paused(False) # Also resume monitoring

            username = user_data.get("login")
            user_dm_id = str(message.from_user.id)
            await self.db_manager.add_destination(user_dm_id)
            reply_text = f"✅ **Token validated!**\n\nConnected to account: *@{username}*.\nMonitoring is active and notifications will be sent to your DM."
            await self.bot.reply_to(message, reply_text, parse_mode="Markdown")
        except GitHubAPIError:
            await self.db_manager.remove_token()
            await self.bot.reply_to(message, "❌ **Invalid Token.** Please provide a valid token.", parse_mode="Markdown")
        finally:
            try: await self.bot.delete_message(message.chat.id, message.message_id)
            except Exception as e: logger.warning(f"Could not delete token message: {e}")

    async def handle_remove_token(self, message: Message):
        if await self.db_manager.token_exists():
            await self.db_manager.remove_token()
            await self.bot.reply_to(message, "✅ Your GitHub token has been removed.")
        else:
            await self.bot.reply_to(message, "ℹ️ No token was found to remove.")

    async def handle_status(self, message: Message):
        """Handles the /status command, now with error display."""
        if not await self.db_manager.token_exists(): await self.bot.reply_to(message, "No GitHub token is set."); return
        wait_msg = await self.bot.reply_to(message, "🔍 Fetching status...")
        try:
            tasks = {
                "user": self.github_api.get_authenticated_user(),
                "rate_limit": self.github_api.get_rate_limit(),
                "destinations": self.db_manager.get_all_destinations(),
                "interval": self.db_manager.get_monitor_interval(),
                "is_paused": self.db_manager.is_monitoring_paused(),
                "last_error": self.db_manager.get_last_error()
            }
            results = await asyncio.gather(*tasks.values())
            res = dict(zip(tasks.keys(), results))

            status_text = "📊 *Bot Status*\n\n"
            

            if res['last_error']:
                status_text += f"⚠️ *CRITICAL ERROR:*\n`{res['last_error']}`\n\n"

            monitoring_status = "Paused ⏸️" if res['is_paused'] else "Active ✅"
            status_text += f"📢 *Monitoring:* `{monitoring_status}`\n"
            status_text += f"👤 *GitHub Account:* `@{res['user'].get('login', 'N/A')}`\n"
            
            if res['rate_limit']:
                core = res['rate_limit'].get('resources', {}).get('core', {})
                status_text += f"📈 *API Limit:* `{core.get('remaining', 'N/A')}/{core.get('limit', 'N/A')}`\n"

            current_interval = res['interval'] if res['interval'] else config.MONITOR_INTERVAL_SECONDS
            status_text += f"⏱️ *Check Interval:* `{format_duration(current_interval)}`\n"
            status_text += f"📍 *Destinations:* `{len(res['destinations'])}` configured."
            
            await self.bot.edit_message_text(status_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error fetching status: {e}")
            await self.bot.edit_message_text("❌ An error occurred.", wait_msg.chat.id, wait_msg.message_id)

    async def handle_add_destination(self, message: Message):
        """Adds a destination with proactive permission check."""
        if not await self.db_manager.token_exists(): await self.bot.reply_to(message, "Please set a GitHub token first."); return
        parts = message.text.split(" ", 1)
        target_id_str = str(message.from_user.id) if len(parts) == 1 else parts[1].strip()

        # --- NEW: Proactive permission check ---
        if target_id_str.startswith('-'): # Check only for groups/channels
            try:
                test_msg = await self.bot.send_message(target_id_str, "✅ Bot permission test successful. This message will be deleted.")
                await self.bot.delete_message(test_msg.chat.id, test_msg.message_id)
            except ApiTelegramException as e:
                logger.error(f"Permission test failed for {target_id_str}: {e.description}")
                await self.bot.reply_to(message, f"❌ Failed to add destination.\n*Reason:* `{e.description}`\nPlease make sure I am an admin in that chat and have permission to send messages.")
                return
        
        await self.db_manager.add_destination(target_id_str)
        await self.bot.reply_to(message, f"✅ Destination added: `{target_id_str}`", parse_mode="Markdown")

    # ... other handlers like remove_destination, list_destinations, and inline mode remain the same ...
    async def handle_remove_destination(self, message: Message):
        parts = message.text.split(" ", 1)
        if len(parts) < 2: await self.bot.reply_to(message, "Please specify destination ID or 'me'."); return
        arg = parts[1].strip().lower()
        target_id = str(message.from_user.id) if arg == 'me' else arg
        rows_affected = await self.db_manager.remove_destination(target_id)
        if rows_affected > 0: await self.bot.reply_to(message, f"✅ Destination removed: `{target_id}`", parse_mode="Markdown")
        else: await self.bot.reply_to(message, f"❌ Destination not found: `{target_id}`", parse_mode="Markdown")
            
    async def handle_list_destinations(self, message: Message):
        destinations = await self.db_manager.get_all_destinations()
        if not destinations: await self.bot.reply_to(message, "No notification destinations are configured."); return
        text = "📋 *Configured Destinations:*\n\n"
        for i, dest in enumerate(destinations, 1): text += f"{i}. `{dest}` {'(Your DM)' if dest == str(message.from_user.id) else ''}\n"
        await self.bot.reply_to(message, text, parse_mode="Markdown")
        
    async def _show_inline_help(self, query: InlineQueryResultArticle):
        help_result = InlineQueryResultArticle(id="help", title="🤖 Bot Help", description="Usage: .repo owner/repo or .user username", input_message_content=InputTextMessageContent(message_text="*Usage:*\n`@YourBotUsername .repo owner/repo`\n`@YourBotUsername .user username`", parse_mode="Markdown"))
        await self.bot.answer_inline_query(query.id, [help_result], cache_time=300)

    async def handle_inline_query(self, query: InlineQueryResultArticle):
        """
        Handles inline queries, now with AI summarization for the .repo command.
        """
        query_text = query.query.strip()
        if not query_text.startswith((".repo ", ".user ")):
            await self._show_inline_help(query)
            return

        results = []
        try:
            if query_text.startswith(".repo "):
                repo_input = query_text[6:]
                parsed = URLParser.parse_repo_input(repo_input)
                if parsed:
                    owner, repo_name = parsed
                    
                    # --- Fetch all data needed for a smart preview ---
                    tasks = {
                        "repo_data": self.github_api.get_repository(owner, repo_name),
                        "languages": self.github_api.get_repository_languages(owner, repo_name),
                        "latest_release": self.github_api.get_latest_release(owner, repo_name),
                        "readme": self.github_api.get_readme(owner, repo_name)
                    }
                    task_results = await asyncio.gather(*tasks.values())
                    res = dict(zip(tasks.keys(), task_results))

                    if res["repo_data"]:
                        # Generate AI summary if possible
                        ai_summary = None
                        if self.summarizer and res["readme"]:
                            ai_summary = await self.summarizer.summarize_readme(res["readme"])
                        
                        # Format the preview using all available data
                        preview_text = RepoFormatter.format_repository_preview(
                            res["repo_data"], res["languages"], res["latest_release"], ai_summary
                        )

                        results.append(InlineQueryResultArticle(
                            id=f"repo_{owner}_{repo_name}",
                            title=f"📦 {owner}/{repo_name}",
                            description=res["repo_data"].get("description", "")[:60],
                            input_message_content=InputTextMessageContent(preview_text, parse_mode="HTML"),
                            thumbnail_url=res["repo_data"].get("owner", {}).get("avatar_url")
                        ))

            elif query_text.startswith(".user "):
                username = query_text[6:]
                user_data = await self.github_api.get_user(username)
                if user_data:
                    info_text = UserFormatter.format_user_info(user_data)
                    results.append(InlineQueryResultArticle(
                        id=f"user_{username}",
                        title=f"👤 {user_data.get('name', username)}",
                        description=f"@{username} - {user_data.get('bio', '')[:50]}",
                        input_message_content=InputTextMessageContent(info_text, parse_mode="HTML"),
                        thumbnail_url=user_data.get("avatar_url")
                    ))
            
            # Answer with the results. This might take a few seconds for .repo queries.
            await self.bot.answer_inline_query(query.id, results, cache_time=10)

        except Exception as e:
            logger.error(f"Error handling inline query: {e}", exc_info=True)