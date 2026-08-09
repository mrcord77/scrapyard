"""
github_client_wrapper — Typed wrapper around the GitHub REST API with real HTTP
execution (requests sync / httpx async), domain exceptions for auth/rate-limit/404,
and an explicit offline mode for tests.

### PART-META-JSON
{
  "name": "github_client_wrapper",
  "layer": "connectors",
  "purpose": "Calls the real GitHub REST API (https://api.github.com) with bearer-token auth: sync requests via requests, async via httpx, typed RepoInfoModel results, and 401/403/404/rate-limit mapped to domain exceptions. An explicit offline=True mode serves caller-seeded plain-dict responses so selftests run without network; module-level get_repo_info() reads GITHUB_TOKEN from the environment.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "requests",
    "httpx (async path only)"
  ],
  "inputs": "GitHub personal-access/app token (constructor arg or GITHUB_TOKEN env var), owner/repo names, arbitrary REST endpoints via _make_request; offline flag plus seeded responses for tests.",
  "outputs": "RepoInfoModel dataclasses and parsed JSON dicts; typed exceptions GitHubNotFoundError/GitHubAuthenticationError/GitHubRateLimitError/GitHubAPIError on failure.",
  "files_created": [],
  "security_notes": "Handles live GitHub tokens: sent only in the Authorization header over TLS to the configured base_url and never logged. A token grants whatever scopes it was minted with - prefer fine-grained read-only tokens for repo metadata. Error text can include GitHub response excerpts; treat logs of raised exceptions as sensitive. base_url is caller-controlled (for GHES); pointing it at an untrusted host would leak the token, so only set it to servers you trust. Offline mode does zero network I/O and is for tests only.",
  "ai_usage": "GitHubClientWrapper(token).get_repo_info(owner, repo) sync, await .aget_repo_info(...) async; get_repo_info(owner, repo) uses GITHUB_TOKEN. Tests: GitHubClientWrapper(token, offline=True) + seed_offline_response.",
  "example": "from scrapyard.connectors.github_client_wrapper import GitHubClientWrapper",
  "import_path": "scrapyard.connectors.github_client_wrapper"
}
### END-PART-META
"""

from typing import Optional, Any, Dict, Tuple
from dataclasses import dataclass, fields
import os
import asyncio
import logging

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT = 30.0


class GitHubAPIError(Exception):
    """Base exception for GitHub API failures."""


class GitHubNotFoundError(GitHubAPIError):
    """Raised when a GitHub resource is not found."""


class GitHubAuthenticationError(GitHubAPIError):
    """Raised on authentication/authorization failures."""


class GitHubRateLimitError(GitHubAPIError):
    """Raised when the GitHub API rate limit has been exceeded."""


@dataclass
class RepoInfoModel:
    name: str
    full_name: str
    description: Optional[str] = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0

    @classmethod
    def from_api(cls, data: Dict[str, Any]) -> "RepoInfoModel":
        keep = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in keep})


class GitHubClientWrapper:
    """Typed wrapper around the GitHub REST API.

    Real mode issues HTTPS requests (requests for sync, httpx for async).
    offline=True serves seeded plain-dict responses with zero network I/O.
    """

    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, *,
                 timeout: float = DEFAULT_TIMEOUT, offline: bool = False) -> None:
        if not token:
            raise ValueError("GitHub token is required")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.offline = offline
        self._offline_responses: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._offline_statuses: Dict[Tuple[str, str], Tuple[int, Dict[str, str]]] = {}
        self._session: Optional[requests.Session] = None

    # -- offline seeding ----------------------------------------------------------
    def seed_offline_response(self, method: str, endpoint: str,
                              response: Dict[str, Any]) -> None:
        """Register a canned 200 JSON response for offline mode."""
        self._offline_responses[(method.upper(), endpoint.lstrip("/"))] = response

    def seed_offline_status(self, method: str, endpoint: str, status: int,
                            headers: Optional[Dict[str, str]] = None) -> None:
        """Register a canned failure status (e.g. 404, 403 + rate-limit headers)."""
        self._offline_statuses[(method.upper(), endpoint.lstrip("/"))] = (
            status, headers or {})

    # -- shared plumbing ----------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _check_status(status: int, headers: Dict[str, str], detail: str = "") -> None:
        """Map an HTTP status to a domain exception (no-op on 2xx)."""
        if 200 <= status < 300:
            return
        if status == 404:
            raise GitHubNotFoundError(f"GitHub resource not found {detail}".strip())
        if status in (401, 403):
            remaining = headers.get("X-RateLimit-Remaining") or headers.get(
                "x-ratelimit-remaining")
            if status == 403 and remaining == "0":
                raise GitHubRateLimitError("GitHub API rate limit exceeded")
            raise GitHubAuthenticationError(
                f"GitHub authentication failed ({status}) {detail}".strip())
        raise GitHubAPIError(f"GitHub API returned unexpected status {status} {detail}".strip())

    def _offline_lookup(self, method: str, endpoint: str) -> Dict[str, Any]:
        key = (method.upper(), endpoint.lstrip("/"))
        if key in self._offline_statuses:
            status, headers = self._offline_statuses[key]
            self._check_status(status, headers, f"({method} {endpoint})")
        if key in self._offline_responses:
            return self._offline_responses[key]
        raise GitHubAPIError(
            f"offline mode: no seeded response for {method} {endpoint}")

    # -- real request paths -------------------------------------------------------
    def _make_request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Synchronous request via requests."""
        if self.offline:
            return self._offline_lookup(method, endpoint)
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if self._session is None:
            self._session = requests.Session()
        try:
            resp = self._session.request(method, url, headers=self._headers(),
                                         timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise GitHubAPIError(f"network error on {method} {url}: {exc}") from exc
        self._check_status(resp.status_code, dict(resp.headers), f"({method} {endpoint})")
        return resp.json() if resp.content else {}

    async def _amake_request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Asynchronous request via httpx."""
        if self.offline:
            return self._offline_lookup(method, endpoint)
        import httpx  # deferred so the sync path never needs it
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"network error on {method} {url}: {exc}") from exc
        self._check_status(resp.status_code, dict(resp.headers), f"({method} {endpoint})")
        return resp.json() if resp.content else {}

    # -- typed operations ---------------------------------------------------------
    def get_repo_info(self, owner: str, repo: str) -> RepoInfoModel:
        """Fetch repository information (sync)."""
        data = self._make_request("GET", f"repos/{owner}/{repo}")
        return RepoInfoModel.from_api(data)

    async def aget_repo_info(self, owner: str, repo: str) -> RepoInfoModel:
        """Fetch repository information (async)."""
        data = await self._amake_request("GET", f"repos/{owner}/{repo}")
        return RepoInfoModel.from_api(data)


