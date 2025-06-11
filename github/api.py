import aiohttp
import asyncio
import time
import logging
from typing import Optional, Dict, Any, List
import base64

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
    Asynchronous GitHub API client designed for a single-user bot.
    It fetches the user's token from the database for every operation
    and uses a shared cache to minimize redundant requests.
    """

    _cache: Dict[str, Any] = {}

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.base_url = config.GITHUB_API_BASE
        self.cache_ttl = config.CACHE_TTL_SECONDS

    async def _get_headers(self) -> Dict[str, str]:
        """
        Constructs the request headers, including the user's token from the database.
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Personal-GitHub-Stars-Bot/1.0",
        }
        token = await self.db_manager.get_token()
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def _check_cache(self, key: str) -> Optional[Any]:
        """Checks if a valid (non-expired) entry exists in the shared cache."""
        if key in GitHubAPI._cache:
            cached_time, cached_data = GitHubAPI._cache[key]
            if time.time() - cached_time < self.cache_ttl:
                logger.info(f"Cache hit for key: {key}")
                return cached_data
        logger.info(f"Cache miss for key: {key}")
        return None

    def _update_cache(self, key: str, data: Any):
        """Updates the shared cache with new data."""
        GitHubAPI._cache[key] = (time.time(), data)

    async def _make_request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """
        Makes an HTTP GET request to the GitHub API, handling rate limits and errors.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = await self._get_headers()

        # If no token is available, cannot make authenticated requests.
        if "Authorization" not in headers:
            logger.warning("Cannot make API request: GitHub token not found in database.")
            # Depending on the endpoint, some public data might be accessible,
            # but for this bot, assume most operations require a token.
            # For simplicity, can block here, or let it fail. Let's block.
            return None

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)) as session:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    
                    # Handle rate limiting
                    if response.status == 403 and 'X-RateLimit-Reset' in response.headers:
                        reset_timestamp = int(response.headers['X-RateLimit-Reset'])
                        wait_duration = max(reset_timestamp - int(time.time()), 0) + 2 # 2s buffer
                        logger.warning(f"Rate limit exceeded. Waiting for {wait_duration} seconds.")
                        await asyncio.sleep(wait_duration)
                        return await self._make_request(endpoint) # Retry the request

                    # Handle other errors
                    error_text = await response.text()
                    logger.error(f"GitHub API error: {response.status} - {error_text} for URL {url}")
                    raise GitHubAPIError(response.status, error_text)

            except asyncio.TimeoutError:
                logger.error(f"Request timeout for: {url}")
                raise GitHubAPIError(408, "Request timed out")
            except Exception as e:
                if not isinstance(e, GitHubAPIError):
                    logger.error(f"An unexpected error occurred for {url}: {e}")
                    raise GitHubAPIError(500, str(e))
                raise e

    async def get_repository(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        """Gets repository information, using cache if available."""
        cache_key = f"repo:{owner}/{repo}"
        if cached_data := self._check_cache(cache_key):
            return cached_data
        
        if live_data := await self._make_request(f"repos/{owner}/{repo}"):
            self._update_cache(cache_key, live_data)
        return live_data

    async def get_repository_languages(self, owner: str, repo: str) -> Optional[Dict[str, int]]:
        """Gets repository programming languages, using cache."""
        cache_key = f"languages:{owner}/{repo}"
        if cached_data := self._check_cache(cache_key):
            return cached_data

        if live_data := await self._make_request(f"repos/{owner}/{repo}/languages"):
            self._update_cache(cache_key, live_data)
        return live_data

    async def get_latest_release(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        """
        Gets latest release information.
        Returns an empty dictionary if no releases are found (to prevent errors).
        """
        cache_key = f"latest_release:{owner}/{repo}"
        if cached_data := self._check_cache(cache_key):
            return cached_data
        
        try:
            live_data = await self._make_request(f"repos/{owner}/{repo}/releases/latest")
            if live_data:
                self._update_cache(cache_key, live_data)
                return live_data
            # If live_data is for some reason None but no error was raised
            return {}

        except GitHubAPIError as e:
            # If the repo has no releases, GitHub returns a 404. This is normal.
            # return an empty dict to avoid causing TypeErrors downstream.
            if e.status_code == 404:
                logger.info(f"No releases found for {owner}/{repo}. Returning empty dict.")
                return {}
            # For other errors, still want to raise them.
            raise e

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Gets a user's profile information, using cache."""
        cache_key = f"user:{username}"
        if cached_data := self._check_cache(cache_key):
            return cached_data

        if live_data := await self._make_request(f"users/{username}"):
            self._update_cache(cache_key, live_data)
        return live_data

    async def get_authenticated_user(self) -> Optional[Dict[str, Any]]:
        """Gets the profile of the user authenticated by the stored token."""
        # don't cache this as it's mainly used for validation.
        return await self._make_request("user")

    async def get_rate_limit(self) -> Optional[Dict[str, Any]]:
        """Gets the current API rate limit status for the authenticated user."""
        # Never cache rate limit calls.
        return await self._make_request("rate_limit")

    async def get_authenticated_user_starred_repos(self, page: int = 1, per_page: int = 30) -> Optional[List[Dict[str, Any]]]:
        """
        Gets the authenticated user's starred repositories.
        It uses a special media type to include the 'starred_at' timestamp.
        """
        # Temporarily modify headers for this specific request to get timestamps
        headers = await self._get_headers()
        headers["Accept"] = "application/vnd.github.star+json"

        url = f"{self.base_url}/user/starred?page={page}&per_page={per_page}&sort=created&direction=desc"

        if "Authorization" not in headers:
            logger.warning("Cannot make API request: GitHub token not found in database.")
            return None

        # This method duplicates some of _make_request to handle custom headers
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)) as session:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    
                    # Handle other errors (rate limiting, etc.) as before
                    error_text = await response.text()
                    logger.error(f"GitHub API error on starred repos endpoint: {response.status} - {error_text}")
                    raise GitHubAPIError(response.status, error_text)
            except Exception as e:
                if not isinstance(e, GitHubAPIError):
                    logger.error(f"An unexpected error occurred getting starred repos: {e}")
                    raise GitHubAPIError(500, str(e))
                raise e
            
    async def get_readme(self, owner: str, repo: str) -> Optional[str]:
        """
        Fetches and decodes the content of a repository's README file.
        Returns the decoded content as a string, or None if not found.
        """
        cache_key = f"readme:{owner}/{repo}"
        if cached_data := self._check_cache(cache_key):
            return cached_data

        try:
            readme_data = await self._make_request(f"repos/{owner}/{repo}/readme")
            if readme_data and 'content' in readme_data:
                # The content is Base64 encoded, so need to decode it.
                decoded_content = base64.b64decode(readme_data['content']).decode('utf-8')
                self._update_cache(cache_key, decoded_content)
                return decoded_content
            return None
        except GitHubAPIError as e:
            if e.status_code == 404:
                logger.info(f"No README file found for {owner}/{repo}.")
                return None
            raise e