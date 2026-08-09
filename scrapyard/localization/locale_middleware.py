"""
locale_middleware — Detect locale from header/user.

### PART-META-JSON
{
  "name": "locale_middleware",
  "layer": "localization",
  "purpose": "Detect locale from header/user.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "fastapi"
  ],
  "inputs": "Public API: negotiate_locale(headers, supported, default, fallback_chain); install_locale(app, supported, default, config); on_locale_change(locale, user, request); detect_locales_from_headers(headers_list, supported, default); serialize_locale(locale); LocaleConfig(...); LocalePolicy(...); LocaleNotFoundError(...) (plus more).",
  "outputs": "Returns: negotiate_locale -> str; detect_locales_from_headers -> Dict[str, str]; serialize_locale -> str; apply_locale_policy -> Optional[str]; get_cached_locale -> str.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import `negotiate_locale` from `scrapyard.localization.locale_middleware` and call it as shown in `example`; run `py -m scrapyard.localization.locale_middleware` to see its offline selftest.",
  "example": "from scrapyard.localization.locale_middleware import negotiate_locale",
  "import_path": "scrapyard.localization.locale_middleware"
}
### END-PART-META
"""
import logging
import re
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException, Request
from pydantic import BaseModel

_log = logging.getLogger("scrapyard.localization.locale_middleware")

class LocaleConfig(BaseModel):
    supported: List[str]
    default: str = "en"
    fallbacks: Optional[List[str]] = None
    policies: Optional[Dict[str, Dict[str, Union[str, bool]]]] = None

class LocalePolicy(BaseModel):
    override: Optional[str] = None
    restrict: Optional[str] = None

class LocaleNotFoundError(HTTPException):
    def __init__(self, locale: str, supported: List[str]):
        super().__init__(
            status_code=406,
            detail=f"Locale '{locale}' is not supported. Supported locales are {', '.join(supported)}."
        )

class LocaleFormatError(HTTPException):
    def __init__(self, locale: str):
        super().__init__(
            status_code=422,
            detail=f"Invalid locale format: {locale}. Locale should be in the form of 'en-US'."
        )

def negotiate_locale(headers: str, supported: List[str], default: str, fallback_chain: Optional[List[str]] = None) -> str:
    if not headers:
        return default
    preferred_locales = headers.split(',')
    for locale in preferred_locales:
        locale = locale.strip().split(';')[0]
        if locale in supported:
            return locale
    if fallback_chain and len(fallback_chain) > 0:
        for fallback in fallback_chain:
            if fallback in supported:
                return fallback
    raise LocaleNotFoundError(locale=preferred_locales[0], supported=supported)

def install_locale(app, supported: List[str], default="en", config: Optional[LocaleConfig] = None):
    @app.middleware("http")
    async def _locale(request: Request, call_next):
        if getattr(request.state, "locale", None) is None:
            headers = request.headers.get("accept-language", "")
            fallback_chain = config.fallbacks if config and config.fallbacks else []
            try:
                request.state.locale = negotiate_locale(headers, supported, default, fallback_chain)
            except LocaleNotFoundError:
                request.state.locale = default
        return await call_next(request)

def on_locale_change(locale: str, user: Optional[Any], request: Request):
    _log.info("locale changed to %s (user=%s)", locale,
              getattr(user, "id", None) if user is not None else None)

def detect_locales_from_headers(headers_list: List[str], supported: List[str], default: str) -> Dict[str, str]:
    results = {}
    for headers in headers_list:
        try:
            locale = negotiate_locale(headers, supported, default)
            results[headers] = locale
        except LocaleNotFoundError as e:
            results[headers] = f"{e.detail}"
    return results

def serialize_locale(locale: str) -> str:
    """Whitelist-sanitize a locale tag (e.g. en, en-US) for safe echoing."""
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", locale or ""):
        raise LocaleFormatError(locale=locale)
    return locale

def apply_locale_policy(locale: str, user: Optional[Any], policy: LocalePolicy,
                        supported: Optional[List[str]] = None) -> Optional[str]:
    if policy.override:
        return policy.override
    if policy.restrict and supported is not None and locale not in supported:
        raise LocaleNotFoundError(locale=locale, supported=supported)
    return locale

_LOCALE_CACHE: Dict[str, tuple] = {}

def get_cached_locale(user_id: str, default: str, cache_ttl: int = 600) -> str:
    import time
    hit = _LOCALE_CACHE.get(user_id)
    if hit and (time.time() - hit[1]) < cache_ttl:
        return hit[0]
    return default

def set_cached_locale(user_id: str, locale: str) -> None:
    import time
    _LOCALE_CACHE[user_id] = (locale, time.time())

def log_locale_usage(locale: str, user: Optional[Any], request: Request):
    _log.debug("locale=%s path=%s user=%s", locale, request.url.path,
               getattr(user, "id", None) if user is not None else None)


def _selftest() -> None:
    """Offline self-test: Accept-Language negotiation picks the right locale,
    defaults/falls back correctly, rejects unsupported locales, and the locale-tag
    sanitizer rejects malformed input."""
    supported = ["en", "fr", "de"]

    # Picks the first supported preference (quality params stripped).
    assert negotiate_locale("fr;q=0.9, en;q=0.8", supported, "en") == "fr"

    # Empty header -> default.
    assert negotiate_locale("", supported, "en") == "en"

    # Unsupported preference with a fallback chain resolves via the chain.
    assert negotiate_locale("es", supported, "en", fallback_chain=["de"]) == "de"

    # Negative: unsupported preference with no usable fallback raises 406.
    try:
        negotiate_locale("es, it", supported, "en")
        raise AssertionError("expected LocaleNotFoundError for unsupported locale")
    except LocaleNotFoundError as e:
        assert e.status_code == 406

    # serialize_locale accepts well-formed tags and rejects malformed/injection-y ones.
    assert serialize_locale("en") == "en"
    assert serialize_locale("en-US") == "en-US"
    for bad in ["en_US", "'; DROP TABLE users;--", "e", "toolongsubtag-xxxxxxxxx"]:
        try:
            serialize_locale(bad)
            raise AssertionError(f"expected LocaleFormatError for {bad!r}")
        except LocaleFormatError:
            pass

    # Policy override wins; restrict raises on out-of-set locale.
    assert apply_locale_policy("fr", None, LocalePolicy(override="de")) == "de"
    try:
        apply_locale_policy("ru", None, LocalePolicy(restrict="true"), supported=supported)
        raise AssertionError("expected LocaleNotFoundError under restrict policy")
    except LocaleNotFoundError:
        pass

    print("locale_middleware selftest: PASS")


if __name__ == "__main__":
    _selftest()
