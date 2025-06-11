# bot/utils.py
from datetime import datetime, timezone

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
