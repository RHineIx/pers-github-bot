# In main.py
import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_filters import SimpleCustomFilter

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI
from bot.monitor import RepositoryMonitor
from bot.handlers.handlers import BotHandlers
from bot.summarizer import AISummarizer
from bot.scheduler import DigestScheduler
from bot.telegram_log_handler import TelegramLogHandler
from bot.notifier import Notifier

# 1. --- Basic Logging Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s"
)
logging.getLogger("telebot").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 2. --- Telegram Log Handler (if configured) ---
if config.LOG_CHANNEL_ID:
    # Create an instance of our custom handler
    telegram_handler = TelegramLogHandler(token=config.BOT_TOKEN, channel_id=config.LOG_CHANNEL_ID)
    # Set it to only send messages for WARNING level and above
    telegram_handler.setLevel(logging.WARNING)
    # Define a clear format for the log messages sent to Telegram
    formatter = logging.Formatter('%(name)s:%(lineno)d - %(message)s')
    telegram_handler.setFormatter(formatter)
    # Add the handler to the root logger to catch errors from all modules
    logging.getLogger("").addHandler(telegram_handler)
    logger.info(f"TelegramLogHandler configured for channel {config.LOG_CHANNEL_ID}.")


# --- Custom Filter for Owner-Only Access ---
class IsOwnerFilter(SimpleCustomFilter):
    key = "is_owner"

    async def check(self, message_or_query):
        if config.OWNER_USER_ID == 0:
            logger.error("OWNER_USER_ID not set!")
            return False
        return message_or_query.from_user.id == config.OWNER_USER_ID


async def main():
    # --- MODIFIED: Initialize new task variables ---
    stars_monitor_task = None
    releases_monitor_task = None
    scheduler_manager = None
    github_api = None
    
    try:
        db_manager = DatabaseManager()
        await db_manager.init_db()
        github_api = GitHubAPI(db_manager)

        summarizer = None
        if config.GEMINI_API_KEY:
            summarizer = AISummarizer(config.GEMINI_API_KEY)
        else:
            logger.warning("GEMINI_API_KEY not found. AI features disabled.")

        bot = AsyncTeleBot(config.BOT_TOKEN, parse_mode=config.PARSE_MODE)
        bot.add_custom_filter(IsOwnerFilter())
        
        # --- Create the Notifier instance first ---
        notifier = Notifier(bot, github_api, db_manager, summarizer)

        # --- Pass the notifier to the scheduler ---
        scheduler_manager = DigestScheduler(db_manager, github_api, notifier)
        
        # --- Pass the notifier to the handlers ---
        handlers = BotHandlers(bot, github_api, db_manager, summarizer, scheduler_manager)
        handlers.register_handlers()

        # --- Pass the notifier to the monitor ---
        monitor = RepositoryMonitor(bot, github_api, db_manager, notifier)

        # --- Start the digest scheduler ---
        scheduler_manager.start()

        # --- MODIFIED: Start monitoring loops as separate tasks ---
        monitor.start_monitoring()  # This just sets the flag to True

        stars_monitor_task = asyncio.create_task(
            monitor.stars_monitoring_loop(interval=config.STARS_MONITOR_INTERVAL)
        )
        releases_monitor_task = asyncio.create_task(
            monitor.releases_monitoring_loop(interval=config.RELEASES_MONITOR_INTERVAL)
        )
        logger.info(f"Stars (interval: {config.STARS_MONITOR_INTERVAL}s) and Releases (interval: {config.RELEASES_MONITOR_INTERVAL}s) monitoring tasks started.")
        # --- End of modification ---

        logger.info("Personal GitHub Stars Bot started successfully!")
        await bot.infinity_polling(logger_level=logging.INFO)

    except Exception as e:
        logger.error(f"A critical error occurred during bot startup or runtime: {e}", exc_info=True)
    finally:
        logger.info("Bot is stopping...")
        
        # --- MODIFIED: Cancel the two new tasks ---
        if stars_monitor_task and not stars_monitor_task.done():
            stars_monitor_task.cancel()
            logger.info("Stars monitoring task has been cancelled.")
        
        if releases_monitor_task and not releases_monitor_task.done():
            releases_monitor_task.cancel()
            logger.info("Releases monitoring task has been cancelled.")
        # --- End of modification ---
        
        if scheduler_manager and scheduler_manager.scheduler.running:
            scheduler_manager.scheduler.shutdown()
            logger.info("Digest scheduler has been shut down.")
        
        if github_api:
            await github_api.close()
            logger.info("GitHub API session has been closed.")
        logger.info("Bot has stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down.")