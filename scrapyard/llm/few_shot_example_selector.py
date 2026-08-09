"""
few_shot_example_selector — ** The `few_shot_example_selector` module selects relevant few-shot examples from a repository based on input context, enabling dynamic and context-aware prompting for LLMs. It supports modular, reusa

### PART-META-JSON
{
  "name": "few_shot_example_selector",
  "layer": "llm",
  "purpose": "Selects relevant few-shot examples from a repository based on input context, enabling dynamic and context-aware prompting for LLMs. It supports modular, reusa.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: configure(engine); select_examples(context, task_type, max_examples, *, domain, language); Example(...); ExampleRepository(...).",
  "outputs": "Returns: select_examples -> List[Example].",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.llm.few_shot_example_selector`.",
  "example": "from scrapyard.llm.few_shot_example_selector import *",
  "import_path": "scrapyard.llm.few_shot_example_selector"
}
### END-PART-META
"""
# PART-META-JSON: {"name": "scrapyard.llm.few_shot_example_selector", "layer": "llm"}

import logging
import re
import math
import tempfile
import os
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import create_engine, String, Text, DateTime, JSON, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)

# Module-level engine storage
_engine = None


@dataclass
class Example:
    """Represents a selected few-shot example."""
    id: int
    task_type: str
    content: str
    rendered: str
    similarity: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExampleRepository(IntPKModel):
    """SQLAlchemy model for the example repository table."""
    __tablename__ = "few_shot_example_selector_example_repository"
    
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    domain: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    template_vars: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    def __repr__(self) -> str:
        return f"<ExampleRepository(id={self.id}, task_type={self.task_type})>"


def configure(engine):
    """Configure the module with a SQLAlchemy engine."""
    global _engine
    _engine = engine
    logger.debug("Configured few_shot_example_selector with engine")


