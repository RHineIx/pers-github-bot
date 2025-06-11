"""
Response formatting utilities for GitHub data.
This file is adapted from the original project to ensure identical message formatting.
"""
import re
from typing import Dict, Any, Optional, List
from telebot import types
from telebot.util import quick_markup
from bot.utils import format_time_ago

# We will create a simplified version of CallbackDataManager later in bot/utils.py
# For now, this import is a placeholder for the code to be valid.
# from bot.utils import CallbackDataManager

class RepoFormatter:
    """Formats repository data for Telegram messages."""

    @staticmethod
    def format_number(num: int) -> str:
        """Formats large numbers with K/M suffixes."""
        if num >= 1000000:
            return f"{num/1000000:.1f}M"
        if num >= 1000:
            return f"{num/1000:.1f}K"
        return str(num)

    @staticmethod
    def calculate_language_percentages(languages: Dict[str, int]) -> Dict[str, float]:
        """Calculates percentage distribution of programming languages."""
        total = sum(languages.values())
        if total == 0:
            return {}
        return {lang: (count / total) * 100 for lang, count in languages.items()}

    @staticmethod
    def format_repository_preview(
        repo_data: Dict[str, Any],
        languages: Optional[Dict[str, int]],
        latest_release: Optional[Dict[str, Any]],
        ai_summary: Optional[str] = None
    ) -> str:
        """Formats the preview, using AI summary if available, otherwise fallback to default."""
        full_name = repo_data.get('full_name', 'N/A')
        html_url = repo_data.get('html_url', '')

        description = ai_summary if ai_summary else repo_data.get('description', 'No description available.')
        
        # ... rest of the data extraction is the same ...
        stars = RepoFormatter.format_number(repo_data.get('stargazers_count', 0))
        forks = RepoFormatter.format_number(repo_data.get('forks_count', 0))
        issues = repo_data.get('open_issues_count', 0)
        pushed_at = repo_data.get('pushed_at')
        last_updated_str = format_time_ago(pushed_at)
        
        # ... the rest of the function remains the same ...
        release_info = "No official releases"
        if latest_release:
            release_name = latest_release.get('tag_name', 'N/A')
            release_url = latest_release.get('html_url', html_url)
            release_info = f"<a href='{release_url}'>{release_name}</a>"

        languages_text = "Not specified"
        if languages:
            lang_percentages = RepoFormatter.calculate_language_percentages(languages)
            top_languages = sorted(lang_percentages.items(), key=lambda x: x[1], reverse=True)[:3]
            languages_text = " ".join([f"#{lang.replace('-', '_')} (<code>{percent:.1f}%</code>)" for lang, percent in top_languages])

        message = f"""📦 <a href='{html_url}'>{full_name}</a>

📝 <b>Desc:</b>
{description}

<blockquote>⭐ Stars: <b>{stars}</b> | 🍴 Forks: <b>{forks}</b> | 🪲 Open Issues: <b>{issues}</b></blockquote>

🚀 <b>Latest Release:</b> {release_info}
⏳ <b>Last updated:</b> {last_updated_str}

💻 <b>Lang's:</b> {languages_text}

<a href='{html_url}'>🔗 View on GitHub</a>
"""
        return message.strip()


class UserFormatter:
    """Formats user data for Telegram messages."""

    @staticmethod
    def format_user_info(user_data: Dict[str, Any]) -> str:
        """Formats user information message."""
        name = user_data.get('name', 'Not specified')
        login = user_data.get('login', 'N/A')
        bio = user_data.get('bio', 'No bio available.')
        followers = RepoFormatter.format_number(user_data.get('followers', 0))
        following = RepoFormatter.format_number(user_data.get('following', 0))
        public_repos = user_data.get('public_repos', 0)
        html_url = user_data.get('html_url', '')

        message = f"""
👤 <b>{name}</b> (<code>@{login}</code>)

📝 <b>Bio:</b>
{bio}
     
👥 Followers: <b>{followers}</b>
👤 Following: <b>{following}</b>
📁 Public Repos: <b>{public_repos}</b>

<a href="{html_url}">🔗 View Profile on GitHub</a>
"""
        return message.strip()


class URLParser:
    """Utility class for parsing GitHub URLs."""

    @staticmethod
    def parse_repo_input(text: str) -> Optional[tuple]:
        """
        Parses GitHub repository URL or 'owner/repo' format.
        Returns a tuple of (owner, repo) or None if parsing fails.
        """
        patterns = [
            r'github\.com/([^/]+)/([^/\s]+)',  # Full GitHub URL
            r'^([^/\s]+)/([^/\s]+)$'          # 'owner/repo' format
        ]
        for pattern in patterns:
            match = re.search(pattern, text.strip())
            if match:
                owner, repo = match.groups()
                repo = repo.replace('.git', '') # Clean '.git' suffix
                return owner, repo
        return None