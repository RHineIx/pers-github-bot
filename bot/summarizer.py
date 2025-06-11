# In bot/summarizer.py
import logging
import google.generativeai as genai
from typing import Optional

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
As a senior software developer, analyze the following README.md file content.
Your task is to generate a concise and engaging summary in clear English prose that explains what the project does, its main features.
Ignore sections about installation, usage examples, licenses, and contribution guidelines. Focus on the core description and purpose of the project.

Here is the README content:
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