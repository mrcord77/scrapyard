"""
lifespan — Startup/shutdown hook registry and a FastAPI lifespan factory.

### PART-META-JSON
{
  "name": "lifespan",
  "layer": "runtime",
  "purpose": "Application lifecycle management: a Hooks registry collecting sync/async startup and shutdown callables with priority ordering, strict (fail-fast) or lenient (collect errors) execution policies, per-hook timeouts, module/class auto-registration, run metrics, and make_lifespan() producing a FastAPI lifespan context manager.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Startup/shutdown callables (sync or async), priorities (-100..100), optional timeout seconds.",
  "outputs": "Ordered hook execution at app start/stop; a lifespan async context manager for FastAPI.",
  "files_created": [],
  "security_notes": "Under the default strict policy a failing startup hook aborts boot (HookError) instead of serving a half-initialized app; lenient mode is for tests/tools and records errors in last_errors. Hooks run in-process with full privileges — register only trusted code. Timeouts bound async hooks so a hung dependency cannot block shutdown forever; sync hooks are not preemptible.",
  "ai_usage": "hooks = Hooks(); hooks.on_startup(init_db); app = FastAPI(lifespan=make_lifespan(hooks)).",
  "example": "hooks = Hooks(); hooks.add_startup(warm_cache, priority=-10); FastAPI(lifespan=make_lifespan(hooks))",
  "import_path": "scrapyard.runtime.lifespan"
}
### END-PART-META
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

logger = logging.getLogger("scrapyard.runtime.lifespan")

LIFESPAN_HOOK_TIMEOUT: float = 10.0
LIFESPAN_DEFAULT_POLICY: str = "strict"  # strict: first failure raises; lenient: collect + continue


class HookError(Exception):
    """Raised under strict policy when a lifecycle hook fails."""


class Hooks:
    """Collect startup/shutdown callables (sync or async) and run them in
    priority order (lower runs first; ties keep registration order)."""

    def __init__(self, policy: str = LIFESPAN_DEFAULT_POLICY) -> None:
        if policy not in ("strict", "lenient"):
            raise ValueError(f"invalid policy {policy!r}")
        self._startup: List[Tuple[int, int, Callable[..., Any]]] = []
        self._shutdown: List[Tuple[int, int, Callable[..., Any]]] = []
        self._seq = 0
        self.policy = policy
        self.startup_ran = 0
        self.shutdown_ran = 0
        self.last_errors: List[Exception] = []

    # -- registration -------------------------------------------------------
    def on_startup(self, fn: Callable[..., Any], priority: int = 0):
        self._add(self._startup, fn, priority)
        return fn

    def on_shutdown(self, fn: Callable[..., Any], priority: int = 0):
        self._add(self._shutdown, fn, priority)
        return fn

    def add_startup(self, fn: Callable[..., Any], priority: int = 0):
        self._check_priority(priority)
        return self.on_startup(fn, priority)

    def add_shutdown(self, fn: Callable[..., Any], priority: int = 0):
        self._check_priority(priority)
        return self.on_shutdown(fn, priority)

    def _add(self, bucket: List[Tuple[int, int, Callable[..., Any]]],
             fn: Callable[..., Any], priority: int) -> None:
        if not callable(fn):
            raise TypeError("hook is not callable")
        self._seq += 1
        bucket.append((priority, self._seq, fn))

    @staticmethod
    def _check_priority(priority: int) -> None:
        if not -100 <= priority <= 100:
            raise ValueError("priority must be between -100 and 100")

    def register_from_module(self, module: ModuleType,
                             prefix: str = "on_startup_") -> int:
        """Register every callable in `module` whose name starts with `prefix`
        (and `on_shutdown_*` counterparts). Returns how many were registered."""
        n = 0
        for name in dir(module):
            obj = getattr(module, name)
            if not callable(obj):
                continue
            if name.startswith(prefix):
                self.on_startup(obj)
                n += 1
            elif name.startswith("on_shutdown_"):
                self.on_shutdown(obj)
                n += 1
        return n

    def register_from_class(self, cls: Type, *,
                            startup_method: str = "startup",
                            shutdown_method: str = "shutdown") -> None:
        """Register an instance's startup/shutdown methods if present."""
        instance = cls() if inspect.isclass(cls) else cls
        if hasattr(instance, startup_method):
            self.on_startup(getattr(instance, startup_method))
        if hasattr(instance, shutdown_method):
            self.on_shutdown(getattr(instance, shutdown_method))

    # -- execution ----------------------------------------------------------
    async def _run(self, bucket: List[Tuple[int, int, Callable[..., Any]]],
                   timeout: Optional[float] = None) -> int:
        n = 0
        self.last_errors = []
        for _prio, _seq, fn in sorted(bucket, key=lambda x: (x[0], x[1])):
            try:
                r = fn()
                if inspect.isawaitable(r):
                    if timeout is not None:
                        await asyncio.wait_for(r, timeout)
                    else:
                        await r
                n += 1
            except Exception as e:
                logger.error("lifecycle hook %s failed",
                             getattr(fn, "__name__", fn), exc_info=True)
                if self.policy == "strict":
                    raise HookError(str(e)) from e
                self.last_errors.append(e)
        return n

    async def run_startup(self, timeout: Optional[float] = None) -> int:
        self.startup_ran = await self._run(self._startup, timeout)
        return self.startup_ran

    async def run_shutdown(self, timeout: Optional[float] = None) -> int:
        self.shutdown_ran = await self._run(self._shutdown, timeout)
        return self.shutdown_ran

    # -- introspection ------------------------------------------------------
    def get_registered_hooks(self) -> List[Dict[str, Any]]:
        out = []
        for kind, bucket in (("startup", self._startup),
                             ("shutdown", self._shutdown)):
            for prio, _seq, fn in sorted(bucket, key=lambda x: (x[0], x[1])):
                out.append({
                    "kind": kind,
                    "name": getattr(fn, "__name__", repr(fn)),
                    "priority": prio,
                    "type": "async" if inspect.iscoroutinefunction(fn) else "sync",
                })
        return out

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "startup_ran": self.startup_ran,
            "shutdown_ran": self.shutdown_ran,
            "registered_startup": len(self._startup),
            "registered_shutdown": len(self._shutdown),
            "last_error_count": len(self.last_errors),
        }


