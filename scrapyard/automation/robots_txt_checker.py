"""Robots.txt checker for polite crawling.

### PART-META-JSON
{
  "name": "robots_txt_checker",
  "layer": "automation",
  "purpose": "Checks whether URLs are allowed by a domain's robots.txt: parses user-agent groups (allow/disallow/crawl-delay), applies longest-match precedence between conflicting allow/disallow rules, caches parsed directives per-domain in a local SQLite database, and treats missing robots.txt as permissive. HONEST LIMIT: the fetch step (_polite_crawler) is an offline placeholder returning canned responses - wire it to a real HTTP fetcher before production crawling.",
  "status": "core",
  "dependencies": [],
  "inputs": "RobotsTxtChecker(user_agent, cache_dir=None); then is_allowed(url), check_url(url), get_crawl_delay(domain).",
  "outputs": "Boolean allow decisions, detailed status dicts, optional crawl-delay floats; robots_cache.db SQLite cache in cache_dir.",
  "files_created": ["<cache_dir>/robots_cache.db (defaults under the system temp dir)"],
  "security_notes": "No real network I/O until you replace _polite_crawler - as shipped, decisions for unknown domains are 'allow everything', so DO NOT treat current output as compliance with a live site's robots.txt. The default cache lives in the world-writable system temp dir: another local user could pre-seed or tamper with cached directives, so point cache_dir at a private path in shared environments. Cached entries never expire (no TTL); stale rules persist until the DB is cleared. URL parsing uses stdlib urllib.parse only; no secrets handled.",
  "ai_usage": "checker = RobotsTxtChecker('mybot', cache_dir=my_private_dir); wire a real fetcher into _polite_crawler, then guard every crawl with checker.is_allowed(url).",
  "example": "from scrapyard.automation.robots_txt_checker import RobotsTxtChecker",
  "import_path": "scrapyard.automation.robots_txt_checker"
}
### END-PART-META
"""

from typing import Optional, Dict, Any
import os
import re
import json
import time
import logging
import tempfile
import sqlite3
import urllib.parse

logger = logging.getLogger(__name__)


