"""
dependency_resolver — Walk part dependencies to produce the full closure for a
chosen part set, with cycle detection and assembly ordering.

### PART-META-JSON
{
  "name": "dependency_resolver",
  "layer": "curation",
  "purpose": "Resolve the full dependency closure for a chosen part set (scrapyard imports found by AST plus PART-META dependencies), with cycle detection and a safe assembly order.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "db_path (the metadata_harvester catalog), part names.",
  "outputs": "Closure dicts: ordered part list, third-party requirements, missing references, cycles.",
  "files_created": [],
  "security_notes": "Read-only over the catalog and part sources; parses with ast (never executes part code).",
  "ai_usage": "closure(db, ['users','invoices']) -> everything those parts need, in dependency-first order; direct_deps(db, part) for one hop; find_cycles(db) for yard hygiene.",
  "example": "from scrapyard.curation.dependency_resolver import closure; plan = closure('catalog.db', ['users']); print(plan['order'], plan['requirements'])",
  "import_path": "scrapyard.curation.dependency_resolver"
}
### END-PART-META
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple

from scrapyard.curation.metadata_harvester import get_part_info, list_all_parts

STATUS = "core"

log = logging.getLogger("scrapyard.curation.dependency_resolver")


def _scrapyard_imports(file_path: str) -> Set[Tuple[str, str]]:
    """(layer, part) pairs this file imports from scrapyard.*, found by AST
    over both top-level and function-body imports."""
    out: Set[Tuple[str, str]] = set()
    try:
        tree = ast.parse(Path(file_path).read_text(encoding="utf-8",
                                                   errors="ignore"))
    except (OSError, SyntaxError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            bits = node.module.split(".")
            if bits[0] == "scrapyard" and len(bits) >= 3:
                out.add((bits[1], bits[2]))
        elif isinstance(node, ast.Import):
            for a in node.names:
                bits = a.name.split(".")
                if bits[0] == "scrapyard" and len(bits) >= 3:
                    out.add((bits[1], bits[2]))
    return out


def direct_deps(db_path: str, name: str) -> Dict[str, List[str]]:
    """One hop: {'parts': [scrapyard part names], 'requirements': [pip deps]}.
    Part deps come from AST imports; pip deps from PART-META dependencies
    (entries that are not scrapyard part names)."""
    info = get_part_info(db_path, name)
    if not info:
        return {"parts": [], "requirements": [], "missing": [name]}
    yard_names = set(list_all_parts(db_path))
    part_deps = sorted({p for _layer, p in
                        _scrapyard_imports(info["file_path"])
                        if p != name})
    reqs: List[str] = []
    for dep in info.get("meta", {}).get("dependencies", []) or []:
        if isinstance(dep, str) and dep and dep not in yard_names:
            reqs.append(dep)
    missing = [p for p in part_deps if p not in yard_names]
    return {"parts": [p for p in part_deps if p in yard_names],
            "requirements": sorted(set(reqs)),
            "missing": missing}


def closure(db_path: str, names: List[str]) -> Dict[str, object]:
    """Full transitive closure for a part set.

    Returns {'order': [parts, dependency-first], 'requirements': [pip deps],
    'missing': [unresolvable references], 'cycles': [[...], ...]}.
    Parts inside a cycle still appear in 'order' (grouped), so a cycle is a
    warning, not a dead end."""
    yard_names = set(list_all_parts(db_path))
    edges: Dict[str, List[str]] = {}
    requirements: Set[str] = set()
    missing: Set[str] = set()

    stack = [n for n in names]
    while stack:
        n = stack.pop()
        if n in edges:
            continue
        if n not in yard_names:
            missing.add(n)
            edges[n] = []
            continue
        d = direct_deps(db_path, n)
        edges[n] = list(d["parts"])
        requirements.update(d["requirements"])
        missing.update(d["missing"])
        stack.extend(p for p in d["parts"] if p not in edges)

    order, cycles = _toposort(edges)
    order = [p for p in order if p not in missing]
    return {"order": order, "requirements": sorted(requirements),
            "missing": sorted(missing), "cycles": cycles}


def _toposort(edges: Dict[str, List[str]]) -> Tuple[List[str], List[List[str]]]:
    """Dependency-first order via DFS; strongly-referenced cycles reported."""
    order: List[str] = []
    state: Dict[str, int] = {}  # 0=unseen 1=visiting 2=done
    cycles: List[List[str]] = []
    path: List[str] = []

    def visit(n: str) -> None:
        s = state.get(n, 0)
        if s == 2:
            return
        if s == 1:
            i = path.index(n)
            cyc = path[i:] + [n]
            if sorted(cyc[:-1]) not in [sorted(c[:-1]) for c in cycles]:
                cycles.append(cyc)
            return
        state[n] = 1
        path.append(n)
        for dep in edges.get(n, []):
            visit(dep)
        path.pop()
        state[n] = 2
        order.append(n)

    for n in sorted(edges):
        visit(n)
    return order, cycles


def find_cycles(db_path: str) -> List[List[str]]:
    """Yard hygiene: cycles across the whole catalog."""
    return closure(db_path, list_all_parts(db_path))["cycles"]  # type: ignore[return-value]


def _selftest() -> None:
    import os
    import tempfile

    from scrapyard.curation.metadata_harvester import harvest

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = os.path.join(tmp, "catalog.db")
        yard = Path(tmp) / "yard"

        def part(layer: str, name: str, body: str, deps: str = "[]") -> None:
            d = yard / layer
            d.mkdir(parents=True, exist_ok=True)
            (d / "__init__.py").write_text("", encoding="utf-8")
            (d / f"{name}.py").write_text(
                f'"""\n{name}.\n\n### PART-META-JSON\n'
                f'{{"name": "{name}", "layer": "{layer}", '
                f'"purpose": "{name}", "dependencies": {deps}}}\n'
                f'### END-PART-META\n"""\n{body}\n', encoding="utf-8")

        # c <- b <- a ; a also needs pip dep "requests"; d+e form a cycle
        part("core", "c", "def fc():\n    return 1\n")
        part("core", "b", "from scrapyard.core.c import fc\n\ndef fb():\n    return fc()\n")
        part("app", "a",
             "def fa():\n    from scrapyard.core.b import fb\n    return fb()\n",
             deps='["requests"]')
        part("app", "d", "from scrapyard.app.e import fe\n\ndef fd():\n    return fe()\n")
        part("app", "e", "def fe():\n    from scrapyard.app.d import fd\n    return 2\n")

        harvest(db, str(yard))

        one = direct_deps(db, "b")
        assert one["parts"] == ["c"] and one["requirements"] == []

        plan = closure(db, ["a"])
        assert plan["order"] == ["c", "b", "a"], plan["order"]
        assert plan["requirements"] == ["requests"]
        assert plan["missing"] == []
        assert plan["cycles"] == []

        plan2 = closure(db, ["d"])
        assert set(plan2["order"]) == {"d", "e"}
        assert len(plan2["cycles"]) == 1

        ghost = closure(db, ["a", "not_a_part"])
        assert "not_a_part" in ghost["missing"]
        assert ghost["order"] == ["c", "b", "a"]


if __name__ == "__main__":
    _selftest()
