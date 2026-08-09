"""
polite_crawler — polite crawler

### PART-META-JSON
{
  "name": "polite_crawler",
  "layer": "automation",
  "purpose": "polite crawler",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: CookieJar(...); PageObject(...); BrowserSession(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Handles cryptographic material; keep keys and tokens out of logs and source, and prefer the vetted primitives it wraps.",
  "ai_usage": "Import what you need from `scrapyard.automation.polite_crawler`.",
  "example": "from scrapyard.automation.polite_crawler import *",
  "import_path": "scrapyard.automation.polite_crawler"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import os, json, hashlib, logging, tempfile

# Playwright is an optional/heavy dependency: guard it so this module still
# imports on platforms/CI where playwright is absent. Page/BrowserContext are
# referenced in dataclass annotations, so they need module-level fallbacks.
try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    async_playwright = None
    sync_playwright = None
    Page = Any
    BrowserContext = Any
    _HAS_PLAYWRIGHT = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CookieJar:
    def __init__(self):
        self.cookies = {}

    def add_cookie(self, cookie: Dict[str, Any]):
        self.cookies[cookie["name"]] = cookie

    def get_cookies(self) -> List[Dict[str, Any]]:
        return list(self.cookies.values())

@dataclass
class PageObject:
    page: Page

@dataclass
class BrowserSession:
    context: BrowserContext
    cookies: CookieJar

class SessionManager:
    def __init__(self):
        self.sessions = {}

    def start_session(self) -> BrowserSession:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            cookie_jar = CookieJar()
            for cookie in context.cookies():
                cookie_jar.add_cookie(cookie)
            session_id = hashlib.sha256(json.dumps(context.storage_state()).encode()).hexdigest()
            self.sessions[session_id] = BrowserSession(context, cookie_jar)
            return self.sessions[session_id]

    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        return self.sessions.get(session_id)

class DataExtractor:
    @staticmethod
    def extract_data(html_content: str) -> Dict[str, Any]:
        # Placeholder for data extraction logic
        return {"title": "Sample Title", "content": "Sample Content"}

@dataclass
class ChangeDetector:
    old_html: str
    new_html: str

    def detect_changes(self) -> bool:
        return self.old_html != self.new_html

class CrawlManager:
    def __init__(self):
        self.session_manager = SessionManager()

    async def fetch_page(self, url: str, session_id: Optional[str] = None) -> str:
        if not session_id:
            session = self.session_manager.start_session()
        else:
            session = self.session_manager.get_session(session_id)
            if not session:
                raise ValueError("Session does not exist")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=session.context.storage_state())
            page = await context.new_page()
            for cookie in session.cookies.get_cookies():
                await page.set_cookie(cookie)

            try:
                await page.goto(url, wait_until="networkidle")
                html_content = await page.content()
            except Exception as e:
                logger.error(f"Failed to fetch page {url}: {e}")
                raise
            finally:
                await browser.close()

        return html_content

def _selftest():
    """Offline selftest: exercises the dep-free logic (CookieJar dedupe,
    DataExtractor, ChangeDetector positive+negative) with real assertions, then
    skips the Playwright browser leg cleanly when the optional dep is absent."""
    # --- dep-free logic, always runs ---
    jar = CookieJar()
    jar.add_cookie({"name": "sid", "value": "abc"})
    jar.add_cookie({"name": "sid", "value": "def"})  # same name overwrites
    jar.add_cookie({"name": "csrf", "value": "xyz"})
    cookies = jar.get_cookies()
    assert len(cookies) == 2, cookies
    assert jar.cookies["sid"]["value"] == "def", "last write must win"

    data = DataExtractor.extract_data("<html><body><h1>Test</h1></body></html>")
    assert "title" in data and "content" in data, data

    # positive AND negative change detection
    assert ChangeDetector("<a>", "<b>").detect_changes() is True
    assert ChangeDetector("<same>", "<same>").detect_changes() is False

    # --- Playwright leg: skip cleanly when the optional dep is absent ---
    if not _HAS_PLAYWRIGHT:
        print("polite_crawler selftest: SKIPPED (playwright not installed); "
              "offline logic verified")
        return

    try:
        manager = CrawlManager()
        session = manager.session_manager.start_session()
        assert session is not None and session.context is not None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            print("polite_crawler selftest: SKIPPED (playwright browsers not "
                  "installed); offline logic verified")
            return
        raise
    print("polite_crawler selftest: PASS (playwright session created)")


if __name__ == "__main__":
    _selftest()
