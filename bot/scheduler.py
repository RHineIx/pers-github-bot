# bot/scheduler.py

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Add this import for type hinting ---
if TYPE_CHECKING:
    from bot.notifier import Notifier

from bot.database import DatabaseManager
from github.api import GitHubAPI

logger = logging.getLogger(__name__)


class DigestScheduler:
    def __init__(
        self,
        db_manager: DatabaseManager,
        github_api: GitHubAPI,
        notifier: "Notifier",
    ):
        # --- The scheduler now only needs these components ---
        self.db_manager = db_manager
        self.github_api = github_api
        self.notifier = notifier
        self.scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    def start(self):
        # --- This part remains the same ---
        self.scheduler.add_job(self.send_daily_digest, "cron", hour=21, minute=0)
        self.scheduler.add_job(
            self.send_weekly_digest, "cron", day_of_week="sun", hour=21, minute=0
        )
        self.scheduler.start()
        logger.info(
            "Digest scheduler started. Daily job at 21:00, Weekly job on Sunday at 21:00."
        )

    async def send_daily_digest(self):
        # --- This part remains the same ---
        digest_mode = await self.db_manager.get_digest_mode()
        if digest_mode == "daily":
            logger.info("Running daily digest job...")
            await self._send_digest()

    async def send_weekly_digest(self):
        # --- This part remains the same ---
        digest_mode = await self.db_manager.get_digest_mode()
        if digest_mode == "weekly":
            logger.info("Running weekly digest job...")
            await self._send_digest()

    async def _send_digest(self):
        # --- This method is now much simpler ---
        queued_repos = await self.db_manager.get_and_clear_digest_queue()
        if not queued_repos:
            logger.info("Digest job ran, but the queue was empty.")
            return

        logger.info(
            f"Found {len(queued_repos)} items in digest queue. Sending notifications now..."
        )
        for repo_full_name in queued_repos:
            try:
                owner, repo_name = repo_full_name.split("/")
                repo_data = await self.github_api.get_repository(owner, repo_name)
                if repo_data:
                    # --- It now calls the notifier to do the heavy lifting ---
                    await self.notifier.send_repo_notification(repo_data)
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(
                    f"Failed to process {repo_full_name} from digest queue: {e}"
                )
                