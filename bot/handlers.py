# In bot/handlers.py

import asyncio
import logging
from datetime import datetime
from telebot.async_telebot import AsyncTeleBot
from telebot.types import Message, InlineQueryResultArticle, InputTextMessageContent

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter, UserFormatter, URLParser

logger = logging.getLogger(__name__)


class BotHandlers:
    """
    Contains all message and query handlers for the bot. It connects user
    commands to the backend logic (database and GitHub API).
    """

    def __init__(self, bot: AsyncTeleBot, github_api: GitHubAPI, db_manager: DatabaseManager):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager

    def register_handlers(self):
        """Registers all handlers with the TeleBot instance."""
        self.bot.message_handler(commands=["start"])(self.handle_start)
        self.bot.message_handler(commands=["help"])(self.handle_help)
        self.bot.message_handler(commands=["settoken"])(self.handle_set_token)
        self.bot.message_handler(commands=["removetoken"])(self.handle_remove_token)
        self.bot.message_handler(commands=["status"])(self.handle_status)
        
        # --- NEW ---: Register the new command handler
        self.bot.message_handler(commands=["setinterval"])(self.handle_set_interval)

        # Destination management commands
        self.bot.message_handler(commands=["add_dest"])(self.handle_add_destination)
        self.bot.message_handler(commands=["remove_dest"])(self.handle_remove_destination)
        self.bot.message_handler(commands=["list_dest"])(self.handle_list_destinations)

        # Inline mode handler
        self.bot.inline_handler(lambda query: True)(self.handle_inline_query)
        logger.info("All message and query handlers registered.")

    async def handle_start(self, message: Message):
        """Handles the /start command."""
        first_name = message.from_user.first_name
        text = f"👋 **Hello, {first_name}!**\n\n"
        text += "I'm your personal GitHub Stars Bot. I'll notify you whenever you star a new repository.\n\n"
        
        if not await self.db_manager.token_exists():
            text += "To get started, please set your GitHub Personal Access Token using the command:\n"
            text += "`/settoken <YOUR_GITHUB_TOKEN>`\n\n"
        
        text += "Type /help to see all available commands."
        await self.bot.reply_to(message, text, parse_mode="Markdown")

    async def handle_help(self, message: Message):
        """Handles the /help command."""
        help_text = """
📖 *Available Commands*

*Token & Settings:*
`/settoken <TOKEN>` - Securely saves your GitHub Token.
`/removetoken` - Deletes your token and all associated data.
`/setinterval <seconds>` - Sets the check interval (min 60s).
`/status` - Shows your linked account, API limit, and current interval.

*Notification Destinations:*
`/add_dest` - Adds your private chat (DM) as a destination.
`/add_dest <ID>` - Adds a channel, group, or topic ID.
`/remove_dest <ID>` - Removes a specific destination ID.
`/remove_dest me` - Removes your DM as a destination.
`/list_dests` - Shows all configured destinations.
"""
        await self.bot.reply_to(message, help_text, parse_mode="Markdown")
        
    # --- NEW ---: Handler for the /setinterval command
    async def handle_set_interval(self, message: Message):
        """Sets the monitoring interval."""
        try:
            parts = message.text.split(" ", 1)
            if len(parts) < 2:
                await self.bot.reply_to(message, "Please provide the interval in seconds.\nExample: `/setinterval 300`", parse_mode="Markdown")
                return

            seconds = int(parts[1])
            
            # Enforce a minimum interval to prevent API spam
            min_interval = 60
            if seconds < min_interval:
                await self.bot.reply_to(message, f"❌ The minimum interval is {min_interval} seconds.", parse_mode="Markdown")
                return
            
            await self.db_manager.update_monitor_interval(seconds)
            await self.bot.reply_to(message, f"✅ Monitoring interval has been set to *{seconds}* seconds.", parse_mode="Markdown")

        except ValueError:
            await self.bot.reply_to(message, "❌ Please enter a valid number of seconds.", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in handle_set_interval: {e}")
            await self.bot.reply_to(message, "An error occurred while setting the interval.")
    
    # --- handle_set_token and handle_remove_token remain the same ---
    async def handle_set_token(self, message: Message):
        token = message.text.split(" ", 1)[-1]
        if token.startswith("/settoken"):
            await self.bot.reply_to(message, "Please provide the token after the command.\nExample: `/settoken ghp_...`", parse_mode="Markdown")
            return
        await self.db_manager.store_token(token)
        try:
            user_data = await self.github_api.get_authenticated_user()
            if not user_data or 'login' not in user_data: raise GitHubAPIError(401, "Invalid token")
            username = user_data.get("login")
            user_dm_id = str(message.from_user.id)
            await self.db_manager.add_destination(user_dm_id)
            logger.info(f"User {username}'s DM ({user_dm_id}) was set as a default destination.")
            reply_text = f"✅ **Token validated and saved!**\n\nI am now connected to the GitHub account: *@{username}*\nNotifications will be sent to your DM by default."
            await self.bot.reply_to(message, reply_text, parse_mode="Markdown")
        except GitHubAPIError:
            await self.db_manager.remove_token()
            await self.bot.reply_to(message, "❌ **Invalid Token.**\nPlease provide a valid GitHub Personal Access Token.", parse_mode="Markdown")
        finally:
            try: await self.bot.delete_message(message.chat.id, message.message_id)
            except Exception as e: logger.warning(f"Could not delete token message: {e}")

    async def handle_remove_token(self, message: Message):
        if await self.db_manager.token_exists():
            await self.db_manager.remove_token()
            await self.bot.reply_to(message, "✅ Your GitHub token and all associated data have been removed.")
        else:
            await self.bot.reply_to(message, "ℹ️ No token was found to remove.")

    async def handle_status(self, message: Message):
        """Handles the /status command."""
        if not await self.db_manager.token_exists():
            await self.bot.reply_to(message, "No GitHub token is set. Please use `/settoken`.", parse_mode="Markdown")
            return

        wait_msg = await self.bot.reply_to(message, "🔍 Fetching status...")
        
        try:
            user_task = self.github_api.get_authenticated_user()
            rate_limit_task = self.github_api.get_rate_limit()
            destinations_task = self.db_manager.get_all_destinations()
            interval_task = self.db_manager.get_monitor_interval()

            user_data, rate_limit_data, destinations, interval = await asyncio.gather(
                user_task, rate_limit_task, destinations_task, interval_task
            )

            status_text = "📊 *Bot Status*\n\n"
            status_text += f"👤 *GitHub Account:* `@{user_data.get('login', 'N/A')}`\n"
            
            if rate_limit_data:
                core_limit = rate_limit_data.get('resources', {}).get('core', {})
                remaining = core_limit.get('remaining', 'N/A')
                limit = core_limit.get('limit', 'N/A')
                reset_time = datetime.fromtimestamp(core_limit.get('reset', 0))
                
                status_text += f"📈 *API Rate Limit:* `{remaining}/{limit}` requests remaining.\n"
                status_text += f"⏳ *Resets in:* `{round((reset_time - datetime.now()).total_seconds() / 60)}` minutes.\n"

            current_interval = interval if interval else config.MONITOR_INTERVAL_SECONDS
            status_text += f"⏱️ *Check Interval:* `{current_interval}` seconds.\n"

            status_text += f"📍 *Notification Destinations:* `{len(destinations)}` configured."
            
            await self.bot.edit_message_text(status_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error fetching status: {e}")
            await self.bot.edit_message_text("❌ An error occurred while fetching status.", wait_msg.chat.id, wait_msg.message_id)

    async def handle_add_destination(self, message: Message):
        if not await self.db_manager.token_exists(): await self.bot.reply_to(message, "Please set a GitHub token before adding destinations."); return
        parts = message.text.split(" ", 1)
        target_id = str(message.from_user.id) if len(parts) == 1 else parts[1].strip()
        await self.db_manager.add_destination(target_id)
        await self.bot.reply_to(message, f"✅ Destination added: `{target_id}`", parse_mode="Markdown")

    async def handle_remove_destination(self, message: Message):
        parts = message.text.split(" ", 1)
        if len(parts) < 2: await self.bot.reply_to(message, "Please specify the destination ID to remove (e.g., `-100...` or `me`)."); return
        arg = parts[1].strip().lower()
        target_id = str(message.from_user.id) if arg == 'me' else arg
        rows_affected = await self.db_manager.remove_destination(target_id)
        if rows_affected > 0: await self.bot.reply_to(message, f"✅ Destination removed: `{target_id}`", parse_mode="Markdown")
        else: await self.bot.reply_to(message, f"❌ Destination not found: `{target_id}`", parse_mode="Markdown")
            
    async def handle_list_destinations(self, message: Message):
        destinations = await self.db_manager.get_all_destinations()
        if not destinations: await self.bot.reply_to(message, "No notification destinations are configured."); return
        text = "📋 *Configured Notification Destinations:*\n\n"
        for i, dest in enumerate(destinations, 1):
            text += f"{i}. `{dest}` {'(Your DM)' if dest == str(message.from_user.id) else ''}\n"
        await self.bot.reply_to(message, text, parse_mode="Markdown")
        
    async def _show_inline_help(self, query: InlineQueryResultArticle):
        # Get bot info to use actual username
        bot_info = await self.bot.get_me()
        bot_username = bot_info.username
        help_result = InlineQueryResultArticle(
            id="help",
            title="🤖 Bot Help",
            description="How to use inline mode: .repo owner/repo or .user username",
            input_message_content=InputTextMessageContent(
                message_text=f"""
🤖 *Personal GitHub Bot - Inline Mode*

*Usage:*
`@{bot_username} .repo owner/repo`
`@{bot_username} .user username`
""",
                parse_mode="Markdown"
            )
        )
        await self.bot.answer_inline_query(query.id, [help_result], cache_time=300)

    async def handle_inline_query(self, query: InlineQueryResultArticle):
        query_text = query.query.strip()
        if not query_text.startswith((".repo ", ".user ")): await self._show_inline_help(query); return
        results = []
        try:
            if query_text.startswith(".repo "):
                repo_input = query_text[6:]
                parsed = URLParser.parse_repo_input(repo_input)
                if parsed:
                    owner, repo_name = parsed
                    repo_data, languages, latest_release = await asyncio.gather(self.github_api.get_repository(owner, repo_name), self.github_api.get_repository_languages(owner, repo_name), self.github_api.get_latest_release(owner, repo_name))
                    if repo_data:
                        preview_text = RepoFormatter.format_repository_preview(repo_data, languages, latest_release)
                        results.append(InlineQueryResultArticle(id=f"repo_{owner}_{repo_name}", title=f"📦 {owner}/{repo_name}", description=repo_data.get("description", "")[:60], input_message_content=InputTextMessageContent(preview_text, parse_mode="HTML"), thumbnail_url=repo_data.get("owner", {}).get("avatar_url")))
            elif query_text.startswith(".user "):
                username = query_text[6:]
                user_data = await self.github_api.get_user(username)
                if user_data:
                    info_text = UserFormatter.format_user_info(user_data)
                    results.append(InlineQueryResultArticle(id=f"user_{username}", title=f"👤 {user_data.get('name', username)}", description=f"@{username} - {user_data.get('bio', '')[:50]}", input_message_content=InputTextMessageContent(info_text, parse_mode="HTML"), thumbnail_url=user_data.get("avatar_url")))
            await self.bot.answer_inline_query(query.id, results, cache_time=10)
        except Exception as e: logger.error(f"Error handling inline query: {e}", exc_info=True)