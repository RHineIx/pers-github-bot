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
from bot.scheduler import DigestScheduler 
from telebot.async_telebot import AsyncTeleBot
from config import config
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bot.notifier import Notifier

logger = logging.getLogger(__name__)


class RepositoryMonitor:
    def __init__(
        self,
        bot: AsyncTeleBot,
        github_api: GitHubAPI,
        db_manager: DatabaseManager,
        notifier: "Notifier",
    ):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.notifier = notifier
        self.is_monitoring = False

    def start_monitoring(self):
        """Sets the monitoring flag to True. The loops are started from main."""
        self.monitoring = True
        logger.info("Repository monitoring enabled.")

    async def stars_monitoring_loop(self, interval: int):
        """The dedicated monitoring loop for checking new stars."""
        logger.info(f"Stars monitoring loop started. Interval: {interval} seconds.")
        while self.monitoring:
            try:
                await self._check_for_new_stars()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Stars monitoring loop was cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in stars monitoring loop: {e}")
                await asyncio.sleep(60) # Wait 1 minute before retrying on error

    async def releases_monitoring_loop(self, interval: int):
        """The dedicated monitoring loop for checking new releases."""
        logger.info(f"Releases monitoring loop started. Interval: {interval} seconds.")
        while self.monitoring:
            try:
                await self._check_for_new_releases()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("Releases monitoring loop was cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in releases monitoring loop: {e}")
                await asyncio.sleep(60) # Wait 1 minute before retrying on error

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

                new_starred_repos.reverse()
                
                if digest_mode == "off":
                    logger.info("Digest mode is OFF. Sending notifications instantly...")
                    for repo in new_starred_repos:
                        # --- It now calls the notifier directly ---
                        await self.notifier.send_repo_notification(repo)
                        await asyncio.sleep(2)
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
            if e.status_code == 401:
                logger.error("GitHub token is invalid or expired. Notifying owner and pausing monitoring.")
                
                await self.db_manager.set_monitoring_paused(True)
                error_msg = "Your GitHub token is invalid or has expired. Monitoring has been automatically paused."
                await self.db_manager.update_last_error(error_msg)
                try:
                    notification_text = (
                        "⚠️ **GitHub Token Error**\n\n"
                        "Your GitHub token is either invalid or has expired. "
                        "The bot has paused monitoring your stars.\n\n"
                        "Please generate a new token and use the following command to resume:\n"
                        "`/settoken <Your_New_Token>`"
                    )
                    await self.bot.send_message(
                        config.OWNER_USER_ID, 
                        notification_text, 
                        parse_mode="Markdown"
                    )
                    logger.info("Successfully sent token error notification to the owner.")
                except Exception as notify_err:
                    logger.error(f"FATAL: Failed to send token error notification to owner: {notify_err}")

            else:
                logger.error(f"A GitHub API error occurred during check: {e}")
        except Exception as e:
            logger.error(f"A critical error occurred during star checking process: {e}", exc_info=True)

    async def _check_for_new_releases(self):
        """Checks all tracked repositories for new releases."""
        logger.info("Checking for new releases...")
        try:
            tracked_repos = await self.db_manager.get_all_tracked_releases_with_subscriptions()

            for repo in tracked_repos:
                repo_full_name = repo['repo_full_name']
                last_seen_tag = repo['last_release_tag']
                subscriptions = repo['subscriptions']

                if not subscriptions:
                    continue

                try:
                    # --- START OF CORRECTION ---
                    owner, repo_name = repo_full_name.split('/')
                    latest_release = await self.github_api.get_latest_release(owner, repo_name)
                    # --- END OF CORRECTION ---

                    if not latest_release:
                        continue
                    
                    current_release_tag = latest_release.get("tag_name")

                    if current_release_tag and current_release_tag != last_seen_tag:
                        logger.info(f"New release found for {repo_full_name}: {current_release_tag}")
                        
                        # --- START OF CORRECTION ---
                        repo_info = await self.github_api.get_repository(owner, repo_name)
                        # --- END OF CORRECTION ---

                        if not repo_info:
                            logger.warning(f"Could not fetch repo info for {repo_full_name}, skipping notification.")
                            continue
                            
                        # This will call the notifier method. Make sure it exists in your notifier.py
                        await self.notifier.send_release_notification(latest_release, repo_info, subscriptions)
                        
                        await self.db_manager.update_last_release_tag(repo_full_name, current_release_tag)

                except Exception as e:
                    logger.error(f"Failed to check releases for {repo_full_name}: {e}")
        except Exception as e:
            logger.error(f"Failed to fetch tracked releases from DB: {e}")