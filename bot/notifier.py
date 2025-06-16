# bot/notifier.py
# This module contains the Notifier class, responsible for processing
# and sending all notifications.

import asyncio
import logging
from typing import Optional

# --- Add required imports from other modules ---
import aiohttp
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InputMediaPhoto, InputMediaVideo, InputMediaAnimation
from telebot.apihelper import ApiTelegramException
from urllib.parse import urlparse

from config import config
from bot.database import DatabaseManager
from github.api import GitHubAPI
from github.formatter import RepoFormatter
from bot.summarizer import AISummarizer
from bot.utils import extract_media_from_readme, get_media_info

# --- Get the logger ---
logger = logging.getLogger(__name__)


class Notifier:
    """
    Handles the logic of fetching repository data, formatting it,
    and sending it to the configured destinations.
    """
    def __init__(
        self,
        bot: AsyncTeleBot,
        github_api: GitHubAPI,
        db_manager: DatabaseManager,
        summarizer: Optional[AISummarizer],
    ):
        # --- Store all necessary components passed from main.py ---
        self.bot = bot
        self.github_api = github_api
        self.db_manager = db_manager
        self.summarizer = summarizer

    async def send_repo_notification(self, repo_data: dict):
        """
        The main method to process and send a notification for a single repository.
        This was moved from the DigestScheduler class.
        """
        owner = repo_data.get("owner", {}).get("login")
        repo_name = repo_data.get("name")
        if not owner or not repo_name:
            return

        destinations = await self.db_manager.get_all_destinations()
        if not destinations:
            return

        # --- Send 'typing...' action to all destinations ---
        typing_tasks = [self.bot.send_chat_action(target.split("/")[0] if "/" in target else target, 'typing') for target in destinations]
        asyncio.gather(*typing_tasks, return_exceptions=True)

        try:
            # --- Step 1: Gather all required data concurrently ---
            tasks = {
                "languages": self.github_api.get_repository_languages(owner, repo_name),
                "release": self.github_api.get_latest_release(owner, repo_name),
                "readme": self.github_api.get_readme(owner, repo_name),
            }
            results = await asyncio.gather(*tasks.values())
            res = dict(zip(tasks.keys(), results))

            # --- Step 2: Generate AI summary and select media ---
            ai_summary = None
            selected_media_urls = []
            if self.summarizer and await self.db_manager.are_ai_features_enabled():
                if res["readme"]:
                    ai_summary = await self.summarizer.summarize_readme(res["readme"])
                    
                    if await self.db_manager.is_ai_media_selection_enabled():
                        all_media = extract_media_from_readme(
                            res["readme"], owner, repo_name, repo_data.get("default_branch", "main")
                        )
                        if all_media:
                            selected_media_urls = await self.summarizer.select_preview_media(
                                res["readme"], all_media
                            )
            
            # --- Step 2.5: Use owner's avatar as a fallback ---
            # This feature is currently disabled as per your request, but the logic would go here.

            # --- Step 3: Format the text caption ---
            caption_text = RepoFormatter.format_repository_preview(
                repo_data, res["languages"], res["release"], ai_summary
            )

            # --- Step 4: Build the media group using the robust classification logic ---
            media_group = []
            if selected_media_urls:
                async with aiohttp.ClientSession() as session:
                    for i, url in enumerate(selected_media_urls):
                        caption = caption_text if i == 0 else None
                        
                        content_type, final_url = await get_media_info(url, session)
                        logger.info(f"URL: {url}, Final URL: {final_url}, Content-Type: {content_type}")

                        media_item = None
                        if content_type:
                            if 'video' in content_type:
                                media_item = InputMediaVideo(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            elif 'gif' in content_type:
                                media_item = InputMediaAnimation(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            elif 'image' in content_type:
                                media_item = InputMediaPhoto(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                        
                        if not media_item:
                            parsed_path = urlparse(final_url).path.lower()
                            if any(parsed_path.endswith(ext) for ext in [".mp4", ".mov", ".webm"]):
                                media_item = InputMediaVideo(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            elif parsed_path.endswith(".gif"):
                                media_item = InputMediaAnimation(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            else:
                                media_item = InputMediaPhoto(media=url, caption=caption, parse_mode=config.PARSE_MODE)

                        media_group.append(media_item)

            # --- Step 5: Send notifications to all destinations ---
            for target in destinations:
                try:
                    chat_id, thread_id = (
                        (target.split("/")[0], int(target.split("/")[1]))
                        if "/" in target
                        else (target, None)
                    )

                    animation_item = next((item for item in media_group if isinstance(item, InputMediaAnimation)), None)

                    if animation_item:
                        await self.bot.send_animation(
                            chat_id=chat_id, animation=animation_item.media,
                            caption=caption_text, parse_mode=config.PARSE_MODE,
                            message_thread_id=thread_id,
                        )
                    elif media_group:
                        await self.bot.send_media_group(
                            chat_id=chat_id, media=media_group, message_thread_id=thread_id
                        )
                    else:
                        await self.bot.send_message(
                            chat_id=chat_id, text=caption_text,
                            parse_mode=config.PARSE_MODE, disable_web_page_preview=False,
                            message_thread_id=thread_id,
                        )
                except ApiTelegramException as e:
                    if "WEBPAGE_CURL_FAILED" in e.description:
                        logger.warning(f"WEBPAGE_CURL_FAILED for {owner, repo_name}. Retrying without preview.")
                        try:
                            await self.bot.send_message(
                                chat_id=chat_id, text=caption_text,
                                parse_mode=config.PARSE_MODE, disable_web_page_preview=True,
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