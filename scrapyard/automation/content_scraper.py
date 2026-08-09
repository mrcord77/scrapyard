"""
content_scraper — ** The `scrapyard.automation.content_scraper` module provides a flexible and reusable framework for scraping structured content from web pages using a chain of customizable extractors. It enables modu

### PART-META-JSON
{
  "name": "content_scraper",
  "layer": "automation",
  "purpose": "Provides a flexible and reusable framework for scraping structured content from web pages using a chain of customizable extractors. It enables modu.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: ContentExtractor(...); ExtractorChain(...); ContentScraper(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.automation.content_scraper`.",
  "example": "from scrapyard.automation.content_scraper import *",
  "import_path": "scrapyard.automation.content_scraper"
}
### END-PART-META
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import re, logging

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ContentExtractor:
    pattern: str
    key: str
    type_hint: Any

    def extract(self, html: str) -> Optional[Any]:
        match = re.search(self.pattern, html)
        if match:
            value = match.group(1)
            return self.type_hint(value)
        return None


class ExtractorChain:
    def __init__(self, extractors: List[ContentExtractor]):
        self.extractors = extractors

    def apply(self, html: str) -> Dict[str, Any]:
        result = {}
        for extractor in self.extractors:
            value = extractor.extract(html)
            if value is not None:
                result[extractor.key] = value
        return result


class ContentScraper:
    def __init__(self, extractor_chain: ExtractorChain, parser: 'HTMLParser'):
        self.extractor_chain = extractor_chain
        self.parser = parser

    def scrape(self, html: str) -> Dict[str, Any]:
        parsed_html = self.parser.parse(html)
        return self.extractor_chain.apply(parsed_html)


class HTMLParser:
    def parse(self, html: str) -> str:
        # Simple example of parsing; in real use, this would be more complex
        return html


def _selftest():
    logging.basicConfig(level=logging.DEBUG)

    # Sample HTML content
    sample_html = """
    <html>
        <body>
            <div class="product">
                <h1>Product Name</h1>
                <p>Price: $99.99</p>
                <p>Availability: In Stock</p>
            </div>
        </body>
    </html>
    """

    # Define extractors
    name_extractor = ContentExtractor(r'<h1>(.*?)</h1>', 'name', str)
    price_extractor = ContentExtractor(r'Price: \$(\d+\.\d+)', 'price', float)
    availability_extractor = ContentExtractor(r'Availability: (.*?)</p>', 'availability', str)

    # Create an extractor chain
    extractors = [name_extractor, price_extractor, availability_extractor]
    extractor_chain = ExtractorChain(extractors)

    # Create a scraper with the parser and extractor chain
    scraper = ContentScraper(extractor_chain, HTMLParser())

    # Scrape sample HTML
    result = scraper.scrape(sample_html)
    logger.debug(f"Scraped data: {result}")

    # Check if the scraping was successful
    assert 'name' in result and result['name'] == 'Product Name'
    assert 'price' in result and result['price'] == 99.99
    assert 'availability' in result and result['availability'] == 'In Stock'

    logger.info("Self-test passed successfully.")


if __name__ == "__main__":
    _selftest()
