# In bot/summarizer.py
import logging
import google.generativeai as genai
from typing import Optional, List

logger = logging.getLogger(__name__)

class AISummarizer:
    """Handles interaction with the Gemini AI model to summarize README content."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Gemini API key is not provided.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')

    async def summarize_readme(self, readme_content: str) -> Optional[str]:
        """
        Generates a smart summary of a README file using the Gemini model.
        """
        if not readme_content or len(readme_content) < 50:
            return None # Don't summarize very short or empty READMEs

        # The "Smart Prompt" we designed
        prompt = f"""
You are a senior software developer.

Summarize the following README.md content in a short, **clear**, and **engaging** English paragraph of **no more than 900 characters**. 
Focus only on what the project does, its key features, and its purpose. Skip installation, usage, license, and contribution parts.

Here is the README:
---
{readme_content[:15000]} 
---""" #truncate to avoid exceeding token limits

        try:
            logger.info("Sending README content to Gemini for summarization...")
            response = await self.model.generate_content_async(prompt)
            summary = response.text.strip()
            logger.info("Successfully received summary from Gemini.")
            return summary
        except Exception as e:
            logger.error(f"An error occurred while communicating with Gemini API: {e}")
            return None
        
    async def select_preview_media(
        self, readme_content: str, media_urls: List[str]
    ) -> List[str]:
        """
        Selects the best 1-3 media URLs from a list based on README context.
        """
        if not media_urls:
            return []

        # Convert the list of URLs into a numbered string for the prompt
        formatted_url_list = "\n".join(f"{i+1}. {url}" for i, url in enumerate(media_urls))

        prompt = f"""
        You are a UI/UX analyst. Based on the provided README content and a list of media URLs, your task is to select the best 1 to 3 media files that create a compelling visual preview of the project.

        1.  **Analyze the README** to understand the project's core functionality.
        2.  **Examine the media list.** Prioritize actual application screenshots, workflow GIFs, or demo videos.
        3.  **Avoid** logos, badges, and simple diagrams if better options exist.
        4.  **Return a comma-separated list** of the URLs you have selected, with the most important one first. Do not add any other text. For example: "https://.../url1.png,https://.../url2.gif"

        **README Content:**
        ---
        {readme_content[:8000]}
        ---

        **Media URL List:**
        ---
        {formatted_url_list}
        ---
        """

        try:
            logger.info("Asking Gemini to select the best preview media...")
            response = await self.model.generate_content_async(prompt)
            # Clean up the response: remove whitespace and split by comma
            selected_urls = [url.strip() for url in response.text.strip().split(',') if url.strip()]
            logger.info(f"Gemini selected {len(selected_urls)} media URLs.")
            return selected_urls[:3] # Ensure we don't exceed the max of 3
        except Exception as e:
            logger.error(f"Error during media selection with Gemini API: {e}")
            return []