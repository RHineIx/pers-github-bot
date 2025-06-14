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
You are a text processing AI assistant. Your task is to extract and slightly reformat the core description from the provided GitHub README.

**CRITICAL RULES:**

1.  **High Fidelity (80% Original):** Your primary goal is to preserve the original text. The output must be approximately 80% identical to the source description. Do NOT creatively rephrase sentences or change the original meaning and tone.

2.  **Minimal Formatting (20% Readability):** The only changes you are allowed to make are for improving readability on a small screen. You can:
    - Add line breaks (`\n`) to separate distinct points or ideas.
    - Split a very long paragraph into two.
    - **Your output MUST be plain text.** Do NOT use any Markdown or HTML (`*`, `_`, `#`, `<b>`, `<a>`, etc.).

3.  **Strict Character Limit:** The final output **"MUST NOT EXCEED 650 characters"**. This is an absolute and critical limit. Be concise. Remove non-essential filler phrases from the original text only if necessary to meet this limit.

4.  **Content Focus:** Extract only the description that explains what the project is, its purpose, and its key features. Ignore sections about installation, configuration, usage examples, or licensing.

**Original README content to process:**
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
            You are an expert UI/UX analyst. Your task is to select the 1 or 2 best media files from a list that visually represent a software project, based on its README file.

            **CRITICAL RULES for SELECTION:**

            1.  **Prioritize High-Value Sections:** Give the highest priority to media found under headings like **"Preview", "Demo", "Screenshots", "Showcase", "Features", or "How it works"**. These are most likely to show the project in action.

            2.  **Avoid Irrelevant Sections:** You **MUST IGNORE** any media listed under sections like **"Sponsors", "Contributors", "Donate", "License", or "Badges"**. These are not visual previews of the project.

            3.  **Content is Key:** Choose media that clearly demonstrates the project's purpose, main features, or user interface. Prioritize application screenshots, workflow GIFs, and demo videos. Avoid abstract diagrams or logos unless they are the only option.

            4.  **Output Format:** Return ONLY a comma-separated list of the selected URLs, ordered by importance. Do not add any explanation or other text.

            **README Content to Analyze:**
            ---
            {readme_content[:10000]}
            ---

            **List of Media URLs to Choose From:**
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
            return selected_urls[:2]  # Enforce the max limit of 2.
        except Exception as e:
            logger.error(f"Error during media selection with Gemini API: {e}")
            return []