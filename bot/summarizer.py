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
            You are a senior software developer.
            Summarize the following README.md content in a short, **clear**, and engaging English paragraph of **no more than 900 characters**.
            Focus only on what the project does, its key features, and its purpose. Skip installation, usage, license, and contribution parts.

            Here is the README:
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
            You are a UI/UX analyst. Based on the provided README content and a list of media URLs, your task is to select the best 1 to 3 media files that create a compelling visual preview of the project.

            1.  **Analyze the README** to understand the project's core functionality.
            2.  **Examine the media list.** Prioritize actual application screenshots, workflow GIFs, or demo videos.
            3.  **Avoid** logos, badges, and simple diagrams if better options exist.
            4.  **Return a comma-separated list** of the URLs you have selected, with the most important one first. Do not add any other text. For example: "https://.../url1.png,https://.../url2.gif"

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
            return selected_urls[:3]  # Enforce the max limit of 3.
        except Exception as e:
            logger.error(f"Error during media selection with Gemini API: {e}")
            return []