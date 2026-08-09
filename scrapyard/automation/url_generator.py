"""
url_generator — Generates URLs based on provided templates or patterns, supporting dynamic replacement and sitemap integration.

### PART-META-JSON
{
  "name": "url_generator",
  "layer": "automation",
  "purpose": "Generates URLs based on provided templates or patterns, supporting dynamic replacement and sitemap integration.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "sitemap_walker"
  ],
  "inputs": "Public API: generate_from_template(template, vars); TemplateParser(...); UrlGenerator(...).",
  "outputs": "Returns: generate_from_template -> List[str].",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.url_generator`.",
  "example": "from scrapyard.automation.url_generator import *",
  "import_path": "scrapyard.automation.url_generator"
}
### END-PART-META
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import re, logging

logger = logging.getLogger(__name__)

@dataclass
class TemplateParser:
    template: str
    variables: Dict[str, Any] = field(default_factory=dict)

    def parse(self) -> List[str]:
        """
        Parses the template and returns a list of variable names.
        """
        pattern = r'\{(\w+)\}'
        matches = re.findall(pattern, self.template)
        return matches

def generate_from_template(template: str, vars: Dict[str, Any]) -> List[str]:
    """
    Generates URLs from a template with provided variables.
    """
    parser = TemplateParser(template=template)
    variable_names = parser.parse()
    
    if not all(var in vars for var in variable_names):
        missing_vars = [var for var in variable_names if var not in vars]
        logger.warning(f"Missing variables: {missing_vars}")
        return []
    
    urls = []
    for values in _generate_combinations(vars, variable_names):
        url = template.format(**values)
        urls.append(url)
    
    return urls

def _generate_combinations(variables: Dict[str, Any], keys: List[str]) -> List[Dict[str, Any]]:
    """
    Generates all possible combinations of variables.
    """
    if not keys:
        yield {}
        return
    
    key = keys[0]
    for value in variables.get(key, []):
        sub_combinations = _generate_combinations(variables, keys[1:])
        for comb in sub_combinations:
            comb[key] = value
            yield comb

class UrlGenerator:
    def __init__(self, sitemap_walker):
        self.sitemap_walker = sitemap_walker
    
    def generate_from_template(self, template: str, vars: Dict[str, Any]) -> List[str]:
        """
        Generates URLs from a template with provided variables.
        """
        return generate_from_template(template, vars)
    
    def generate_from_sitemap(self) -> List[str]:
        """
        Generates URLs by walking through the sitemap.
        """
        return self.sitemap_walker.walk()

def _selftest():
    # Setup
    class MockSitemapWalker:
        def walk(self) -> List[str]:
            return ["http://example.com/page1", "http://example.com/page2"]
    
    template = "http://example.com/{page_id}"
    vars = {"page_id": [1, 2]}
    
    # Generate from template
    urls_from_template = generate_from_template(template, vars)
    assert urls_from_template == ["http://example.com/1", "http://example.com/2"]
    
    # Generate from sitemap
    url_gen = UrlGenerator(MockSitemapWalker())
    urls_from_sitemap = url_gen.generate_from_sitemap()
    assert urls_from_sitemap == ["http://example.com/page1", "http://example.com/page2"]
    
    logger.info("Self-test passed.")

if __name__ == "__main__":
    _selftest()
