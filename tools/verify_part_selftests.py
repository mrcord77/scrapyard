#!/usr/bin/env python3
"""Run every catalog module's offline self-test in an isolated process.

The catalog verifier proves importability and structural completeness. This tool
provides the separate behavioral signal promised by the public README. Isolation
prevents one module's globals, environment changes, or SQLAlchemy metadata from
masking failures in another module.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scrapyard"


def discover_modules() -> list[str]:
    modules: list[str] = []
    for path in sorted(PACKAGE.glob("*/*.py")):
        if path.name == "__init__.py":
            continue
        modules.append(".".join(path.relative_to(ROOT).with_suffix("").parts))
    return modules


def run_one(module: str, timeout: float) -> dict:
    env = os.environ.copy()
    env["APP_ENV"] = "development"
    env["ENVIRONMENT"] = "development"
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-m", module],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        status = "passed" if result.returncode == 0 else "failed"
        return {
            "module": module,
            "status": status,
            "returncode": result.returncode,
            "duration_s": round(time.monotonic() - started, 3),
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "module": module,
            "status": "timed_out",
            "returncode": None,
            "duration_s": round(time.monotonic() - started, 3),
            "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--module", action="append", dest="modules")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)

    modules = args.modules or discover_modules()
    if args.jobs < 1 or args.timeout <= 0:
        parser.error("--jobs and --timeout must be positive")

    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_one, module, args.timeout): module for module in modules}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            if result["status"] != "passed":
                print(f"{result['status'].upper():9} {result['module']}")

    results.sort(key=lambda item: item["module"])
    totals = {
        "modules": len(results),
        "passed": sum(r["status"] == "passed" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "timed_out": sum(r["status"] == "timed_out" for r in results),
    }
    report = {"schema": "scrapyard/part-selftests@1", "totals": totals, "results": results}
    if args.json_path:
        output = Path(args.json_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        "part self-tests: "
        f"{totals['passed']}/{totals['modules']} passed; "
        f"{totals['failed']} failed; {totals['timed_out']} timed out"
    )
    if totals["failed"] or totals["timed_out"]:
        for result in results:
            if result["status"] == "passed":
                continue
            detail = (result["stderr"] or result["stdout"]).strip()
            if detail:
                print(f"\n--- {result['module']} ---\n{detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
