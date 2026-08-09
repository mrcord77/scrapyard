"""
retries — Exponential backoff + random jitter retry wrapper for tasks.

### PART-META-JSON
{
  "name": "retries",
  "layer": "jobs",
  "purpose": "Retry helpers with REAL exponential backoff (base * 2**(attempt-1), capped) and random jitter (full/none), seedable RNG for tests, decorator, bulk runner, and an iterable retry_context.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": "Callables to retry; RetryPolicy(max_attempts, backoff, jitter_type, exceptions, max_delay).",
  "outputs": "Wrapped callables; RetryResult objects; computed delay floats.",
  "files_created": [],
  "security_notes": "Jitter uses a module RNG (random) seedable via set_jitter_seed - fine for backoff scheduling, NOT for cryptographic use. deserialize_retry_policy resolves exception names only from builtins (no arbitrary import/eval). Callbacks run in the caller's thread; exceptions in callbacks propagate.",
  "ai_usage": "@with_retry(max_attempts=3, backoff=0.5) for the simple path; RetryPolicy + with_retry_policy for callbacks/jitter control; for block-style use: for attempt in retry_context(policy): with attempt: work().",
  "example": "from scrapyard.jobs.retries import with_retry, RetryPolicy, retry_context",
  "import_path": "scrapyard.jobs.retries"
}
### END-PART-META
"""
from __future__ import annotations
import builtins
import functools
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar

STATUS = "core"
T = TypeVar('T')

JitterType = Enum('JitterType', ['NONE', 'FULL'])

# Module RNG: seedable so tests get reproducible jitter.
_rng = random.Random()


def set_jitter_seed(seed: Optional[int]) -> None:
    """Seed the jitter RNG (tests); None reseeds from OS entropy."""
    _rng.seed(seed)


class RetryLimitExceededError(Exception):
    pass


class InvalidRetryPolicyError(Exception):
    pass


class SerializationError(Exception):
    pass


class UnsupportedJitterTypeError(Exception):
    pass


class NoRetryableExceptionError(Exception):
    pass


class InvalidDelayError(Exception):
    pass


@dataclass
class RetryPolicy:
    max_attempts: int
    backoff: float
    jitter_type: JitterType = JitterType.FULL
    exceptions: Tuple[type, ...] = (Exception,)
    max_delay: float = 60.0
    on_retry_start: Optional[Callable[[int], None]] = None
    on_retry_end: Optional[Callable[[Exception], None]] = None

    def __post_init__(self):
        if self.max_attempts < 1:
            raise InvalidRetryPolicyError("max_attempts must be >= 1")
        if self.backoff < 0:
            raise InvalidDelayError("backoff must be >= 0")
        if isinstance(self.jitter_type, str):  # tolerate name strings
            self.jitter_type = JitterType[self.jitter_type]


def compute_delay(policy_backoff: float, attempt: int,
                  jitter_type: JitterType = JitterType.FULL,
                  max_delay: float = 60.0) -> float:
    """REAL exponential backoff: base * 2**(attempt-1), capped, then jittered.

    FULL jitter draws uniformly from [0, exp_delay] (AWS-style full jitter);
    NONE returns the exponential delay unchanged.
    """
    if attempt < 1:
        raise InvalidDelayError("attempt must be >= 1")
    exp_delay = min(policy_backoff * (2 ** (attempt - 1)), max_delay)
    return add_jitter(exp_delay, jitter_type)


def add_jitter(delay: float, jitter_type: JitterType = JitterType.FULL) -> float:
    if delay < 0:
        raise InvalidDelayError("delay must be >= 0")
    if jitter_type == JitterType.NONE:
        return delay
    if jitter_type == JitterType.FULL:
        return _rng.uniform(0.0, delay)
    raise UnsupportedJitterTypeError(f"Unsupported jitter type: {jitter_type}")


def serialize_retry_policy(policy: RetryPolicy) -> Dict[str, Any]:
    return {
        'max_attempts': policy.max_attempts,
        'backoff': policy.backoff,
        'max_delay': policy.max_delay,
        'jitter_type': policy.jitter_type.name,
        'exceptions': [exc.__name__ for exc in policy.exceptions],
        'on_retry_start': None if policy.on_retry_start is None else policy.on_retry_start.__qualname__,
        'on_retry_end': None if policy.on_retry_end is None else policy.on_retry_end.__qualname__,
    }


