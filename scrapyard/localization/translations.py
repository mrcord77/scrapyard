"""
translations — Catalog format + loader for messages.

### PART-META-JSON
{
  "name": "translations",
  "layer": "localization",
  "purpose": "Catalog format + loader for messages.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: load_from_file(self, path, format); load_from_dict(self, locale, mapping); save_to_file(self, path, format); get_all(self); get_missing(self, locale); TranslationLoader(...); Translations(...) (plus more).",
  "outputs": "Returns: load_from_file -> None; load_from_dict -> None; save_to_file -> None; get_all -> Dict[str, Dict[str, str]]; get_missing -> List[str].",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import `load_from_file` from `scrapyard.localization.translations` and call it as shown in `example`; run `py -m scrapyard.localization.translations` to see its offline selftest.",
  "example": "from scrapyard.localization.translations import load_from_file",
  "import_path": "scrapyard.localization.translations"
}
### END-PART-META
"""
from typing import Any, Dict, List, Optional, Union, Callable
import json
import yaml
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

class TranslationLoader(BaseModel):
    format: str = "json"
    path: str

def load_from_file(self: TranslationLoader, path: str, format: str = "json") -> None:
    loader = _get_loader(format)
    if not loader:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    with open(path, 'r') as file:
        data = loader(file.read())
        self.load_from_dict(None, data)

def load_from_dict(self: TranslationLoader, locale: str, mapping: Dict[str, Any]) -> None:
    if locale not in self._cat:
        self._cat[locale] = {}
    for key, text in mapping.items():
        if key not in self._cat.get(locale, {}):
            raise ValueError(f"Key {key} is missing in the provided dictionary.")
        self._cat[locale][key] = text

def save_to_file(self: TranslationLoader, path: str, format: str = "json") -> None:
    serializer = _get_serializer(format)
    if not serializer:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    with open(path, 'w') as file:
        file.write(serializer(self._cat))

def get_all(self: TranslationLoader) -> Dict[str, Dict[str, str]]:
    return self._cat

def get_missing(self: TranslationLoader, locale: str) -> List[str]:
    missing = []
    for key in self.default:
        if key not in self._cat.get(locale, {}):
            missing.append(key)
    return missing

def set_default_locale(self: TranslationLoader, locale: str) -> None:
    if locale not in self._cat:
        raise ValueError(f"Locale {locale} does not exist.")
    self.default = locale

def add_bulk(self: TranslationLoader, mappings: Dict[str, Dict[str, str]]) -> None:
    for locale, mapping in mappings.items():
        self.load_from_dict(locale, mapping)

def serialize(self: TranslationLoader, format: str = "json") -> str:
    return _get_serializer(format)(self._cat)

def deserialize(self: TranslationLoader, data: str, format: str = "json") -> None:
    loader = _get_loader(format)
    if not loader:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    self.load_from_dict(None, loader(data))

def register_loader(self: TranslationLoader, format: str, loader: Callable) -> None:
    LOADER_REGISTRY[format] = loader

def register_serializer(self: TranslationLoader, format: str, serializer: Callable) -> None:
    SERIALIZER_REGISTRY[format] = serializer

def get_locale_list(self: TranslationLoader) -> List[str]:
    return list(self._cat.keys())

def get_key_list(self: TranslationLoader, locale: str) -> List[str]:
    return list(self._cat.get(locale, {}).keys())

def get_locale_keys(self: TranslationLoader) -> Dict[str, List[str]]:
    return {locale: list(mapping.keys()) for locale, mapping in self._cat.items()}

def get_locale_missing(self: TranslationLoader, locale: str) -> List[str]:
    missing = []
    for key in self.default:
        if key not in self._cat.get(locale, {}):
            missing.append(key)
    return missing

def _get_loader(format: str) -> Optional[Callable]:
    return LOADER_REGISTRY.get(format)

def _get_serializer(format: str) -> Optional[Callable]:
    return SERIALIZER_REGISTRY.get(format)

LOADER_REGISTRY = {
    "json": json.loads,
    "yaml": yaml.safe_load
}

SERIALIZER_REGISTRY = {
    "json": json.dumps,
    "yaml": yaml.dump
}


# --- grafted from original part (API stability) ---
class Translations:
    """Catalog of {locale: {key: text}} with fallback to a default locale."""
    def __init__(self, default="en"):
        self.default = default; self._cat = {}
    def add(self, locale, mapping: dict):
        self._cat.setdefault(locale, {}).update(mapping)
    def get(self, locale, key, **fmt):
        text = (self._cat.get(locale, {}).get(key)
                or self._cat.get(self.default, {}).get(key) or key)
        return text.format(**fmt) if fmt else text


def _selftest() -> None:
    """Offline self-test: catalog lookup with fallback-to-default-locale, missing-key
    passthrough, interpolation, and JSON round-trip via the loader registry."""
    cat = Translations(default="en")
    cat.add("en", {"greeting": "Hello", "bye": "Goodbye", "hi": "Hi {name}"})
    cat.add("fr", {"greeting": "Bonjour"})  # intentionally missing 'bye'

    # Direct locale hit.
    assert cat.get("fr", "greeting") == "Bonjour"
    assert cat.get("en", "greeting") == "Hello"

    # Missing key in a locale falls back to the default locale's value.
    assert cat.get("fr", "bye") == "Goodbye", "should fall back to default locale 'en'"

    # Interpolation.
    assert cat.get("en", "hi", name="Andre") == "Hi Andre"

    # Negative/adversarial: an entirely unknown key returns the key itself (never
    # raises, never returns None).
    assert cat.get("fr", "does_not_exist_anywhere") == "does_not_exist_anywhere"

    # Locale list reflects what was added.
    assert set(cat.get_key_list("en") if hasattr(cat, "get_key_list") else cat._cat["en"].keys()) >= {"greeting", "bye", "hi"}

    # Loader/serializer registry round-trips JSON.
    payload = _get_serializer("json")({"k": "v"})
    assert _get_loader("json")(payload) == {"k": "v"}
    assert _get_loader("no_such_format") is None  # unknown format -> None, no crash

    print("translations selftest: PASS")


if __name__ == "__main__":
    _selftest()

