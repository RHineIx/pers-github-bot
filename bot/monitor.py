import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter

logger = logging.getLogger(__name__)


class RepositoryMonitor:
    """
    Monitors the user's GitHub account for newly starred repositories
    and sends formatted notifications to all registered destinations.
    """

    def __init__(self, bot: AsyncTeleBot, github_api: GitHubAPI, db_manager: DatabaseManager):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.is_monitoring = False

    async def start_monitoring(self):
        """
        Starts the background monitoring loop. The loop dynamically fetches the
        interval from the database, allowing for runtime changes.
        """
        self.is_monitoring = True
        logger.info("Repository monitoring service started.")

        while self.is_monitoring:
            try:
                if await self.db_manager.token_exists():
                    await self._check_for_new_stars()
                else:
                    logger.debug("No GitHub token found. Skipping monitoring cycle.")
                
                # Fetch interval from DB, or use the default from config if not set
                interval_seconds = await self.db_manager.get_monitor_interval()
                if not interval_seconds or interval_seconds < 60:
                    interval_seconds = config.MONITOR_INTERVAL_SECONDS
                
                logger.debug(f"Monitoring loop sleeping for {interval_seconds} seconds.")
                await asyncio.sleep(interval_seconds)

            except Exception as e:
                logger.error(f"An unexpected error occurred in the monitoring loop: {e}")
                await asyncio.sleep(60)

    def stop_monitoring(self):
        """Stops the monitoring loop."""
        self.is_monitoring = False
        logger.info("Repository monitoring service stopped.")

    async def _check_for_new_stars(self):
        """
        The core logic for checking for new stars using timestamps for accuracy.
        This method is robust against un-starring events.
        """
        logger.info("Checking for new starred repositories using timestamp method...")
        try:
            # 1. Fetch the most recently starred repos with timestamp data
            starred_events = await self.github_api.get_authenticated_user_starred_repos(page=1, per_page=50)
            if not starred_events:
                logger.info("No starred repositories found or API error.")
                return

            # 2. Get the timestamp of the last repo we processed
            last_check_timestamp = await self.db_manager.get_last_check_timestamp()

            # 3. Find all repos starred *after* our last check
            new_starred_repos = []
            if last_check_timestamp:
                for event in starred_events:
                    if event['starred_at'] > last_check_timestamp:
                        new_starred_repos.append(event['repo'])
                    else:
                        # Since the list is sorted newest to oldest, we can stop
                        # as soon as we see an event older than our last check.
                        break
            
            # 4. Handle the initial run: just set the baseline
            else:
                newest_timestamp = starred_events[0]['starred_at']
                logger.info(f"This is the first run. Establishing baseline timestamp: {newest_timestamp}")
                await self.db_manager.update_last_check_timestamp(newest_timestamp)
                return

            # 5. If new repos were found, process and notify
            if not new_starred_repos:
                logger.info("No new starred repositories found.")
                # We still update the timestamp to the very latest one found
                await self.db_manager.update_last_check_timestamp(starred_events[0]['starred_at'])
                return
            
            logger.info(f"Found {len(new_starred_repos)} new starred repositories!")
            
            # Reverse to notify in the order they were starred (oldest first)
            new_starred_repos.reverse()

            for repo_data in new_starred_repos:
                await self._send_notification(repo_data)
            
            # 6. Update the database with the timestamp of the newest repo found
            # in this batch, making it the baseline for the next check.
            latest_timestamp_in_batch = starred_events[0]['starred_at']
            await self.db_manager.update_last_check_timestamp(latest_timestamp_in_batch)

        except GitHubAPIError as e:
            logger.error(f"GitHub API error while checking for stars: {e}")
        except Exception as e:
            logger.error(f"Error during star checking process: {e}", exc_info=True)

    async def _send_notification(self, repo_data: dict):
        """
        Fetches full details for a repository, formats the message,
        and sends it to all saved destinations.
        """
        owner = repo_data.get("owner", {}).get("login")
        repo_name = repo_data.get("name")
        
        if not owner or not repo_name:
            logger.error(f"Could not parse owner/repo from data: {repo_data.get('full_name')}")
            return

        try:
            # Fetch supplementary data for a rich preview
            full_repo_data_task = self.github_api.get_repository(owner, repo_name)
            languages_task = self.github_api.get_repository_languages(owner, repo_name)
            release_task = self.github_api.get_latest_release(owner, repo_name)
            
            # Run all API calls concurrently for speed
            repo_details, languages, latest_release = await asyncio.gather(
                full_repo_data_task, languages_task, release_task
            )

            if not repo_details:
                logger.error(f"Failed to fetch full details for {owner}/{repo_name}")
                return

            # Format the message using our formatter
            message_text = RepoFormatter.format_repository_preview(
                repo_details, languages, latest_release
            )
            
            # Get all destinations and send the message
            destinations = await self.db_manager.get_all_destinations()
            if not destinations:
                logger.warning(f"New star found ({owner}/{repo_name}), but no notification destinations are set.")
                return

            logger.info(f"Sending notification for {owner}/{repo_name} to {len(destinations)} destination(s).")
            for target in destinations:
                try:
                    chat_id = target
                    thread_id = None
                    if '/' in target:
                        parts = target.split('/')
                        chat_id = parts[0]
                        thread_id = int(parts[1])

                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message_text,
                        parse_mode=config.PARSE_MODE,
                        disable_web_page_preview=False, # Show the repo link preview
                        message_thread_id=thread_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to destination {target}: {e}")

        except Exception as e:
            logger.error(f"Failed to process and send notification for {owner}/{repo_name}: {e}")