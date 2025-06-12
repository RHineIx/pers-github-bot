# bot/monitor.py
# This module contains the RepositoryMonitor, which continuously checks for
# new starred repos and decides whether to queue them for a digest or
# trigger an instant notification.

import asyncio
import logging
from typing import Optional

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from bot.scheduler import DigestScheduler  # Import scheduler for dependency

logger = logging.getLogger(__name__)


class RepositoryMonitor:
    def __init__(
        self,
        github_api: GitHubAPI,
        db_manager: DatabaseManager,
        scheduler: DigestScheduler, # Now depends on the scheduler for instant notifications
    ):
        self.github_api = github_api
        self.db_manager = db_manager
        self.scheduler = scheduler
        self.is_monitoring = False

    async def start_monitoring(self):
        # Starts the background monitoring loop.
        self.is_monitoring = True
        logger.info("Repository monitoring service started.")
        while self.is_monitoring:
            try:
                # First, check if monitoring is paused by the user.
                if await self.db_manager.is_monitoring_paused():
                    logger.info("Monitoring is paused. Skipping check cycle.")
                # Then, check if a token exists to perform the check.
                elif await self.db_manager.token_exists():
                    await self._check_for_new_stars()
                else:
                    logger.debug("No GitHub token found. Skipping monitoring cycle.")

                # Dynamically fetch the sleep interval.
                interval_seconds = await self.db_manager.get_monitor_interval() or config.MONITOR_INTERVAL_SECONDS
                if interval_seconds < 60:
                    interval_seconds = 60 # Enforce a minimum of 60 seconds.
                
                logger.debug(f"Monitoring loop sleeping for {interval_seconds} seconds.")
                await asyncio.sleep(interval_seconds)

            except Exception as e:
                logger.error(f"An unexpected error in monitoring loop: {e}", exc_info=True)
                await asyncio.sleep(60) # Wait a minute before retrying on major errors.

    async def _check_for_new_stars(self):
        # The core logic for detecting new stars.
        logger.info("Checking for new starred repositories...")
        try:
            starred_events = await self.github_api.get_authenticated_user_starred_repos()
            if not starred_events:
                return

            last_check_timestamp = await self.db_manager.get_last_check_timestamp()
            new_starred_repos = []

            # Establish baseline on first run.
            if not last_check_timestamp:
                await self.db_manager.update_last_check_timestamp(starred_events[0]['starred_at'])
                logger.info("First run. Baseline timestamp established.")
                return

            # Find all repos starred after the last check.
            for event in starred_events:
                if event['starred_at'] > last_check_timestamp:
                    new_starred_repos.append(event['repo'])
                else:
                    break # The list is sorted, so we can stop here.

            if new_starred_repos:
                logger.info(f"Found {len(new_starred_repos)} new starred repositories.")
                digest_mode = await self.db_manager.get_digest_mode()

                # Reverse the list to process them in the order they were starred.
                new_starred_repos.reverse()
                
                # Based on the user's setting, either send instantly or queue for digest.
                if digest_mode == "off":
                    logger.info("Digest mode is OFF. Sending notifications instantly...")
                    for repo in new_starred_repos:
                        # Call the notification logic directly from the scheduler to avoid code duplication.
                        await self.scheduler._process_and_send_notification(repo)
                        await asyncio.sleep(2) # A small delay between instant sends.
                else:
                    logger.info(f"Digest mode is '{digest_mode}'. Adding new repos to the queue.")
                    for repo in new_starred_repos:
                        await self.db_manager.add_repo_to_digest(repo['full_name'])
            else:
                logger.info("No new starred repositories found.")

            # Update the timestamp to the latest one found in this batch.
            await self.db_manager.update_last_check_timestamp(starred_events[0]['starred_at'])
            # If the check was successful, clear any previous error state.
            await self.db_manager.clear_last_error()

        except GitHubAPIError as e:
            # Smart error handling for invalid tokens.
            if e.status_code == 401:
                logger.error("GitHub token is invalid. Pausing monitoring.")
                await self.db_manager.set_monitoring_paused(True)
                error_msg = "Your GitHub token is invalid. Monitoring automatically paused."
                await self.db_manager.update_last_error(error_msg)
            else:
                logger.error(f"A GitHub API error occurred during check: {e}")
        except Exception as e:
            logger.error(f"A critical error occurred during star checking process: {e}", exc_info=True)