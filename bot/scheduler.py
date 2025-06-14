# bot/scheduler.py
# This module contains the DigestScheduler, which is responsible for sending
# batched notifications on a daily or weekly schedule.

import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InputMediaPhoto, InputMediaVideo, InputMediaAnimation
from telebot.apihelper import ApiTelegramException

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI
from github.formatter import RepoFormatter
from bot.summarizer import AISummarizer
from bot.utils import extract_media_from_readme

logger = logging.getLogger(__name__)


class DigestScheduler:
    def __init__(
        self,
        bot: AsyncTeleBot,
        github_api: GitHubAPI,
        db_manager: DatabaseManager,
        summarizer: Optional[AISummarizer],
    ):
        # Store all necessary components passed from main.py
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.summarizer = summarizer
        # Initialize the scheduler with the user's timezone.
        self.scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    def start(self):
        # Adds jobs to the scheduler and starts it in the background.
        
        # Schedule the daily digest to run every day at 21:00 (9 PM).
        self.scheduler.add_job(self.send_daily_digest, "cron", hour=21, minute=0)

        # Schedule the weekly digest to run every Sunday at 21:00 (9 PM).
        self.scheduler.add_job(
            self.send_weekly_digest, "cron", day_of_week="sun", hour=21, minute=0
        )

        self.scheduler.start()
        logger.info(
            "Digest scheduler started. Daily job at 21:00, Weekly job on Sunday at 21:00."
        )

    async def send_daily_digest(self):
        # This function is triggered by the daily cron job.
        digest_mode = await self.db_manager.get_digest_mode()
        if digest_mode == "daily":
            logger.info("Running daily digest job...")
            await self._send_digest()

    async def send_weekly_digest(self):
        # This function is triggered by the weekly cron job.
        digest_mode = await self.db_manager.get_digest_mode()
        if digest_mode == "weekly":
            logger.info("Running weekly digest job...")
            await self._send_digest()

    async def _send_digest(self):
        # Fetches all queued repos and sends their notifications sequentially.
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
                # We need the full repo data object to generate the rich notification.
                repo_data = await self.github_api.get_repository(owner, repo_name)
                if repo_data:
                    await self._process_and_send_notification(repo_data)
                    # Wait 2 seconds between each notification to avoid spamming.
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(
                    f"Failed to process {repo_full_name} from digest queue: {e}"
                )

    async def _process_and_send_notification(self, repo_data: dict):
        owner, repo_name = repo_data.get("owner", {}).get("login"), repo_data.get("name")
        if not owner or not repo_name:
            return

        destinations = await self.db_manager.get_all_destinations()
        if not destinations:
            return

        typing_tasks = [self.bot.send_chat_action(target.split("/")[0] if "/" in target else target, 'typing') for target in destinations]
        asyncio.gather(*typing_tasks, return_exceptions=True)

        try:
            # Step 1: Gather all required data concurrently
            tasks = {
                "languages": self.github_api.get_repository_languages(owner, repo_name),
                "release": self.github_api.get_latest_release(owner, repo_name),
                "readme": self.github_api.get_readme(owner, repo_name),
            }
            results = await asyncio.gather(*tasks.values())
            res = dict(zip(tasks.keys(), results))

            # Step 2: Generate AI summary and conditionally select media (Unified & Correct Logic)
            ai_summary = None
            selected_media_urls = []
            if self.summarizer and await self.db_manager.are_ai_features_enabled():
                if res["readme"]:
                    ai_summary = await self.summarizer.summarize_readme(res["readme"])
                    
                    # Media selection now correctly respects the toggle
                    if await self.db_manager.is_ai_media_selection_enabled():
                        all_media = extract_media_from_readme(
                            res["readme"], owner, repo_name, repo_data.get("default_branch", "main")
                        )
                        if all_media:
                            selected_media_urls = await self.summarizer.select_preview_media(
                                res["readme"], all_media
                            )

            # Step 3: Format the text caption
            caption_text = RepoFormatter.format_repository_preview(
                repo_data, res["languages"], res["release"], ai_summary
            )

            # Step 4: Build the media group if URLs were selected
            media_group = []
            if selected_media_urls:
                for i, url in enumerate(selected_media_urls):
                    # The caption is now assigned directly from caption_text
                    caption = caption_text if i == 0 else None
                    url_lower = url.lower()

                    if url_lower.endswith(".gif"):
                        media_item = InputMediaAnimation(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                    elif any(url_lower.endswith(ext) for ext in [".mp4", ".mov", ".webm"]):
                        media_item = InputMediaVideo(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                    else:
                        media_item = InputMediaPhoto(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                    media_group.append(media_item)

            # Step 5: Send notifications to all destinations
            for target in destinations:
                try:
                    chat_id, thread_id = (
                        (target.split("/")[0], int(target.split("/")[1]))
                        if "/" in target
                        else (target, None)
                    )
                    if media_group:
                        await self.bot.send_media_group(
                            chat_id=chat_id, media=media_group, message_thread_id=thread_id
                        )
                    else:
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=caption_text,
                            parse_mode=config.PARSE_MODE,
                            disable_web_page_preview=False,
                            message_thread_id=thread_id,
                        )
                except ApiTelegramException as e:
                    if "WEBPAGE_CURL_FAILED" in e.description:
                        logger.warning(f"WEBPAGE_CURL_FAILED for {owner, repo_name}. Retrying without preview.")
                        try:
                            await self.bot.send_message(
                                chat_id=chat_id,
                                text=caption_text,
                                parse_mode=config.PARSE_MODE,
                                disable_web_page_preview=True,
                                message_thread_id=thread_id,
                            )
                        except Exception as final_e:
                            logger.error(f"Failed to send notification to {target} even after retry: {final_e}")
                    else:
                        logger.error(f"Failed to send notification to destination {target}: {e}")
                except Exception as e:
                    logger.error(f"An unexpected error occurred sending to {target} for {owner, repo_name}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to process and send notification for {owner, repo_name}: {e}", exc_info=True)