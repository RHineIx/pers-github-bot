# bot/utils.py
import re
from datetime import datetime, timezone
from typing import List

def format_duration(seconds: int) -> str:
    """Formats a duration in seconds into a human-readable string."""
    if seconds < 120:
        return f"{seconds} seconds"
    
    minutes = seconds / 60
    if minutes < 120:
        return f"{seconds} seconds (approx. {minutes:.1f} minutes)"
        
    hours = minutes / 60
    if hours < 48:
        return f"{seconds} seconds (approx. {hours:.1f} hours)"
        
    days = hours / 24
    return f"{seconds} seconds (approx. {days:.1f} days)"

def format_time_ago(timestamp_str: str) -> str:
    """Converts an ISO 8601 timestamp string to a human-readable 'time ago' format."""
    if not timestamp_str:
        return "N/A"
    
    # Parse the timestamp string from GitHub
    # The 'Z' at the end means UTC, which is equivalent to +00:00
    date_obj = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    
    # Get the current time in UTC to compare
    now = datetime.now(timezone.utc)
    
    delta = now - date_obj
    seconds = delta.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif seconds < 2592000: # 30 days
        days = int(seconds / 86400)
        return f"{days} day{'s' if days > 1 else ''} ago"
    elif seconds < 31536000: # 365 days
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = int(seconds / 31536000)
        return f"{years} year{'s' if years > 1 else ''} ago"

def extract_media_from_readme(
    markdown_text: str, owner: str, repo: str, branch: str
) -> List[str]:
    """
    Extracts and resolves all image and GIF URLs from README markdown text.
    Converts relative URLs to absolute GitHub URLs.
    """
    if not markdown_text:
        return []

    # Regex to find Markdown images `![alt](url)` and HTML images `<img src="url">`
    # It captures the URL part.
    image_pattern = r'\!\[.*?\]\((.*?)\)|<img.*?src=[\'"](.*?)[\'"]'
    found_urls = re.findall(image_pattern, markdown_text)

    # The regex returns tuples of capture groups, so we need to flatten the list
    # and filter out empty matches.
    urls = [url for group in found_urls for url in group if url]

    absolute_urls = []
    for url in urls:
        url = url.strip()
        # If the URL is already absolute, add it directly
        if url.startswith('http://') or url.startswith('https://'):
            absolute_urls.append(url)
        # If the URL is a relative path, construct the full raw GitHub URL
        else:
            # Clean up relative path prefixes like './'
            clean_path = url.lstrip('./').lstrip('/')
            absolute_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{clean_path}"
            absolute_urls.append(absolute_url)

    # Filter for common image and GIF formats
    valid_media_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.mov', '.webm')
    valid_urls = [
        url for url in absolute_urls if url.lower().endswith(valid_media_extensions)
    ]

    return valid_urls