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
        This version includes the corrected fix for relative URLs.
        """
        owner = repo_data.get("owner", {}).get("login")
        repo_name = repo_data.get("name")
        if not owner or not repo_name:
            return

        destinations = await self.db_manager.get_all_destinations()
        if not destinations:
            return

        typing_tasks = [self.bot.send_chat_action(target.split("/")[0], 'typing') for target in destinations]
        asyncio.gather(*typing_tasks, return_exceptions=True)

        try:
            # Step 1: Gather all required data concurrently
            tasks = {
                "languages": self.github_api.get_repository_languages(owner, repo_name),
                "release": self.github_api.get_latest_release(owner, repo_name),
                "readme": self.github_api.get_readme(owner, repo_name),
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            res = dict(zip(tasks.keys(), results))

            # Step 2: Generate AI summary and select media
            ai_summary, selected_media_urls = None, []
            if self.summarizer and await self.db_manager.are_ai_features_enabled() and res.get("readme"):
                ai_summary = await self.summarizer.summarize_readme(res["readme"])
                if await self.db_manager.is_ai_media_selection_enabled():
                    all_media = extract_media_from_readme(res["readme"], owner, repo_name, repo_data.get("default_branch", "main"))
                    if all_media:
                        selected_media_urls = await self.summarizer.select_preview_media(res["readme"], all_media)
            
            # Step 2.5: Normalize URLs returned by Gemini to be absolute
            final_media_urls = []
            if selected_media_urls:
                logger.info(f"Normalizing {len(selected_media_urls)} URLs returned by Gemini...")
                for url in selected_media_urls:
                    if not url.startswith("http"):
                        clean_path = url.lstrip("./").lstrip("/")
                        absolute_url = f"https://raw.githubusercontent.com/{owner}/{repo_name}/{repo_data.get('default_branch', 'main')}/{clean_path}"
                        final_media_urls.append(absolute_url)
                        logger.info(f"Converted relative URL '{url}' to '{absolute_url}'")
                    else:
                        final_media_urls.append(url)
            
            # Step 3: Format the text caption
            caption_text = RepoFormatter.format_repository_preview(repo_data, res.get("languages"), res.get("release"), ai_summary)

            # Step 4: Build the media group using the *CORRECTED* final_media_urls list
            media_group = []
            if final_media_urls: # <-- CORRECTED
                async with aiohttp.ClientSession() as session:
                    for i, url in enumerate(final_media_urls): # <-- CORRECTED
                        caption = caption_text if i == 0 else None
                        content_type, final_url_after_redirect = await get_media_info(url, session)
                        
                        media_item = None
                        if content_type:
                            if 'video' in content_type: media_item = InputMediaVideo(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            elif 'gif' in content_type: media_item = InputMediaAnimation(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            elif 'image' in content_type: media_item = InputMediaPhoto(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                        
                        if not media_item: # Fallback based on URL extension
                            parsed_path = urlparse(final_url_after_redirect).path.lower()
                            if any(parsed_path.endswith(ext) for ext in [".mp4", ".mov", ".webm"]): media_item = InputMediaVideo(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            elif parsed_path.endswith(".gif"): media_item = InputMediaAnimation(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                            else: media_item = InputMediaPhoto(media=url, caption=caption, parse_mode=config.PARSE_MODE)
                        media_group.append(media_item)

            # Step 5: Send notifications to all destinations
            for target in destinations:
                try:
                    chat_id, thread_id = (target.split("/")[0], int(target.split("/")[1])) if "/" in target else (target, None)
                    
                    # More robust sending logic
                    if not media_group:
                        # Send as plain text if no media
                        await self.bot.send_message(chat_id, caption_text, parse_mode=config.PARSE_MODE, disable_web_page_preview=False, message_thread_id=thread_id)
                    elif len(media_group) == 1:
                        # Send single media item using the appropriate method
                        item = media_group[0]
                        if isinstance(item, InputMediaVideo): await self.bot.send_video(chat_id, item.media, caption=item.caption, parse_mode=config.PARSE_MODE, message_thread_id=thread_id)
                        elif isinstance(item, InputMediaAnimation): await self.bot.send_animation(chat_id, item.media, caption=item.caption, parse_mode=config.PARSE_MODE, message_thread_id=thread_id)
                        else: await self.bot.send_photo(chat_id, item.media, caption=item.caption, parse_mode=config.PARSE_MODE, message_thread_id=thread_id)
                    else:
                        # Send as a media group for 2 or more items
                        await self.bot.send_media_group(chat_id=chat_id, media=media_group, message_thread_id=thread_id)

                except ApiTelegramException as e:
                    if "WEBPAGE_CURL_FAILED" in str(e):
                        logger.warning(f"Webpage preview failed for {target}. Retrying without preview.")
                        try:
                            await self.bot.send_message(chat_id, caption_text, parse_mode=config.PARSE_MODE, disable_web_page_preview=True, message_thread_id=thread_id)
                        except Exception as final_e:
                            logger.error(f"Failed to send to {target} even after retry: {final_e}")
                    else:
                        logger.error(f"Telegram API error sending to {target}: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"An unexpected error occurred sending to {target} for {owner}/{repo_name}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Failed to process and send notification for {owner}/{repo_name}: {e}", exc_info=True)
