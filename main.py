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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("telebot").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class IsOwnerFilter(SimpleCustomFilter):
    key = "is_owner"

    async def check(self, message_or_query):
        if config.OWNER_USER_ID == 0:
            logger.error("OWNER_USER_ID not set!")
            return False
        return message_or_query.from_user.id == config.OWNER_USER_ID


async def main():
    try:
        logger.info("Initializing bot components...")
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

        handlers = BotHandlers(bot, github_api, db_manager, summarizer)
        handlers.register_handlers()

        monitor = RepositoryMonitor(bot, github_api, db_manager)

        scheduler = DigestScheduler(bot, github_api, db_manager, summarizer)
        scheduler.start()

        monitor_task = asyncio.create_task(monitor.start_monitoring())

        logger.info("Personal GitHub Stars Bot started successfully!")
        await bot.infinity_polling(logger_level=logging.INFO)

    except Exception as e:
        logger.error(f"A critical error occurred: {e}", exc_info=True)
    finally:
        logger.info("Bot has stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shutting down.")
