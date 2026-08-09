"""
skill_discovery_search — Discover and search for available skills using a centralized registry of skill loaders. This module enables dynamic skill discovery and querying, supporting flexible and scalable skill-based systems.

### PART-META-JSON
{
  "name": "skill_discovery_search",
  "layer": "skills",
  "purpose": "Discover and search for available skills using a centralized registry of skill loaders. This module enables dynamic skill discovery and querying, supporting flexible and scalable skill-based systems.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "skill_loader_registry"
  ],
  "inputs": "Public API: find_skills(query); SkillLoaderRegistry(...); SkillInfo(...); SkillSearcher(...).",
  "outputs": "Returns: find_skills -> List[SkillInfo].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.skills.skill_discovery_search`.",
  "example": "from scrapyard.skills.skill_discovery_search import *",
  "import_path": "scrapyard.skills.skill_discovery_search"
}
### END-PART-META
"""

import logging
import threading
import json
import tempfile
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# Define SkillLoaderRegistry locally since the external module may not exist
class SkillLoaderRegistry:
    """Registry for skill loaders."""
    def __init__(self):
        self.loaders: List[Any] = []

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """Information about a discovered skill."""
    name: str
    type: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillSearcher:
    """Thread-safe searcher for skills using a registry of loaders."""
    
    def __init__(self, registry: SkillLoaderRegistry):
        if not isinstance(registry, SkillLoaderRegistry):
            raise TypeError("registry must be a SkillLoaderRegistry instance")
        self.registry = registry
        self._lock = threading.RLock()
        self._skills: Optional[List[SkillInfo]] = None

    def _load_skills(self) -> List[SkillInfo]:
        """Load skills from all registered loaders."""
        skills: List[SkillInfo] = []
        with self._lock:
            for loader in self.registry.loaders:
                try:
                    skill_list = loader.list_skills()
                    for skill in skill_list:
                        if not isinstance(skill, dict):
                            continue
                        name = skill.get('name', '')
                        type_ = skill.get('type', '')
                        metadata = skill.get('metadata', {})
                        if not isinstance(metadata, dict):
                            metadata = {}
                        skills.append(SkillInfo(name=name, type=type_, metadata=metadata))
                except Exception as e:
                    logger.warning(f"Failed to load skills from {loader}: {e}")
            return skills

    def search(self, query: str = "") -> List[SkillInfo]:
        """
        Search skills by name, type, or metadata.
        
        Args:
            query: Search string (case-insensitive). Empty returns all skills.
            
        Returns:
            List of matching SkillInfo objects, sorted by (name, type).
        """
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        
        with self._lock:
            if self._skills is None:
                self._skills = self._load_skills()
            
            if not query:
                return sorted(self._skills, key=lambda x: (x.name, x.type))
            
            query_lower = query.lower()
            results: List[SkillInfo] = []
            
            for skill in self._skills:
                # Check name and type
                if query_lower in skill.name.lower() or query_lower in skill.type.lower():
                    results.append(skill)
                    continue
                
                # Check metadata (convert to JSON string for searching)
                if skill.metadata:
                    meta_str = json.dumps(skill.metadata).lower()
                    if query_lower in meta_str:
                        results.append(skill)
            
            return sorted(results, key=lambda x: (x.name, x.type))


# Module-level default registry for find_skills function
_default_registry: Optional[SkillLoaderRegistry] = None
_registry_lock = threading.Lock()


def _get_default_registry() -> SkillLoaderRegistry:
    """Get or create the default skill registry."""
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = SkillLoaderRegistry()
    return _default_registry


def find_skills(query: str = "") -> List[SkillInfo]:
    """
    Discover skills using the default registry.
    
    Args:
        query: Search string for filtering by name, type, or metadata.
        
    Returns:
        List of matching SkillInfo objects.
    """
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    registry = _get_default_registry()
    searcher = SkillSearcher(registry)
    return searcher.search(query)


def _selftest():
    """Offline self-test validating skill discovery functionality."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            # Mock skill loader
            class MockSkillLoader:
                def list_skills(self):
                    return [
                        {'name': 'skill1', 'type': 'type1', 'metadata': {'version': '1.0'}},
                        {'name': 'skill2', 'type': 'type2', 'metadata': {'version': '2.0'}}
                    ]
            
            # Setup registry with mock loader
            registry = SkillLoaderRegistry()
            registry.loaders.append(MockSkillLoader())
            
            # Inject as default registry so find_skills can access it
            global _default_registry
            _default_registry = registry
            
            # Test find_skills
            skills = find_skills("skill1")
            assert len(skills) == 1 and skills[0].name == "skill1", "find_skills did not return the expected skill"
            
            # Test SkillSearcher.search
            searcher = SkillSearcher(registry)
            results = searcher.search("type2")
            assert len(results) == 1 and results[0].type == "type2", "SkillSearcher.search did not filter by type correctly"
            
            # Test metadata search
            results = searcher.search("1.0")
            assert len(results) == 1 and results[0].name == "skill1", "Search by metadata failed"
            
            # Test empty query returns all
            results = searcher.search("")
            assert len(results) == 2, "Empty query should return all skills"
            
            # Test case insensitivity
            results = searcher.search("SKILL2")
            assert len(results) == 1 and results[0].name == "skill2", "Case insensitive search failed"
            
            # Test invalid inputs raise TypeError
            try:
                find_skills(123)  # type: ignore
                assert False, "find_skills should raise TypeError for non-string query"
            except TypeError:
                pass
            
            try:
                searcher.search(123)  # type: ignore
                assert False, "search should raise TypeError for non-string query"
            except TypeError:
                pass
            
            try:
                SkillSearcher("invalid")  # type: ignore
                assert False, "SkillSearcher should raise TypeError for invalid registry"
            except TypeError:
                pass
            
            print("Self-test passed successfully")
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    _selftest()