def make_lifespan(hooks: Hooks, *, timeout: Optional[float] = None):
    """FastAPI lifespan factory: `FastAPI(lifespan=make_lifespan(hooks))`."""

    @asynccontextmanager
    async def lifespan(app):
        await hooks.run_startup(timeout)
        try:
            yield
        finally:
            await hooks.run_shutdown(timeout)

    return lifespan


STATUS = "core"


def _selftest() -> None:
    order: List[str] = []

    async def main() -> None:
        # priority ordering + sync/async mix
        h = Hooks()
        h.on_startup(lambda: order.append("late"), priority=10)
        h.add_startup(lambda: order.append("early"), priority=-10)

        async def mid():
            order.append("mid")
        h.on_startup(mid)  # priority 0
        assert await h.run_startup() == 3
        assert order == ["early", "mid", "late"]

        # strict policy: first failure raises HookError
        bad = Hooks()
        bad.on_startup(lambda: 1 / 0)
        try:
            await bad.run_startup()
            raise AssertionError("strict policy did not raise")
        except HookError:
            pass

        # lenient policy: errors collected, remaining hooks still run
        len_hooks = Hooks(policy="lenient")
        ran: List[str] = []
        len_hooks.on_startup(lambda: 1 / 0)
        len_hooks.on_startup(lambda: ran.append("ok"))
        assert await len_hooks.run_startup() == 1
        assert ran == ["ok"] and len(len_hooks.last_errors) == 1

        # timeout bounds async hooks
        slow = Hooks()

        async def sleepy():
            await asyncio.sleep(5)
        slow.on_startup(sleepy)
        try:
            await slow.run_startup(timeout=0.05)
            raise AssertionError("timeout not enforced")
        except HookError:
            pass

        # priority bounds + non-callable rejection
        try:
            h.add_startup(lambda: None, priority=999)
            raise AssertionError("out-of-range priority accepted")
        except ValueError:
            pass
        try:
            h.on_startup("not-callable")  # type: ignore[arg-type]
            raise AssertionError("non-callable accepted")
        except TypeError:
            pass

        # class registration + introspection + metrics
        class Service:
            def __init__(self):
                self.events: List[str] = []
            def startup(self):
                self.events.append("up")
            def shutdown(self):
                self.events.append("down")

        svc = Service()
        h2 = Hooks()
        h2.register_from_class(svc)
        await h2.run_startup()
        await h2.run_shutdown()
        assert svc.events == ["up", "down"]
        kinds = {e["kind"] for e in h2.get_registered_hooks()}
        assert kinds == {"startup", "shutdown"}
        m = h2.get_metrics()
        assert m["startup_ran"] == 1 and m["shutdown_ran"] == 1

        # lifespan factory drives startup/shutdown around the app context
        seq: List[str] = []
        h3 = Hooks()
        h3.on_startup(lambda: seq.append("start"))
        h3.on_shutdown(lambda: seq.append("stop"))
        lifespan = make_lifespan(h3)
        async with lifespan(None):
            seq.append("serving")
        assert seq == ["start", "serving", "stop"]

        # invalid policy rejected
        try:
            Hooks(policy="wishful")
            raise AssertionError("invalid policy accepted")
        except ValueError:
            pass

    asyncio.run(main())
    print("lifespan selftest: PASS")


if __name__ == "__main__":
    _selftest()
