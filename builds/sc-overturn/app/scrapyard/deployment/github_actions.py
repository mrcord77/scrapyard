"""
github_actions — CI: lint/test/build/deploy workflow.

### PART-META-JSON
{
  "name": "github_actions",
  "layer": "deployment",
  "purpose": "CI: lint/test/build/deploy workflow.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ci_workflow(*, python).",
  "outputs": "Returns: ci_workflow -> str.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `ci_workflow` from `scrapyard.deployment.github_actions` and call it as shown in `example`; run `py -m scrapyard.deployment.github_actions` to see its offline selftest.",
  "example": "from scrapyard.deployment.github_actions import ci_workflow",
  "import_path": "scrapyard.deployment.github_actions"
}
### END-PART-META
"""
from __future__ import annotations

from typing import List, Optional, Sequence

STATUS = "core"

_NL = chr(10)


def ci_workflow(*, python: str | Sequence[str] = ("3.11", "3.12"),
                name: str = "CI",
                branches: Sequence[str] = ("main",),
                install: str = "pip install -r requirements-dev.txt",
                test_cmd: str = "python tools/verify_build.py basic_saas",
                lint_cmd: Optional[str] = "python -m ruff check .",
                os_runner: str = "ubuntu-latest") -> str:
    """Generate a real GitHub Actions CI workflow: a Python version matrix, pip
    dependency caching (via setup-python's built-in cache), an optional lint
    step, and the test command, triggered on push and PRs to the given branches.

    `python` may be a single version or a list -> a build matrix. Returns YAML.
    """
    versions: List[str] = [python] if isinstance(python, str) else list(python)
    br = "[" + ", ".join(branches) + "]"
    steps = [
        "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5",
        "        with:",
        '          python-version: "${{ matrix.python-version }}"',
        '          cache: "pip"',
        f"      - run: {install}",
    ]
    if lint_cmd:
        steps.append(f"      - run: {lint_cmd}")
    steps.append(f"      - run: {test_cmd}")

    lines = [
        f"name: {name}",
        "on:",
        f"  push: {{ branches: {br} }}",
        f"  pull_request: {{ branches: {br} }}",
        "jobs:",
        "  test:",
        f"    runs-on: {os_runner}",
        "    strategy:",
        "      fail-fast: false",
        "      matrix:",
        "        python-version: [" + ", ".join(f'"{v}"' for v in versions) + "]",
        "    steps:",
        *steps,
    ]
    return _NL.join(lines) + _NL


def _selftest() -> None:
    import yaml
    wf = ci_workflow(python=["3.11", "3.12"], branches=("main", "dev"))
    doc = yaml.safe_load(wf)  # must be valid YAML
    assert doc["name"] == "CI"
    job = doc["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-latest"
    # matrix over BOTH requested versions
    assert job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    steps = job["steps"]
    # pip caching is wired through setup-python
    sp = next(s for s in steps if "setup-python" in str(s.get("uses", "")))
    assert sp["with"]["cache"] == "pip"
    assert "${{ matrix.python-version }}" in str(sp["with"]["python-version"])
    # trigger branches propagate to push AND pull_request
    assert doc[True]["push"]["branches"] == ["main", "dev"]        # YAML 'on' -> True
    assert doc[True]["pull_request"]["branches"] == ["main", "dev"]
    # lint step present by default, and the test command is included
    runs = [s.get("run", "") for s in steps]
    assert any("ruff check" in r for r in runs)
    assert any("verify_build" in r for r in runs)
    # a single version string still yields a valid one-entry matrix
    solo = yaml.safe_load(ci_workflow(python="3.12"))
    assert solo["jobs"]["test"]["strategy"]["matrix"]["python-version"] == ["3.12"]
    # lint can be disabled
    nolint = [s.get("run", "") for s in
              yaml.safe_load(ci_workflow(lint_cmd=None))["jobs"]["test"]["steps"]]
    assert not any("ruff" in r for r in nolint)
    print("github_actions selftest OK")


if __name__ == "__main__":
    _selftest()
