import asyncio
import logging

from telebot.async_telebot import AsyncTeleBot

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI
from bot.monitor import RepositoryMonitor
from bot.handlers import BotHandlers

# --- Logging Configuration ---
# Configure logging to display informational messages in the console.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# You can set telebot's logger to a higher level to reduce noise if needed
logging.getLogger("telebot").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    """
    The main function to initialize and run the bot.
    """
    try:
        # --- Initialization ---
        logger.info("Initializing bot components...")

        # 1. Initialize the database manager and ensure tables are created
        db_manager = DatabaseManager()
        await db_manager.init_db()

        # 2. Initialize the GitHub API client, passing the database manager
        github_api = GitHubAPI(db_manager)

        # 3. Initialize the Telegram bot instance
        if not config.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not configured. Please set it in your .env file.")
        
        bot = AsyncTeleBot(config.BOT_TOKEN, parse_mode=config.PARSE_MODE)

        # 4. Initialize and register all command handlers
        handlers = BotHandlers(bot, github_api, db_manager)
        handlers.register_handlers()

        # 5. Initialize the repository monitor
        monitor = RepositoryMonitor(bot, github_api, db_manager)

        # --- Start Services ---
        # Create a background task for the repository monitor
        monitor_task = asyncio.create_task(monitor.start_monitoring())

        logger.info("Personal GitHub Stars Bot started successfully!")
        logger.info("Bot is now polling for messages...")

        # Start the bot's polling loop. This will run indefinitely.
        await bot.infinity_polling(logger_level=logging.INFO)

    except ValueError as e:
        logger.error(f"Configuration Error: {e}")
    except Exception as e:
        logger.error(f"A critical error occurred during bot startup: {e}")
    finally:
        # This part will run if the bot stops
        if 'monitor_task' in locals() and not monitor_task.done():
            monitor_task.cancel()
            logger.info("Monitoring task has been cancelled.")
        logger.info("Bot has stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down gracefully.")