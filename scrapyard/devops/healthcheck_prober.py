"""
healthcheck_prober — Generate customizable health check endpoints and readiness/liveness probes for cloud-native services, ensuring robustness and observability in distributed systems.

### PART-META-JSON
{
  "name": "healthcheck_prober",
  "layer": "devops",
  "purpose": "Generate customizable health check endpoints and readiness/liveness probes for cloud-native services, ensuring robustness and observability in distributed systems.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: create_health_check(name, interval, timeout, callback); HealthProbe(...).",
  "outputs": "Returns: create_health_check -> Dict[str, Any].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.devops.healthcheck_prober`.",
  "example": "from scrapyard.devops.healthcheck_prober import *",
  "import_path": "scrapyard.devops.healthcheck_prober"
}
### END-PART-META
"""

from typing import Dict, Any, Callable
import json
import logging
import tempfile

logger = logging.getLogger(__name__)


def _selftest():
    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Mock callback function
        def mock_callback():
            return {"status": "healthy", "details": {}}

        # Create health check
        probe_config = create_health_check("mock_probe", 1, 1, mock_callback)
        assert isinstance(probe_config, dict)

        # Initialize HealthProbe with the config
        probe = HealthProbe(**probe_config)

        # Evaluate and assert valid status
        result = probe.evaluate()
        assert "status" in result
        assert "details" in result

        # Convert to JSON and YAML
        json_output = probe.to_json()
        yaml_output = probe.to_yaml()

        # Assert valid syntax for JSON and YAML
        try:
            json.loads(json_output)
        except json.JSONDecodeError as e:
            raise AssertionError(f"Invalid JSON: {e}")

        try:
            import yaml  # Import here to avoid re-import issues in functions
            yaml.safe_load(yaml_output)
        except yaml.YAMLError as e:
            raise AssertionError(f"Invalid YAML: {e}")

        # Evaluate with mock callback and assert structured health status
        result = probe.evaluate()
        assert "status" in result
        assert "details" in result

        logger.info("Self-test passed successfully")


class HealthProbe:
    """
    A health probe that evaluates custom health check logic with configurable
    intervals and timeouts.
    """

    def __init__(self, name: str, interval: int, timeout: int, callback: Callable):
        """
        Initialize a health probe.

        :param name: Name of the health probe.
        :param interval: Interval in seconds between checks.
        :param timeout: Timeout for each check in seconds.
        :param callback: Function to execute during the health check. Should return a dict.
        """
        self.name: str = name
        self.interval: int = interval
        self.timeout: int = timeout
        self.callback: Callable = callback
        self.status: str = "unknown"
        self.details: Dict[str, Any] = {}

    def evaluate(self) -> Dict[str, Any]:
        """
        Execute the health check callback and update internal status.

        :return: Dictionary containing the evaluation result with status, name,
                 interval, timeout, and details.
        """
        try:
            result = self.callback()
            self.status = "healthy"
            self.details = result.get("details", {})
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            self.status = "unhealthy"
            self.details = {"error": str(e)}

        return {
            "status": self.status,
            "name": self.name,
            "interval": self.interval,
            "timeout": self.timeout,
            "details": self.details
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the current probe state to a dictionary.

        :return: Dictionary representation excluding the callback function.
        """
        return {
            "name": self.name,
            "interval": self.interval,
            "timeout": self.timeout,
            "status": self.status,
            "details": self.details
        }

    def to_json(self) -> str:
        """
        Serialize the probe state to a JSON formatted string.

        :return: JSON string representation of the probe.
        """
        return json.dumps(self.to_dict(), indent=4)

    def to_yaml(self) -> str:
        """
        Serialize the probe state to a YAML formatted string.

        :return: YAML string representation of the probe.
        """
        import yaml  # Import here to avoid re-import issues in functions
        return yaml.dump(self.to_dict())


def create_health_check(name: str, interval: int, timeout: int, callback: Callable) -> Dict[str, Any]:
    """
    Create a health check configuration with the provided parameters.

    :param name: Name of the health check.
    :param interval: Interval in seconds between checks.
    :param timeout: Timeout for each check in seconds.
    :param callback: Function to execute during the health check.
    :return: Dictionary containing the health check configuration suitable for
             unpacking into HealthProbe constructor.
    """
    return {
        "name": name,
        "interval": interval,
        "timeout": timeout,
        "callback": callback
    }


if __name__ == "__main__":
    _selftest()
