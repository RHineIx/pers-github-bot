# bot/summarizer.py
# This module encapsulates all interactions with the Gemini Generative AI model.

import logging
import textwrap
from typing import Optional, List

import google.generativeai as genai

from config import config

logger = logging.getLogger(__name__)


class AISummarizer:
    def __init__(self, api_key: str):
        # Initialize the connection to the Gemini API.
        if not api_key:
            raise ValueError("Gemini API key is not provided.")
        genai.configure(api_key=api_key)
        
        logger.info(f"Initializing Gemini with model: {config.GEMINI_MODEL_NAME}")
        self.model = genai.GenerativeModel(config.GEMINI_MODEL_NAME)

    async def summarize_readme(self, readme_content: str) -> Optional[str]:
        # Generates a smart, character-limited summary of a README file.
        if not readme_content or len(readme_content) < 50:
            return None  # Don't summarize very short or empty READMEs

        # The prompt for generating the repository summary.
        prompt = textwrap.dedent(f"""
You are a senior software developer with experience in technical writing for open-source projects.

Your task is to refine the following GitHub README.md description, but **only make minimal improvements** — do not change the original meaning or style. Apply edits **only if absolutely necessary** (e.g., grammar, clarity), and **limit changes to 1%** of the content.
**Very Important:** The final description **must not exceed 650 characters**. This is a hard limit. Your response must be in plain text with no formatting or quotes.
Focus strictly on describing what the project does, its purpose, and key features. Ignore installation, setup, or licensing details.
Original README content:
---
            {readme_content[:15000]}
            ---
        """) # Truncate content to avoid exceeding token limits.

        try:
            logger.info("Sending README content to Gemini for summarization...")
            response = await self.model.generate_content_async(prompt)
            summary = response.text.strip().strip('"')
            logger.info("Successfully received summary from Gemini.")
            return summary
        except Exception as e:
            logger.error(f"An error occurred while communicating with Gemini API: {e}")
            return None

    async def select_preview_media(
        self, readme_content: str, media_urls: List[str]
    ) -> List[str]:
        # Selects the best 1-3 media URLs from a list based on README context.
        if not media_urls:
            return []

        # Convert the list of URLs into a numbered string for the prompt.
        formatted_url_list = "\n".join(
            f"{i+1}. {url}" for i, url in enumerate(media_urls)
        )

        # The prompt for selecting the best visual media.
        prompt = textwrap.dedent(f"""
            You are a skilled UI/UX analyst with expertise in selecting media that best represent software projects visually.

            Given the README content and a list of media URLs, your task is to select the top 1  media files that effectively showcase the project's core functionality and user experience.

            Selection criteria:
            1. Prioritize screenshots of the actual application (e.g., .png, .jpg), workflow animations (e.g., .gif), or demo videos (e.g., .mp4, .webm) that clearly demonstrate usage.
            2. Avoid generic logos, badges, or simple static diagrams unless no better options exist.
            3. Choose media that best engage potential users by providing clear insight into the project's purpose and features.
            4. Return only a comma-separated list of the selected URLs, ordered by importance. Do not add any additional text or formatting.

            **README Content:**
            ---
            {readme_content[:10000]}
            ---

            **Media URL List:**
            ---
            {formatted_url_list}
            ---
        """)

        try:
            logger.info("Asking Gemini to select the best preview media...")
            response = await self.model.generate_content_async(prompt)
            
            # Clean up the response: remove whitespace and split by comma.
            selected_urls = [
                url.strip() for url in response.text.strip().split(",") if url.strip()
            ]
            
            logger.info(f"Gemini selected {len(selected_urls)} media URLs.")
            return selected_urls[:1]  # Enforce the max limit of 1.
        except Exception as e:
            logger.error(f"Error during media selection with Gemini API: {e}")
            return []