def get_repo_info(owner: str, repo: str) -> RepoInfoModel:
    """Convenience function that builds a wrapper from ``GITHUB_TOKEN``."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GitHub token is required (set GITHUB_TOKEN)")
    return GitHubClientWrapper(token).get_repo_info(owner, repo)


# Plain-dict sample used only to seed offline mode in the selftest.
_SAMPLE_REPO = {
    "name": "test-repo",
    "full_name": "user/test-repo",
    "description": "A test repository",
    "stargazers_count": 10,
    "forks_count": 5,
    "open_issues_count": 2,
    "html_url": "https://github.com/user/test-repo",  # extra field must be tolerated
}


def _selftest() -> None:
    # Sync path in offline mode
    client = GitHubClientWrapper("offline_token", offline=True)
    client.seed_offline_response("GET", "repos/user/test-repo", _SAMPLE_REPO)

    result = client.get_repo_info("user", "test-repo")
    assert isinstance(result, RepoInfoModel)
    assert result.name == "test-repo"
    assert result.full_name == "user/test-repo"
    assert result.description == "A test repository"
    assert result.stargazers_count == 10
    assert result.forks_count == 5
    assert result.open_issues_count == 2

    # Headers are correctly formed
    headers = client._headers()
    assert headers["Authorization"] == "Bearer offline_token"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"

    # Async variant (offline)
    async_result = asyncio.run(client.aget_repo_info("user", "test-repo"))
    assert async_result.full_name == "user/test-repo"

    # 404 handling
    client.seed_offline_status("GET", "repos/user/missing", 404)
    try:
        client.get_repo_info("user", "missing")
        raise AssertionError("Expected GitHubNotFoundError")
    except GitHubNotFoundError:
        pass

    # Rate-limit handling
    client.seed_offline_status("GET", "repos/user/limited", 403,
                               {"X-RateLimit-Remaining": "0"})
    try:
        client.get_repo_info("user", "limited")
        raise AssertionError("Expected GitHubRateLimitError")
    except GitHubRateLimitError:
        pass

    # Authentication failure handling
    client.seed_offline_status("GET", "repos/user/private", 401)
    try:
        client.get_repo_info("user", "private")
        raise AssertionError("Expected GitHubAuthenticationError")
    except GitHubAuthenticationError:
        pass

    # Unseeded offline endpoint is an honest error
    try:
        client.get_repo_info("user", "never-seeded")
        raise AssertionError("Expected GitHubAPIError")
    except GitHubNotFoundError:
        raise AssertionError("unseeded must not masquerade as 404")
    except GitHubAPIError as e:
        assert "no seeded response" in str(e)

    # Module-level convenience function against an offline-mode wrapper:
    # patch env var without unittest.mock (plain os.environ handling).
    old = os.environ.get("GITHUB_TOKEN")
    try:
        os.environ["GITHUB_TOKEN"] = "env_token"
        # Route through offline mode by constructing directly (get_repo_info
        # would hit the network; only its token plumbing is under test here).
        wrapper = GitHubClientWrapper(os.environ["GITHUB_TOKEN"], offline=True)
        wrapper.seed_offline_response("GET", "repos/user/test-repo", _SAMPLE_REPO)
        assert wrapper.get_repo_info("user", "test-repo").name == "test-repo"
        assert wrapper.token == "env_token"

        os.environ.pop("GITHUB_TOKEN", None)
        try:
            get_repo_info("user", "test-repo")
            raise AssertionError("Expected ValueError for missing token")
        except ValueError:
            pass
    finally:
        if old is not None:
            os.environ["GITHUB_TOKEN"] = old
        else:
            os.environ.pop("GITHUB_TOKEN", None)

    # Empty token rejected at construction
    try:
        GitHubClientWrapper("")
        raise AssertionError("Expected ValueError for empty token")
    except ValueError:
        pass

    print("github_client_wrapper selftest: all tests passed")


if __name__ == "__main__":
    _selftest()
