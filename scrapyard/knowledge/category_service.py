from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional, List

from sqlalchemy import create_engine, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session, relationship

from scrapyard.database.base_model import IntPKModel

"""
category_service — Manage hierarchical article categories and their article associations.

### PART-META-JSON
{
  "name": "category_service",
  "layer": "knowledge",
  "purpose": "Manages hierarchical article categories and their relationships: tree navigation, category creation with parent validation, and article association. CANONICAL OWNER of the knowledge-layer Category and Article models (tables category_service_category / category_service_article): export_service and other knowledge parts import these instead of defining duplicates.",
  "addition": true,
  "status": "core",
  "dependencies": ["sqlalchemy", "scrapyard.database.base_model"],
  "inputs": "Category names, optional parent ids, category ids; a Session bound via _configure_session().",
  "outputs": "Category/Article ORM instances, root-category lists, per-category article lists; ValueError for missing parents.",
  "files_created": [],
  "security_notes": "No authorization checks: any caller with a session can create categories or read any article association, so enforce access control in the calling layer. Category names are stored verbatim - escape on render if displayed in HTML.",
  "ai_usage": "Bind a session with _configure_session(session), then use create_category / get_category_tree / get_articles_by_category, or import the canonical Category/Article models.",
  "example": "from scrapyard.knowledge.category_service import Category, Article, create_category",
  "import_path": "scrapyard.knowledge.category_service"
}
### END-PART-META
"""

logger = logging.getLogger(__name__)

_session: Optional[Session] = None


class Category(IntPKModel):
    """Canonical knowledge-layer category model (owned by category_service)."""

    __tablename__ = "category_service_category"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("category_service_category.id"), nullable=True
    )

    parent: Mapped[Optional["Category"]] = relationship(
        "Category",
        remote_side="Category.id",
        foreign_keys=[parent_id],
        back_populates="children",
    )
    children: Mapped[List["Category"]] = relationship(
        "Category", back_populates="parent"
    )
    articles: Mapped[List["Article"]] = relationship("Article", back_populates="category")


class Article(IntPKModel):
    """Canonical knowledge-layer article model (owned by category_service)."""

    __tablename__ = "category_service_article"

    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category_id: Mapped[int] = mapped_column(ForeignKey("category_service_category.id"), nullable=False)

    category: Mapped["Category"] = relationship("Category", back_populates="articles")


def _configure_session(session: Optional[Session]) -> None:
    global _session
    _session = session


def _get_session() -> Session:
    if _session is None:
        raise RuntimeError(
            "category_service has no active session. Use _configure_session()."
        )
    return _session


def create_category(name: str, parent_id: Optional[int]) -> Category:
    """Create a new category, optionally under an existing parent."""
    session = _get_session()

    if parent_id is not None:
        parent = session.get(Category, parent_id)
        if parent is None:
            raise ValueError(f"Parent category {parent_id} does not exist")

    category = Category(name=name, parent_id=parent_id)
    session.add(category)
    session.flush()
    return category


def get_category_tree() -> List[Category]:
    """Return all root-level categories."""
    session = _get_session()
    roots = session.execute(
        select(Category).where(Category.parent_id.is_(None))
    ).scalars().all()
    return list(roots)


def get_articles_by_category(category_id: int) -> List[Article]:
    """Return articles associated with the given category ID."""
    session = _get_session()
    articles = session.execute(
        select(Article).where(Article.category_id == category_id)
    ).scalars().all()
    return list(articles)


def _selftest() -> None:
    """Offline self-test using a temporary SQLite database."""
    previous_session = _session

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "category_service_selftest.db")
        engine = create_engine(f"sqlite:///{db_path}")

        try:
            IntPKModel.metadata.create_all(engine)

            with Session(engine) as session:
                _configure_session(session)

                commit_calls = 0
                original_commit = session.commit

                def no_commit(*args, **kwargs):
                    nonlocal commit_calls
                    commit_calls += 1
                    raise AssertionError("session.commit() was called during self-test")

                session.commit = no_commit

                # Root categories
                root = create_category("Root", None)
                assert root.id is not None
                assert root.parent_id is None

                root2 = create_category("Root2", None)
                assert root2.parent_id is None

                # Child category
                child = create_category("Child", root.id)
                assert child.parent_id == root.id

                # Validate parent validation
                try:
                    create_category("Orphan", 9999)
                    raise AssertionError("Expected ValueError for missing parent")
                except ValueError:
                    pass

                # Articles
                article1 = Article(title="Article One", category_id=root.id)
                article2 = Article(title="Article Two", category_id=child.id)
                article3 = Article(title="Article Three", category_id=root.id)
                session.add_all([article1, article2, article3])
                session.flush()

                # Tree retrieval
                tree = get_category_tree()
                assert len(tree) == 2
                tree_ids = {c.id for c in tree}
                assert root.id in tree_ids
                assert root2.id in tree_ids
                assert child.id not in tree_ids

                # Parent-child relationships
                fetched_child = session.get(Category, child.id)
                assert fetched_child is not None
                assert fetched_child.parent is not None
                assert fetched_child.parent.id == root.id
                assert any(c.id == child.id for c in root.children)

                # Articles by category
                root_articles = get_articles_by_category(root.id)
                assert len(root_articles) == 2
                assert {a.title for a in root_articles} == {
                    "Article One",
                    "Article Three",
                }

                child_articles = get_articles_by_category(child.id)
                assert len(child_articles) == 1
                assert child_articles[0].title == "Article Two"

                empty_articles = get_articles_by_category(root2.id)
                assert empty_articles == []

                # Ensure no commits occurred
                assert commit_calls == 0, "Unexpected commit during self-test"

                session.rollback()

        finally:
            engine.dispose()
            _configure_session(previous_session)


if __name__ == "__main__":
    _selftest()
