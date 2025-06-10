"""
Configuration settings for the Personal GitHub Stars Bot.
"""
import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()


class Config:
    """
    Application configuration class.
    Reads settings from environment variables and defines constants.
    """

    # --- Telegram Bot Settings ---
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # --- GitHub API Settings ---
    GITHUB_API_BASE: str = "https://api.github.com"
    # Note: GITHUB_TOKEN is now managed via the database, not from .env

    # --- Bot Behavior Settings ---
    PARSE_MODE: str = "HTML"
    REQUEST_TIMEOUT: int = 30  # seconds
    CACHE_TTL_SECONDS: int = 600  # Cache API responses for 10 minutes

    # --- Monitoring Settings ---
    MONITOR_INTERVAL_SECONDS: int = 300  # Check for new stars every 5 minutes

    # --- Download Settings (for inline mode and future features) ---
    MAX_DOWNLOAD_SIZE_MB: int = 50
    ITEMS_PER_PAGE: int = 5


# Create a global config instance to be used throughout the application
config = Config()