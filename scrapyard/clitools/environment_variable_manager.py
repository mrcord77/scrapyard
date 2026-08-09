"""
environment_variable_manager — Manages environment variables for CLI tools, ensuring consistent access and validation across the application. Provides a safe and reusable interface for reading, defaulting, and validating environmen

### PART-META-JSON
{
  "name": "environment_variable_manager",
  "layer": "clitools",
  "purpose": "Manages environment variables for CLI tools, ensuring consistent access and validation across the application. Provides a safe and reusable interface for reading, defaulting, and validating environmen",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: get_env_var(name, default); EnvVarManager(...).",
  "outputs": "Returns: get_env_var -> str.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.clitools.environment_variable_manager`.",
  "example": "from scrapyard.clitools.environment_variable_manager import *",
  "import_path": "scrapyard.clitools.environment_variable_manager"
}
### END-PART-META
"""

import os
import threading
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


def _normalize_key(key: str) -> str:
    """Convert nested key notation to flat env var name.
    
    Replaces dots with underscores and converts to uppercase.
    Example: 'database.host' -> 'DATABASE_HOST'
    """
    return key.replace('.', '_').upper()


def get_env_var(name: str, default: Optional[str] = None) -> str:
    """Get environment variable from os.environ with optional default.
    
    Args:
        name: The environment variable name
        default: Optional default value if variable is not set
        
    Returns:
        The environment variable value as string
        
    Raises:
        KeyError: If variable is not set and no default provided
    """
    if name in os.environ:
        return os.environ[name]
    if default is not None:
        return default
    raise KeyError(f"Environment variable '{name}' not set")


class EnvVarManager:
    """Thread-safe manager for environment variables with nested key support."""
    
    def __init__(self, env_vars: Optional[Dict[str, str]] = None):
        """Initialize the manager.
        
        Args:
            env_vars: Optional dictionary to use as environment storage.
                     If None, uses os.environ.
        """
        self._env = env_vars if env_vars is not None else os.environ
        self._lock = threading.RLock()
    
    def get(self, name: str, default: Optional[str] = None) -> str:
        """Get environment variable with nested key support.
        
        Args:
            name: Variable name (supports dot notation like 'app.database.host')
            default: Optional default value
            
        Returns:
            The variable value as string
            
        Raises:
            KeyError: If variable not found and no default provided
        """
        normalized = _normalize_key(name)
        with self._lock:
            if normalized in self._env:
                return self._env[normalized]
            if default is not None:
                return default
            raise KeyError(f"Environment variable '{name}' ({normalized}) not set")
    
    def has(self, name: str) -> bool:
        """Check if environment variable exists.
        
        Args:
            name: Variable name (supports dot notation)
            
        Returns:
            True if exists, False otherwise
        """
        normalized = _normalize_key(name)
        with self._lock:
            return normalized in self._env
    
    def set(self, name: str, value: str) -> None:
        """Set environment variable.
        
        Args:
            name: Variable name (supports dot notation)
            value: String value to set
            
        Raises:
            TypeError: If value is not a string
        """
        if not isinstance(value, str):
            raise TypeError(f"Value must be str, got {type(value).__name__}")
        normalized = _normalize_key(name)
        with self._lock:
            self._env[normalized] = value
    
    def unset(self, name: str) -> None:
        """Remove environment variable.
        
        Args:
            name: Variable name (supports dot notation)
        """
        normalized = _normalize_key(name)
        with self._lock:
            if normalized in self._env:
                del self._env[normalized]
    
    def get_int(self, name: str, default: Optional[int] = None) -> int:
        """Get variable as integer with validation.
        
        Args:
            name: Variable name
            default: Optional default integer value
            
        Returns:
            Integer value
            
        Raises:
            KeyError: If not found and no default
            ValueError: If value cannot be converted to int
        """
        try:
            val_str = self.get(name)
            return int(val_str)
        except KeyError:
            if default is not None:
                return default
            raise
        except ValueError as e:
            raise ValueError(f"Environment variable '{name}' has invalid integer value: {self.get(name)}") from e
    
    def get_bool(self, name: str, default: Optional[bool] = None) -> bool:
        """Get variable as boolean with validation.
        
        Recognizes: true/false, yes/no, 1/0, on/off (case insensitive)
        
        Args:
            name: Variable name
            default: Optional default boolean value
            
        Returns:
            Boolean value
            
        Raises:
            KeyError: If not found and no default
            ValueError: If value cannot be converted to bool
        """
        try:
            val_str = self.get(name).lower().strip()
            if val_str in ('true', '1', 'yes', 'on'):
                return True
            if val_str in ('false', '0', 'no', 'off'):
                return False
            raise ValueError(f"Cannot convert '{val_str}' to boolean")
        except KeyError:
            if default is not None:
                return default
            raise
        except ValueError as e:
            if "Cannot convert" in str(e):
                raise ValueError(f"Environment variable '{name}' has invalid boolean value: {self.get(name)}") from e
            raise
    
    def get_float(self, name: str, default: Optional[float] = None) -> float:
        """Get variable as float with validation.
        
        Args:
            name: Variable name
            default: Optional default float value
            
        Returns:
            Float value
            
        Raises:
            KeyError: If not found and no default
            ValueError: If value cannot be converted to float
        """
        try:
            val_str = self.get(name)
            return float(val_str)
        except KeyError:
            if default is not None:
                return default
            raise
        except ValueError as e:
            raise ValueError(f"Environment variable '{name}' has invalid float value: {self.get(name)}") from e


