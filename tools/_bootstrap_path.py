"""
_bootstrap_path — put the repo root (and tools dir) on sys.path so the tools work
from any shell without the caller having to export PYTHONPATH.

When you run `python tools/<tool>.py`, the script's own directory (tools/) is sys.path[0],
so this module is importable; importing it (as the FIRST import in each entry tool)
makes `import scrapyard` and `import <sibling_tool>` resolve regardless of cwd. Also
provides subprocess_env() so child Python processes inherit the same import roots.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
for _p in (TOOLS, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def subprocess_env(extra: dict | None = None, *, pythonpath_roots=None) -> dict:
    """An environment dict for child Python processes that includes the repo root on
    PYTHONPATH (so they can import scrapyard / tools), preserving any existing value.
    Pass pythonpath_roots to override the roots (e.g. a generated app dir for isolation)."""
    env = dict(os.environ)
    roots = list(pythonpath_roots) if pythonpath_roots is not None else [ROOT, TOOLS]
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in roots if p]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env
