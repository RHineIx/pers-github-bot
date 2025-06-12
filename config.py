import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

class Config:
    # --- Telegram & Owner ---
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    # The bot will only respond to this user ID.
    OWNER_USER_ID: int = int(os.getenv("OWNER_USER_ID", 0))

    # --- ID for the private error logging channel ---
    LOG_CHANNEL_ID: str = os.getenv("LOG_CHANNEL_ID")

    # --- Gemini AI Settings ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # Load model name from .env for flexibility. Fallback to a stable version.
    GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash-latest")

    # --- GitHub API Settings ---
    GITHUB_API_BASE: str = "https://api.github.com"
    
    # --- Bot Behavior ---
    PARSE_MODE: str = "HTML"
    REQUEST_TIMEOUT: int = 30  # seconds
    CACHE_TTL_SECONDS: int = 1800  # Cache API responses for 30 minutes

    # --- Monitoring Settings ---
    # Default interval, can be overridden by user command.
    MONITOR_INTERVAL_SECONDS: int = 300  # 5 minutes

config = Config()