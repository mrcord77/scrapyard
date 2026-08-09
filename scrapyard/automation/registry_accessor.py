"""
registry_accessor — Safe, type-aware Windows registry read/write/delete with root-key
resolution (string or handle), guarded winreg import for cross-platform importability,
and an isolated in-memory registry contract test.

### PART-META-JSON
{
  "name": "registry_accessor",
  "layer": "automation",
  "purpose": "Reads, writes, and deletes Windows registry values with the root key honored on BOTH read and write paths (accepts winreg handles or names like 'HKEY_LOCAL_MACHINE'/'HKLM'), correct value typing for REG_SZ/EXPAND_SZ/MULTI_SZ/DWORD/QWORD/BINARY, and honest RuntimeError on non-Windows platforms (module still imports there).",
  "addition": true,
  "status": "core",
  "dependencies": [
    "winreg (Windows stdlib; import guarded on other platforms)"
  ],
  "inputs": "Root key (winreg constant or string alias), subkey path, value name, value + registry type for writes.",
  "outputs": "Python-typed registry values (str, int, bytes, list[str]) or None when absent; write/delete return None.",
  "files_created": [],
  "security_notes": "Writes to the Windows registry are system mutations: HKLM writes require elevation and can affect every user and boot behavior (Run keys are a persistence vector) - restrict callers to HKCU unless elevation is deliberate, and never write attacker-controlled subkey paths or values. Registry values routinely contain secrets (product keys, tokens); this module never logs value data, only key paths. Deletes are irreversible. The selftest replaces winreg with an in-memory contract double and never touches the host registry.",
  "ai_usage": "read_registry_value('HKCU', r'Software\\\\X', 'Name'); write_registry_value('HKCU', r'Software\\\\X', 'Name', 'val'); delete_registry_value/delete_registry_key to clean up.",
  "example": "from scrapyard.automation.registry_accessor import read_registry_value",
  "import_path": "scrapyard.automation.registry_accessor"
}
### END-PART-META
"""
import logging
import sys
from typing import Any, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    import winreg
except ImportError:  # non-Windows: module stays importable, calls fail honestly
    winreg = None

RootKey = Union[int, str]

_ROOT_ALIASES = {
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE", "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER", "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CLASSES_ROOT": "HKEY_CLASSES_ROOT", "HKCR": "HKEY_CLASSES_ROOT",
    "HKEY_USERS": "HKEY_USERS", "HKU": "HKEY_USERS",
    "HKEY_CURRENT_CONFIG": "HKEY_CURRENT_CONFIG", "HKCC": "HKEY_CURRENT_CONFIG",
}


def _require_winreg() -> None:
    if winreg is None:
        raise RuntimeError(
            "registry_accessor requires Windows (winreg unavailable on "
            f"{sys.platform}); no registry exists on this platform")


def resolve_root_key(key: RootKey) -> int:
    """Resolve a root key given as a winreg handle int or a name/alias string."""
    _require_winreg()
    if isinstance(key, int):
        return key
    if isinstance(key, str):
        name = _ROOT_ALIASES.get(key.strip().upper())
        if name is not None:
            return getattr(winreg, name)
    raise ValueError(f"Unrecognized registry root key: {key!r}")


def convert_to_python_type(data: Any, value_type: int) -> Any:
    """Normalize a value returned by winreg.QueryValueEx.

    winreg already decodes REG_SZ/EXPAND_SZ to str, DWORD/QWORD to int,
    MULTI_SZ to list[str], and BINARY to bytes; this validates and passes
    through, and decodes raw bytes if a caller hands them in directly.
    """
    _require_winreg()
    if value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        if isinstance(data, bytes):  # raw export data, not from QueryValueEx
            return data.decode("utf-16-le").rstrip("\x00")
        return str(data)
    if value_type in (winreg.REG_DWORD, winreg.REG_QWORD):
        if isinstance(data, bytes):
            return int.from_bytes(data, byteorder="little", signed=False)
        return int(data)
    if value_type == winreg.REG_MULTI_SZ:
        return [str(s) for s in data]
    if value_type == winreg.REG_BINARY:
        return bytes(data) if data is not None else b""
    raise ValueError(f"Unsupported registry value type: {value_type}")


def convert_to_binary(value: Any, value_type: int) -> Any:
    """Coerce a Python object to the form winreg.SetValueEx expects.

    (Historic name kept for compatibility; SetValueEx wants str for string
    types, int for DWORD/QWORD, list[str] for MULTI_SZ, bytes for BINARY -
    not hand-encoded byte blobs.)
    """
    _require_winreg()
    if value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        return str(value)
    if value_type in (winreg.REG_DWORD, winreg.REG_QWORD):
        return int(value)
    if value_type == winreg.REG_MULTI_SZ:
        return [str(s) for s in value]
    if value_type == winreg.REG_BINARY:
        return bytes(value)
    raise ValueError(f"Unsupported registry value type: {value_type}")


def read_registry_value(key: RootKey, subkey: str, value_name: str) -> Any:
    """Read a registry value under the GIVEN root key (honored, not hardcoded).

    Returns the Python-typed value, or None when the key/value is absent.
    """
    root = resolve_root_key(key)
    try:
        with winreg.OpenKey(root, subkey) as reg_key:
            value_data, value_type = winreg.QueryValueEx(reg_key, value_name)
            return convert_to_python_type(value_data, value_type)
    except FileNotFoundError:
        logger.warning("Registry key/value not found: %s\\%s:%s",
                       key, subkey, value_name)
        return None
    except OSError as e:
        logger.error("Failed to read registry value %s\\%s:%s (%s)",
                     key, subkey, value_name, e)
        raise


