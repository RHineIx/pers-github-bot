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

    # Gemini API  Key https://aistudio.google.com/apikey
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL_NAME: str = "gemini-2.5-flash-preview-05-20"

    # --- NEW: Define the Bot Owner's User ID ---
    # The default of 0 is an invalid ID, ensuring the bot is locked if not set.
    OWNER_USER_ID: int = int(os.getenv("OWNER_USER_ID", 0))

    # --- GitHub API Settings ---
    GITHUB_API_BASE: str = "https://api.github.com"
    # Note: GITHUB_TOKEN is now managed via the database, not from .env
    # --- Bot Behavior Settings ---
    PARSE_MODE: str = "HTML"
    REQUEST_TIMEOUT: int = 30  # seconds
    CACHE_TTL_SECONDS: int = 1800  # Cache API responses for 30 minutes

    # --- Monitoring Settings ---
    MONITOR_INTERVAL_SECONDS: int = 300  # Check for new stars every 5 minutes


# Create a global config instance to be used throughout the application
config = Config()
