"""
skill_loader_registry — Dynamic skill loading and registration: validate_skill_id, import_class and load_skills populate a SkillRegistry from standardized skill metadata, rejecting malformed entries via SkillMetadataError.

### PART-META-JSON
{
  "name": "skill_loader_registry",
  "layer": "skills",
  "purpose": "Dynamic skill loading and registration: validate_skill_id, import_class and load_skills populate a SkillRegistry from standardized skill metadata, rejecting malformed entries via SkillMetadataError.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: validate_skill_id(skill_id); import_class(full_class_string); load_skills(metadata_paths); SkillMetadataError(...); SkillRegistry(...).",
  "outputs": "Returns: validate_skill_id -> None; import_class -> type; load_skills -> None.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.skills.skill_loader_registry`.",
  "example": "from scrapyard.skills.skill_loader_registry import *",
  "import_path": "scrapyard.skills.skill_loader_registry"
}
### END-PART-META
"""
import os
import re
import json
import logging
import sys
from typing import Optional, List, Dict
import tempfile

logger = logging.getLogger(__name__)

class SkillMetadataError(Exception):
    pass

def validate_skill_id(skill_id: str) -> None:
    if not re.match(r'^[a-zA-Z0-9_]+$', skill_id):
        raise ValueError("Invalid skill ID")

class SkillRegistry:
    _skills: Dict[str, type] = {}
    
    def __init__(self):
        self.skills = self.__class__._skills

    def register_skill(self, skill_id: str, skill_class: type) -> None:
        validate_skill_id(skill_id)
        if skill_id in self.skills:
            raise ValueError(f"Skill ID {skill_id} is already registered")
        self.skills[skill_id] = skill_class

    def get_skill(self, skill_id: str) -> Optional[type]:
        return self.skills.get(skill_id)
    
    @classmethod
    def _clear(cls):
        """Clear the registry. For testing purposes only."""
        cls._skills.clear()

def import_class(full_class_string: str) -> type:
    module_name, class_name = full_class_string.rsplit('.', 1)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)

def load_skills(metadata_paths: List[str]) -> None:
    registry = SkillRegistry()
    for metadata_path in metadata_paths:
        if not os.path.isfile(metadata_path):
            raise FileNotFoundError(f"Metadata file {metadata_path} does not exist")
        with open(metadata_path, 'r') as f:
            try:
                metadata_data = json.load(f)
            except json.JSONDecodeError as e:
                raise SkillMetadataError(f"Failed to parse metadata file {metadata_path}: {e}")
        
        if not isinstance(metadata_data, dict):
            raise SkillMetadataError(f"Metadata file {metadata_path} must contain a JSON object")
        
        for skill_id, skill_info in metadata_data.items():
            validate_skill_id(skill_id)
            if 'class' not in skill_info:
                raise SkillMetadataError(f"Missing 'class' key for skill ID {skill_id} in metadata")
            
            try:
                skill_class = import_class(skill_info['class'])
            except ImportError as e:
                raise SkillMetadataError(f"Failed to import class {skill_info['class']} for skill ID {skill_id}: {e}")
            
            registry.register_skill(skill_id, skill_class)

# Self-test suite
def _selftest():
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    
    try:
        # Create a temporary test skill module
        module_path = os.path.join(temp_dir.name, 'test_skill_module.py')
        with open(module_path, 'w') as f:
            f.write("""class TestSkillClass:
    pass

class AnotherTestSkillClass:
    pass
""")
        
        # Add temp directory to sys.path to allow importing the test module
        sys.path.insert(0, temp_dir.name)
        
        # Clear registry to ensure clean state
        SkillRegistry._clear()
        
        # Create a temporary metadata file
        metadata_path = os.path.join(temp_dir.name, 'metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump({
                "skill1": {"class": "test_skill_module.TestSkillClass"},
                "skill2": {"class": "test_skill_module.AnotherTestSkillClass"}
            }, f)
        
        # Load skills from the metadata file
        load_skills([metadata_path])
        
        # Verify skill registration
        registry = SkillRegistry()
        assert len(registry.skills) == 2, "Skills not registered correctly"
        
        # Get and verify specific skills
        skill1_class = registry.get_skill('skill1')
        assert skill1_class is not None, "Skill 'skill1' not found in registry"
        
        skill2_class = registry.get_skill('skill2')
        assert skill2_class is not None, "Skill 'skill2' not found in registry"
        
    finally:
        # Cleanup sys.path
        if temp_dir.name in sys.path:
            sys.path.remove(temp_dir.name)
        temp_dir.cleanup()


if __name__ == "__main__":
    _selftest()
