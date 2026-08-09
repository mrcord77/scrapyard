"""
memory_system_assembler — Assembles the sibling agent-memory parts (episodic store, semantic index, recall scoring, consolidation, forgetting, scratchpad, configuration) into one wired MemorySystem backed by a shared SQLite engine, and applies MemoryDelta updates across those components.

### PART-META-JSON
{
  "name": "memory_system_assembler",
  "layer": "agents",
  "purpose": "Composition root for the agent memory stack: initialize_memory_system() opens one SQLAlchemy engine, configures episodic_memory_store and semantic_memory_index against it, creates a scratchpad, loads memory_system_configuration, and returns a MemorySystem whose fields are the live component modules/handles. update_memory_system() applies a MemoryDelta (new episodes, new vectors, scratchpad writes, config changes) to every affected component in one call.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "conversation_state",
    "episodic_memory_store",
    "semantic_memory_index",
    "memory_recall_scoring",
    "memory_consolidation_summarizer",
    "forgetting_policy_manager",
    "scratchpad_storage",
    "memory_system_configuration",
    "sqlalchemy"
  ],
  "inputs": "initialize_memory_system(MemorySystemConfig(db_url=..., config_path=...)); update_memory_system(system, MemoryDelta(episodes=[...], vectors=[...], scratchpad={...}, recall_threshold=...)).",
  "outputs": "MemorySystem with live component handles (module refs + engine + scratchpad id); shutdown_memory_system() disposes the engine.",
  "files_created": [
    "SQLite database at config.db_url (default temp)",
    "memory_system_config.json at config.config_path"
  ],
  "security_notes": "The assembler wires sibling components; it stores nothing itself. episodic_memory_store and semantic_memory_index use module-level engines, so two MemorySystems in one process share those modules' state - initialize the assembler once per process (documented limitation of the underlying parts). Delta payloads are caller data written verbatim into the stores; validate upstream if they originate from untrusted input.",
  "ai_usage": "cfg = MemorySystemConfig(db_url='sqlite:///mem.db'); sys = initialize_memory_system(cfg); update_memory_system(sys, MemoryDelta(episodes=[...])); shutdown_memory_system(sys).",
  "example": "from scrapyard.agents.memory_system_assembler import initialize_memory_system, MemorySystemConfig",
  "import_path": "scrapyard.agents.memory_system_assembler"
}
### END-PART-META
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import os
import logging
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scrapyard.agents import episodic_memory_store
from scrapyard.agents import semantic_memory_index
from scrapyard.agents import memory_recall_scoring
from scrapyard.agents import memory_consolidation_summarizer
from scrapyard.agents import forgetting_policy_manager
from scrapyard.agents import scratchpad_storage
from scrapyard.agents import memory_system_configuration
from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


@dataclass
class MemorySystemConfig:
    """Assembly configuration: where the shared DB and JSON config live."""
    db_url: Optional[str] = None            # default: temp sqlite file
    config_path: Optional[str] = None       # default: alongside the db
    recall_threshold: Optional[float] = None


@dataclass
class MemoryDelta:
    """A batch of changes to apply across the memory subsystems."""
    episodes: List[Dict[str, Any]] = field(default_factory=list)   # {agent_id, content, metadata, timestamp?}
    vectors: List[Dict[str, Any]] = field(default_factory=list)    # {vector, metadata}
    scratchpad: Dict[str, Any] = field(default_factory=dict)       # {key: value}
    recall_threshold: Optional[float] = None
    forgetting_policies: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class MemorySystem:
    conversation_state: Any
    episodic_memory_store: Any
    semantic_memory_index: Any
    memory_recall_scoring: Any
    memory_consolidation_summarizer: Any
    forgetting_policy_manager: Any
    scratchpad_storage: Any
    config: MemorySystemConfig
    engine: Any = None
    session_factory: Any = None
    scratchpad_id: Optional[int] = None
    _tempdir: Any = None


def initialize_memory_system(config: MemorySystemConfig) -> MemorySystem:
    """Wire every memory component against one shared SQLite engine."""
    tempdir = None
    db_url = config.db_url
    if not db_url:
        tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_url = f"sqlite:///{os.path.join(tempdir.name, 'memory_system.db')}"

    engine = create_engine(db_url, future=True)
    IntPKModel.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # episodic store + semantic index run on module-level engines/sessions
    episodic_memory_store._configure_engine(db_url)
    semantic_memory_index.configure_session_factory(lambda: session_factory())

    # persistent scratchpad for working data
    with session_factory() as session:
        pad = scratchpad_storage.create_scratchpad(session)
        scratchpad_id = pad.id

    # configuration file
    if config.config_path:
        memory_system_configuration.set_config_path(config.config_path)
    elif tempdir is not None:
        memory_system_configuration.set_config_path(
            os.path.join(tempdir.name, "memory_system_config.json"))
    if config.recall_threshold is not None:
        memory_system_configuration.set_recall_threshold(config.recall_threshold)

    from scrapyard.agents import conversation_state
    return MemorySystem(
        conversation_state=conversation_state,
        episodic_memory_store=episodic_memory_store,
        semantic_memory_index=semantic_memory_index,
        memory_recall_scoring=memory_recall_scoring,
        memory_consolidation_summarizer=memory_consolidation_summarizer,
        forgetting_policy_manager=forgetting_policy_manager,
        scratchpad_storage=scratchpad_storage,
        config=config,
        engine=engine,
        session_factory=session_factory,
        scratchpad_id=scratchpad_id,
        _tempdir=tempdir,
    )


def update_memory_system(system: MemorySystem, delta: MemoryDelta) -> Dict[str, int]:
    """Apply a MemoryDelta across all affected components. Returns counts of
    what was actually written where."""
    applied = {"episodes": 0, "vectors": 0, "scratchpad_keys": 0, "config_changes": 0}

    for ep in delta.episodes:
        mem = episodic_memory_store.Memory(
            timestamp=ep.get("timestamp") or datetime.now(timezone.utc),
            agent_id=ep["agent_id"],
            content=ep["content"],
            metadata=ep.get("metadata", {}),
        )
        system.episodic_memory_store.add_memory(mem)
        applied["episodes"] += 1

    for vec in delta.vectors:
        system.semantic_memory_index.add_vector(vec["vector"], vec.get("metadata", {}))
        applied["vectors"] += 1

    if delta.scratchpad:
        with system.session_factory() as session:
            for key, value in delta.scratchpad.items():
                scratchpad_storage.store_data(session, system.scratchpad_id, key, value)
                applied["scratchpad_keys"] += 1

    if delta.recall_threshold is not None:
        memory_system_configuration.set_recall_threshold(delta.recall_threshold)
        applied["config_changes"] += 1
    for name, params in delta.forgetting_policies.items():
        memory_system_configuration.configure_forgetting_policy(name, **params)
        applied["config_changes"] += 1

    return applied


def shutdown_memory_system(system: MemorySystem) -> None:
    """Dispose the shared engine and release temp resources."""
    try:
        if system.engine is not None:
            system.engine.dispose()
        episodic_memory_store._engine = None
    finally:
        if system._tempdir is not None:
            system._tempdir.cleanup()


def _selftest():
    """Assemble the real components, push a delta through, read it back."""
    from datetime import timedelta

    config = MemorySystemConfig(recall_threshold=0.8)
    system = initialize_memory_system(config)
    try:
        assert isinstance(system, MemorySystem)
        # every component slot is a live handle, not None
        for slot in ("conversation_state", "episodic_memory_store",
                     "semantic_memory_index", "memory_recall_scoring",
                     "memory_consolidation_summarizer",
                     "forgetting_policy_manager", "scratchpad_storage"):
            assert getattr(system, slot) is not None, f"{slot} not wired"
        assert system.scratchpad_id is not None

        now = datetime.now(timezone.utc)
        delta = MemoryDelta(
            episodes=[{"agent_id": "a1", "content": "saw a red car",
                       "metadata": {"kind": "obs"}}],
            vectors=[{"vector": [1.0, 0.0, 0.0], "metadata": {"name": "red"}},
                     {"vector": [0.0, 1.0, 0.0], "metadata": {"name": "green"}}],
            scratchpad={"note": "remember the red car"},
            recall_threshold=0.65,
            forgetting_policies={"linear": {"half_life": 7}},
        )
        applied = update_memory_system(system, delta)
        assert applied == {"episodes": 1, "vectors": 2,
                           "scratchpad_keys": 1, "config_changes": 2}, applied

        # episodic store actually holds the episode
        eps = episodic_memory_store.retrieve_memories(
            now - timedelta(minutes=1), now + timedelta(minutes=1), agent_id="a1")
        assert len(eps) == 1 and eps[0].content == "saw a red car"

        # semantic index recalls the closest vector
        top = semantic_memory_index.recall_top_n([1.0, 0.0, 0.0], 1)
        assert top and top[0]["metadata"]["name"] == "red"

        # scratchpad round-trips
        with system.session_factory() as session:
            val = scratchpad_storage.retrieve_data(
                session, system.scratchpad_id, "note")
        assert val == "remember the red car"

        # configuration reflects the delta
        cfg = memory_system_configuration.get_config()
        assert cfg.recall_threshold == 0.65
        assert cfg.forgetting_policy_configs["linear"] == {"half_life": 7}
    finally:
        shutdown_memory_system(system)

    logger.info("memory_system_assembler selftest passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
