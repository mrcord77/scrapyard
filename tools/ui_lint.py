"""ui_lint — the composability gate for the ui/ layer.

Guarantees that every UI component actually composes with the others and the
theme system, mechanically rather than by hope:

  1. TOKEN DISCIPLINE  — a component must not hardcode a color; it styles via
     var(--token). Raw 6-digit hex in a component source is a violation
     (#fff/#000 shorthands are tolerated).
  2. NO DANGLING VARS  — every var(--x) a component's demo() emits must resolve
     to a token variable defined by ui.theme (across all themes) or a known
     baseline-only variable. A reference to an undefined var renders broken.
  3. COMPOSITION        — every component exposes demo() -> str; all demos are
     rendered into ONE themed document and that page must be valid and contain
     every component (proof they coexist).

Foundation parts (design_tokens, theme, css_baseline) define/emit the tokens
and are exempt from the component rules.

Exit 0 = clean; nonzero = a component broke the contract.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FOUNDATION = {"design_tokens", "theme", "css_baseline", "__init__"}
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
VAR = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*\)")


def defined_vars() -> set:
    from scrapyard.ui import theme
    from scrapyard.ui.design_tokens import list_themes
    names = set()
    for th in list_themes():
        names.update(theme.var_names(th))
    return names


def component_modules():
    import scrapyard.ui as uipkg
    for m in pkgutil.iter_modules(uipkg.__path__):
        if m.name not in FOUNDATION:
            yield m.name


def main() -> int:
    violations = []
    defined = defined_vars()
    demos = {}

    for name in component_modules():
        modname = f"scrapyard.ui.{name}"
        src = (ROOT / "scrapyard" / "ui" / f"{name}.py").read_text(encoding="utf-8")

        # 1. token discipline: no raw 6-digit hex in a component
        for hx in set(HEX.findall(src)):
            if hx.lower() in ("#ffffff", "#000000"):
                continue
            violations.append(f"{name}: hardcoded color {hx} (use a var(--color-*) token)")

        try:
            mod = importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001
            violations.append(f"{name}: import failed: {type(e).__name__}: {e}")
            continue

        demo = getattr(mod, "demo", None)
        if not callable(demo):
            violations.append(f"{name}: missing demo() -> str (required for the composition gate)")
            continue
        try:
            out = demo()
        except Exception as e:  # noqa: BLE001
            violations.append(f"{name}: demo() raised {type(e).__name__}: {e}")
            continue
        if not isinstance(out, str) or not out.strip():
            violations.append(f"{name}: demo() must return non-empty HTML")
            continue
        demos[name] = out

        # 2. no dangling vars
        for v in set(VAR.findall(out)):
            if v not in defined:
                violations.append(f"{name}: references undefined token {v}")

    # 3. composition: render every demo into one themed page
    if demos:
        try:
            from scrapyard.ui.css_baseline import render_document
            page = render_document("\n".join(demos.values()), theme="bento",
                                   title="UI kit composition")
            assert page.startswith("<!doctype html>")
            assert "--color-primary:" in page
            missing = [n for n in demos if demos[n].strip() not in page]
            if missing:
                violations.append(f"composition: demos dropped from the page: {missing}")
        except Exception as e:  # noqa: BLE001
            violations.append(f"composition render failed: {type(e).__name__}: {e}")

    n = len(list(component_modules()))
    if violations:
        print(f"ui_lint: {len(violations)} violation(s) across {n} component(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"ui_lint: clean — {n} component(s), {len(demos)} demo(s) compose into one themed page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
