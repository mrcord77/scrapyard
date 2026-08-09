"""
semantic_version_bumper — Automate semantic version number bumping and changelog generation for software projects. Ensures consistent versioning and tracks changes in a structured format.

### PART-META-JSON
{
  "name": "semantic_version_bumper",
  "layer": "devops",
  "purpose": "Automate semantic version number bumping and changelog generation for software projects. Ensures consistent versioning and tracks changes in a structured format.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: parse_version(version_str); bump_version(current_version, bump_type, commit_messages); ChangelogEntry(...).",
  "outputs": "Returns: parse_version -> tuple[int, int, int]; bump_version -> str.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.devops.semantic_version_bumper`.",
  "example": "from scrapyard.devops.semantic_version_bumper import *",
  "import_path": "scrapyard.devops.semantic_version_bumper"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import List
import re
import logging

logger = logging.getLogger(__name__)

@dataclass
class ChangelogEntry:
    version: str
    type: str
    message: str

def parse_version(version_str: str) -> tuple[int, int, int]:
    match = re.match(r'^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?', version_str)
    if not match:
        raise ValueError(f"Invalid semantic version string: {version_str}")
    return tuple(map(int, match.groups()[:3]))

def bump_version(current_version: str, bump_type: str, commit_messages: List[str]) -> str:
    current_major, current_minor, current_patch = parse_version(current_version)
    
    if bump_type == 'major':
        new_major = current_major + 1
        new_minor = 0
        new_patch = 0
    elif bump_type == 'minor':
        new_major = current_major
        new_minor = current_minor + 1
        new_patch = 0
    elif bump_type == 'patch':
        new_major = current_major
        new_minor = current_minor
        new_patch = current_patch + 1
    
    # Validate commit messages for correct bump type
    if bump_type == 'major' and not any(re.search(r'\bfeat\b', msg, re.IGNORECASE) for msg in commit_messages):
        raise ValueError("No major features found in commit messages")
    elif bump_type == 'minor' and not any(re.search(r'\bfix|feat\b', msg, re.IGNORECASE) for msg in commit_messages):
        raise ValueError("No minor fixes or features found in commit messages")
    elif bump_type == 'patch' and not any(re.search(r'\bfix\b', msg, re.IGNORECASE) for msg in commit_messages):
        raise ValueError("No bug fixes found in commit messages")
    
    return f"v{new_major}.{new_minor}.{new_patch}"

def _selftest():
    # Test bump_version function
    assert bump_version('1.2.3', 'major', ['feat: add new feature']) == 'v2.0.0'
    assert bump_version('1.2.3', 'minor', ['fix: bug in module A', 'feat: add new feature']) == 'v1.3.0'
    assert bump_version('1.2.3', 'patch', ['fix: bug in module B']) == 'v1.2.4'
    
    # Test ChangelogEntry creation
    entry = ChangelogEntry(version='1.2.3', type='major', message='feat: add new feature')
    assert entry.version == '1.2.3'
    assert entry.type == 'major'
    assert entry.message == 'feat: add new feature'
    
    # Test exception for invalid version string
    try:
        parse_version('invalid-version')
        assert False, "Expected ValueError"
    except ValueError as e:
        assert str(e) == "Invalid semantic version string: invalid-version"

    print("All tests passed!")

if __name__ == "__main__":
    _selftest()
