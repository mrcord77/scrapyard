#!/usr/bin/env python3
"""
verify_marketing.py — the marketing gate.

Boots a generated app, checks for a landing/marketing page, and judges its copy
against the marketing-standard.md rubric. A build with no marketable face, or one
that leads with "AI", makes ungrounded claims, has no CTA, or contains fabricated
social proof, FAILS with the same weight as a backend or frontend failure.

    python tools/verify_marketing.py <app_dir>

Returns exit 0 if the rubric passes, exit 1 with a line-by-line verdict if not.
"""
from __future__ import annotations
import importlib
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

RUBRIC = [
    ("M1a", "Landing page exists at a public-facing route"),
    ("M1b", "Headline names the OUTCOME, not the mechanism (never AI)"),
    ("M1c", "Hook + pitch readable in under 10 seconds"),
    ("M1d", "Clear call to action exists and is visually prominent"),
    ("M2a", "Buyer named in copy matches Phase 1 research"),
    ("M2b", "Pain named in copy matches Phase 1 research"),
    ("M2c", "Differentiator matches Phase 1 research gap"),
    ("M2d", "No ungrounded claims"),
    ("M3a", "Pricing section exists"),
    ("M3b", "What the buyer GETS is explicit"),
    ("M3c", "Why it's worth it vs. alternatives is stated"),
    ("M4a", "Alternatives named or clearly implied"),
    ("M4b", "Differentiator framed as buyer benefit not tech feature"),
    ("M5a", "No AI in marketing copy"),
    ("M5b", "No unverifiable superlatives"),
    ("M5c", "Would not embarrass if competitor read it"),
    ("M5d", "HARD FAIL: No fabricated social proof"),
]

LANDING_PATHS = ["/landing", "/pricing", "/marketing", "/sell", "/for-installers",
                 "/about", "/why", "/get-started"]


def _boot_app(app_dir, port=18250):
    sys.path.insert(0, app_dir)
    os.chdir(app_dir)
    os.environ["APP_ENV"] = "development"
    try:
        if "main" in sys.modules:
            del sys.modules["main"]
        mod = importlib.import_module("main")
        app = mod.app
    except Exception as e:
        print(f"  [marketing-gate] could not import app: {e}")
        return None
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(40):
        try:
            import httpx
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return server
        except Exception:
            pass
        time.sleep(0.25)
    return None


def _find_landing_page(port):
    """Find the marketing/landing page by trying known paths."""
    import httpx
    base = f"http://127.0.0.1:{port}"
    for path in LANDING_PATHS:
        try:
            r = httpx.get(f"{base}{path}", timeout=3, follow_redirects=True)
            if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
                return path, r.text
        except Exception:
            continue
    return None, None