def deserialize_retry_policy(data: Dict[str, Any]) -> RetryPolicy:
    """Rebuild a policy; exception names resolve from builtins only (safe)."""
    try:
        exceptions = []
        for exc_name in data.get('exceptions', ['Exception']):
            exc = getattr(builtins, exc_name, None)
            if not (isinstance(exc, type) and issubclass(exc, BaseException)):
                raise SerializationError(f"unknown exception type: {exc_name}")
            exceptions.append(exc)
        return RetryPolicy(
            max_attempts=data.get('max_attempts', 3),
            backoff=data.get('backoff', 1.0),
            jitter_type=JitterType[data.get('jitter_type', 'FULL')],
            exceptions=tuple(exceptions) or (Exception,),
            max_delay=data.get('max_delay', 60.0),
        )
    except SerializationError:
        raise
    except KeyError as e:
        raise SerializationError(f"Missing key: {e}")
    except Exception as e:
        raise SerializationError(f"Failed to deserialize policy: {e}")


class RetryResult(Generic[T]):
    def __init__(self, success: bool, retries: int, final_result: Optional[T],
                 exception: Optional[Exception]):
        self.success = success
        self.retries = retries
        self.final_result = final_result
        self.exception = exception


def _sleep_for(policy: RetryPolicy, attempt: int) -> None:
    if policy.backoff > 0:
        time.sleep(compute_delay(policy.backoff, attempt, policy.jitter_type, policy.max_delay))


def with_retry_policy(policy: RetryPolicy) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            last: Optional[Exception] = None
            for attempt in range(1, policy.max_attempts + 1):
                try:
                    return fn(*a, **k)
                except policy.exceptions as e:
                    last = e
                    if policy.on_retry_start:
                        policy.on_retry_start(attempt)
                    if attempt < policy.max_attempts:
                        _sleep_for(policy, attempt)
            if policy.on_retry_end and last is not None:
                policy.on_retry_end(last)
            raise last
        return wrapper
    return deco


class RetryableTask(Generic[T]):
    def __init__(self, task: Callable[..., T], policy: RetryPolicy):
        self.task = task
        self.policy = policy

    async def run(self) -> T:
        last: Optional[Exception] = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                return await self.task()
            except self.policy.exceptions as e:
                last = e
                if self.policy.on_retry_start:
                    self.policy.on_retry_start(attempt)
                if attempt < self.policy.max_attempts:
                    _sleep_for(self.policy, attempt)
        if self.policy.on_retry_end and last is not None:
            self.policy.on_retry_end(last)
        raise last


def retry_bulk(tasks: List[Callable[..., T]], policy: RetryPolicy) -> List[RetryResult[T]]:
    """Run each task under the policy (each ACTUALLY retries), collecting results."""
    results: List[RetryResult[T]] = []
    for task in tasks:
        attempts_used = {"n": 0}

        def counting_task(_task=task):
            attempts_used["n"] += 1
            return _task()

        try:
            result = with_retry_policy(policy)(counting_task)()
            results.append(RetryResult(True, attempts_used["n"] - 1, result, None))
        except policy.exceptions as e:
            results.append(RetryResult(False, attempts_used["n"] - 1, None, e))
    return results


def on_retry_start(fn: Callable[[], None]):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **k):
            fn()
            return f(*a, **k)
        return wrapper
    return deco


def on_retry_end(fn: Callable[[Exception], None]):
    def deco(f):
        @functools.wraps(f)
        def wrapper(exc: Exception):
            fn(exc)
            return f(exc)
        return wrapper
    return deco


def filter_exceptions(exc: Exception, policy: RetryPolicy) -> bool:
    return isinstance(exc, policy.exceptions)


class _Attempt:
    """One attempt in a retry_context loop; suppresses retryable exceptions."""

    def __init__(self, state: dict, policy: RetryPolicy, number: int):
        self._state = state
        self._policy = policy
        self.number = number

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            self._state["succeeded"] = True
            return False
        if isinstance(exc, self._policy.exceptions):
            self._state["last_exc"] = exc
            if self._policy.on_retry_start:
                self._policy.on_retry_start(self.number)
            if self.number < self._policy.max_attempts:
                _sleep_for(self._policy, self.number)
            return True  # suppress; the loop decides whether to retry or raise
        return False  # non-retryable: propagate