def _selftest() -> None:
    """Run comprehensive offline self-test suite."""
    import tempfile
    import sqlite3
    import threading
    
    logger.info("Starting environment_variable_manager selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        # Setup SQLite for test tracking (satisfies temp SQLite requirement)
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS test_log (test_name TEXT, status TEXT)")
        
        try:
            # Test 1: get_env_var returns default when missing
            test_key = "_SCRAPYARD_TEST_VAR_"
            if test_key in os.environ:
                del os.environ[test_key]
            result = get_env_var(test_key, "default_value")
            assert result == "default_value", f"Expected default_value, got {result}"
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("get_env_var_default", "PASS"))
            
            # Test 2: get_env_var raises KeyError when missing and no default
            try:
                get_env_var("_NONEXISTENT_VAR_")
                assert False, "Should have raised KeyError"
            except KeyError:
                pass
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("get_env_var_keyerror", "PASS"))
            
            # Test 3: EnvVarManager get/set/has/unset with custom dict
            test_env: Dict[str, str] = {}
            manager = EnvVarManager(env_vars=test_env)
            
            manager.set("app.name", "TestApp")
            assert manager.has("app.name") is True
            assert manager.get("app.name") == "TestApp"
            assert test_env["APP_NAME"] == "TestApp"  # Verify normalization
            
            manager.unset("app.name")
            assert manager.has("app.name") is False
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("manager_basic_ops", "PASS"))
            
            # Test 4: Nested keys handling
            manager.set("database.connection.host", "localhost")
            assert manager.get("database.connection.host") == "localhost"
            assert manager.get("DATABASE_CONNECTION_HOST") == "localhost"  # Direct normalized access
            manager.unset("database.connection.host")
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("nested_keys", "PASS"))
            
            # Test 5: Type validation raises appropriate errors
            manager.set("invalid_int", "not_a_number")
            try:
                manager.get_int("invalid_int")
                assert False, "Should raise ValueError for invalid int"
            except ValueError:
                pass
            
            manager.set("invalid_bool", "maybe")
            try:
                manager.get_bool("invalid_bool")
                assert False, "Should raise ValueError for invalid bool"
            except ValueError:
                pass
            
            manager.set("invalid_float", "abc")
            try:
                manager.get_float("invalid_float")
                assert False, "Should raise ValueError for invalid float"
            except ValueError:
                pass
            
            # Verify valid types work
            manager.set("valid_int", "42")
            assert manager.get_int("valid_int") == 42
            
            manager.set("valid_bool", "true")
            assert manager.get_bool("valid_bool") is True
            
            manager.set("valid_float", "3.14")
            assert abs(manager.get_float("valid_float") - 3.14) < 0.001
            
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("type_validation", "PASS"))
            
            # Test 6: Thread safety
            errors = []
            success_count = [0]
            
            def worker(thread_id: int):
                try:
                    for i in range(50):
                        key = f"thread_{thread_id}_key_{i % 5}"
                        manager.set(key, str(i))
                        _ = manager.get(key)
                        manager.get_int(key)
                        if i % 10 == 0:
                            manager.unset(key)
                    with threading.Lock():
                        success_count[0] += 1
                except Exception as e:
                    errors.append(str(e))
            
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            assert len(errors) == 0, f"Thread errors occurred: {errors}"
            assert success_count[0] == 10, "Not all threads completed successfully"
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("thread_safety", "PASS"))
            
            # Test 7: Default values in typed getters
            assert manager.get_int("missing_int", 100) == 100
            assert manager.get_bool("missing_bool", True) is True
            assert abs(manager.get_float("missing_float", 1.5) - 1.5) < 0.001
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("typed_defaults", "PASS"))
            
            # Test 8: Type validation in set()
            try:
                manager.set("bad_type", 123)  # type: ignore
                assert False, "Should raise TypeError for non-string value"
            except TypeError:
                pass
            conn.execute("INSERT INTO test_log VALUES (?, ?)", ("set_type_validation", "PASS"))
            
            # Verify SQLite operations worked
            conn.commit()
            cursor = conn.execute("SELECT COUNT(*) FROM test_log WHERE status = 'PASS'")
            passed = cursor.fetchone()[0]
            assert passed >= 8, f"Expected at least 8 passed tests, got {passed}"
            
            logger.info(f"Selftest completed: {passed} tests passed")
            
        finally:
            conn.close()


if __name__ == "__main__":
    _selftest()
