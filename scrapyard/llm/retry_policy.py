"""
retry_policy — ** Implement a retry strategy with exponential backoff for failed LLM inference requests. This module enables robust handling of transient failures in LLM inference workflows by providing configurable

### PART-META-JSON
{
  "name": "retry_policy",
  "layer": "llm",
  "purpose": "Implement a retry strategy with exponential backoff for failed LLM inference requests. This module enables robust handling of transient failures in LLM inference workflows by providing configurable.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: should_retry(status_code, error); calculate_backoff(attempt, base, max_backoff); main(); RetryPolicy(...).",
  "outputs": "Returns: should_retry -> bool; calculate_backoff -> float.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.llm.retry_policy`.",
  "example": "from scrapyard.llm.retry_policy import *",
  "import_path": "scrapyard.llm.retry_policy"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import Optional
import os
import sqlite3
import tempfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def should_retry(status_code: int, error: Optional[Exception]) -> bool:
    """Determine if a request should be retried based on status code and/or error.
    
    Returns True for 5xx server errors.
    Returns False for 4xx client errors and 2xx success codes.
    """
    if 500 <= status_code < 600:
        return True
    return False


def calculate_backoff(attempt: int, base: float = 1.0, max_backoff: float = 60.0) -> float:
    """Calculate backoff delay with deterministic jitter.
    
    Uses exponential backoff: base * 2^attempt, capped at max_backoff.
    Applies deterministic jitter multiplier based on attempt number for reproducible testing.
    """
    if attempt < 0:
        raise ValueError("Attempt must be non-negative")
        
    backoff = min(base * (2 ** attempt), max_backoff)
    
    # Deterministic jitter using golden ratio conjugate for good distribution
    # Produces jitter multiplier between 0.5 and 1.5
    jitter_factor = 0.5 + ((attempt * 0.618033988749895) % 1.0)
    
    return backoff * jitter_factor


@dataclass
class RetryPolicy:
    max_retries: int
    base_backoff: float
    max_backoff: float

    def get_next_delay(self, attempt: int) -> float:
        """Get the delay for the next retry attempt.
        
        Raises:
            ValueError: If attempt exceeds max_retries or is negative
        """
        if attempt < 0:
            raise ValueError("Attempt must be non-negative")
        if attempt > self.max_retries:
            raise ValueError("Exceeded maximum number of retries")
        return calculate_backoff(attempt, self.base_backoff, self.max_backoff)


def _selftest():
    """Run offline self-tests with temporary SQLite database."""
    # Test should_retry logic
    test_cases = [
        (500, None, True),
        (404, None, False),
        (503, Exception('Service Unavailable'), True),
        (500, Exception('Internal Server Error'), True),
        (200, Exception('Connection Reset by Peer'), False),
    ]

    for status_code, error, expected in test_cases:
        result = should_retry(status_code, error)
        assert result == expected, f"should_retry({status_code}, {error}) = {result}, expected {expected}"

    # Test calculate_backoff determinism and properties
    # Verify deterministic behavior (same input = same output)
    delay0_first = calculate_backoff(0, 1.0, 60.0)
    delay0_second = calculate_backoff(0, 1.0, 60.0)
    assert delay0_first == delay0_second, "calculate_backoff must be deterministic"
    
    # Verify exponential growth
    d0 = calculate_backoff(0, 1.0, 60.0)
    d1 = calculate_backoff(1, 1.0, 60.0)
    d2 = calculate_backoff(2, 1.0, 60.0)
    assert d1 > d0, f"Backoff should increase with attempt: {d1} <= {d0}"
    assert d2 > d1, f"Backoff should increase with attempt: {d2} <= {d1}"
    
    # Verify max_backoff cap is respected (allowing for jitter multiplier up to 1.5)
    d_large = calculate_backoff(10, 1.0, 60.0)
    assert d_large <= 90.0, f"Backoff with jitter should respect max: {d_large} > 90.0"

    # Test RetryPolicy integration
    retry_policy = RetryPolicy(max_retries=3, base_backoff=1.0, max_backoff=60.0)
    delays = [retry_policy.get_next_delay(i) for i in range(4)]
    expected_delays = [
        calculate_backoff(0, 1.0, 60.0),
        calculate_backoff(1, 1.0, 60.0),
        calculate_backoff(2, 1.0, 60.0),
        calculate_backoff(3, 1.0, 60.0)
    ]
    assert delays == expected_delays, f"RetryPolicy delays mismatch: {delays} != {expected_delays}"
    
    # Test ValueError on exceeded retries
    try:
        retry_policy.get_next_delay(4)
        assert False, "Should raise ValueError for attempt > max_retries"
    except ValueError as e:
        assert "Exceeded maximum number of retries" in str(e)
    
    # Test ValueError on negative attempt
    try:
        retry_policy.get_next_delay(-1)
        assert False, "Should raise ValueError for negative attempt"
    except ValueError as e:
        assert "Attempt must be non-negative" in str(e)
    
    # Test with temporary SQLite database (verifies offline capability)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        db_path = os.path.join(temp_dir, 'retry_test.db')
        conn = sqlite3.connect(db_path)
        try:
            # Store retry configuration in SQLite
            conn.execute('''
                CREATE TABLE retry_config (
                    id INTEGER PRIMARY KEY,
                    max_retries INTEGER,
                    base_backoff REAL,
                    max_backoff REAL
                )
            ''')
            
            conn.execute(
                'INSERT INTO retry_config (max_retries, base_backoff, max_backoff) VALUES (?, ?, ?)',
                (3, 1.0, 60.0)
            )
            conn.commit()
            
            # Retrieve and verify
            cursor = conn.execute('SELECT max_retries, base_backoff, max_backoff FROM retry_config WHERE id = 1')
            row = cursor.fetchone()
            assert row is not None
            assert row == (3, 1.0, 60.0)
            
            # Verify policy works with DB-retrieved values
            db_policy = RetryPolicy(max_retries=row[0], base_backoff=row[1], max_backoff=row[2])
            assert db_policy.get_next_delay(0) == calculate_backoff(0, 1.0, 60.0)
            
        finally:
            conn.close()
    
    logger.info("All self-tests passed")


def main():
    """Main entry point for running self-tests."""
    _selftest()


if __name__ == "__main__":
    main()
