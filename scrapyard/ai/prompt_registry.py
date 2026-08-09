"""
prompt_registry — Versioned, named prompt templates.

### PART-META-JSON
{
  "name": "prompt_registry",
  "layer": "ai",
  "purpose": "Versioned, named prompt templates.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "jinja2"
  ],
  "inputs": "Public API: PromptModel(...); TagModel(...); PromptTags(...) (plus more).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import `PromptModel` from `scrapyard.ai.prompt_registry` and call it as shown in `example`; run `py -m scrapyard.ai.prompt_registry` to see its offline selftest.",
  "example": "from scrapyard.ai.prompt_registry import PromptModel",
  "import_path": "scrapyard.ai.prompt_registry"
}
### END-PART-META
"""
from __future__ import annotations
STATUS = "core"
from typing import Any, Dict, List, Optional
import json
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from jinja2 import Template
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class PromptModel(Base):
    __tablename__ = 'prompts'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    version: Mapped[int]
    template: Mapped[str]
    description: Mapped[Optional[str]]
    tags: Mapped[List["TagModel"]] = relationship('TagModel', secondary='prompt_tags')
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

class TagModel(Base):
    __tablename__ = 'tags'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

class PromptTags(Base):
    __tablename__ = 'prompt_tags'
    prompt_id: Mapped[int] = mapped_column(ForeignKey('prompts.id'), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey('tags.id'), primary_key=True)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_name: Mapped[str]
    version: Mapped[Optional[int]]
    action: Mapped[str]
    timestamp: Mapped[str]

class PromptRegistry:
    """Versioned named prompt templates with {var} rendering. Keeps prompts out of
    code paths and lets you pin/roll versions."""
    def __init__(self): self._p = {}
    def register(self, name: str, template: str, version: int = 1):
        self._p.setdefault(name, {})[version] = template
    def render(self, name, /, *, version=None, **vars):
        versions = self._p[name]
        tmpl = versions[version or max(versions)]
        return tmpl.format(**vars)
    def latest(self, name: str) -> int:
        return max(self._p[name])
registry = PromptRegistry()


def _selftest():
    import tempfile
    import os
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    # in-memory registry: register, render, versioning
    r = PromptRegistry()
    r.register("greet", "Hello {name}!", version=1)
    r.register("greet", "Hi {name}, welcome back!", version=2)
    assert r.render("greet", name="Ada") == "Hi Ada, welcome back!"
    assert r.render("greet", version=1, name="Ada") == "Hello Ada!"
    assert r.latest("greet") == 2
    try:
        r.render("missing")
        raise AssertionError("expected KeyError for unknown prompt")
    except KeyError:
        pass

    # persistence models: create tables, store a prompt with tags + audit event
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        engine = create_engine(f"sqlite:///{os.path.join(tmpdir, 'prompts.db')}")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            tag = TagModel(name="prod")
            session.add(tag)
            pm = PromptModel(name="greet", version=2,
                             template="Hi {name}!", description="greeting",
                             tags=[tag])
            session.add(pm)
            session.add(AuditEvent(prompt_name="greet", version=2,
                                   action="register",
                                   timestamp=datetime.now(timezone.utc).isoformat()))
            session.commit()

            got = session.execute(select(PromptModel).where(
                PromptModel.name == "greet")).scalar_one()
            assert got.version == 2 and not got.archived
            assert [t.name for t in got.tags] == ["prod"]
            assert session.query(AuditEvent).count() == 1

            # render the persisted template through the registry
            r2 = PromptRegistry()
            r2.register(got.name, got.template, version=got.version)
            assert r2.render("greet", name="Bo") == "Hi Bo!"
        finally:
            session.close()
            engine.dispose()

    print("prompt_registry selftest passed")


if __name__ == "__main__":
    _selftest()