class RobotsTxtChecker:
    """
    Checks if a URL is allowed by a domain's robots.txt.

    Features:
    - Parses robots.txt groups and directives.
    - Respects user-agent-specific rules.
    - Caches parsed directives in a local SQLite database.
    - Handles missing/malformed robots.txt gracefully.
    """

    def __init__(self, user_agent: str, cache_dir: str = None):
        self.user_agent = user_agent.strip()
        self.cache_dir = cache_dir or os.path.join(
            tempfile.gettempdir(), "robots_txt_checker_cache"
        )
        os.makedirs(self.cache_dir, exist_ok=True)

    # --------------------------------------------------------------------- #
    # Network / fetching
    # --------------------------------------------------------------------- #
    def _fetch_robots_txt(self, domain: str) -> Optional[str]:
        url = f"http://{domain}/robots.txt"
        return self._polite_crawler(url)

    def _polite_crawler(self, url: str) -> Optional[str]:
        """
        Offline, network-safe placeholder.

        In a real deployment this would integrate with polite_crawler.
        For testing and safe default behavior it returns canned responses.
        """
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc

        if domain == "example.com":
            return (
                "User-agent: mybot\n"
                "Disallow: /private/\n"
                "Allow: /\n"
                "\n"
                "User-agent: *\n"
                "Allow: /\n"
            )
        if domain == "nomissingrobots.com":
            return None

        # Default permissive policy for unknown domains.
        return "User-agent: *\nAllow: /\n"

    # --------------------------------------------------------------------- #
    # Parsing
    # --------------------------------------------------------------------- #
    def _parse_robots_txt(self, robots_txt: str) -> Dict[str, Any]:
        directives: Dict[str, Any] = {}
        current_agents: list[str] = []

        for raw_line in robots_txt.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                current_agents = []
                continue

            match = re.match(
                r"^\s*(user-agent|disallow|allow|crawl-delay)\s*:\s*(.*)\s*$",
                line,
                re.IGNORECASE,
            )
            if not match:
                continue

            key = match.group(1).lower()
            value = match.group(2).strip()

            if key == "user-agent":
                current_agents.append(value)
                for ua in current_agents:
                    directives.setdefault(
                        ua, {"allow": [], "disallow": [], "crawl-delay": None}
                    )
            elif key in ("allow", "disallow"):
                if not current_agents:
                    continue
                for ua in current_agents:
                    directives[ua][key].append(value)
            elif key == "crawl-delay":
                if not current_agents:
                    continue
                try:
                    delay = float(value)
                except ValueError:
                    delay = None
                for ua in current_agents:
                    directives[ua]["crawl-delay"] = delay

        return directives

    # --------------------------------------------------------------------- #
    # Caching (SQLite)
    # --------------------------------------------------------------------- #
    def _db_path(self) -> str:
        return os.path.join(self.cache_dir, "robots_cache.db")

    def _init_cache_db(self) -> None:
        conn = sqlite3.connect(self._db_path())
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS robots_cache (
                    domain TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _load_cached_directives(self, domain: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self._db_path()):
            return None

        conn = sqlite3.connect(self._db_path())
        try:
            row = conn.execute(
                "SELECT content FROM robots_cache WHERE domain = ?", (domain,)
            ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        finally:
            conn.close()

    def _save_directives(self, domain: str, directives: Dict[str, Any]) -> None:
        self._init_cache_db()
        conn = sqlite3.connect(self._db_path())
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO robots_cache (domain, content, cached_at)
                VALUES (?, ?, ?)
                """,
                (domain, json.dumps(directives), time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def get_directives(self, domain: str) -> Dict[str, Any]:
        cached = self._load_cached_directives(domain)
        if cached is not None:
            return cached

        robots_txt = self._fetch_robots_txt(domain)
        if robots_txt is None:
            logger.warning("No robots.txt found for %s", domain)
            self._save_directives(domain, {})
            return {}

        directives = self._parse_robots_txt(robots_txt)
        self._save_directives(domain, directives)
        return directives

    def is_allowed(self, url: str) -> bool:
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        path = parsed_url.path or "/"
        if not path.startswith("/"):
            path = "/" + path

        directives = self.get_directives(domain)

        # Prefer an exact user-agent match; fall back to wildcard.
        group = None
        if self.user_agent in directives:
            group = directives[self.user_agent]
        elif "*" in directives:
            group = directives["*"]

        if group is None:
            return True

        allows = group.get("allow", [])
        disallows = group.get("disallow", [])

        def matches(rule: str, url_path: str) -> bool:
            if rule == "":
                return True
            if not rule.startswith("/"):
                rule = "/" + rule
            return url_path.startswith(rule)

        matched_allow = any(matches(rule, path) for rule in allows)
        matched_disallow = any(matches(rule, path) for rule in disallows)

        if matched_allow and matched_disallow:
            longest_allow = max(
                (len(rule) for rule in allows if matches(rule, path)), default=-1
            )
            longest_disallow = max(
                (len(rule) for rule in disallows if matches(rule, path)), default=-1
            )
            return longest_allow >= longest_disallow

        if matched_disallow:
            return False
        return True

    def check_url(self, url: str) -> Dict[str, Any]:
        """Return a detailed status dictionary for the URL."""
        parsed_url = urllib.parse.urlparse(url)
        return {
            "url": url,
            "domain": parsed_url.netloc,
            "allowed": self.is_allowed(url),
            "directives": self.get_directives(parsed_url.netloc),
        }

    def get_crawl_delay(self, domain: str) -> Optional[float]:
        directives = self.get_directives(domain)
        group = directives.get(self.user_agent) or directives.get("*")
        if group is None:
            return None
        return group.get("crawl-delay")


def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        checker = RobotsTxtChecker("mybot", cache_dir=tmpdir)

        # Valid parsing and allow/disallow logic.
        assert checker.is_allowed("http://example.com/public/page") is True
        assert checker.is_allowed("http://example.com/private/page") is False
        assert checker.is_allowed("http://example.com/private/subpage") is False
        assert checker.is_allowed("http://example.com/public/another_page") is True

        # Missing robots.txt is treated as fully permissive.
        assert checker.is_allowed("http://nomissingrobots.com/page") is True

        # Cached result returns the same value.
        assert checker.is_allowed("http://example.com/private/subpage") is False

        # User-agent-specific enforcement: '*' has no /private/ disallow.
        wildcard_checker = RobotsTxtChecker("*", cache_dir=tmpdir)
        assert wildcard_checker.is_allowed("http://example.com/private/page") is True

        # Verify the SQLite cache was used.
        db_path = os.path.join(tmpdir, "robots_cache.db")
        assert os.path.exists(db_path)
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT domain FROM robots_cache").fetchall()
            domains = {row[0] for row in rows}
            assert "example.com" in domains
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
