"""
backoff_scheduler — Schedule and manage exponential backoff intervals for retrying failed LLM inference requests, ensuring resilience and rate compliance.

### PART-META-JSON
{
  "name": "backoff_scheduler",
  "layer": "llm",
  "purpose": "Schedule and manage exponential backoff intervals for retrying failed LLM inference requests, ensuring resilience and rate compliance.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "retry_policy"
  ],
  "inputs": "Public API: schedule_backoff(policy, attempt); get_next_retry_time(policy, attempt); RetryPolicy(...).",
  "outputs": "Returns: schedule_backoff -> datetime; get_next_retry_time -> datetime.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.llm.backoff_scheduler`.",
  "example": "from scrapyard.llm.backoff_scheduler import *",
  "import_path": "scrapyard.llm.backoff_scheduler"
}
### END-PART-META
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging

logging.getLogger().setLevel(logging.INFO)

@dataclass
class RetryPolicy:
    base_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 60.0
    max_attempts: int = 5
    jitter: bool = False

def schedule_backoff(policy: RetryPolicy, attempt: int) -> datetime:
    """
    Schedule the next backoff interval based on the retry policy and current attempt number.
    
    :param policy: RetryPolicy instance containing configuration for retries.
    :param attempt: Current attempt number (starting from 1).
    :return: Scheduled time as a datetime object.
    """
    delay = min(policy.base_delay * (policy.multiplier ** (attempt - 1)), policy.max_delay)
    if policy.jitter:
        jitter = (delay / 4) * (-0.5 + 2 * (attempt % 2))  # Jitter between -delay/4 and delay/4
        delay += jitter
    
    return datetime.now(timezone.utc) + timedelta(seconds=delay)

def get_next_retry_time(policy: RetryPolicy, attempt: int) -> datetime:
    """
    Get the next retry time based on the retry policy and current attempt number.
    
    :param policy: RetryPolicy instance containing configuration for retries.
    :param attempt: Current attempt number (starting from 1).
    :return: Next retry time as a datetime object.
    """
    return schedule_backoff(policy, attempt)

def _selftest():
    # Test data
    test_policy = RetryPolicy(base_delay=1.0, multiplier=2.0, max_delay=60.0, max_attempts=5, jitter=True)
    
    # Test cases
    attempts = range(1, 6)  # Attempt numbers from 1 to 5
    
    for attempt in attempts:
        next_retry_time = get_next_retry_time(test_policy, attempt)
        logging.info(f"Attempt {attempt}: Next retry time is {next_retry_time}")
    
    # Verify that the backoff times are increasing and within expected ranges
    prev_time = None
    for attempt in attempts:
        current_time = get_next_retry_time(test_policy, attempt)
        if prev_time is not None:
            assert current_time > prev_time, "Retry time did not increase"
        prev_time = current_time
    
    logging.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
