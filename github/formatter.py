# github/formatter.py

import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from telebot import types
from telebot.util import quick_markup

from bot.utils import format_time_ago


# Formats data related to repositories.
class RepoFormatter:

    @staticmethod
    def format_number(num: int) -> str:
        # Abbreviates large numbers, e.g., 12345 -> 12.3K
        if num >= 1000000:
            return f"{num/1000000:.1f}M"
        if num >= 1000:
            return f"{num/1000:.1f}K"
        return str(num)

    @staticmethod
    def calculate_language_percentages(languages: Dict[str, int]) -> Dict[str, float]:
        # Calculates the percentage of each programming language used.
        total = sum(languages.values())
        if total == 0:
            return {}
        return {lang: (count / total) * 100 for lang, count in languages.items()}

    @staticmethod
    def format_repository_preview(
        repo_data: Dict[str, Any],
        languages: Optional[Dict[str, int]],
        latest_release: Optional[Dict[str, Any]],
        ai_summary: Optional[str] = None,
    ) -> str:
        """Constructs the main HTML message for a repository preview."""
        full_name = repo_data.get("full_name", "N/A")
        html_url = repo_data.get("html_url", "")

        # Use the smart AI summary if available, otherwise fall back to the default repo description.
        description = (  
            ai_summary[:730] + "..." if ai_summary and len(ai_summary) > 730  
            else ai_summary  
            if ai_summary  
            else repo_data.get("description", "No description available.")  
        )

        stars = RepoFormatter.format_number(repo_data.get("stargazers_count", 0))
        forks = RepoFormatter.format_number(repo_data.get("forks_count", 0))
        issues = repo_data.get("open_issues_count", 0)
        
        pushed_at = repo_data.get("pushed_at")
        if pushed_at:
            date_obj = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            absolute_date_str = date_obj.strftime('%Y-%m-%d')
            relative_time_str = format_time_ago(pushed_at)
            last_updated_str = f"{absolute_date_str} ({relative_time_str})"
        else:
            last_updated_str = "N/A"

        release_info = "No official releases"
        if latest_release:
            release_name = latest_release.get("tag_name", "N/A")
            release_url = latest_release.get("html_url", html_url)
            release_info = f"<a href='{release_url}'>{release_name}</a>"

        languages_text = "Not specified"
        if languages:
            lang_percentages = RepoFormatter.calculate_language_percentages(languages)
            top_languages = sorted(
                lang_percentages.items(), key=lambda x: x[1], reverse=True
            )[:3]
            languages_text = " ".join(
                [
                    f"#{lang.replace('-', '_')} (<code>{percent:.1f}%</code>)"
                    for lang, percent in top_languages
                ]
            )

        # Format Topics, to be placed at the bottom
        topics = repo_data.get("topics", [])[:4]
        topics_text = ""
        if topics:
            formatted_topics = " ".join([f"#{topic.replace('-', '_')}" for topic in topics])
            topics_text = f"\n\n{formatted_topics}"


        # The final HTML message template.
        message = f"""📦 <a href='{html_url}'>{full_name}</a>

<blockquote expandable>📝 {description}</blockquote>

⭐ <b>Stars:</b> {stars} | 🍴 <b>Forks:</b> {forks} | 🪲 <b>Open Issues:</b> {issues}

🚀 <b>Latest Release:</b> {release_info}
⏳ <b>Last updated:</b> {last_updated_str}
💻 <b>Langs:</b> {languages_text}

<a href='{html_url}'>🔗 View on GitHub</a>{topics_text}
"""
        return message.strip()


# Formats data related to GitHub users.
class UserFormatter:

    @staticmethod
    def format_user_info(user_data: Dict[str, Any]) -> str:
        """Constructs the HTML message for a user profile."""
        name = user_data.get("name", "Not specified")
        login = user_data.get("login", "N/A")
        bio = user_data.get("bio", "No bio available.")
        followers = RepoFormatter.format_number(user_data.get("followers", 0))
        following = RepoFormatter.format_number(user_data.get("following", 0))
        public_repos = user_data.get("public_repos", 0)
        html_url = user_data.get("html_url", "")

        message = f"""
👤 <b>{name}</b> (<code>@{login}</code>)

📝 <b>Bio:</b>
{bio}
     
👥 <b>Followers:</b> {followers}
👤 <b>Following:</b> {following}
📁 <b>Public Repos:</b> {public_repos}

<a href="{html_url}">🔗 View Profile on GitHub</a>
"""
        return message.strip()


# Parses different formats of GitHub URLs.
class URLParser:

    @staticmethod
    def parse_repo_input(text: str) -> Optional[tuple]:
        """
        Parses a string to extract owner and repo name.
        Handles both full URLs and 'owner/repo' format.
        """
        patterns = [
            r"github\.com/([^/]+)/([^/\s]+)",  # Pattern for full GitHub URLs
            r"^([^/\s]+)/([^/\s]+)$",          # Pattern for 'owner/repo' format
        ]
        for pattern in patterns:
            match = re.search(pattern, text.strip())
            if match:
                owner, repo = match.groups()
                # Clean '.git' suffix if present, e.g., from a clone URL.
                repo = repo.replace(".git", "")
                return owner, repo
        return None