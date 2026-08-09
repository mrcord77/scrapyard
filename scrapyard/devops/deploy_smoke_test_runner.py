"""
deploy_smoke_test_runner — Run smoke tests post-deployment to validate core system functionality, ensuring minimal operational impact and rapid failure detection.

### PART-META-JSON
{
  "name": "deploy_smoke_test_runner",
  "layer": "devops",
  "purpose": "Run smoke tests post-deployment to validate core system functionality, ensuring minimal operational impact and rapid failure detection.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: run_smoke_tests(test_config); execute_command(command); SmokeTestResult(...).",
  "outputs": "Returns: run_smoke_tests -> List[SmokeTestResult]; execute_command -> bool.",
  "files_created": [],
  "security_notes": "Invokes subprocesses with an argument vector and shell=False. String commands are parsed with shlex rather than evaluated by a shell; prefer an explicit list of arguments when any value is externally supplied.",
  "ai_usage": "Import what you need from `scrapyard.devops.deploy_smoke_test_runner`.",
  "example": "from scrapyard.devops.deploy_smoke_test_runner import *",
  "import_path": "scrapyard.devops.deploy_smoke_test_runner"
}
### END-PART-META
"""

from typing import Optional, List, Dict, Any, Sequence
import shlex
import subprocess
import sys
import time

class SmokeTestResult:
    def __init__(self, test_name: str, status: str, message: Optional[str] = None, duration_seconds: float = 0.0):
        self.test_name = test_name
        self.status = status
        self.message = message
        self.duration_seconds = duration_seconds

def run_smoke_tests(test_config: Dict[str, Any]) -> List[SmokeTestResult]:
    results = []
    
    # Load tests from config
    for test_name, test_details in test_config.items():
        start_time = time.time()
        
        try:
            # Execute the test based on the provided configuration
            if 'command' in test_details:
                result_status = execute_command(test_details['command'])
            elif 'function' in test_details:
                result_status = test_details['function']()
            else:
                raise ValueError(f"Test {test_name} is missing required details.")
            
            end_time = time.time()
            duration_seconds = end_time - start_time
            
            # Create and append the SmokeTestResult
            results.append(SmokeTestResult(test_name, 'PASS' if result_status else 'FAIL', None, duration_seconds))
        except Exception as e:
            end_time = time.time()
            duration_seconds = end_time - start_time
            results.append(SmokeTestResult(test_name, 'ERROR', str(e), duration_seconds))
    
    return results

def execute_command(command: str | Sequence[str], timeout: float = 60.0) -> bool:
    """Execute a command without invoking a shell.

    An explicit argument sequence is the safest input. Strings are supported for
    compatibility and split according to the current platform; shell operators
    such as ``&&``, pipes, substitutions, and redirects are never interpreted.
    """
    if isinstance(command, str):
        argv = shlex.split(command, posix=sys.platform != "win32")
    else:
        argv = [str(item) for item in command]
    if not argv:
        raise ValueError("command must not be empty")
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0

# Self-test function to validate the implementation
def _selftest():
    test_config = {
        'test1': {'command': [sys.executable, '-c', 'print("Test 1 passed")']},
        'test2': {'function': lambda: True},
        'test3': {'command': [sys.executable, '-c', 'raise SystemExit(3)']}
    }
    
    results = run_smoke_tests(test_config)
    
    assert len(results) == 3
    for result in results:
        if result.test_name == 'test1':
            assert result.status == 'PASS'
        elif result.test_name == 'test2':
            assert result.status == 'PASS'
        elif result.test_name == 'test3':
            assert result.status == 'FAIL'
    
    print("Self-test passed successfully.")


if __name__ == "__main__":
    _selftest()