def _tokenize(text: str) -> Dict[str, int]:
    """Simple tokenization for bag-of-words similarity."""
    words = re.findall(r'\b\w+\b', text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return freq


def _cosine_similarity(vec1: Dict[str, int], vec2: Dict[str, int]) -> float:
    """Calculate cosine similarity between two word frequency dictionaries."""
    intersection = set(vec1.keys()) & set(vec2.keys())
    numerator = sum(vec1[x] * vec2[x] for x in intersection)
    
    sum1 = sum(v**2 for v in vec1.values())
    sum2 = sum(v**2 for v in vec2.values())
    denominator = math.sqrt(sum1) * math.sqrt(sum2)
    
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _render_template(content: str, variables: Optional[Dict[str, Any]] = None) -> str:
    """Render template content with variables using str.format()."""
    if variables is None:
        return content
    try:
        return content.format(**variables)
    except (KeyError, ValueError):
        return content


def select_examples(
    context: str, 
    task_type: str, 
    max_examples: int = 3,
    *,
    domain: Optional[str] = None,
    language: Optional[str] = None
) -> List[Example]:
    """
    Select relevant few-shot examples based on context and filters.
    
    Args:
        context: Input context for semantic matching
        task_type: Task type to filter by
        max_examples: Maximum number of examples to return
        domain: Optional domain filter
        language: Optional language filter
        
    Returns:
        List of Example objects sorted by similarity (descending)
        
    Raises:
        ValueError: On invalid input parameters
        RuntimeError: If module not configured with engine
    """
    if _engine is None:
        raise RuntimeError("Module not configured. Call configure(engine) first.")
    
    if not context or not isinstance(context, str):
        raise ValueError("Context must be a non-empty string")
    if not task_type or not isinstance(task_type, str):
        raise ValueError("Task type must be a non-empty string")
    if max_examples < 1:
        raise ValueError("max_examples must be at least 1")
    
    logger.debug(f"Selecting examples: task_type={task_type}, domain={domain}, language={language}")
    
    context_vec = _tokenize(context)
    
    with Session(_engine) as session:
        stmt = select(ExampleRepository).where(ExampleRepository.task_type == task_type)
        
        if domain is not None:
            stmt = stmt.where(ExampleRepository.domain == domain)
        if language is not None:
            stmt = stmt.where(ExampleRepository.language == language)
            
        results = session.execute(stmt).scalars().all()
        
        if not results:
            logger.info(f"No examples found for criteria")
            return []
        
        scored = []
        for repo_ex in results:
            ex_vec = _tokenize(repo_ex.content)
            sim = _cosine_similarity(context_vec, ex_vec)
            rendered = _render_template(repo_ex.content, repo_ex.template_vars)
            
            ex = Example(
                id=repo_ex.id,
                task_type=repo_ex.task_type,
                content=repo_ex.content,
                rendered=rendered,
                similarity=sim,
                metadata={
                    "domain": repo_ex.domain,
                    "language": repo_ex.language,
                    "created_at": repo_ex.created_at.isoformat() if repo_ex.created_at else None
                }
            )
            scored.append((sim, ex))
        
        # Sort by similarity desc, then by id asc for determinism
        scored.sort(key=lambda x: (-x[0], x[1].id))
        
        selected = [ex for _, ex in scored[:max_examples]]
        logger.info(f"Selected {len(selected)} examples for task_type={task_type}")
        return selected


def _selftest():
    """Offline self-test for the module."""
    logger.info("Starting _selftest")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        
        # Create tables
        IntPKModel.metadata.create_all(engine)
        configure(engine)
        
        # Populate test data
        with Session(engine) as session:
            test_examples = [
                ExampleRepository(
                    task_type="classification",
                    domain="general",
                    language="en",
                    content="Input: This is great\nOutput: positive",
                    template_vars={"input": "This is great", "output": "positive"}
                ),
                ExampleRepository(
                    task_type="classification",
                    domain="general",
                    language="en",
                    content="Input: This is terrible\nOutput: negative",
                    template_vars={"input": "This is terrible", "output": "negative"}
                ),
                ExampleRepository(
                    task_type="classification",
                    domain="sports",
                    language="en",
                    content="Input: The team won the match\nOutput: victory",
                    template_vars={"input": "The team won the match", "output": "victory"}
                ),
                ExampleRepository(
                    task_type="summarization",
                    domain="news",
                    language="en",
                    content="Input: Long article text\nOutput: Short summary",
                    template_vars={"input": "Long article text", "output": "Short summary"}
                )
            ]
            session.add_all(test_examples)
            session.commit()
        
        # Test 1: Basic selection with similarity
        results = select_examples("This is great news", "classification", max_examples=2)
        assert len(results) <= 2
        assert all(r.task_type == "classification" for r in results)
        # "great" should match the first example best
        assert "great" in results[0].content.lower()
        
        # Test 2: Template rendering
        assert "positive" in results[0].rendered
        
        # Test 3: Domain filtering
        sports_results = select_examples("team match", "classification", max_examples=1, domain="sports")
        assert len(sports_results) == 1
        assert sports_results[0].metadata["domain"] == "sports"
        
        # Test 4: Language filtering
        en_results = select_examples("test", "classification", language="en")
        assert all(r.metadata["language"] == "en" for r in en_results)
        
        # Test 5: Empty result for non-matching task
        empty = select_examples("test", "translation")
        assert empty == []
        
        # Test 6: Input validation
        try:
            select_examples("", "classification")
            assert False, "Should raise ValueError for empty context"
        except ValueError:
            pass
            
        try:
            select_examples("test", "", max_examples=1)
            assert False, "Should raise ValueError for empty task_type"
        except ValueError:
            pass
            
        try:
            select_examples("test", "classification", max_examples=0)
            assert False, "Should raise ValueError for max_examples < 1"
        except ValueError:
            pass
        
        # Test 7: Different task type selection
        sum_results = select_examples("article text long", "summarization", max_examples=1)
        assert len(sum_results) == 1
        assert sum_results[0].task_type == "summarization"
        
        engine.dispose()
    
    # Cleanup
    global _engine
    _engine = None
    logger.info("_selftest passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    _selftest()
