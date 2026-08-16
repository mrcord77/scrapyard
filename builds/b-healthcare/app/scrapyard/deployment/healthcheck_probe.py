"""
healthcheck_probe — Container/orchestrator probe script.

### PART-META-JSON
{
  "name": "healthcheck_probe",
  "layer": "deployment",
  "purpose": "Container/orchestrator probe script.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: check(url, *, timeout); validate_url(url); check_with_retry(url, *, timeout, max_retries, backoff); check_with_logging(url, *, logger, log_level); check_with_timeout_policy(url, *, env); CheckResult(...) (plus more).",
  "outputs": "Returns: check -> dict; validate_url -> None; check_with_retry -> Dict[str, Any]; check_with_logging -> Dict[str, Any]; check_with_timeout_policy -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Makes outbound network calls; set timeouts, validate URLs/hosts, and never send secrets to untrusted endpoints.",
  "ai_usage": "Import `check` from `scrapyard.deployment.healthcheck_probe` and call it as shown in `example`; run `py -m scrapyard.deployment.healthcheck_probe` to see its offline selftest.",
  "example": "from scrapyard.deployment.healthcheck_probe import check",
  "import_path": "scrapyard.deployment.healthcheck_probe"
}
### END-PART-META
"""
from __future__ import annotations

import time
import urllib.request
import logging
from typing import Any, Dict, List, Optional

STATUS = "core"

def check(url: str, *, timeout: float = 5.0) -> dict:
    """Hit a health endpoint and report up/down + latency. Returns down (never
    raises) so it's safe to call from a probe loop."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            ms = round((time.perf_counter() - start) * 1000, 1)
            return {"up": 200 <= r.status < 400, "status": r.status, "latency_ms": ms}
    except Exception as e:
        return {"up": False, "status": None, "error": str(e)}

class CheckResult:
    def __init__(self, up: bool, status: Optional[int], latency_ms: float, error: Optional[str]):
        self.up = up
        self.status = status
        self.latency_ms = latency_ms
        self.error = error

def validate_url(url: str) -> None:
    try:
        result = urllib.request.urlopen(url, timeout=1)
        if result.getcode() != 200:
            raise ValueError("Invalid URL")
    except Exception as e:
        raise ValueError(f"Invalid URL: {e}")

async def check_with_retry(
    url: str,
    *,
    timeout: float = 5.0,
    max_retries: int = 3,
    backoff: float = 1.0
) -> Dict[str, Any]:
    for attempt in range(max_retries + 1):
        try:
            result = check(url, timeout=timeout)
            return {"up": result["up"], "status": result["status"], "latency_ms": result["latency_ms"]}
        except Exception as e:
            if attempt < max_retries:
                time.sleep(backoff ** (attempt + 1))
    raise Exception("Service Unavailable")

def check_with_logging(
    url: str,
    *,
    logger: logging.Logger,
    log_level: str = "INFO"
) -> Dict[str, Any]:
    result = check(url)
    logger.log(getattr(logging, log_level.upper()), f"Healthcheck result: {result}")
    return result

def check_with_timeout_policy(
    url: str,
    *,
    env: str = "prod"
) -> Dict[str, Any]:
    timeout_map = {
        "dev": 2.0,
        "staging": 3.0,
        "prod": 5.0
    }
    return check(url, timeout=timeout_map.get(env, 5.0))

def check_with_custom_headers(
    url: str,
    headers: Dict[str, str],
    *,
    timeout: float = 5.0
) -> Dict[str, Any]:
    result = check(url, timeout=timeout)
    return result

def check_with_circuit_breaker(
    url: str,
    *,
    max_failures: int = 5,
    reset_timeout: float = 60.0
) -> Dict[str, Any]:
    class CircuitBreaker:
        def __init__(self, max_failures: int, reset_timeout: float):
            self.max_failures = max_failures
            self.reset_timeout = reset_timeout
            self.failures = 0
            self.last_failure_time = 0

        def is_open(self):
            return self.failures >= self.max_failures

        def update_status(self, up: bool):
            if not up:
                self.failures += 1
                self.last_failure_time = time.time()
            else:
                self.failures = 0

    breaker = CircuitBreaker(max_failures=max_failures, reset_timeout=reset_timeout)
    if not breaker.is_open():
        result = check(url)
        breaker.update_status(result["up"])
    else:
        return {"up": False, "error": "Circuit Breaker Open"}
    return result

def check_with_audit(
    url: str,
    *,
    event_type: str = "healthcheck",
    audit_logger: logging.Logger
) -> Dict[str, Any]:
    result = check(url)
    audit_logger.info(f"Audit Event: {event_type}, Result: {result}")
    return result

def check_with_bulk_health(
    urls: List[str],
    *,
    timeout: float = 5.0,
    max_concurrent: int = 10
) -> List[Dict[str, Any]]:
    results = []
    for url in urls:
        try:
            result = check(url, timeout=timeout)
            results.append(result)
        except Exception as e:
            results.append({"up": False, "error": str(e)})
    return results


def _selftest() -> None:
    import threading
    import http.server

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):  # silence
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        # healthy target -> up + 200
        up = check(f"http://127.0.0.1:{port}/")
        assert up["up"] is True and up["status"] == 200
        assert isinstance(up["latency_ms"], float)
        # NEGATIVE: nothing listening on port 1 -> down, no status, error recorded
        down = check("http://127.0.0.1:1/", timeout=1.0)
        assert down["up"] is False and down["status"] is None and "error" in down
        # bulk mixes healthy + unhealthy correctly
        results = check_with_bulk_health(
            [f"http://127.0.0.1:{port}/", "http://127.0.0.1:1/"], timeout=1.0
        )
        assert results[0]["up"] is True and results[1]["up"] is False
    finally:
        srv.shutdown()
        srv.server_close()
    print("healthcheck_probe selftest OK")


if __name__ == "__main__":
    _selftest()
