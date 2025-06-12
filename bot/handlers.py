# bot/handlers.py
# This module contains the BotHandlers class, which defines and registers
# all the command, message, and query handlers for the bot.

import asyncio
import logging
from datetime import datetime
from typing import Optional

from telebot.async_telebot import AsyncTeleBot
from telebot.types import (
    Message,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ReactionTypeEmoji,
)
from telebot.apihelper import ApiTelegramException

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter, UserFormatter, URLParser
from bot.utils import format_duration
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

    def register_handlers(self):
        # Register all command and query handlers, protected by the owner filter.
        
        # Main Commands
        self.bot.message_handler(is_owner=True, commands=["start", "help"])(self.handle_help)
        self.bot.message_handler(is_owner=True, commands=["status"])(self.handle_status)
        
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

        # General handler for reactions on any message from the owner.
        self.bot.message_handler(is_owner=True, content_types=['text'])(self.handle_reaction)
        
        logger.info("All message and query handlers registered.")

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

    async def handle_reaction(self, message: Message):
        # Reacts to every message from the owner.
        try:
            reaction = [ReactionTypeEmoji(emoji='👍')]
            await self.bot.set_message_reaction(chat_id=message.chat.id, message_id=message.message_id, reaction=reaction, is_big=False)
        except Exception as e:
            logger.warning(f"Could not set reaction: {e}")

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
