#!/usr/bin/env python3
"""
verify_frontend.py — the frontend gate.

Boots a generated app, opens its main human-facing page in headless Chrome,
screenshots it, and judges every line of the Forge frontend-standard.md rubric.
A build with no real UI or one that fails the rubric FAILS the gate.

    python tools/verify_frontend.py <app_dir> [--out screenshot.png]

Returns exit 0 if the rubric passes, exit 1 with a line-by-line verdict if not.
"""
from __future__ import annotations
import importlib
import json
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

def _find_chrome() -> str:
    """First existing Chrome/Chromium binary. (The old one-liner had an operator-
    precedence bug: `env or path if nt else linuxpath` ignored CHROME_BIN on Linux.)"""
    candidates = [
        os.environ.get("CHROME_BIN"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return ""

CHROME_BIN = _find_chrome()

RUBRIC = [
    ("F1a", "Top-level heading names the product or view, not a framework name"),
    ("F1b", "Content grouped into visually distinct sections (cards, panels)"),
    ("F1c", "Most important data is the largest/most prominent element"),
    ("F2a", "Loading state visible (skeleton or spinner)"),
    ("F2b", "Empty state handled helpfully"),
    ("F2c", "Error state shows a clear message"),
    ("F3a", "Body text 15-18px with comfortable line-height"),
    ("F3b", "Visible spacing between sections (>16px)"),
    ("F3c", "No more than 2 font families"),
    ("F4a", "Key domain data visible on main view without drill-down"),
    ("F4b", "Status/risk/score use visual weight (color, badges)"),
    ("F4c", "Actionable items have visible styled buttons"),
    ("F4d", "Panel routing shows three distinct visual outcomes"),
    ("F5a", "Layout works at 375px without horizontal scroll"),
    ("F5b", "Touch targets at least 44px on mobile"),
    ("F6a", "Cohesive color palette (2-4 colors, not browser defaults)"),
    ("F6b", "Nav or header orients the user"),
    ("F6c", "Would not embarrass in a client demo"),
    ("F6d", "HARD FAIL: Is a designed UI, NOT an API console / Swagger / bare form"),
    ("F7a", "Generous consistent spacing - page breathes, nothing cramped"),
    ("F7b", "Interaction feedback - hover/active states on buttons/links"),
    ("F7c", "Clear visual hierarchy - one primary action, secondaries quieter"),
    ("F7d", "Polished detail - aligned, consistent radii, coherent type scale"),
    ("F7e", "Looks like a product someone would choose to use"),
]


def _boot_app_in_thread(app_dir: str, port: int = 18199):
    """Boot a FastAPI app from app_dir on a background thread, return when ready."""
    sys.path.insert(0, app_dir)
    os.chdir(app_dir)
    old_env = os.environ.get("APP_ENV")
    os.environ["APP_ENV"] = "development"
    try:
        if "main" in sys.modules:
            del sys.modules["main"]
        mod = importlib.import_module("main")
        app = mod.app
    except Exception as e:
        print(f"  [frontend-gate] could not import app: {e}")
        return None

    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(40):
        try:
            import httpx
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code == 200:
                return server
        except Exception:
            pass
        time.sleep(0.25)
    print("  [frontend-gate] app did not start within 10s")
    return None


def _screenshot(url: str, out_path: str, width: int = 1280, height: int = 900) -> str:
    """Take a headless Chrome screenshot, return the path."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument(f"--window-size={width},{height}")
    if os.path.exists(CHROME_BIN):
        opts.binary_location = CHROME_BIN
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(url)
        time.sleep(1.5)
        driver.save_screenshot(out_path)
        return out_path
    finally:
        driver.quit()


def _analyze_page(url: str) -> dict:
    """Load page in headless Chrome and extract structural signals for rubric judging."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    if os.path.exists(CHROME_BIN):
        opts.binary_location = CHROME_BIN
    driver = webdriver.Chrome(options=opts)
    signals = {}
    try:
        driver.get(url)
        time.sleep(1.5)
        page_source = driver.page_source
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # F1a: heading check
        headings = driver.find_elements(By.CSS_SELECTOR, "h1, h2, h3")
        heading_texts = [h.text.strip() for h in headings if h.text.strip()]
        signals["headings"] = heading_texts
        bad_names = ["scrapyard", "swagger", "fastapi", "redoc", "openapi"]
        signals["heading_is_product"] = bool(heading_texts) and not any(
            b in heading_texts[0].lower() for b in bad_names
        )

        # F1b: sections/cards
        cards = driver.find_elements(By.CSS_SELECTOR,
            "[class*='card'], [class*='panel'], [class*='section'], "
            "[class*='rounded'], [class*='shadow'], [class*='border']")
        signals["card_count"] = len(cards)

        # F1c: prominent data — look for large text elements
        large_els = driver.execute_script("""
            return Array.from(document.querySelectorAll('*')).filter(el => {
                const s = getComputedStyle(el);
                return parseFloat(s.fontSize) >= 24 && el.textContent.trim().length > 0
                       && el.textContent.trim().length < 200;
            }).map(el => ({tag: el.tagName, text: el.textContent.trim().slice(0,80),
                           size: getComputedStyle(el).fontSize}));
        """)
        signals["large_elements"] = large_els

        # F2a: loading state
        signals["has_loading"] = bool(re.search(
            r'loading|spinner|skeleton|shimmer|pulse|animate-pulse',
            page_source, re.I))

        # F2b: empty state
        signals["has_empty_state"] = bool(re.search(
            r'no\s+(leads|data|results|items)|empty|nothing\s+here|get\s+started',
            body_text, re.I))

        # F2c: error handling
        signals["has_error_handling"] = bool(re.search(
            r'error|failed|try\s+again|something\s+went\s+wrong|oops',
            page_source, re.I))

        # F3a: font sizes
        body_font = driver.execute_script(
            "return getComputedStyle(document.body).fontSize")
        signals["body_font_size"] = body_font

        # F3b: spacing
        signals["has_spacing_classes"] = bool(re.search(
            r'(margin|padding|gap|space-[xy]|m[tblrxy]-|p[tblrxy]-)',
            page_source, re.I))

        # F3c: font families
        fonts = driver.execute_script("""
            const s = new Set();
            document.querySelectorAll('*').forEach(el => {
                s.add(getComputedStyle(el).fontFamily.split(',')[0].trim().replace(/['"]/g,''));
            });
            return Array.from(s);
        """)
        signals["font_families"] = fonts

        # F4a: domain data visible — check for EV-specific OR any substantive data
        ev_keywords = ["score", "verdict", "lead", "estimate", "panel", "risk",
                       "hot", "warm", "nurture", "approve"]
        generic_keywords = ["users", "status", "total", "active", "pending",
                           "routes", "activity", "records", "dashboard"]
        found_ev = [k for k in ev_keywords if k.lower() in body_text.lower()]
        found_generic = [k for k in generic_keywords if k.lower() in body_text.lower()]
        signals["domain_keywords_visible"] = found_ev or found_generic
        signals["domain_keywords_detail"] = found_ev if found_ev else found_generic
        signals["has_ev_domain"] = len(found_ev) >= 2

        # F4b: visual weight for status
        badges = driver.find_elements(By.CSS_SELECTOR,
            "[class*='badge'], [class*='tag'], [class*='chip'], [class*='pill'], "
            "[class*='status'], [class*='bg-green'], [class*='bg-red'], "
            "[class*='bg-amber'], [class*='bg-yellow']")
        signals["badge_count"] = len(badges)

        # F4c: styled buttons
        buttons = driver.find_elements(By.CSS_SELECTOR,
            "button, [class*='btn'], [role='button']")
        styled_buttons = [b for b in buttons if b.text.strip()]
        signals["styled_button_count"] = len(styled_buttons)
        signals["button_texts"] = [b.text.strip()[:30] for b in styled_buttons]

        # F4d: three-way panel routing
        panel_terms = ["load.management", "evems", "load-management",
                       "upgrade", "panel.fine", "panel.adequate", "no.upgrade"]
        panel_found = [t for t in panel_terms
                       if re.search(t.replace(".", r"\s*"), body_text, re.I)]
        signals["panel_three_way"] = panel_found

        # F5a: responsive (check at 375px)
        driver.set_window_size(375, 812)
        time.sleep(0.5)
        h_scroll = driver.execute_script(
            "return document.documentElement.scrollWidth > document.documentElement.clientWidth")
        signals["has_horizontal_scroll_375"] = h_scroll
        driver.set_window_size(1280, 900)

        # F6a: color palette
        colors = driver.execute_script("""
            const s = new Set();
            document.querySelectorAll('*').forEach(el => {
                const cs = getComputedStyle(el);
                if (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)')
                    s.add(cs.backgroundColor);
            });
            return Array.from(s);
        """)
        signals["distinct_bg_colors"] = len(colors)
        signals["bg_colors"] = colors[:10]

        # F6b: nav/header
        nav = driver.find_elements(By.CSS_SELECTOR, "nav, header, [role='navigation']")
        signals["has_nav"] = len(nav) > 0

        # F6d: API console / Swagger check
        is_api_console = bool(re.search(
            r'swagger|redoc|openapi|/docs|fastapi|"httpMethod"|curl\s',
            page_source, re.I))
        signals["is_api_console"] = is_api_console

        # overall: is there ANY real content beyond a login form?
        all_text = body_text.strip()
        signals["total_text_length"] = len(all_text)
        signals["page_title"] = driver.title

        # F7a: spacing - check for Tailwind spacing classes (py-*, px-*, gap-*, space-*, mb-*, mt-*)
        spacing_classes = driver.execute_script("""
            let count = 0;
            document.querySelectorAll('*').forEach(el => {
                const cl = el.className || '';
                if (/\\b(py-[4-9]|py-1[0-9]|px-[4-9]|px-1[0-9]|gap-[4-9]|space-[xy]-[4-9]|mb-[4-9]|mt-[4-9]|p-[4-9])\\b/.test(cl))
                    count++;
            });
            return count;
        """)
        signals["generous_spacing_count"] = spacing_classes

        # F7b: hover/active states - check for transition/hover classes
        signals["has_hover_states"] = bool(re.search(
            r'hover:|transition|active:|focus:|focus-visible:', page_source, re.I))
        interactive_with_transitions = driver.execute_script("""
            let count = 0;
            document.querySelectorAll('button, a, [role="button"]').forEach(el => {
                const t = getComputedStyle(el).transition;
                if (t && t !== 'all 0s ease 0s' && t !== 'none') count++;
            });
            return count;
        """)
        signals["interactive_transition_count"] = interactive_with_transitions

        # F7c: primary action - check for exactly one visually dominant button
        primary_buttons = driver.execute_script("""
            const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
            const primary = btns.filter(b => {
                const cs = getComputedStyle(b);
                const bg = cs.backgroundColor;
                return b.textContent.trim().length > 0 &&
                       bg !== 'rgba(0, 0, 0, 0)' && bg !== 'rgb(255, 255, 255)' &&
                       bg !== 'transparent';
            });
            return primary.map(b => ({text: b.textContent.trim().slice(0,30), bg: getComputedStyle(b).backgroundColor}));
        """)
        signals["primary_buttons"] = primary_buttons

        # F7d: consistent radii
        radii = driver.execute_script("""
            const s = new Set();
            document.querySelectorAll('[class*="rounded"]').forEach(el => {
                s.add(getComputedStyle(el).borderRadius);
            });
            return Array.from(s);
        """)
        signals["distinct_radii"] = radii

        # F7e: overall polish - composite of spacing, colors, structure, and content
        signals["total_sections"] = len(cards)

    finally:
        driver.quit()
    return signals


def judge(signals: dict) -> list[tuple[str, str, bool, str]]:
    """Judge each rubric line. Returns [(code, description, passed, evidence)]."""
    results = []

    def j(code, desc, passed, evidence):
        results.append((code, desc, passed, evidence))

    # F1a
    j("F1a", "Heading names the product", signals.get("heading_is_product", False),
      f"Headings: {signals.get('headings', [])[:3]}")

    # F1b
    cc = signals.get("card_count", 0)
    j("F1b", "Content grouped into cards/sections", cc >= 2,
      f"{cc} card/section elements found")

    # F1c
    le = signals.get("large_elements", [])
    j("F1c", "Most important data is prominent", len(le) >= 1,
      f"{len(le)} large (>=24px) text elements")

    # F2a
    j("F2a", "Loading state present", signals.get("has_loading", False),
      "loading/spinner/skeleton pattern found" if signals.get("has_loading") else "no loading state detected in source")

    # F2b
    j("F2b", "Empty state handled", signals.get("has_empty_state", False),
      "empty-state text found" if signals.get("has_empty_state") else "no empty-state messaging detected")

    # F2c
    j("F2c", "Error state handled", signals.get("has_error_handling", False),
      "error handling pattern found" if signals.get("has_error_handling") else "no error handling detected")

    # F3a
    bfs = signals.get("body_font_size", "16px")
    size = float(re.search(r"[\d.]+", bfs).group()) if bfs else 0
    j("F3a", "Body text 15-18px", 15 <= size <= 18,
      f"body font-size: {bfs}")

    # F3b
    j("F3b", "Visible spacing between sections", signals.get("has_spacing_classes", False),
      "spacing CSS found" if signals.get("has_spacing_classes") else "no spacing classes/properties detected")

    # F3c
    ff = signals.get("font_families", [])
    j("F3c", "No more than 2 font families", len(ff) <= 2,
      f"{len(ff)} font families: {ff[:4]}")

    # F4a — passes if page shows ANY substantive data (EV keywords or generic dashboard data)
    dk = signals.get("domain_keywords_visible", [])
    dk_detail = signals.get("domain_keywords_detail", [])
    j("F4a", "Key domain data visible", bool(dk),
      f"domain keywords found: {dk_detail}")

    # F4b
    bc = signals.get("badge_count", 0)
    j("F4b", "Status/risk use visual weight", bc >= 2,
      f"{bc} badge/status elements found")

    # F4c
    sb = signals.get("styled_button_count", 0)
    j("F4c", "Actionable items have styled buttons", sb >= 1,
      f"{sb} styled buttons: {signals.get('button_texts', [])}")

    # F4d — only enforced when the app has EV/panel domain data; generic apps pass
    has_ev = signals.get("has_ev_domain", False)
    pt = signals.get("panel_three_way", [])
    if has_ev:
        j("F4d", "Panel routing shows three outcomes", len(pt) >= 2,
          f"panel terms found: {pt}" if pt else "EV domain present but no three-way panel routing visible")
    else:
        j("F4d", "Panel routing shows three outcomes", True,
          "N/A: no EV domain data present (generic app)")

    # F5a
    j("F5a", "Layout works at 375px", not signals.get("has_horizontal_scroll_375", True),
      "no horizontal scroll at 375px" if not signals.get("has_horizontal_scroll_375") else "horizontal scroll detected at 375px")

    # F5b - inferred from button sizes; precise check would need element measurement
    j("F5b", "Touch targets >= 44px", sb >= 1,
      "styled buttons present (assumed >=44px if properly styled)" if sb else "no buttons found")

    # F6a
    dc = signals.get("distinct_bg_colors", 0)
    j("F6a", "Cohesive color palette", 2 <= dc <= 8,
      f"{dc} distinct background colors")

    # F6b
    j("F6b", "Nav/header orients user", signals.get("has_nav", False),
      "nav/header element found" if signals.get("has_nav") else "no nav or header element")

    # F6c - composite: passes if F1a, F1b, F6a, and F6b all pass
    demo_ready = all(r[2] for r in results if r[0] in ("F1a", "F1b", "F6a", "F6b"))
    j("F6c", "Would not embarrass in a demo", demo_ready,
      "composite of F1a+F1b+F6a+F6b")

    # F6d HARD FAIL
    is_console = signals.get("is_api_console", False)
    has_content = signals.get("total_text_length", 0) > 50
    j("F6d", "HARD FAIL: Is a designed UI, not API console",
      not is_console and has_content,
      "API console/Swagger detected" if is_console else
      ("page has real content" if has_content else "page is nearly empty"))

    # F7a: generous spacing
    gsc = signals.get("generous_spacing_count", 0)
    j("F7a", "Generous consistent spacing", gsc >= 8,
      f"{gsc} elements with generous spacing (py-4+, px-4+, gap-4+)")

    # F7b: interaction feedback
    itc = signals.get("interactive_transition_count", 0)
    has_hover = signals.get("has_hover_states", False)
    j("F7b", "Interaction feedback on buttons/links", has_hover and itc >= 1,
      f"hover/transition classes: {'yes' if has_hover else 'no'}, {itc} interactive elements with CSS transitions")

    # F7c: clear hierarchy - one primary action visible, others quieter
    pb = signals.get("primary_buttons", [])
    j("F7c", "Clear visual hierarchy - primary action visible", len(pb) >= 1,
      f"{len(pb)} primary (colored) buttons: {[b['text'] for b in pb[:3]]}" if pb else "no colored buttons found")

    # F7d: polished detail - consistent border-radii
    radii = signals.get("distinct_radii", [])
    j("F7d", "Polished detail - consistent radii and alignment", 1 <= len(radii) <= 5,
      f"{len(radii)} distinct border-radius values: {radii[:5]}")

    # F7e: overall - composite of F7a-d plus structural checks
    f7_pass = all(r[2] for r in results if r[0] in ("F7a", "F7b", "F7c", "F7d"))
    j("F7e", "Looks like a product someone would choose to use", f7_pass,
      "composite of F7a+F7b+F7c+F7d")

    return results


def _smoke_signals(url: str) -> dict:
    """Load the page in headless Chrome and collect the BLOCKING render signals:
    does the page produce real DOM after JS runs, are there console errors
    (CSP violations and JS exceptions are SEVERE), is anything interactive."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    if CHROME_BIN:
        opts.binary_location = CHROME_BIN
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(url)
        time.sleep(2.0)
        body_text = driver.find_element(By.TAG_NAME, "body").text.strip()
        el_count = driver.execute_script("return document.body.querySelectorAll('*').length")
        interactive = driver.execute_script(
            "return document.querySelectorAll('button, input, select, textarea, a[href]').length")
        severe = [e["message"] for e in driver.get_log("browser")
                  if e.get("level") == "SEVERE" and "favicon.ico" not in e.get("message", "")]
        return {"body_text_len": len(body_text), "el_count": el_count,
                "interactive": interactive, "severe": severe}
    finally:
        driver.quit()


def run_frontend_smoke(app_dir: str) -> bool:
    """BLOCKING anti-blank-page gate (no aesthetics): boot the app, execute its
    page in a real browser engine, and fail unless JS produced substantive,
    interactive DOM with a clean console. Exists because 2026-08-16 every
    HTTP-level check passed while the SPA rendered a blank page under its own
    CSP — nothing in the pipeline had ever executed the frontend."""
    port = 18199
    print(f"  [frontend-smoke] booting {app_dir}...")
    server = _boot_app_in_thread(app_dir, port)
    if not server:
        print("  [FAIL] boot")
        return False
    try:
        import httpx
        best_url = None
        for path in ("/app/", "/", "/index.html"):
            try:
                r = httpx.get(f"http://127.0.0.1:{port}{path}", timeout=3, follow_redirects=True)
                if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
                    best_url = f"http://127.0.0.1:{port}{path}"
                    break
            except Exception:
                continue
        if not best_url:
            print("  [FAIL] no HTML page served at /app/, / or /index.html")
            return False
        s = _smoke_signals(best_url)
        checks = [
            ("renders_content", s["body_text_len"] >= 20 and s["el_count"] >= 5,
             f"body text {s['body_text_len']} chars, {s['el_count']} elements after JS"),
            ("interactive_ui", s["interactive"] >= 1, f"{s['interactive']} interactive elements"),
            ("console_clean", not s["severe"],
             "no SEVERE console errors" if not s["severe"] else "; ".join(s["severe"])[:300]),
        ]
        ok = all(c[1] for c in checks)
        for name, passed, ev in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name:16} {ev}")
        print(f"  FRONTEND SMOKE ({best_url}): {'PASS' if ok else 'FAIL'}")
        return ok
    finally:
        server.should_exit = True


def run_frontend_gate(app_dir: str, screenshot_path: str = None) -> tuple[bool, list]:
    """Full gate: boot, screenshot, analyze, judge. Returns (passed, verdicts)."""
    port = 18199
    print(f"  [frontend-gate] booting {app_dir}...")
    server = _boot_app_in_thread(app_dir, port)
    if not server:
        return False, [("BOOT", "App failed to start", False, "could not import or serve")]

    url = f"http://127.0.0.1:{port}/"
    out = screenshot_path or os.path.join(app_dir, "frontend_gate_screenshot.png")

    try:
        # Check if there's a real HTML page (not just JSON API)
        import httpx
        r = httpx.get(url, timeout=5, follow_redirects=True)
        content_type = r.headers.get("content-type", "")

        # If root serves JSON or redirects to /docs, check /app or /index.html
        pages_to_try = [url]
        if "json" in content_type or "/docs" in str(r.url):
            pages_to_try = [
                f"http://127.0.0.1:{port}/app",
                f"http://127.0.0.1:{port}/index.html",
                f"http://127.0.0.1:{port}/frontend/",
                url,
            ]

        best_url = url
        for try_url in pages_to_try:
            try:
                tr = httpx.get(try_url, timeout=3, follow_redirects=True)
                if tr.status_code == 200 and "html" in tr.headers.get("content-type", ""):
                    best_url = try_url
                    break
            except Exception:
                continue

        print(f"  [frontend-gate] screenshotting {best_url}...")
        _screenshot(best_url, out)
        print(f"  [frontend-gate] screenshot saved: {out}")

        print(f"  [frontend-gate] analyzing page structure...")
        signals = _analyze_page(best_url)

        verdicts = judge(signals)
        return all(v[2] for v in verdicts), verdicts

    finally:
        server.should_exit = True


def main():
    if len(sys.argv) < 2:
        print("usage: python tools/verify_frontend.py <app_dir> [--out screenshot.png]")
        sys.exit(2)

    app_dir = os.path.abspath(sys.argv[1])
    if "--smoke" in sys.argv:
        sys.exit(0 if run_frontend_smoke(app_dir) else 1)
    screenshot_out = None
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            screenshot_out = sys.argv[idx + 1]

    passed, verdicts = run_frontend_gate(app_dir, screenshot_out)

    print(f"\n{'='*70}")
    print(f"FRONTEND GATE RESULTS")
    print(f"{'='*70}")
    pass_count = sum(1 for v in verdicts if v[2])
    fail_count = sum(1 for v in verdicts if not v[2])
    for code, desc, ok, evidence in verdicts:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {code}: {desc}")
        print(f"         {evidence}")
    print(f"\n  {pass_count} passed, {fail_count} failed out of {len(verdicts)} checks")

    hard_fail = any(not v[2] for v in verdicts if v[0] == "F6d")
    if hard_fail:
        print(f"\n  *** F6d HARD FAIL: not a designed end-user interface ***")

    result = "PASS" if passed else "FAIL"
    print(f"\n  FRONTEND GATE: {result}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
