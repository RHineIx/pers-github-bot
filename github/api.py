# github/api.py  
  
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
    # Custom exception for GitHub API related errors.  
    def __init__(self, status_code: int, message: str):  
        self.status_code = status_code  
        self.message = message  
        super().__init__(f"GitHub API Error {status_code}: {message}")  
  
  
class GitHubAPI:  
    # The cache stores: (timestamp, etag, data)  
    _cache: Dict[str, Tuple[float, Optional[str], Any]] = {}  
  
    def __init__(self, db_manager: DatabaseManager):  
        self.db_manager = db_manager  
        self.base_url = config.GITHUB_API_BASE  
        self.cache_ttl = config.CACHE_TTL_SECONDS  
        # Initialize shared session as None - will be created when needed  
        self._session = None  
  
    async def _get_session(self) -> aiohttp.ClientSession:  
        """Get or create shared session for connection pooling"""  
        if self._session is None or self._session.closed:  
            timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)  
            self._session = aiohttp.ClientSession(timeout=timeout)  
        return self._session  
  
    async def close(self):  
        """Close the shared session"""  
        if self._session and not self._session.closed:  
            await self._session.close()  
  
    async def _get_headers(self) -> Dict[str, str]:  
        # Constructs base request headers with authentication.  
        headers = {  
            "Accept": "application/vnd.github.v3+json",  
            "User-Agent": "Personal-GitHub-Stars-Bot/1.0",  
        }  
        token = await self.db_manager.get_token()  
        if token:  
            headers["Authorization"] = f"token {token}"  
        return headers  
  
    async def _make_request(  
        self, endpoint: str, etag: Optional[str] = None, extra_headers: Optional[Dict] = None  
    ) -> Tuple[int, Dict, Optional[Any]]:  
        # Central method for making all HTTP requests to the GitHub API.  
        url = f"{self.base_url}/{endpoint.lstrip('/')}"  
        headers = await self._get_headers()  
  
        if "Authorization" not in headers:  
            raise GitHubAPIError(401, "GitHub token not found.")  
          
        # Add E-Tag for conditional requests if provided.  
        if etag:  
            headers["If-None-Match"] = etag  
          
        # Merge any extra headers, e.g., for getting starred timestamps.  
        if extra_headers:  
            headers.update(extra_headers)  
  
        # Use shared session instead of creating new one for each request  
        session = await self._get_session()  
        try:  
            async with session.get(url, headers=headers) as response:  
                # Handle 304 Not Modified for cached requests.  
                if response.status == 304:  
                    return 304, response.headers, None  
  
                # Handle successful responses.  
                if 200 <= response.status < 300:  
                    return response.status, response.headers, await response.json()  
  
                # Handle rate limiting.  
                if response.status == 403 and "X-RateLimit-Reset" in response.headers:  
                    reset_timestamp = int(response.headers["X-RateLimit-Reset"])  
                    wait_duration = max(reset_timestamp - int(time.time()), 0) + 2  
                    logger.warning(f"Rate limit exceeded. Waiting for {wait_duration}s.")  
                    await asyncio.sleep(wait_duration)  
                    return await self._make_request(endpoint, etag, extra_headers)  
  
                # Handle all other errors.  
                raise GitHubAPIError(response.status, await response.text())  
  
        except asyncio.TimeoutError:  
            raise GitHubAPIError(408, "Request timed out")  
        except Exception as e:  
            if not isinstance(e, GitHubAPIError):  
                logger.error(f"Unexpected request error for {url}: {e}")  
                raise GitHubAPIError(500, str(e))  
            raise e  
      
    async def _make_cached_request(self, endpoint: str) -> Optional[Any]:  
        # Generic wrapper for API calls that should be cached using E-Tags.  
        cache_key = endpoint  
        cached_entry = self._cache.get(cache_key)  
        etag = None  
  
        if cached_entry:  
            timestamp, etag, cached_data = cached_entry  
            # For very recent requests (<60s), serve directly from cache to save an API call.  
            if time.time() - timestamp < 60:  
                 return cached_data  
          
        try:  
            status, headers, data = await self._make_request(endpoint, etag=etag)  
              
            if status == 304 and cached_entry:  
                # Cache is still valid. Update timestamp and return cached data.  
                _, etag, cached_data = cached_entry  
                self._cache[cache_key] = (time.time(), etag, cached_data)  
                return cached_data  
              
            elif status == 200:  
                # New data received. Update cache with new data and E-Tag.  
                new_etag = headers.get("ETag")  
                self._cache[cache_key] = (time.time(), new_etag, data)  
                return data  
  
        except GitHubAPIError as e:  
            # If a conditional request returns 404, the resource was likely deleted.  
            if e.status_code == 404 and cache_key in self._cache:  
                del self._cache[cache_key]  
            raise e  
              
        return None  
  
    # --- Public API methods ---  
  
    async def get_repository(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:  
        return await self._make_cached_request(f"repos/{owner}/{repo}")  
  
    async def get_repository_languages(self, owner: str, repo: str) -> Optional[Dict[str, int]]:  
        return await self._make_cached_request(f"repos/{owner}/{repo}/languages")  
  
    async def get_latest_release(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:  
        try:  
            return await self._make_cached_request(f"repos/{owner}/{repo}/releases/latest")  
        except GitHubAPIError as e:  
            if e.status_code == 404: return {} # Return empty dict if no releases found.  
            raise e  
              
    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:  
        return await self._make_cached_request(f"users/{username}")  
  
    async def get_readme(self, owner: str, repo: str) -> Optional[str]:  
        try:  
            readme_data = await self._make_cached_request(f"repos/{owner}/{repo}/readme")  
            if readme_data and "content" in readme_data:  
                return base64.b64decode(readme_data["content"]).decode("utf-8")  
            return None  
        except GitHubAPIError as e:  
            if e.status_code == 404: return None  
            raise e  
  
    # --- Methods that should NOT be cached or have custom logic ---  
  
    async def get_authenticated_user(self) -> Optional[Dict[str, Any]]:  
        # This is for validation, should always be fresh.  
        status, _, data = await self._make_request("user")  
        return data if status == 200 else None  
  
    async def get_rate_limit(self) -> Optional[Dict[str, Any]]:  
        # Rate limit status should always be fresh.  
        status, _, data = await self._make_request("rate_limit")  
        return data if status == 200 else None  
  
    async def get_authenticated_user_starred_repos(  
        self, page: int = 1, per_page: int = 50  
    ) -> Optional[List[Dict[str, Any]]]:  
        # Star feed must be fresh and requires a special 'Accept' header for timestamps.  
        # Now uses the central _make_request method for robustness.  
        endpoint = f"user/starred?page={page}&per_page={per_page}&sort=created&direction=desc"  
        extra_headers = {"Accept": "application/vnd.github.star+json"}  
        status, _, data = await self._make_request(endpoint, extra_headers=extra_headers)  
        return data if status == 200 else None