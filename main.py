# In main.py
import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_filters import SimpleCustomFilter

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI
from bot.monitor import RepositoryMonitor
from bot.handlers import BotHandlers
from bot.summarizer import AISummarizer
from bot.scheduler import DigestScheduler
from bot.telegram_log_handler import TelegramLogHandler

# 1. --- Basic Logging Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s"
)
logging.getLogger("telebot").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 2. --- Add Telegram Log Handler (if configured) ---
if config.LOG_CHANNEL_ID:
    # Create an instance of our custom handler
    telegram_handler = TelegramLogHandler(token=config.BOT_TOKEN, channel_id=config.LOG_CHANNEL_ID)
    # Set it to only send messages for ERROR level and above
    telegram_handler.setLevel(logging.ERROR)
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
    # Define tasks here to be accessible in the 'finally' block for cleanup
    monitor_task = None
    scheduler = None
    
    try:
        
        # Initialize database and API clients first as they are dependencies for others.
        db_manager = DatabaseManager()
        await db_manager.init_db()
        github_api = GitHubAPI(db_manager)

        # Initialize the AI summarizer only if the API key is provided.
        summarizer = None
        if config.GEMINI_API_KEY:
            summarizer = AISummarizer(config.GEMINI_API_KEY)
        else:
            logger.warning("GEMINI_API_KEY not found. AI features disabled.")

        # Initialize the main bot instance.
        bot = AsyncTeleBot(config.BOT_TOKEN, parse_mode=config.PARSE_MODE)
        
        # Register our custom owner-only filter.
        bot.add_custom_filter(IsOwnerFilter())

        # Initialize the background task managers that handlers depend on.
        scheduler = DigestScheduler(bot, github_api, db_manager, summarizer)
        
        # Initialize command handlers and register them with the bot.
        # We pass the scheduler instance to the handlers now.
        handlers = BotHandlers(bot, github_api, db_manager, summarizer, scheduler)
        handlers.register_handlers()

        # Initialize the repository monitor.
        monitor = RepositoryMonitor(bot, github_api, db_manager, scheduler)

        # Start the digest scheduler (for daily/weekly notifications).
        scheduler.start()

        # Start the repository monitoring loop as a concurrent task.
        monitor_task = asyncio.create_task(monitor.start_monitoring())


        logger.info("Personal GitHub Stars Bot started successfully!")
        await bot.infinity_polling(logger_level=logging.INFO)

    except Exception as e:
        logger.error(f"A critical error occurred during bot startup or runtime: {e}", exc_info=True)
    finally:
        # This block ensures that background tasks are properly shut down when the bot stops.
        logger.info("Bot is stopping...")
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()
            logger.info("Monitoring task has been cancelled.")
        if scheduler and scheduler.scheduler.running:
            scheduler.scheduler.shutdown()
            logger.info("Digest scheduler has been shut down.")
        if 'github_api' in locals() and github_api:
            await github_api.close()
            logger.info("GitHub API session has been closed.")
        logger.info("Bot has stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down.")