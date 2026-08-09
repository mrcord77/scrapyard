"""
file_system_tools — Provides reusable CLI file system utilities for reading, writing, and managing files and directories. Designed to be modular, type-safe, and testable.

### PART-META-JSON
{
  "name": "file_system_tools",
  "layer": "clitools",
  "purpose": "Provides reusable CLI file system utilities for reading, writing, and managing files and directories. Designed to be modular, type-safe, and testable.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: read_file(path, encoding); write_file(path, content, encoding); DirectoryManager(...).",
  "outputs": "Returns: read_file -> str; write_file -> None.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.clitools.file_system_tools`.",
  "example": "from scrapyard.clitools.file_system_tools import *",
  "import_path": "scrapyard.clitools.file_system_tools"
}
### END-PART-META
"""
from typing import List
import os
import re
import logging
from tempfile import TemporaryDirectory

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def read_file(path: str, encoding: str = "utf-8") -> str:
    if not os.path.exists(path):
        logger.error(f"Path {path} does not exist.")
        return ""
    with open(path, 'r', encoding=encoding) as file:
        content = file.read()
    return content

def write_file(path: str, content: str, encoding: str = "utf-8") -> None:
    directory = os.path.dirname(path)
    if not os.path.exists(directory):
        logger.error(f"Directory {directory} does not exist.")
        return
    with open(path, 'w', encoding=encoding) as file:
        file.write(content)

class DirectoryManager:
    def __init__(self, root: str):
        self.root = root

    def create_dir(self, name: str) -> str:
        dir_path = os.path.join(self.root, name)
        try:
            os.makedirs(dir_path, exist_ok=True)
            logger.info(f"Directory created at {dir_path}")
            return dir_path
        except Exception as e:
            logger.error(f"Failed to create directory {dir_path}: {e}")
            return ""

    def delete_dir(self, name: str) -> None:
        dir_path = os.path.join(self.root, name)
        try:
            if os.path.exists(dir_path):
                os.rmdir(dir_path)
                logger.info(f"Directory deleted at {dir_path}")
            else:
                logger.error(f"Directory {dir_path} does not exist.")
        except Exception as e:
            logger.error(f"Failed to delete directory {dir_path}: {e}")

    def list_files(self, pattern: str = "*") -> List[str]:
        dir_path = os.path.join(self.root)
        try:
            files = [os.path.join(dir_path, f) for f in os.listdir(dir_path) if re.match(pattern, f)]
            logger.info(f"Files matching {pattern} found: {files}")
            return files
        except Exception as e:
            logger.error(f"Failed to list files in directory {dir_path}: {e}")
            return []

def _selftest():
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        test_file = os.path.join(tmp_dir, "test.txt")
        test_dir = os.path.join(tmp_dir, "test_dir")

        # Test write_file
        write_file(test_file, "Hello, World!")
        assert read_file(test_file) == "Hello, World!"

        # Test read_file
        test_content = "This is a test content."
        with open(test_file, 'w') as file:
            file.write(test_content)
        assert read_file(test_file) == test_content

        # Test DirectoryManager
        dm = DirectoryManager(tmp_dir)
        subdir_path = dm.create_dir("subdir")
        assert os.path.isdir(subdir_path)

        # Test delete_dir
        dm.delete_dir("subdir")
        assert not os.path.isdir(subdir_path)

if __name__ == "__main__":
    _selftest()
