# In github/api.py

import aiohttp
import asyncio
import time
import logging
import base64
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote_plus

from config import config
from bot.database import DatabaseManager

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Custom exception for GitHub API errors."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API Error {status_code}: {message}")


class GitHubAPI:
    """
    Asynchronous GitHub API client with an advanced E-Tag based caching system
    to minimize API rate limit consumption and improve performance.
    """

    # --- CACHE STRUCTURE ---
    # The cache now stores: (timestamp, etag, data)
    _cache: Dict[str, Tuple[float, Optional[str], Any]] = {}

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.base_url = config.GITHUB_API_BASE
        self.cache_ttl = config.CACHE_TTL_SECONDS

    async def _get_headers(self) -> Dict[str, str]:
        """Constructs the base request headers with the user's token."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Personal-GitHub-Stars-Bot/1.0",
        }
        token = await self.db_manager.get_token()
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    async def _make_request(
        self, endpoint: str, etag: Optional[str] = None
    ) -> Tuple[int, Dict[str, Any], Optional[Any]]:
        """
        Makes a request to the GitHub API. Now includes E-Tag handling.
        Returns a tuple of (status_code, response_headers, response_json).
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = await self._get_headers()

        if "Authorization" not in headers:
            raise GitHubAPIError(
                401, "Cannot make API request: GitHub token not found."
            )

        # --- Add the If-None-Match header if an E-Tag is provided ---
        if etag:
            headers["If-None-Match"] = etag

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
        ) as session:
            try:
                async with session.get(url, headers=headers) as response:
                    # --- Handle 304 Not Modified status ---
                    if response.status == 304:
                        logger.info(
                            f"Cache valid (304 Not Modified) for endpoint: {endpoint}"
                        )
                        return 304, response.headers, None

                    if response.status in [200, 201, 202]:
                        return response.status, response.headers, await response.json()

                    if (
                        response.status == 403
                        and "X-RateLimit-Reset" in response.headers
                    ):
                        reset_timestamp = int(response.headers["X-RateLimit-Reset"])
                        wait_duration = max(reset_timestamp - int(time.time()), 0) + 2
                        logger.warning(
                            f"Rate limit exceeded. Waiting for {wait_duration} seconds."
                        )
                        await asyncio.sleep(wait_duration)
                        return await self._make_request(endpoint, etag)

                    error_text = await response.text()
                    logger.error(
                        f"GitHub API error: {response.status} - {error_text} for URL {url}"
                    )
                    raise GitHubAPIError(response.status, error_text)

            except asyncio.TimeoutError:
                raise GitHubAPIError(408, "Request timed out")
            except Exception as e:
                if not isinstance(e, GitHubAPIError):
                    raise GitHubAPIError(500, str(e))
                raise e

    async def _make_cached_request(self, endpoint: str) -> Optional[Any]:
        """
        A generic method to handle cached requests using the E-Tag mechanism.
        """
        cache_key = endpoint
        cached_entry = self._cache.get(cache_key)
        etag = None

        if cached_entry:
            timestamp, etag, cached_data = cached_entry
            # For very recent requests, serve from cache immediately without checking E-Tag
            if time.time() - timestamp < 60:  # 1-minute fast cache
                logger.info(f"Serving fresh (<60s) cached data for: {endpoint}")
                return cached_data

        try:
            status, headers, data = await self._make_request(endpoint, etag=etag)

            if status == 304:
                # Content has not changed, update timestamp and return cached data
                if cached_entry:
                    _, etag, cached_data = cached_entry
                    self._cache[cache_key] = (time.time(), etag, cached_data)
                    return cached_data

            elif status == 200:
                # New data received, update cache with new data and new E-Tag
                new_etag = headers.get("ETag")
                self._cache[cache_key] = (time.time(), new_etag, data)
                return data

        except GitHubAPIError as e:
            # If a 404 happens on a conditional request, the cached data might be for a deleted repo.
            # In this case, we should invalidate the cache and return None.
            if e.status_code == 404 and cache_key in self._cache:
                del self._cache[cache_key]
            # Re-raise other errors to be handled by the caller
            raise e

        return None

    async def get_repository(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        return await self._make_cached_request(f"repos/{owner}/{repo}")

    async def get_repository_languages(
        self, owner: str, repo: str
    ) -> Optional[Dict[str, int]]:
        return await self._make_cached_request(f"repos/{owner}/{repo}/languages")

    async def get_latest_release(
        self, owner: str, repo: str
    ) -> Optional[Dict[str, Any]]:
        try:
            return await self._make_cached_request(
                f"repos/{owner}/{repo}/releases/latest"
            )
        except GitHubAPIError as e:
            if e.status_code == 404:
                return {}
            raise e

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        return await self._make_cached_request(f"users/{username}")

    async def get_readme(self, owner: str, repo: str) -> Optional[str]:
        try:
            readme_data = await self._make_cached_request(
                f"repos/{owner}/{repo}/readme"
            )
            if readme_data and "content" in readme_data:
                return base64.b64decode(readme_data["content"]).decode("utf-8")
            return None
        except GitHubAPIError as e:
            if e.status_code == 404:
                return None
            raise e

    # --- Methods that should NOT be cached or have different logic ---

    async def get_authenticated_user(self) -> Optional[Dict[str, Any]]:
        # This is for validation, should not be cached.
        status, _, data = await self._make_request("user")
        return data if status == 200 else None

    async def get_rate_limit(self) -> Optional[Dict[str, Any]]:
        # Rate limit status should always be fresh.
        status, _, data = await self._make_request("rate_limit")
        return data if status == 200 else None

    async def get_authenticated_user_starred_repos(
        self, page: int = 1, per_page: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        # Star feed should always be fresh for the monitor.
        # This requires a custom header, so we call _make_request directly.
        headers = await self._get_headers()
        headers["Accept"] = "application/vnd.github.star+json"
        url = f"{self.base_url}/user/starred?page={page}&per_page={per_page}&sort=created&direction=desc"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                raise GitHubAPIError(response.status, await response.text())
