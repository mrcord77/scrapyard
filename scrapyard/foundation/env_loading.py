"""
env_loading — Locate and load .env files across environments.

### PART-META-JSON
{
  "name": "env_loading",
  "layer": "foundation",
  "purpose": "Dotenv loading without external deps: parse KEY=VALUE files into os.environ (no-overwrite by default, custom delimiter, quote stripping, per-environment file variants), recursive discovery under a base dir, environment detection from ENV, prefix-filtered loading, required-var validation, and env dumps to file.",
  "addition": false,
  "status": "core",
  "dependencies": [],
  "inputs": ".env file paths / base directories; environment names; prefixes; required-var lists.",
  "outputs": "Dicts of the variables actually set; mutations of os.environ.",
  "files_created": [],
  "security_notes": ".env files hold credentials: loading never overwrites existing environment values unless override=True, so a compromised file cannot silently replace injected production secrets. log_loaded_envs logs variable NAMES only, never values. dump_env_to_file writes plaintext values to disk — use it only for generating deploy templates, never with live secrets in shared locations. Parsing is line-based (no eval, no shell expansion).",
  "ai_usage": "load_dotenv(['.env']) at process start (before reading config); validate_env(['DATABASE_URL']) to fail fast.",
  "example": "load_dotenv(['.env', 'config/.env']); missing = validate_env(['DATABASE_URL'])",
  "import_path": "scrapyard.foundation.env_loading"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

STATUS = "core"

logger = logging.getLogger("scrapyard.foundation.env_loading")


def _parse_env_file(path: str, delimiter: str = "=", strip_quotes: bool = True) -> Dict[str, str]:
    """Parse a KEY<delimiter>VALUE file into a dict (comments/blank lines skipped)."""
    parsed: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or delimiter not in line:
                continue
            k, v = line.split(delimiter, 1)
            k = k.strip()
            v = v.strip()
            if strip_quotes and len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k:
                parsed[k] = v
    return parsed


def load_dotenv(paths: Optional[List[str]] = None, env: str = "default",
                override: bool = False, delimiter: str = "=",
                strip_quotes: bool = True) -> Dict[str, str]:
    """Load KEY=VALUE lines into os.environ (no overwrite unless override=True).
    For env != 'default', a '<path>.<env>' variant is loaded after each path
    (so environment-specific values win within this call). Returns what was set."""
    loaded: Dict[str, str] = {}
    candidates: List[str] = []
    for path in paths or []:
        candidates.append(path)
        if env and env != "default":
            candidates.append(f"{path}.{env}")
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            for k, v in _parse_env_file(path, delimiter, strip_quotes).items():
                if k not in os.environ or override or k in loaded:
                    os.environ[k] = v
                    loaded[k] = v
        except Exception as e:
            logger.error("Failed to load %s: %s", path, e)
    return loaded


def detect_env() -> str:
    """Detect the current environment from the ENV variable.
    dev/development -> 'dev'; prod/production -> 'prod'; staging -> 'staging';
    unset -> 'default'; anything else -> 'unknown'."""
    env = os.getenv("ENV", "").strip().lower()
    if env in ("", "default"):
        return "default"
    if env in ("dev", "development"):
        return "dev"
    if env in ("prod", "production"):
        return "prod"
    if env == "staging":
        return "staging"
    return "unknown"


def load_dotenv_recursive(base_dir: str, env: str = "default") -> Dict[str, str]:
    """Recursively load .env files under ``base_dir``. For env='default' this
    loads plain '.env' files; otherwise it loads '.env.<env>' variants."""
    base_path = Path(base_dir)
    wanted = ".env" if env == "default" else f".env.{env}"
    loaded: Dict[str, str] = {}
    for path in sorted(base_path.glob("**/.env*")):
        if path.name != wanted:
            continue
        try:
            loaded.update(load_dotenv([str(path)], override=True))
        except Exception as e:
            logger.error("Failed to load %s: %s", path, e)
    return loaded


def log_loaded_envs(logger_: logging.Logger) -> None:
    """Log the NAMES of all current environment variables (never the values —
    env vars routinely hold credentials)."""
    for k in sorted(os.environ):
        logger_.info("env var present: %s", k)


def validate_env(required: List[str]) -> List[str]:
    """Return the required environment variables that are missing."""
    return [var for var in required if var not in os.environ]


def load_dotenv_with_prefix(prefix: str, path: str = ".env") -> Dict[str, str]:
    """Load only the variables with a given prefix from a file (always sets them)."""
    loaded: Dict[str, str] = {}
    if not os.path.exists(path):
        return loaded
    try:
        for k, v in _parse_env_file(path).items():
            if k.startswith(prefix):
                os.environ[k] = v
                loaded[k] = v
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
    return loaded


def dump_env_to_file(path: str, env_vars: Dict[str, str]) -> None:
    """Write KEY=VALUE lines to a file (plaintext — mind where you put it)."""
    with open(path, "w", encoding="utf-8") as f:
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")


def load_dotenv_delimited(path: str = ".env", delimiter: str = "=",
                          strip_quotes: bool = True) -> Dict[str, str]:
    """Load a dotenv-style file that uses a custom KEY/VALUE delimiter
    (e.g. 'KEY: value' with delimiter=':'). No overwrite of existing vars."""
    loaded: Dict[str, str] = {}
    if not os.path.exists(path):
        return loaded
    try:
        for k, v in _parse_env_file(path, delimiter, strip_quotes).items():
            if k not in os.environ:
                os.environ[k] = v
                loaded[k] = v
    except Exception as e:
        logger.error("Failed to load %s: %s", path, e)
    return loaded


def _selftest() -> None:
    import tempfile

    prefixes = ("EL_",)
    saved = {k: v for k, v in os.environ.items() if k.startswith(prefixes)}
    saved_env = os.environ.get("ENV")
    try:
        for k in list(os.environ):
            if k.startswith(prefixes):
                del os.environ[k]

        with tempfile.TemporaryDirectory() as tmp:
            envfile = os.path.join(tmp, ".env")
            with open(envfile, "w", encoding="utf-8") as f:
                f.write("# comment\n\nEL_A=1\nEL_QUOTED=\"hello world\"\nEL_SINGLE='x'\nbad-line\n")

            # basic load: comments skipped, quotes stripped, values set
            loaded = load_dotenv([envfile])
            assert loaded == {"EL_A": "1", "EL_QUOTED": "hello world", "EL_SINGLE": "x"}
            assert os.environ["EL_QUOTED"] == "hello world"

            # no-overwrite semantics vs override
            with open(envfile, "w", encoding="utf-8") as f:
                f.write("EL_A=999\n")
            assert load_dotenv([envfile]) == {}
            assert os.environ["EL_A"] == "1"
            assert load_dotenv([envfile], override=True) == {"EL_A": "999"}

            # env-specific variant wins within the call
            with open(envfile, "w", encoding="utf-8") as f:
                f.write("EL_MODE=base\n")
            with open(envfile + ".prod", "w", encoding="utf-8") as f:
                f.write("EL_MODE=prod\n")
            os.environ.pop("EL_MODE", None)
            loaded = load_dotenv([envfile], env="prod")
            assert loaded["EL_MODE"] == "prod" and os.environ["EL_MODE"] == "prod"

            # recursive discovery: plain .env for default, .env.<env> otherwise
            sub = os.path.join(tmp, "svc")
            os.makedirs(sub)
            with open(os.path.join(sub, ".env"), "w", encoding="utf-8") as f:
                f.write("EL_REC=default\n")
            with open(os.path.join(sub, ".env.staging"), "w", encoding="utf-8") as f:
                f.write("EL_REC=staging\n")
            assert load_dotenv_recursive(tmp)["EL_REC"] == "default"
            assert load_dotenv_recursive(tmp, env="staging")["EL_REC"] == "staging"

            # prefix loading
            with open(envfile, "w", encoding="utf-8") as f:
                f.write("EL_PFX_ONE=a\nOTHER_VAR=b\nEL_PFX_TWO=c\n")
            loaded = load_dotenv_with_prefix("EL_PFX_", envfile)
            assert set(loaded) == {"EL_PFX_ONE", "EL_PFX_TWO"}
            assert "OTHER_VAR" not in loaded

            # custom delimiter file
            colonfile = os.path.join(tmp, "colon.env")
            with open(colonfile, "w", encoding="utf-8") as f:
                f.write("EL_COLON: with colon\n")
            os.environ.pop("EL_COLON", None)
            assert load_dotenv_delimited(colonfile, delimiter=":")["EL_COLON"] == "with colon"

            # dump + reload round trip
            dumpfile = os.path.join(tmp, "dump.env")
            dump_env_to_file(dumpfile, {"EL_DUMPED": "42"})
            os.environ.pop("EL_DUMPED", None)
            assert load_dotenv([dumpfile])["EL_DUMPED"] == "42"

        # validate_env
        os.environ["EL_HAVE"] = "1"
        assert validate_env(["EL_HAVE", "EL_MISSING_X"]) == ["EL_MISSING_X"]

        # detect_env mapping
        cases = {"development": "dev", "dev": "dev", "prod": "prod",
                 "production": "prod", "staging": "staging", "weird": "unknown"}
        for raw, expected in cases.items():
            os.environ["ENV"] = raw
            assert detect_env() == expected, raw
        os.environ.pop("ENV", None)
        assert detect_env() == "default"

        # log_loaded_envs must log names only, never values
        records: list = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        cap_logger = logging.getLogger("env_loading.selftest")
        cap_logger.setLevel(logging.INFO)
        cap_logger.addHandler(_Capture())
        cap_logger.propagate = False
        os.environ["EL_SECRET"] = "hunter2-do-not-log"
        log_loaded_envs(cap_logger)
        joined = "\n".join(records)
        assert "EL_SECRET" in joined and "hunter2-do-not-log" not in joined
    finally:
        for k in list(os.environ):
            if k.startswith(prefixes):
                del os.environ[k]
        os.environ.update(saved)
        if saved_env is None:
            os.environ.pop("ENV", None)
        else:
            os.environ["ENV"] = saved_env

    print("env_loading selftest: PASS")


if __name__ == "__main__":
    _selftest()