def _analyze_marketing(html, body_text):
    """Extract signals from the landing page for rubric judging."""
    signals = {}

    # M1a: page exists (caller already confirmed)
    signals["page_exists"] = html is not None

    if not html:
        return signals

    # M1b: headline names outcome, not AI
    ai_terms = re.findall(r'\b(AI[- ]powered|artificial intelligence|smart system|machine learning|neural|GPT|LLM)\b',
                          body_text, re.I)
    signals["ai_terms_found"] = ai_terms
    outcome_terms = re.findall(r'(pre-qualified|panel.risk|lead|install|charger|estimate|quote|electrician|installer)',
                               body_text, re.I)
    signals["outcome_terms"] = outcome_terms

    # M1c: hook + pitch length
    signals["text_length"] = len(body_text.strip())

    # M1d: CTA
    cta_patterns = re.findall(r'(request|book|start|contact|get started|sign up|try|schedule|call|demo|learn more)',
                              body_text, re.I)
    signals["cta_terms"] = cta_patterns
    has_cta_element = bool(re.search(
        r'<(button|a)[^>]*class="[^"]*\b(bg-|btn|cta|primary)[^"]*"[^>]*>',
        html, re.I))
    signals["has_cta_element"] = has_cta_element

    # M2a: buyer named
    buyer_terms = re.findall(r'(installer|electrician|contractor|licensed)', body_text, re.I)
    signals["buyer_terms"] = buyer_terms

    # M2b: pain named
    pain_terms = re.findall(r'(frustrat|wasted|site visit|surprise|unqualified|panel upgrade|waste)',
                            body_text, re.I)
    signals["pain_terms"] = pain_terms

    # M2c: differentiator
    diff_terms = re.findall(r'(load.management|three.way|panel.risk|EVEMS|625\.42|scored|pre.qualified|safety)',
                            body_text, re.I)
    signals["diff_terms"] = diff_terms

    # M2d: ungrounded claims (superlatives without citation)
    ungrounded = re.findall(r'\b(best|fastest|most accurate|#1|number one|industry.leading)\b',
                            body_text, re.I)
    signals["ungrounded_claims"] = ungrounded

    # M3a: pricing
    pricing_terms = re.findall(r'(\$\d|pricing|price|cost|per lead|per month|subscription|free trial|plan)',
                               body_text, re.I)
    signals["pricing_terms"] = pricing_terms

    # M3b: what buyer gets
    gets_terms = re.findall(r'(you get|includes|each lead|per lead|scored|draft reply|panel risk|estimate range)',
                            body_text, re.I)
    signals["gets_terms"] = gets_terms

    # M3c: vs alternatives
    vs_terms = re.findall(r'(vs\.?|compared to|instead of|unlike|Angi|Qmerit|Treehouse|Thumbtack|per click)',
                          body_text, re.I)
    signals["vs_terms"] = vs_terms

    # M4a: alternatives named
    competitor_terms = re.findall(r'(Angi|Qmerit|Treehouse|Thumbtack|HomeAdvisor|marketplace|lead gen)',
                                 body_text, re.I)
    signals["competitor_terms"] = competitor_terms

    # M5a: no AI
    signals["has_ai_marketing"] = len(ai_terms) > 0

    # M5d: fabricated social proof
    fake_proof = re.findall(
        r'(trusted by \d|join \d|\d+ installer|\d+ customer|\d+ electrician|★|star rating|testimonial|"[^"]{20,}"[^<]*—\s*[A-Z])',
        body_text, re.I)
    # Also check for lorem/placeholder text
    lorem = re.findall(r'(lorem ipsum|placeholder|sample testimonial|fake review)', body_text, re.I)
    signals["fake_proof"] = fake_proof + lorem

    return signals


