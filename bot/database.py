# bot/database.py
# This module contains the DatabaseManager class, which encapsulates all
# database operations using a persistent SQLite database.

import aiosqlite
import json
import logging
import os
from cryptography.fernet import Fernet
from typing import Optional, List, Set

logger = logging.getLogger(__name__)

DB_PATH = "bot_data.db"
KEY_PATH = "bot_secret.key"


# Manages all persistent data using SQLite.
class DatabaseManager:

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        # Ensures encryption key exists for token security.
        self.encryption_key = self._get_or_create_key()
        self.cipher = Fernet(self.encryption_key)
        self._db_initialized = False

    def _get_or_create_key(self) -> bytes:
        # Loads the key from a file, or generates a new one if not found.
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
        # Sets up the database schema on the first run.
        if self._db_initialized:
            return
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                # Key-value store for general bot settings.
                await conn.execute("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                # Stores notification chat/channel/topic IDs.
                await conn.execute("CREATE TABLE IF NOT EXISTS destinations (target_id TEXT PRIMARY KEY)")
                # Queue for repos to be included in the next digest.
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS digest_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        repo_full_name TEXT UNIQUE NOT NULL,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.commit()
            self._db_initialized = True
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
            
    # --- Digest/Queue Management ---

    async def update_digest_mode(self, mode: str):
        # Stores the user's preferred notification mode ('off', 'daily', 'weekly').
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("digest_mode", mode))
            await conn.commit()
        logger.info(f"Digest mode set to: {mode}")

    async def get_digest_mode(self) -> str:
        # Retrieves the current digest mode, defaulting to 'off'.
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("digest_mode",))
            result = await cursor.fetchone()
            return result[0] if result else "off"

    async def add_repo_to_digest(self, repo_full_name: str):
        # Adds a newly starred repo to the queue for the next digest.
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO digest_queue (repo_full_name) VALUES (?)", (repo_full_name,))
            await conn.commit()

    async def get_and_clear_digest_queue(self) -> List[str]:
        # Atomically retrieves and clears the digest queue for processing.
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT repo_full_name FROM digest_queue ORDER BY added_at ASC")
            repo_list = [row[0] for row in await cursor.fetchall()]
            if repo_list:
                await conn.execute("DELETE FROM digest_queue")
                await conn.commit()
            return repo_list
    
    async def get_digest_queue_count(self) -> int:
        """Counts the number of items currently in the digest queue."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM digest_queue")
            result = await cursor.fetchone()
            return result[0] if result else 0

    # --- Core State & Token Management ---

    async def store_token(self, token: str) -> None:
        # Encrypts and saves the GitHub token.
        encrypted_token = self.cipher.encrypt(token.encode()).decode()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("github_token", encrypted_token))
            await conn.commit()

    async def get_token(self) -> Optional[str]:
        # Retrieves and decrypts the GitHub token.
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("github_token",))
            result = await cursor.fetchone()
            if result:
                return self.cipher.decrypt(result[0].encode()).decode()
        return None

    async def remove_token(self) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM bot_state WHERE key = ?", ("github_token",))
            await conn.commit()

    async def token_exists(self) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT 1 FROM bot_state WHERE key = ?", ("github_token",))
            return await cursor.fetchone() is not None

    # --- Destination Management ---

    async def add_destination(self, target_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO destinations (target_id) VALUES (?)", (target_id,))
            await conn.commit()

    async def remove_destination(self, target_id: str) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("DELETE FROM destinations WHERE target_id = ?", (target_id,))
            await conn.commit()
            return cursor.rowcount

    async def get_all_destinations(self) -> List[str]:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT target_id FROM destinations")
            rows = await cursor.fetchall()
            return [row[0] for row in rows] if rows else []

    # --- Generic Key-Value State Methods ---

    async def update_last_check_timestamp(self, timestamp: str) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("last_check_timestamp", timestamp))
            await conn.commit()

    async def get_last_check_timestamp(self) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("last_check_timestamp",))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def update_monitor_interval(self, seconds: int) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("monitor_interval", str(seconds)))
            await conn.commit()

    async def get_monitor_interval(self) -> Optional[int]:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("monitor_interval",))
            result = await cursor.fetchone()
            return int(result[0]) if result else None

    async def set_monitoring_paused(self, paused: bool) -> None:
        value_to_store = "1" if paused else "0"
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("monitoring_paused", value_to_store))
            await conn.commit()

    async def is_monitoring_paused(self) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("monitoring_paused",))
            result = await cursor.fetchone()
            return result[0] == "1" if result else False

    async def update_last_error(self, message: str) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("last_error_message", message))
            await conn.commit()

    async def get_last_error(self) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("last_error_message",))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def clear_last_error(self) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM bot_state WHERE key = ?", ("last_error_message",))
            await conn.commit()

    async def set_bot_state(self, state: str):  
        async with aiosqlite.connect(self.db_path) as conn:  
            await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("bot_state", state))  
            await conn.commit()  
    
    async def get_bot_state(self):  
        async with aiosqlite.connect(self.db_path) as conn:  
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("bot_state",))  
            result = await cursor.fetchone()  
            return {"state": result[0]} if result else None  
    
    async def clear_bot_state(self):  
        async with aiosqlite.connect(self.db_path) as conn:  
            await conn.execute("DELETE FROM bot_state WHERE key = ?", ("bot_state",))  
            await conn.commit()

    async def set_ai_features_enabled(self, enabled: bool) -> None:
            """Saves the on/off state for AI features."""
            value_to_store = "1" if enabled else "0"
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", ("ai_features_enabled", value_to_store))
                await conn.commit()

    async def are_ai_features_enabled(self) -> bool:
        """Checks if AI features are enabled, defaulting to True."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute("SELECT value FROM bot_state WHERE key = ?", ("ai_features_enabled",))
            result = await cursor.fetchone()
            # Default to True (1) if the setting is not found
            return result[0] == "1" if result else True