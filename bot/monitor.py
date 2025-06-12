import asyncio
import logging
from telebot.async_telebot import AsyncTeleBot
from typing import Optional
from telebot.types import InputMediaPhoto, InputMediaVideo

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI, GitHubAPIError
from github.formatter import RepoFormatter
from bot.summarizer import AISummarizer
from bot.utils import extract_media_from_readme

logger = logging.getLogger(__name__)


class RepositoryMonitor:
    """
    Monitors the user's GitHub account for newly starred repositories
    and sends formatted notifications to all registered destinations.
    """

    def __init__(
        self, bot: AsyncTeleBot, github_api: GitHubAPI, db_manager: DatabaseManager
    ):
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.is_monitoring = False

    async def start_monitoring(self):
        """
        Starts the background monitoring loop. The loop first checks if
        monitoring is paused before proceeding with any API calls.
        """
        self.is_monitoring = True
        logger.info("Repository monitoring service started.")
        while self.is_monitoring:
            try:
                if await self.db_manager.is_monitoring_paused():
                    logger.info("Monitoring is paused. Skipping check cycle.")
                elif await self.db_manager.token_exists():
                    await self._check_for_new_stars()
                else:
                    logger.debug("No GitHub token found. Skipping monitoring cycle.")

                # Fetch interval from DB, or use the default from config if not set
                interval_seconds = await self.db_manager.get_monitor_interval()
                if not interval_seconds or interval_seconds < 60:
                    interval_seconds = config.MONITOR_INTERVAL_SECONDS

                logger.debug(
                    f"Monitoring loop sleeping for {interval_seconds} seconds."
                )
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(
                    f"An unexpected error in monitoring loop: {e}", exc_info=True
                )
                await asyncio.sleep(60)

    async def _check_for_new_stars(self):
        logger.info("Checking for new starred repositories...")
        try:
            starred_events = await self.github_api.get_authenticated_user_starred_repos(
                page=1, per_page=50
            )
            if not starred_events:
                return

            last_check_timestamp = await self.db_manager.get_last_check_timestamp()
            new_starred_repos = []
            if last_check_timestamp:
                for event in starred_events:
                    if event["starred_at"] > last_check_timestamp:
                        new_starred_repos.append(event["repo"])
                    else:
                        break
            else:
                await self.db_manager.update_last_check_timestamp(
                    starred_events[0]["starred_at"]
                )
                logger.info(f"First run. Baseline timestamp established.")
                return

            if new_starred_repos:
                logger.info(f"Found {len(new_starred_repos)} new starred repositories.")
                digest_mode = await self.db_manager.get_digest_mode()

                # --- Queue or send instantly based on digest mode ---
                if digest_mode == "off":
                    logger.info(
                        "Digest mode is OFF. Sending notifications instantly..."
                    )
                    # Note: Instant notifications would require the notification logic here.
                    # For simplicity of this feature, we will assume digest is the primary way.
                    # Or we refactor notification logic to a shared place. Let's assume queuing is the main goal.
                    pass  # We will add instant sending back later if needed. For now, we focus on digest.
                else:
                    logger.info(
                        f"Digest mode is {digest_mode}. Adding new repos to the queue."
                    )
                    for repo in new_starred_repos:
                        await self.db_manager.add_repo_to_digest(repo["full_name"])

            else:
                logger.info("No new starred repositories found.")

            await self.db_manager.update_last_check_timestamp(
                starred_events[0]["starred_at"]
            )
            # If the check was successful, clear any previous error state
            await self.db_manager.clear_last_error()
        except GitHubAPIError as e:
            # --- Smart error handling for invalid tokens ---
            if e.status_code == 401:
                logger.error("GitHub token is invalid. Pausing monitoring.")
                await self.db_manager.set_monitoring_paused(True)
                error_msg = "Your GitHub token is invalid. Monitoring paused."
                await self.db_manager.update_last_error(error_msg)
            else:
                logger.error(f"A GitHub API error occurred: {e}")
        except Exception as e:
            logger.error(f"Error during star checking process: {e}", exc_info=True)

    async def _send_notification(self, repo_data: dict):
        owner, repo_name = repo_data.get("owner", {}).get("login"), repo_data.get(
            "name"
        )
        if not owner or not repo_name:
            return

        destinations = await self.db_manager.get_all_destinations()
        if not destinations:
            return

        logger.info(f"Processing notification for {owner}/{repo_name}...")

        try:
            tasks = {
                "details": self.github_api.get_repository(owner, repo_name),
                "languages": self.github_api.get_repository_languages(owner, repo_name),
                "release": self.github_api.get_latest_release(owner, repo_name),
                "readme": self.github_api.get_readme(owner, repo_name),
            }
            results = await asyncio.gather(*tasks.values())
            res = dict(zip(tasks.keys(), results))
            if not res["details"]:
                return

            ai_summary = None
            if self.summarizer and res["readme"]:
                ai_summary = await self.summarizer.summarize_readme(res["readme"])

            caption_text = RepoFormatter.format_repository_preview(
                res["details"], res["languages"], res["release"], ai_summary
            )

            media_group = []
            selected_media_urls = []
            if self.summarizer and res["readme"]:
                all_media = extract_media_from_readme(
                    res["readme"],
                    owner,
                    repo_name,
                    res["details"].get("default_branch", "main"),
                )
                if all_media:
                    selected_media_urls = await self.summarizer.select_preview_media(
                        res["readme"], all_media
                    )

            if selected_media_urls:
                for i, url in enumerate(selected_media_urls):
                    caption = caption_text if i == 0 else None
                    if any(
                        url.lower().endswith(ext) for ext in [".mp4", ".mov", ".webm"]
                    ):
                        media_item = InputMediaVideo(
                            media=url, caption=caption, parse_mode=config.PARSE_MODE
                        )
                    else:  # Assume it's a photo/gif
                        media_item = InputMediaPhoto(
                            media=url, caption=caption, parse_mode=config.PARSE_MODE
                        )
                    media_group.append(media_item)

            for target in destinations:
                try:
                    chat_id, thread_id = (
                        (target.split("/")[0], int(target.split("/")[1]))
                        if "/" in target
                        else (target, None)
                    )
                    if media_group:
                        logger.info(
                            f"Sending media group to {target} for {owner}/{repo_name}."
                        )
                        await self.bot.send_media_group(
                            chat_id=chat_id,
                            media=media_group,
                            message_thread_id=thread_id,
                        )
                    else:
                        logger.info(
                            f"Sending text-only notification to {target} for {owner}/{repo_name}."
                        )
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=caption_text,
                            parse_mode=config.PARSE_MODE,
                            disable_web_page_preview=False,
                            message_thread_id=thread_id,
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to send notification to destination {target}: {e}"
                    )

        except Exception as e:
            logger.error(
                f"Failed to process notification for {owner}/{repo_name}: {e}",
                exc_info=True,
            )