def judge(signals):
    results = []
    def j(code, desc, passed, evidence):
        results.append((code, desc, passed, evidence))

    exists = signals.get("page_exists", False)
    j("M1a", "Landing page exists", exists,
      "landing page found" if exists else "no landing/marketing page at any known route")

    if not exists:
        for code, desc in RUBRIC[1:]:
            j(code, desc, False, "no landing page to evaluate")
        return results

    # M1b
    ai = signals.get("ai_terms_found", [])
    outcome = signals.get("outcome_terms", [])
    j("M1b", "Headline names outcome not AI", len(ai) == 0 and len(outcome) >= 2,
      f"AI terms: {ai}, outcome terms: {outcome[:5]}")

    # M1c
    tl = signals.get("text_length", 0)
    j("M1c", "Hook + pitch present", tl >= 100,
      f"page text length: {tl} chars")

    # M1d
    cta = signals.get("cta_terms", [])
    has_el = signals.get("has_cta_element", False)
    j("M1d", "Clear CTA exists", len(cta) >= 1 and has_el,
      f"CTA terms: {cta[:3]}, styled CTA element: {has_el}")

    # M2a
    buyers = signals.get("buyer_terms", [])
    j("M2a", "Buyer matches research", len(buyers) >= 1,
      f"buyer terms: {buyers[:3]}")

    # M2b
    pains = signals.get("pain_terms", [])
    j("M2b", "Pain matches research", len(pains) >= 1,
      f"pain terms: {pains[:3]}")

    # M2c
    diffs = signals.get("diff_terms", [])
    j("M2c", "Differentiator matches research", len(diffs) >= 2,
      f"differentiator terms: {diffs[:4]}")

    # M2d
    ungrounded = signals.get("ungrounded_claims", [])
    j("M2d", "No ungrounded claims", len(ungrounded) == 0,
      f"ungrounded superlatives: {ungrounded}" if ungrounded else "no ungrounded claims found")

    # M3a
    pricing = signals.get("pricing_terms", [])
    j("M3a", "Pricing section exists", len(pricing) >= 1,
      f"pricing terms: {pricing[:3]}")

    # M3b
    gets = signals.get("gets_terms", [])
    j("M3b", "What buyer gets is explicit", len(gets) >= 2,
      f"value terms: {gets[:4]}")

    # M3c
    vs = signals.get("vs_terms", [])
    j("M3c", "Worth it vs alternatives stated", len(vs) >= 1,
      f"comparison terms: {vs[:3]}")

    # M4a
    comps = signals.get("competitor_terms", [])
    j("M4a", "Alternatives named", len(comps) >= 1,
      f"competitor terms: {comps[:3]}")

    # M4b (composite — differentiator framed as benefit)
    has_diff = len(diffs) >= 2
    has_buyer_benefit = any(t in signals.get("gets_terms", []) for t in ["scored", "pre-qualified", "panel risk", "draft reply"]) or len(gets) >= 2
    j("M4b", "Differentiator as buyer benefit", has_diff and has_buyer_benefit,
      "differentiator + value terms both present" if has_diff and has_buyer_benefit else "missing differentiation or value framing")

    # M5a
    j("M5a", "No AI in marketing copy", not signals.get("has_ai_marketing", True),
      f"AI terms: {ai}" if ai else "no AI terms found")

    # M5b
    j("M5b", "No unverifiable superlatives", len(ungrounded) == 0,
      f"superlatives: {ungrounded}" if ungrounded else "none found")

    # M5c (composite of M1b, M2d, M5a, M5b)
    not_embarrassing = all(r[2] for r in results if r[0] in ("M1b", "M2d", "M5a", "M5b"))
    j("M5c", "Would not embarrass if competitor read it", not_embarrassing,
      "composite of M1b+M2d+M5a+M5b")

    # M5d HARD FAIL
    fake = signals.get("fake_proof", [])
    j("M5d", "HARD FAIL: No fabricated social proof", len(fake) == 0,
      f"fabricated proof found: {fake}" if fake else "no fabricated social proof detected")

    return results


def run_marketing_gate(app_dir):
    port = 18250
    print(f"  [marketing-gate] booting {app_dir}...")
    server = _boot_app(app_dir, port)
    if not server:
        return False, [("BOOT", "App failed to start", False, "could not import or serve")]

    try:
        path, html = _find_landing_page(port)
        if html:
            print(f"  [marketing-gate] found landing page at {path}")
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--window-size=1280,900")
            chrome_bin = os.environ.get("CHROME_BIN",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe" if os.name == "nt" else "/usr/bin/google-chrome")
            if os.path.exists(chrome_bin):
                opts.binary_location = chrome_bin
            driver = webdriver.Chrome(options=opts)
            driver.get(f"http://127.0.0.1:{port}{path}")
            time.sleep(1.5)
            body_text = driver.find_element(By.TAG_NAME, "body").text
            html = driver.page_source
            driver.quit()
        else:
            print(f"  [marketing-gate] no landing page found")
            body_text = ""

        signals = _analyze_marketing(html, body_text)
        verdicts = judge(signals)
        return all(v[2] for v in verdicts), verdicts
    finally:
        server.should_exit = True


def main():
    if len(sys.argv) < 2:
        print("usage: python tools/verify_marketing.py <app_dir>")
        sys.exit(2)

    app_dir = os.path.abspath(sys.argv[1])
    passed, verdicts = run_marketing_gate(app_dir)

    print(f"\n{'='*60}")
    print("MARKETING GATE RESULTS")
    print(f"{'='*60}")
    pass_count = sum(1 for v in verdicts if v[2])
    fail_count = sum(1 for v in verdicts if not v[2])
    for code, desc, ok, evidence in verdicts:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {code}: {desc}")
        print(f"         {evidence}")
    print(f"\n  {pass_count} passed, {fail_count} failed out of {len(verdicts)} checks")

    hard_fail = any(not v[2] and "fabricated" in v[3] for v in verdicts if v[0] == "M5d")
    if hard_fail:
        print(f"\n  *** M5d HARD FAIL: fabricated social proof detected ***")

    result = "PASS" if passed else "FAIL"
    print(f"\n  MARKETING GATE: {result}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
