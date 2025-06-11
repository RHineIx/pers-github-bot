import aiosqlite
import json
import logging
import os
from cryptography.fernet import Fernet
from typing import Optional, List, Set

# Configure logger
logger = logging.getLogger(__name__)

# Define the paths for the database and encryption key
DB_PATH = "bot_data.db"
KEY_PATH = "bot_secret.key"


class DatabaseManager:
    """
    Manages all database operations for the bot in a persistent SQLite database.
    This includes handling the encrypted user token, notification destinations,
    and the state of the last seen starred repositories.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.encryption_key = self._get_or_create_key()
        self.cipher = Fernet(self.encryption_key)
        self._db_initialized = False

    def _get_or_create_key(self) -> bytes:
        """
        Loads the encryption key from a file or generates a new one if it doesn't exist.
        This ensures the token remains encrypted with the same key across bot restarts.
        """
        if os.path.exists(KEY_PATH):
            with open(KEY_PATH, "rb") as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(KEY_PATH, "wb") as f:
                f.write(key)
            logger.info(f"New encryption key generated and saved to {KEY_PATH}")
            return key

    async def init_db(self):
        """
        Initializes the database connection and creates the necessary tables
        if they do not already exist.
        """
        if self._db_initialized:
            return

        try:
            async with aiosqlite.connect(self.db_path) as conn:
                # A simple key-value table for storing state like the token and last starred IDs
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS bot_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                """)

                # A table to store all notification destinations
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS destinations (
                        target_id TEXT PRIMARY KEY
                    )
                """)
                await conn.commit()
            self._db_initialized = True
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    # --- Token Management ---

    async def store_token(self, token: str) -> None:
        """Encrypts and stores the GitHub token in the database."""
        encrypted_token = self.cipher.encrypt(token.encode()).decode()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                ("github_token", encrypted_token),
            )
            await conn.commit()
        logger.info("GitHub token has been successfully encrypted and stored.")

    async def get_token(self) -> Optional[str]:
        """Retrieves and decrypts the GitHub token from the database."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", ("github_token",)
            )
            result = await cursor.fetchone()
            if result:
                decrypted_token = self.cipher.decrypt(result[0].encode()).decode()
                return decrypted_token
        return None

    async def remove_token(self) -> None:
        """Removes the GitHub token from the database."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM bot_state WHERE key = ?", ("github_token",))
            await conn.commit()
        logger.info("GitHub token has been removed from the database.")

    async def token_exists(self) -> bool:
        """Checks if a GitHub token is currently stored."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM bot_state WHERE key = ?", ("github_token",)
            )
            return await cursor.fetchone() is not None

    # --- Destination Management ---

    async def add_destination(self, target_id: str) -> None:
        """Adds a new notification destination."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO destinations (target_id) VALUES (?)", (target_id,)
            )
            await conn.commit()

    async def remove_destination(self, target_id: str) -> int:
        """Removes a notification destination and returns the number of rows affected."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM destinations WHERE target_id = ?", (target_id,)
            )
            await conn.commit()
            return cursor.rowcount

    async def get_all_destinations(self) -> List[str]:
        """Retrieves a list of all stored notification destinations."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT target_id FROM destinations")
            rows = await cursor.fetchall()
            return [row[0] for row in rows] if rows else []

    # --- State Management (for Star Tracking) ---

    async def update_last_check_timestamp(self, timestamp: str) -> None:
        """Saves the timestamp of the last processed starred repository."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                ("last_check_timestamp", timestamp),
            )
            await conn.commit()

    async def get_last_check_timestamp(self) -> Optional[str]:
        """Retrieves the timestamp of the last processed starred repository."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", ("last_check_timestamp",)
            )
            result = await cursor.fetchone()
            return result[0] if result else None

    async def update_monitor_interval(self, seconds: int) -> None:
        """Saves the monitor interval in seconds to the database."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                ("monitor_interval", str(seconds)),
            )
            await conn.commit()
        logger.info(f"Monitor interval has been updated to {seconds} seconds.")

    async def get_monitor_interval(self) -> Optional[int]:
        """Retrieves the monitor interval in seconds from the database."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", ("monitor_interval",)
            )
            result = await cursor.fetchone()
            if result:
                return int(result[0])
        return None
    
    async def set_monitoring_paused(self, paused: bool) -> None:
        """Sets the monitoring paused state in the database."""
        # We store the boolean as "1" for True and "0" for False.
        value_to_store = "1" if paused else "0"
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                ("monitoring_paused", value_to_store),
            )
            await conn.commit()
        logger.info(f"Monitoring paused state set to: {paused}")

    async def is_monitoring_paused(self) -> bool:
        """Checks if monitoring is currently paused, returning False by default."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", ("monitoring_paused",)
            )
            result = await cursor.fetchone()
            # If the value is "1", it's paused. Otherwise, it's not.
            return result[0] == "1" if result else False
        
    async def update_last_error(self, message: str) -> None:
        """Stores the last critical error message."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)",
                ("last_error_message", message),
            )
            await conn.commit()

    async def get_last_error(self) -> Optional[str]:
        """Retrieves the last critical error message."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", ("last_error_message",)
            )
            result = await cursor.fetchone()
            return result[0] if result else None

    async def clear_last_error(self) -> None:
        """Clears the last critical error message."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM bot_state WHERE key = ?", ("last_error_message",))
            await conn.commit()