def write_registry_value(key: RootKey, subkey: str, value_name: str,
                         value: Any, value_type: Optional[int] = None) -> None:
    """Write a registry value under the given root key, creating the subkey.

    value_type defaults to REG_SZ (str), REG_DWORD (int), REG_BINARY (bytes),
    or REG_MULTI_SZ (list) based on the Python type.
    """
    root = resolve_root_key(key)
    if value_type is None:
        if isinstance(value, int) and not isinstance(value, bool):
            value_type = winreg.REG_DWORD
        elif isinstance(value, (bytes, bytearray)):
            value_type = winreg.REG_BINARY
        elif isinstance(value, (list, tuple)):
            value_type = winreg.REG_MULTI_SZ
        else:
            value_type = winreg.REG_SZ
    try:
        with winreg.CreateKeyEx(root, subkey, 0, winreg.KEY_WRITE) as reg_key:
            winreg.SetValueEx(reg_key, value_name, 0, value_type,
                              convert_to_binary(value, value_type))
    except OSError as e:
        logger.error("Failed to write registry value %s\\%s:%s (%s)",
                     key, subkey, value_name, e)
        raise


def delete_registry_value(key: RootKey, subkey: str, value_name: str) -> bool:
    """Delete one value; returns True if deleted, False if it did not exist."""
    root = resolve_root_key(key)
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE) as reg_key:
            winreg.DeleteValue(reg_key, value_name)
            return True
    except FileNotFoundError:
        return False


def delete_registry_key(key: RootKey, subkey: str) -> bool:
    """Delete an (empty) subkey; returns True if deleted, False if absent."""
    root = resolve_root_key(key)
    try:
        winreg.DeleteKey(root, subkey)
        return True
    except FileNotFoundError:
        return False


def _selftest() -> None:
    """Exercise the registry contract without mutating the host registry."""
    class _Key:
        def __init__(self, fake, root, subkey):
            self.fake, self.root, self.subkey = fake, root, subkey
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    class _FakeWinreg:
        HKEY_LOCAL_MACHINE = 1
        HKEY_CURRENT_USER = 2
        HKEY_CLASSES_ROOT = 3
        HKEY_USERS = 4
        HKEY_CURRENT_CONFIG = 5
        REG_SZ = 10
        REG_EXPAND_SZ = 11
        REG_MULTI_SZ = 12
        REG_DWORD = 13
        REG_QWORD = 14
        REG_BINARY = 15
        KEY_WRITE = 20
        KEY_SET_VALUE = 21
        values = {}

        @classmethod
        def CreateKeyEx(cls, root, subkey, *_):
            return _Key(cls, root, subkey)
        @classmethod
        def OpenKey(cls, root, subkey, *_):
            if not any(k[:2] == (root, subkey) for k in cls.values):
                raise FileNotFoundError(subkey)
            return _Key(cls, root, subkey)
        @classmethod
        def SetValueEx(cls, key, name, _reserved, value_type, value):
            cls.values[(key.root, key.subkey, name)] = (value, value_type)
        @classmethod
        def QueryValueEx(cls, key, name):
            try:
                return cls.values[(key.root, key.subkey, name)]
            except KeyError as exc:
                raise FileNotFoundError(name) from exc
        @classmethod
        def DeleteValue(cls, key, name):
            try:
                del cls.values[(key.root, key.subkey, name)]
            except KeyError as exc:
                raise FileNotFoundError(name) from exc
        @classmethod
        def DeleteKey(cls, root, subkey):
            keys = [k for k in cls.values if k[:2] == (root, subkey)]
            if not keys:
                raise FileNotFoundError(subkey)
            for key in keys:
                del cls.values[key]

    global winreg
    real_winreg = winreg
    winreg = _FakeWinreg
    test_subkey = r"Software\ScrapyardRegistryAccessorTest"
    try:
        # Root-key resolution: aliases and raw handles agree
        assert resolve_root_key("HKLM") == winreg.HKEY_LOCAL_MACHINE
        assert resolve_root_key("hkey_current_user") == winreg.HKEY_CURRENT_USER
        assert resolve_root_key(winreg.HKEY_CURRENT_USER) == winreg.HKEY_CURRENT_USER
        try:
            resolve_root_key("HKEY_NOPE")
            raise AssertionError("bad root must raise")
        except ValueError:
            pass

        # String round-trip under the DECLARED root (HKCU, not hardcoded HKLM)
        write_registry_value("HKCU", test_subkey, "TestString", "TestValue123")
        assert read_registry_value("HKCU", test_subkey, "TestString") == "TestValue123"
        # The same read via HKLM must NOT find it - proves the root is honored
        assert read_registry_value("HKLM", test_subkey, "TestString") is None

        # DWORD and BINARY round-trips
        write_registry_value("HKCU", test_subkey, "TestDword", 42)
        assert read_registry_value("HKCU", test_subkey, "TestDword") == 42
        write_registry_value("HKCU", test_subkey, "TestBin", b"\x01\x02\x03")
        assert read_registry_value("HKCU", test_subkey, "TestBin") == b"\x01\x02\x03"

        # MULTI_SZ round-trip
        write_registry_value("HKCU", test_subkey, "TestMulti", ["a", "b"])
        assert read_registry_value("HKCU", test_subkey, "TestMulti") == ["a", "b"]

        # Missing value reads as None
        assert read_registry_value("HKCU", test_subkey, "NoSuchValue") is None

        # Deletes
        assert delete_registry_value("HKCU", test_subkey, "TestString") is True
        assert delete_registry_value("HKCU", test_subkey, "TestString") is False
        assert read_registry_value("HKCU", test_subkey, "TestString") is None
    finally:
        winreg = real_winreg

    print("registry_accessor selftest: PASS (isolated registry double)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    _selftest()