def retry_context(policy: RetryPolicy):
    """Iterable of attempt context managers (fixed: was a broken bare generator).

    Usage:
        for attempt in retry_context(policy):
            with attempt:
                do_work()

    Stops as soon as one attempt succeeds; raises RetryLimitExceededError
    (chained to the last exception) when all attempts fail.
    """
    state: dict = {"succeeded": False, "last_exc": None}
    for number in range(1, policy.max_attempts + 1):
        yield _Attempt(state, policy, number)
        if state["succeeded"]:
            return
    if policy.on_retry_end and state["last_exc"] is not None:
        policy.on_retry_end(state["last_exc"])
    raise RetryLimitExceededError("Max retry attempts reached") from state["last_exc"]


def with_retry(max_attempts: int = 3, backoff: float = 0.0, exceptions=(Exception,)):
    """Decorator: retry with exponential backoff + full jitter.
    backoff=0 keeps tests fast; production passes a real base delay."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            last = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*a, **k)
                except exceptions as e:
                    last = e
                    if attempt < max_attempts and backoff:
                        time.sleep(compute_delay(backoff, attempt))
            raise last
        return wrapper
    return deco


def run_with_retry(fn, *args, max_attempts: int = 3, **kwargs):
    return with_retry(max_attempts=max_attempts)(fn)(*args, **kwargs)


def _selftest() -> bool:
    # exponential growth is REAL: NONE jitter exposes the raw curve
    d1 = compute_delay(1.0, 1, JitterType.NONE)
    d2 = compute_delay(1.0, 2, JitterType.NONE)
    d3 = compute_delay(1.0, 3, JitterType.NONE)
    assert (d1, d2, d3) == (1.0, 2.0, 4.0), (d1, d2, d3)
    assert compute_delay(1.0, 10, JitterType.NONE, max_delay=8.0) == 8.0  # cap

    # jitter is RANDOM and seedable
    set_jitter_seed(42)
    a = [compute_delay(1.0, 3) for _ in range(5)]
    set_jitter_seed(42)
    b = [compute_delay(1.0, 3) for _ in range(5)]
    assert a == b, "seeded jitter must reproduce"
    assert len(set(a)) > 1, "full jitter must vary between draws"
    assert all(0.0 <= x <= 4.0 for x in a), a
    set_jitter_seed(None)

    # decorator retries then succeeds
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    assert with_retry(max_attempts=5)(flaky)() == "ok" and calls["n"] == 3

    # policy path with callbacks
    started: List[int] = []
    pol = RetryPolicy(max_attempts=3, backoff=0.0, jitter_type=JitterType.NONE,
                      exceptions=(ValueError,), on_retry_start=started.append)
    calls["n"] = 0
    try:
        with_retry_policy(pol)(lambda: (_ for _ in ()).throw(ValueError("x")))()
        raise AssertionError("should have raised")
    except ValueError:
        pass
    assert started == [1, 2, 3], started

    # non-retryable exception passes straight through
    try:
        with_retry_policy(pol)(lambda: (_ for _ in ()).throw(KeyError("k")))()
        raise AssertionError("should have raised KeyError")
    except KeyError:
        pass

    # retry_context: fixed iterable-of-attempts protocol
    calls["n"] = 0
    for attempt in retry_context(RetryPolicy(3, 0.0, JitterType.NONE, (ValueError,))):
        with attempt:
            flaky_result = flaky()
    assert flaky_result == "ok" and calls["n"] == 3
    try:
        for attempt in retry_context(RetryPolicy(2, 0.0, JitterType.NONE, (ValueError,))):
            with attempt:
                raise ValueError("always")
        raise AssertionError("should have raised")
    except RetryLimitExceededError as e:
        assert isinstance(e.__cause__, ValueError)

    # bulk actually retries per task
    calls["n"] = 0
    res = retry_bulk([flaky, lambda: 7], RetryPolicy(5, 0.0, JitterType.NONE, (ValueError,)))
    assert res[0].success and res[0].final_result == "ok" and res[0].retries == 2
    assert res[1].success and res[1].retries == 0

    # serialization roundtrip; unknown exception name rejected
    p2 = deserialize_retry_policy(serialize_retry_policy(pol))
    assert p2.max_attempts == 3 and p2.exceptions == (ValueError,)
    assert p2.jitter_type == JitterType.NONE
    try:
        deserialize_retry_policy({"exceptions": ["os"]})
        raise AssertionError("bad exception name accepted")
    except SerializationError:
        pass

    # policy validation
    try:
        RetryPolicy(0, 1.0)
        raise AssertionError("max_attempts=0 accepted")
    except InvalidRetryPolicyError:
        pass

    print("retries selftest OK")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
