"""
browser_automation — Playwright-based browser automation with reusable page objects and
session management; headless by default, import-safe without Playwright, offline selftest.

### PART-META-JSON
{
  "name": "browser_automation",
  "layer": "automation",
  "purpose": "Drives real browsers through Playwright's async API: BrowserSession manages playwright/browser/context/page lifecycle (headless Chromium by default, configurable), PageObject wraps load/click/type/get_text/set_content interactions for page-object-pattern reuse. Playwright is imported lazily so the module imports on machines without it; the selftest drives a real headless browser against locally-set HTML (no network) and skips gracefully when Playwright or its browser binaries are absent.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "playwright (lazy import; 'playwright install chromium' needed for live use)"
  ],
  "inputs": "URLs or local HTML content, CSS selectors, text to type; headless flag and browser channel via BrowserSession.",
  "outputs": "Live browser interactions; get_text returns element text content.",
  "files_created": [],
  "security_notes": "A driven browser executes arbitrary JavaScript from every page it loads - treat navigated URLs as code execution in the browser sandbox, never load untrusted URLs in a context holding cookies/credentials of value, and prefer fresh contexts per site. Text typed via type() ends up in real page inputs: do not pipe secrets through automation scripts that log actions (this module logs selectors, not typed text). headless=False opens visible windows on the desktop. Playwright downloads browser binaries out of band ('playwright install'); this module never downloads anything itself. Scraping targets may prohibit automation - respect robots/ToS upstream (see automation/robots_txt_checker).",
  "ai_usage": "async: s = BrowserSession(); await s.start(); po = PageObject(s.page); await po.load(url); ... await s.close(). Always close in finally.",
  "example": "from scrapyard.automation.browser_automation import BrowserSession, PageObject",
  "import_path": "scrapyard.automation.browser_automation"
}
### END-PART-META
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _playwright_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except ImportError:
        return False


class PageObject:
    """Reusable page-object wrapper over a Playwright Page."""

    def __init__(self, page: Any):
        self.page = page

    async def load(self, url: str) -> None:
        await self.page.goto(url)

    async def set_content(self, html: str) -> None:
        """Render local HTML directly (no network)."""
        await self.page.set_content(html)

    async def click(self, selector: str) -> None:
        await self.page.click(selector)

    async def type(self, selector: str, text: str) -> None:
        await self.page.type(selector, text)

    async def get_text(self, selector: str) -> Optional[str]:
        return await self.page.text_content(selector)

    async def get_value(self, selector: str) -> str:
        return await self.page.input_value(selector)


class BrowserSession:
    """Owns the Playwright lifecycle: playwright -> browser -> context -> page."""

    def __init__(self, headless: bool = True, browser_name: str = "chromium"):
        self.headless = headless
        self.browser_name = browser_name
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed; run 'pip install playwright' and "
                "'playwright install chromium' to use browser_automation") from exc
        self.playwright = await async_playwright().start()
        launcher = getattr(self.playwright, self.browser_name, None)
        if launcher is None:
            await self.playwright.stop()
            raise ValueError(f"unknown browser: {self.browser_name!r}")
        self.browser = await launcher.launch(headless=self.headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

    async def new_page(self) -> Any:
        if self.context is None:
            raise RuntimeError("session not started; call start() first")
        return await self.context.new_page()

    async def close(self) -> None:
        if self.page:
            await self.page.close()
            self.page = None
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    async def __aenter__(self) -> "BrowserSession":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()


_SELFTEST_HTML = """
<!DOCTYPE html>
<html><body>
  <h1 id="title">Selftest Page</h1>
  <input id="search-input" type="text" />
  <div id="result">initial</div>
  <button id="btn" onclick="document.getElementById('result').textContent='clicked'">
    Go
  </button>
</body></html>
"""


async def _selftest_async() -> None:
    session = BrowserSession(headless=True)
    await session.start()
    try:
        page_obj = PageObject(session.page)

        # Local HTML only - no network
        await page_obj.set_content(_SELFTEST_HTML)
        title = await page_obj.get_text("#title")
        assert title == "Selftest Page", title

        # Real typing into a real input
        await page_obj.click("#search-input")
        await page_obj.type("#search-input", "hello")
        assert await page_obj.get_value("#search-input") == "hello"

        # Real click mutates the DOM via the page's own JS
        await page_obj.click("#btn")
        assert await page_obj.get_text("#result") == "clicked"

        # Second page from the same context
        extra = await session.new_page()
        await extra.set_content("<p id='p'>two</p>")
        assert await extra.text_content("#p") == "two"
        await extra.close()
    finally:
        await session.close()


def _selftest() -> None:
    """Offline selftest: exercises pure session sub-logic always, then drives a
    real headless browser on local HTML; skips the live leg gracefully (exit 0)
    when Playwright or its browsers are unavailable."""
    import asyncio

    # --- pure sub-logic, always runs (no browser needed) ---
    assert isinstance(_playwright_available(), bool)
    s = BrowserSession()
    assert s.headless is True and s.browser_name == "chromium" and s.page is None
    s2 = BrowserSession(headless=False, browser_name="firefox")
    assert s2.headless is False and s2.browser_name == "firefox"
    # NEGATIVE: requesting a page before start() must raise, not return None.
    try:
        asyncio.run(BrowserSession().new_page())
        raise AssertionError("new_page() before start() should raise")
    except RuntimeError:
        pass

    if not _playwright_available():
        print("browser_automation selftest: PASS "
              "(offline sub-logic verified; live browser leg skipped)")
        return
    try:
        asyncio.run(_selftest_async())
    except Exception as exc:
        # Playwright installed but browser binaries missing (needs
        # 'playwright install') - an environment gap, not a code defect.
        msg = str(exc)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            print("browser_automation selftest: PASS "
                  "(browser binaries not installed; live leg skipped)")
            return
        raise
    print("browser_automation selftest: PASS (live headless browser verified)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    _selftest()
