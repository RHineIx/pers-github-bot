# main.py

import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI
from bot.monitor import RepositoryMonitor
from bot.handlers import BotHandlers
from bot.summarizer import AISummarizer

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("telebot").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main():
    """
    The main function to initialize and run the bot.
    """
    try:
        logger.info("Initializing bot components...")
        db_manager = DatabaseManager()
        await db_manager.init_db()

        github_api = GitHubAPI(db_manager)
        
        # This is the section that initializes the summarizer
        if not config.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not found. AI summarization will be disabled.")
            summarizer = None
        else:
            summarizer = AISummarizer(config.GEMINI_API_KEY)
        
        bot = AsyncTeleBot(config.BOT_TOKEN, parse_mode=config.PARSE_MODE)
        
        # This is the line that was causing the error.
        # correctly passes the 'summarizer' object.
        handlers = BotHandlers(bot, github_api, db_manager, summarizer)
        handlers.register_handlers()
        
        monitor = RepositoryMonitor(bot, github_api, db_manager, summarizer)
        monitor_task = asyncio.create_task(monitor.start_monitoring())

        logger.info("Personal GitHub Stars Bot started successfully!")
        logger.info("Bot is now polling for messages...")
        await bot.infinity_polling(logger_level=logging.INFO)

    except Exception as e:
        logger.error(f"A critical error occurred during bot startup: {e}", exc_info=True)
    finally:
        logger.info("Bot has stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down.")