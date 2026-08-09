"""
build_metadata_composer — Generate a build metadata from job descriptions: compose_metadata/assemble_parts order curated BuildParts into a consistent, dependency-respecting assembly plan.

### PART-META-JSON
{
  "name": "build_metadata_composer",
  "layer": "curation",
  "purpose": "Generate a build metadata from job descriptions: compose_metadata/assemble_parts order curated BuildParts into a consistent, dependency-respecting assembly plan.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: compose_metadata(job_spec); assemble_parts(metadata); BuildPart(...); BuildMetadata(...).",
  "outputs": "Returns: compose_metadata -> List[BuildPart]; assemble_parts -> BuildMetadata.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.curation.build_metadata_composer`.",
  "example": "from scrapyard.curation.build_metadata_composer import *",
  "import_path": "scrapyard.curation.build_metadata_composer"
}
### END-PART-META
"""
from dataclasses import dataclass, field
from typing import List
import logging, tempfile

logger = logging.getLogger(__name__)

@dataclass
class BuildPart:
    part_id: int
    name: str
    description: str
    dependencies: List[int] = field(default_factory=list)

@dataclass
class BuildMetadata:
    parts: List[BuildPart]

def compose_metadata(job_spec: dict) -> List[BuildPart]:
    if not job_spec or not isinstance(job_spec, dict):
        return []

    # Placeholder for part composition logic
    parts = []
    for part_id, part_data in job_spec.items():
        dependencies = part_data.get('dependencies', [])
        parts.append(BuildPart(part_id=int(part_id), name=part_data['name'], description=part_data['description'], dependencies=dependencies))
    
    return sorted(parts, key=lambda x: (x.dependencies, x.part_id))

def assemble_parts(metadata: List[BuildPart]) -> BuildMetadata:
    if not metadata or not isinstance(metadata, list):
        return BuildMetadata(parts=[])

    # Placeholder for dependency resolution and ordering logic
    ordered_parts = []
    visited = set()

    def traverse(part):
        if part.part_id in visited:
            return
        visited.add(part.part_id)
        for dep_id in part.dependencies:
            next_part = next((p for p in metadata if p.part_id == dep_id), None)
            if next_part:
                traverse(next_part)
        ordered_parts.append(part)

    for part in metadata:
        traverse(part)

    return BuildMetadata(parts=ordered_parts)

def _selftest():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        # Mock job spec
        job_spec = {
            '1': {'name': 'part1', 'description': 'description1', 'dependencies': []},
            '2': {'name': 'part2', 'description': 'description2', 'dependencies': ['1']},
            '3': {'name': 'part3', 'description': 'description3', 'dependencies': ['2']}
        }

        # Compose metadata
        parts = compose_metadata(job_spec)
        assert len(parts) == 3

        # Assemble parts
        metadata = assemble_parts(parts)
        assert len(metadata.parts) == 3
        assert [p.part_id for p in metadata.parts] == [1, 2, 3]

        logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
