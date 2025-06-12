# bot/utils.py
# A collection of utility functions used across the bot.

import re
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from collections import OrderedDict

# Formats a duration in seconds into a human-readable string (e.g., "3600 seconds (1.0 hours)").
def format_duration(seconds: int) -> str:
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

# Converts a GitHub ISO timestamp into a 'time ago' format (e.g., "5 days ago").
def format_time_ago(timestamp_str: str) -> str:
    if not timestamp_str:
        return "N/A"

    # Parse the UTC timestamp from GitHub by replacing the 'Z' suffix.
    date_obj = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    
    # Get the current time in UTC for an accurate comparison.
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
    elif seconds < 2592000:  # 30 days
        days = int(seconds / 86400)
        return f"{days} day{'s' if days > 1 else ''} ago"
    elif seconds < 31536000:  # 365 days
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = int(seconds / 31536000)
        return f"{years} year{'s' if years > 1 else ''} ago"

# Extracts all valid media URLs (images, gifs, videos) from README markdown text.
def extract_media_from_readme(
    markdown_text: str, owner: str, repo: str, branch: str
) -> List[str]:
    if not markdown_text:
        return []

    # Regex to find both Markdown `![alt](url)` and HTML `<img src="url">` tags.
    image_pattern = r'\!\[.*?\]\((.*?)\)|<img.*?src=[\'"](.*?)[\'"]'
    found_urls = re.findall(image_pattern, markdown_text)

    # Flatten the list of tuples from regex groups and filter out empty matches.
    urls = [url for group in found_urls for url in group if url]

    absolute_urls = []
    for url in urls:
        url = url.strip()
        # If the URL is already absolute, use it directly.
        if url.startswith("http://") or url.startswith("https://"):
            absolute_urls.append(url)
        # Otherwise, resolve the relative path to a full GitHub raw content URL.
        else:
            clean_path = url.lstrip("./").lstrip("/")
            absolute_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{clean_path}"
            absolute_urls.append(absolute_url)

    # Filter the final list to include only supported media file types.
    valid_media_extensions = (
        ".png", ".jpg", ".jpeg", ".gif", ".webp",
        ".mp4", ".mov", ".webm",
    )
    valid_urls = [
        url for url in absolute_urls if url.lower().endswith(valid_media_extensions)
    ]

    return valid_urls

# Manages callback data to overcome Telegram's 64-byte limit.
class CallbackDataManager:
    _data_store: Dict[str, tuple] = OrderedDict()
    _MAX_ITEMS = 1000
    _TTL_SECONDS = 3600 * 6  # Keep data for 6 hours

    @classmethod
    def _cleanup(cls):
        now = time.time()
        expired_keys = [k for k, (ts, _) in cls._data_store.items() if now - ts > cls._TTL_SECONDS]
        for key in expired_keys: del cls._data_store[key]
        while len(cls._data_store) > cls._MAX_ITEMS: cls._data_store.popitem(last=False)

    @classmethod
    def create_callback_data(cls, action: str, data: Optional[Dict[str, Any]] = None) -> str:
        # Creates a short, hashed representation for callback data.
        if data is None: data = {}
        if len(cls._data_store) % 100 == 0: cls._cleanup()
        
        data_str = json.dumps(data, sort_keys=True) + str(time.time())
        data_hash = hashlib.md5(data_str.encode()).hexdigest()[:10]
        
        cls._data_store[data_hash] = (time.time(), {'action': action, **data})
        return data_hash

    @classmethod
    def get_callback_data(cls, data_hash: str) -> Optional[Dict[str, Any]]:
        # Retrieves the full data dictionary from its hash.
        stored = cls._data_store.get(data_hash)
        return stored[1] if stored else None
