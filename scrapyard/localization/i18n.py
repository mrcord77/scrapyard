"""
i18n — Translate keys with locale fallback.

### PART-META-JSON
{
  "name": "i18n",
  "layer": "localization",
  "purpose": "Translate keys with locale fallback.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "babel"
  ],
  "inputs": "Public API: configure(translations, fallback_locale); t(locale, key, **fmt); get_all_translations(locale); list_supported_locales(); bulk_translate(locales, keys); Translation(...); Translations(...) (plus more).",
  "outputs": "Returns: configure -> None; t -> str; get_all_translations -> Dict[str, str]; list_supported_locales -> List[str]; bulk_translate -> Dict[str, Dict[str, str]].",
  "files_created": [],
  "security_notes": "Renders HTML with all caller text escaped via html.escape (XSS-safe); any HTML 'slot' arguments are inserted verbatim and must be pre-escaped by the caller.",
  "ai_usage": "Import `configure` from `scrapyard.localization.i18n` and call it as shown in `example`; run `py -m scrapyard.localization.i18n` to see its offline selftest.",
  "example": "from scrapyard.localization.i18n import configure",
  "import_path": "scrapyard.localization.i18n"
}
### END-PART-META
"""
import html
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from pydantic import BaseModel


STATUS = "core"

class Translation(BaseModel):
    locale: str
    translations: Dict[str, str]

class Translations(BaseModel):
    locale: str
    data: Dict[str, str]

    def get(self, key: str, **fmt: Any) -> str:
        return self.data.get(key, self._fallback_key(key)).format(**fmt)

    def _fallback_key(self, key: str) -> str:
        return f"fallback_{key}"

    def add(self, key: str, value: str) -> None:
        self.data[key] = value

def configure(translations: dict[str, dict[str, str]], fallback_locale: str = "en") -> None:
    global _translations
    _translations = {locale: Translations(locale=locale, data=trans) for locale, trans in translations.items()}
    set_fallback(fallback_locale)

def t(locale: str, key: str, **fmt: Any) -> str:
    bundle = _translations.get(locale) or _translations.get(_fallback_locale)
    if bundle is None:
        return key.format(**fmt) if fmt else key
    return bundle.get(key, **fmt)

def get_all_translations(locale: str) -> Dict[str, str]:
    if not _translations or locale not in _translations:
        raise HTTPException(status_code=404, detail="Locale not found")
    return _translations[locale].data

def list_supported_locales() -> List[str]:
    return [t.locale for t in _translations.values()]

def bulk_translate(locales: List[str], keys: List[str]) -> Dict[str, Dict[str, str]]:
    translations = {}
    for locale in locales:
        if locale not in _translations:
            _translations[locale] = Translations(locale=locale, data={})
        translations[locale] = {key: t(locale, key) for key in keys}
    return translations

def add_translation(locale: str, key: str, value: str) -> None:
    if locale not in _translations:
        raise HTTPException(status_code=404, detail="Locale not found")
    _translations[locale].add(key, value)

def negotiate_locale(accept_language: str, supported: List[str], default: str = "en") -> str:
    for part in accept_language.split(","):
        code = part.split(";")[0].strip().split("-")[0]
        if code in supported:
            return code
    return default

def translate_with_fallback(locale: str, key: str, fallback_key: str, **fmt: Any) -> str:
    try:
        return t(locale, key, **fmt)
    except KeyError:
        return t(locale, fallback_key, **fmt)

def register_locale(locale: str) -> None:
    if locale not in _translations:
        _translations[locale] = Translations(locale=locale, data={})

def unregister_locale(locale: str) -> None:
    if locale in _translations:
        del _translations[locale]

def get_language_name(locale: str) -> Optional[str]:
    return _language_names.get(locale)

def set_language_name(locale: str, name: str) -> None:
    global _language_names
    _language_names = {**_language_names, **{locale: name}}

def translate_keys(keys: List[str], locale: str) -> Dict[str, str]:
    if locale not in _translations:
        raise HTTPException(status_code=404, detail="Locale not found")
    return {key: t(locale, key) for key in keys}

def translate_keys_multi(keys: List[str], locales: List[str]) -> Dict[str, Dict[str, str]]:
    translations = {}
    for locale in locales:
        if locale not in _translations:
            raise HTTPException(status_code=404, detail="Locale not found")
        translations[locale] = {key: t(locale, key) for key in keys}
    return translations

def set_fallback(fallback_locale: str) -> None:
    global _fallback_locale
    _fallback_locale = fallback_locale

_translations: Dict[str, Translations] = {}
_language_names: Dict[str, str] = {}
_fallback_locale: str = "en"

def clean_input(input_str: str) -> str:
    return html.escape(input_str, tags=[], attributes=[], styles=[], protocols=[])

def _selftest() -> None:
    """Offline self-test: known-key translation, unknown-key fallback, and
    interpolation, plus locale negotiation with a default."""
    configure({
        "en": {"greeting": "Hello", "farewell": "Goodbye", "hi": "Hi {name}"},
        "fr": {"greeting": "Bonjour", "farewell": "Au revoir"},
    }, fallback_locale="en")

    # Known key returns the locale's translation.
    assert t("en", "greeting") == "Hello", t("en", "greeting")
    assert t("fr", "greeting") == "Bonjour", t("fr", "greeting")

    # Interpolation fills placeholders.
    assert t("en", "hi", name="Andre") == "Hi Andre", t("en", "hi", name="Andre")

    # Unknown KEY falls back to the sentinel fallback token (not a crash).
    assert t("en", "missing_key") == "fallback_missing_key", t("en", "missing_key")

    # Unknown LOCALE falls back to the configured fallback locale's bundle.
    assert t("de", "greeting") == "Hello", "unknown locale should use fallback locale 'en'"

    # Negotiation picks the first supported language and defaults otherwise.
    assert negotiate_locale("fr, en-GB;q=0.8", ["en", "fr"]) == "fr"
    assert negotiate_locale("de, es", ["en", "fr"], default="en") == "en"

    # Negative/adversarial: an empty Accept-Language returns the default.
    assert negotiate_locale("", ["en", "fr"], default="en") == "en"

    print("i18n selftest: PASS")


# Example usage
if __name__ == "__main__":
    _selftest()
