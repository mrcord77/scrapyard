#!/usr/bin/env python3
"""
gen_models.py — turn a domain's entities into a working data layer.

A domain pack describes entities conceptually (name + fields). This generates
the code that those descriptions imply:

    models.py    SQLAlchemy 2.0 models (Mapped / mapped_column)
    schemas.py   Pydantic v2 Create + Read schemas
    services.py  a CRUD service per entity over a Session
    routes.py    a FastAPI APIRouter per entity (list / get / create / delete)

Field types are inferred from field names (id, *_id, *_at/_on, is_*, *_cents,
*_qty, email, body/notes/description -> Text, tags/items/* -> JSON). Entities
may instead give typed fields: {"name": "...", "type": "int|str|text|bool|
datetime|float|json", "optional": true}.

    python tools/gen_models.py <domain> <out_dir>
    python tools/gen_models.py sobriety ./generated/sobriety
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOM = os.path.join(ROOT, "domains")

# field-name -> (sqlalchemy_type, python_type, pydantic_default_optional)
SA = {
    "int": "Mapped[int]", "str": "Mapped[str]", "text": "Mapped[str]",
    "bool": "Mapped[bool]", "datetime": "Mapped[datetime]",
    "float": "Mapped[float]", "json": "Mapped[dict]",
}
SA_COL = {
    "int": "mapped_column(Integer)", "str": "mapped_column(String(255))",
    "text": "mapped_column(Text)", "bool": "mapped_column(Boolean, default=False)",
    "datetime": "mapped_column(DateTime(timezone=True))",
    "float": "mapped_column(Float)", "json": "mapped_column(JSON, default=dict)",
}
PY = {"int": "int", "str": "str", "text": "str", "bool": "bool",
      "datetime": "datetime", "float": "float", "json": "dict"}


def infer_type(field: str) -> str:
    f = field.lower()
    NUM_SUFFIX = ("_id", "_cents", "_qty", "_days", "_count", "_no", "_bbl", "_mcf")
    NUM_EXACT = {"id", "count", "beds", "baths", "sqft", "order"}
    if f in NUM_EXACT or f.endswith(NUM_SUFFIX):
        return "int"
    if f.endswith("_at") or f.endswith("_on") or f in ("since", "dob", "due"):
        return "datetime"
    if f.startswith("is_") or f.startswith("has_") or f == "private":
        return "bool"
    if f in ("body", "notes", "description", "content", "message", "reason"):
        return "text"
    if f in ("tags", "items", "entitlements", "fields", "schedule", "location"):
        return "json"
    return "str"


def norm_fields(entity: dict) -> list[dict]:
    out = []
    for f in entity.get("fields", []):
        if isinstance(f, dict):
            name = f["name"]
            t = f.get("type", infer_type(name))
            optional = f.get("optional", name != "id")
        else:
            name = f
            t = infer_type(f)
            optional = name not in ("id",)
        out.append({"name": name, "type": t, "optional": optional})
    return out


_IRREGULAR_PLURALS = {"child": "children", "person": "people", "man": "men",
                      "woman": "women", "staff": "staff", "equipment": "equipment"}

def _plural(name: str) -> str:
    import re
    n = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()  # JournalEntry -> journal_entry
    last = n.rsplit("_", 1)[-1]
    if last in _IRREGULAR_PLURALS:                     # child -> children (never 'childs')
        return n[: len(n) - len(last)] + _IRREGULAR_PLURALS[last]
    if n.endswith("y") and n[-2:-1] not in "aeiou":
        return n[:-1] + "ies"        # entry -> entries
    if n.endswith(("s", "x", "z", "ch", "sh")):
        return n + "es"
    return n + "s"


SENSITIVE_FIELD_NAMES = {"body", "notes", "content", "relapse_notes", "message", "journal", "entry"}

# Tables owned by library parts (auth/billing/compliance). A generated domain
# entity must never reuse one of these names, or its create_all would clobber
# (or be clobbered by) the library schema. Generated collisions are renamed.
RESERVED_TABLES = {
    "users", "sessions", "audit_logs", "consent_logs", "email_verifications",
    "invoices", "password_reset_tokens", "processed_webhook_events",
    "saved_searches", "subscriptions", "usage_events",
}


def _table_name(entity_name: str) -> str:
    """Plural table name for an entity, namespaced if it would collide with a
    library-owned table (e.g. a domain `User` entity -> `app_users`)."""
    plural = _plural(entity_name)
    return f"app_{plural}" if plural in RESERVED_TABLES else plural

# What each data-sensitivity tier requires by default. Explicit per-entity
# route_policies override these. One source of truth used by both generation
# and assembly (so EOS can include the parts the generated code will import).
SENSITIVITY_DEFAULTS = {
    "low":       {},
    "moderate":  {"auth": True},
    "high":      {"auth": True, "owner": True, "encrypt": True, "audit": ["create", "update", "delete"]},
    "regulated": {"auth": True, "owner": True, "encrypt": True, "audit": ["create", "update", "delete"]},
}


def effective_policies(entities, domain) -> dict:
    """Resolve the per-entity security policy: tier defaults, overlaid with any
    explicit route_policies the domain declares. Returns {EntityName: policy}.

    Encryption fields come from (in order of authority): an explicit per-entity
    route_policy `encrypted_fields`, the domain's declared `sensitive_fields`,
    then the conservative name heuristic."""
    domain = domain or {}
    tier = domain.get("data_sensitivity") or "low"
    base = SENSITIVITY_DEFAULTS.get(tier, {})
    explicit = domain.get("route_policies") or {}
    declared = domain.get("sensitive_fields") or {}   # {EntityName: [field, ...]}
    eps = {}
    for e in entities:
        fields = norm_fields(e)  # tolerate shorthand string fields from raw domain specs
        ftypes = {f["name"]: f.get("type") for f in fields}
        has_uid = any(f["name"] == "user_id" for f in fields)
        declared_here = [f for f in (declared.get(e["name"]) or []) if ftypes.get(f) in ("str", "text")]
        heuristic_here = [f["name"] for f in fields
                          if f["name"] in SENSITIVE_FIELD_NAMES and f.get("type") in ("str", "text")]
        enc_candidates = list(dict.fromkeys(declared_here + heuristic_here))
        d = {}
        if base.get("auth"):
            d["requires_auth"] = True
        if base.get("owner") and has_uid:
            d["owner_field"] = "user_id"
        if base.get("encrypt") and enc_candidates:
            d["encrypted_fields"] = enc_candidates
        if base.get("audit") and has_uid:
            d["audit"] = list(base["audit"])
        if e["name"] in explicit:               # explicit declaration overrides the tier default
            d = {**d, **explicit[e["name"]]}
        eps[e["name"]] = d
    return eps


def text_field_classification(entities, domain) -> dict:
    """For a high/regulated domain, classify every str/text field of every entity
    as one of: encrypted (per effective policy), exempt (explicitly reviewed as
    non-sensitive via the domain's `exempt_fields`), or UNCLASSIFIED. An
    unclassified text field is silent plaintext-PII risk: it was never decided.
    Returns {EntityName: {"encrypted": [...], "exempt": [...], "unclassified": [...]}}."""
    domain = domain or {}
    eps = effective_policies(entities, domain)
    exempt_map = domain.get("exempt_fields") or {}
    out = {}
    for e in entities:
        name = e["name"]
        text_fields = [f["name"] for f in e.get("fields", [])
                       if f.get("type") in ("str", "text") and f["name"] != "id"]
        enc = set(eps.get(name, {}).get("encrypted_fields") or [])
        ex = set(exempt_map.get(name) or [])
        out[name] = {
            "encrypted": [f for f in text_fields if f in enc],
            "exempt": [f for f in text_fields if f in ex and f not in enc],
            "unclassified": [f for f in text_fields if f not in enc and f not in ex],
        }
    return out


def encryption_coverage_fails(entities, domain) -> list:
    """Gate-grade check: in a high/regulated domain, EVERY text field must be
    explicitly classified as encrypted or exempt. Returns [(EntityName, [fields])]
    of unclassified text fields — empty means full coverage. This is what turns
    'present but unencrypted' from a silent default into a hard build failure."""
    domain = domain or {}
    if domain.get("data_sensitivity") not in ("high", "regulated"):
        return []
    return [(name, c["unclassified"])
            for name, c in text_field_classification(entities, domain).items()
            if c["unclassified"]]


def sensitivity_warnings(entities, domain) -> list:
    """Advisory mirror of encryption_coverage_fails for non-gated (advisory) runs:
    surface any text field in a high/regulated domain that is neither encrypted nor
    explicitly exempt, so the author classifies it before it ships as plaintext."""
    domain = domain or {}
    warnings = []
    for name, unclassified in encryption_coverage_fails(entities, domain):
        warnings.append(
            f"{name} has unclassified text field(s): {unclassified}. In a "
            f"'{domain.get('data_sensitivity')}' domain every text field must be "
            "declared encrypted (route_policies/sensitive_fields) or exempt (exempt_fields)."
        )
    return warnings


def implied_capabilities(eps: dict) -> set:
    """Capabilities the generated routes/models will import for a given policy set,
    so the assembler can guarantee they're present."""
    caps = set()
    for p in eps.values():
        if p.get("requires_auth") or p.get("owner_field"):
            caps.add("session_manager")
        if p.get("encrypted_fields"):
            # generated models now encrypt at rest under hybrid PQ key transport
            caps.update(["pq_field_encryption", "pq_envelope", "crypto_agility"])
        if p.get("audit"):
            caps.add("audit_logs")
    return caps


def _state_machine(entity: dict):
    """Return the entity's executable state machine, or None. Shape:
    {"field": "status", "initial": "intake",
     "transitions": {"intake": ["diagnosed"], ...},
     "guards": {"ready": [{"field": "parts_received", "equals": true, "error": "..."}]}}"""
    sm = entity.get("state_machine")
    if not sm or not sm.get("field") or not sm.get("transitions"):
        return None
    return sm


def _normalize_links(links):
    """Normalize domain many_to_many declarations into join-table descriptors:
    {left, right, table, left_col, right_col, cls}. Default table = <left>_<right plural>."""
    import re
    out = []
    for lk in (links or []):
        left, right = lk["left"], lk["right"]
        lcol = re.sub(r"(?<!^)(?=[A-Z])", "_", left).lower() + "_id"
        rcol = re.sub(r"(?<!^)(?=[A-Z])", "_", right).lower() + "_id"
        table = lk.get("table") or (re.sub(r"(?<!^)(?=[A-Z])", "_", left).lower() + "_" + _plural(right))
        cls = "".join(p.capitalize() for p in table.split("_"))
        out.append({"left": left, "right": right, "table": table,
                    "left_col": lcol, "right_col": rcol, "cls": cls})
    return out


def gen_models(entities, safe=False, policies=None, links=None) -> str:
    """policies: {EntityName: {encrypted_fields: [...], ...}}. When a policy
    declares encrypted_fields, those are encrypted; otherwise (safe heuristic)
    fields named in SENSITIVE_FIELD_NAMES are encrypted. links: many-to-many join tables."""
    policies = policies or {}
    need_enc = safe or any(p.get("encrypted_fields") for p in policies.values())
    L = ['"""Generated SQLAlchemy models. Do not hand-edit; regenerate from the domain."""',
         "from __future__ import annotations",
         "from datetime import datetime",
         "from sqlalchemy import Integer, String, Text, Boolean, DateTime, Float, JSON, func, ForeignKey, UniqueConstraint",
         "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column"]
    if need_enc:
        L.append("from scrapyard.security.pq_field_encryption import PQEncryptedString  # hybrid PQ encryption at rest")
    L += ["", "", "class Base(DeclarativeBase):", "    pass", "", ""]
    # Relationship targets: a client-supplied '<entity>_id' becomes a real FOREIGN KEY
    # to that entity's table (so an orphaned reference is rejected by the database).
    # 'user_id' is intentionally excluded — it is the OWNER, set server-side from the
    # authenticated principal (never client input), so it cannot be orphaned; it is
    # indexed for owner-scoped queries but needs no FK.
    import re as _re
    rel_targets = {}
    for _e in entities:
        _base = _re.sub(r"(?<!^)(?=[A-Z])", "_", _e["name"]).lower()
        if _base == "user":
            continue
        rel_targets[f"{_base}_id"] = _table_name(_e["name"])
    for e in entities:
        pol = policies.get(e["name"], {})
        # explicit policy wins; else fall back to the sensitivity heuristic
        enc_fields = set(pol.get("encrypted_fields") or ([] if pol else (SENSITIVE_FIELD_NAMES if safe else [])))
        L.append(f"class {e['name']}(Base):")
        L.append(f'    __tablename__ = "{_table_name(e["name"])}"')
        _sm = _state_machine(e)
        for fld in e["fields"]:
            n, t, opt = fld["name"], fld["type"], fld["optional"]
            if n == "id":
                L.append("    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)")
                continue
            if _sm and n == _sm["field"]:
                # state-machine field: a real column defaulting to the initial state, indexed
                init = _sm.get("initial", "")
                L.append(f'    {n}: Mapped[str] = mapped_column(String(50), default="{init}", index=True)')
                continue
            if n in ("created_at", "updated_at"):
                extra = "server_default=func.now()"
                if n == "updated_at":
                    extra += ", onupdate=func.now()"
                L.append(f"    {n}: Mapped[datetime] = mapped_column(DateTime(timezone=True), {extra})")
                continue
            if n in enc_fields and t in ("str", "text"):
                ann = "Mapped[str | None]" if opt else "Mapped[str]"
                aad = f"{_table_name(e['name'])}.{n}"
                L.append(f"    {n}: {ann} = mapped_column(PQEncryptedString(aad=b'{aad}'){', nullable=True' if opt else ''})")
                continue
            if n.endswith("_id") and n != "id":
                ann = "Mapped[int | None]" if opt else "Mapped[int]"
                nb = ", nullable=True" if opt else ""
                target = rel_targets.get(n)
                if target:  # client-supplied relationship -> enforce referential integrity
                    L.append(f'    {n}: {ann} = mapped_column(Integer, ForeignKey("{target}.id", ondelete="CASCADE"), index=True{nb})')
                else:       # owner (user_id) or external ref -> index only
                    L.append(f"    {n}: {ann} = mapped_column(Integer, index=True{nb})")
                continue
            ann = SA[t].replace("]", " | None]") if opt else SA[t]
            col = SA_COL[t]
            if opt and "default" not in col:
                col = col[:-1] + ", nullable=True)"
            L.append(f"    {n}: {ann} = {col}")
        L.append("")
    # many-to-many join tables: id PK + two CASCADE FKs + a uniqueness constraint
    for lk in _normalize_links(links):
        lt, rt = _table_name(lk["left"]), _table_name(lk["right"])
        L += [f"class {lk['cls']}(Base):",
              f"    __tablename__ = {lk['table']!r}",
              "    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)",
              f"    {lk['left_col']}: Mapped[int] = mapped_column(Integer, ForeignKey(\"{lt}.id\", ondelete=\"CASCADE\"), index=True)",
              f"    {lk['right_col']}: Mapped[int] = mapped_column(Integer, ForeignKey(\"{rt}.id\", ondelete=\"CASCADE\"), index=True)",
              f"    __table_args__ = (UniqueConstraint({lk['left_col']!r}, {lk['right_col']!r}, name=\"uq_{lk['table']}\"),)",
              ""]
    return "\n".join(L)


def gen_schemas(entities) -> str:
    L = ['"""Generated Pydantic v2 schemas."""',
         "from __future__ import annotations",
         "from datetime import datetime",
         "from pydantic import BaseModel, ConfigDict", "", ""]
    for e in entities:
        # Create: writable fields (skip id + timestamps)
        L.append(f"class {e['name']}Create(BaseModel):")
        wrote = False
        for fld in e["fields"]:
            n, t, opt = fld["name"], fld["type"], fld["optional"]
            if n in ("id", "created_at", "updated_at"):
                continue
            pyt = PY[t]
            L.append(f"    {n}: {pyt}" + (" | None = None" if opt else ""))
            wrote = True
        if not wrote:
            L.append("    pass")
        L.append("")
        # Update: every writable field optional (PATCH/PUT partial update)
        L.append(f"class {e['name']}Update(BaseModel):")
        uwrote = False
        for fld in e["fields"]:
            n, t, opt = fld["name"], fld["type"], fld["optional"]
            if n in ("id", "created_at", "updated_at"):
                continue
            L.append(f"    {n}: {PY[t]} | None = None")
            uwrote = True
        if not uwrote:
            L.append("    pass")
        L.append("")
        # Read: everything, with ORM mode
        L.append(f"class {e['name']}Read(BaseModel):")
        L.append("    model_config = ConfigDict(from_attributes=True)")
        for fld in e["fields"]:
            n, t, opt = fld["name"], fld["type"], fld["optional"]
            pyt = PY[t]
            L.append(f"    {n}: {pyt}" + (" | None = None" if (opt and n != 'id') else ""))
        L.append("")
    return "\n".join(L)


def _reference_rules(entity: dict) -> dict:
    """Per-field reference preconditions: {field: {entity, status_field, allowed, error}}.
    Enforced in the service before create — existence and (optional) status of the
    referenced row, with a clean domain error rather than a raw FK failure."""
    return entity.get("reference_rules") or {}


def _no_overlap(entity: dict):
    """Date-overlap conflict rule: {scope, start, end, active:[...], error}. Rejects a
    create whose [start,end) overlaps an existing active row sharing the scope field."""
    o = entity.get("no_overlap")
    if o and o.get("scope") and o.get("start") and o.get("end"):
        return o
    return None


def gen_services(entities, links=None) -> str:
    nlinks = _normalize_links(links)
    names = ", ".join(e["name"] for e in entities)
    join_names = ", ".join(lk["cls"] for lk in nlinks)
    import_models = f"from .models import {names}" + (f", {join_names}" if join_names else "")
    L = ['"""Generated services: CRUD + domain-rule enforcement."""',
         "from __future__ import annotations",
         "from sqlalchemy import select, delete",
         "from sqlalchemy.orm import Session",
         import_models, "", "",
         "from scrapyard.api.domain_errors import WorkflowError, DomainRuleError", "", "",
         "_MODELS = {" + ", ".join(f"{e['name']!r}: {e['name']}" for e in entities) + "}", "", ""]
    for e in entities:
        n = e["name"]
        ref_rules = _reference_rules(e)
        overlap = _no_overlap(e)
        L += [f"class {n}Service:",
              "    def __init__(self, db: Session):",
              "        self.db = db", ""]
        # create() with reference preconditions + overlap conflict checks
        cl = [f"    def create(self, **data) -> {n}:"]
        for fld, rule in ref_rules.items():
            tgt = rule["entity"]; sf = rule.get("status_field", "status")
            allowed = rule.get("allowed"); err = rule.get("error", f"{fld}: referenced {tgt} not valid")
            cl += [f"        _v = data.get({fld!r})",
                   "        if _v is not None:",
                   f"            _ref = self.db.get({tgt}, _v)",
                   "            if _ref is None:",
                   f"                raise DomainRuleError({('nonexistent ' + fld)!r})"]
            if allowed:
                cl += [f"            if getattr(_ref, {sf!r}, None) not in {list(allowed)!r}:",
                       f"                raise DomainRuleError({err!r})"]
        if overlap:
            sc, st, en = overlap["scope"], overlap["start"], overlap["end"]
            act = list(overlap.get("active", [])); oerr = overlap.get("error", "overlapping reservation")
            cl += [f"        if data.get({sc!r}) is not None and data.get({st!r}) is not None and data.get({en!r}) is not None:",
                   f"            _conf = self.db.scalar(select({n}).where(",
                   f"                {n}.{sc} == data[{sc!r}], {n}.status.in_({act!r}),",
                   f"                {n}.{st} < data[{en!r}], {n}.{en} > data[{st!r}]))",
                   "            if _conf is not None:",
                   f"                raise DomainRuleError({oerr!r})"]
        cl += [f"        obj = {n}(**data)", "        self.db.add(obj); self.db.flush(); return obj", ""]
        L += cl
        L += [f"    def get(self, id_: int) -> {n} | None:",
              f"        return self.db.get({n}, id_)", "",
              "    def list(self, *, limit: int = 50, offset: int = 0):",
              f"        return list(self.db.scalars(select({n}).limit(limit).offset(offset)))", "",
              f"    def update(self, id_: int, **data) -> {n} | None:",
              "        obj = self.get(id_)",
              "        if not obj: return None",
              "        for k, v in data.items(): setattr(obj, k, v)",
              "        self.db.flush(); return obj", "",
              "    def delete(self, id_: int) -> bool:",
              "        obj = self.get(id_)",
              "        if not obj: return False",
              "        self.db.delete(obj); self.db.flush(); return True", ""]
        sm = _state_machine(e)
        if sm:
            field = sm["field"]
            L += [
                f"    def transition(self, id_: int, to_state: str) -> {n} | None:",
                '        """Enforce the state machine: only declared transitions are allowed, and',
                "        each target state's guards must hold. Guards may check a field on this row",
                '        (equals) OR a related row\'s status (ref/entity/field/in). Raises WorkflowError."""',
                "        obj = self.get(id_)",
                "        if not obj: return None",
                f"        _T = {sm['transitions']!r}",
                f"        _G = {sm.get('guards', {})!r}",
                f"        cur = getattr(obj, {field!r})",
                "        if to_state not in _T.get(cur, []):",
                "            raise WorkflowError(f'illegal transition: {cur} -> {to_state}')",
                "        for g in _G.get(to_state, []):",
                "            if 'ref' in g:  # cross-entity guard: related row must be in an allowed status",
                "                _rid = getattr(obj, g['ref'], None)",
                "                _ro = self.db.get(_MODELS.get(g['entity']), _rid) if (_rid is not None and g.get('entity') in _MODELS) else None",
                "                if _ro is None or getattr(_ro, g.get('field', 'status'), None) not in g.get('in', []):",
                "                    raise WorkflowError(g.get('error') or 'related precondition failed')",
                "            elif getattr(obj, g['field'], None) != g.get('equals'):",
                "                raise WorkflowError(g.get('error') or f'guard failed entering {to_state}')",
                f"        setattr(obj, {field!r}, to_state)",
                f"        _E = {sm.get('effects', {})!r}",
                "        for _eff in _E.get(to_state, []):",
                "            if 'set_related' in _eff:  # mutate a related row (e.g. tool -> checked_out)",
                "                _sr = _eff['set_related']; _rid = getattr(obj, _sr['ref'], None)",
                "                if _sr.get('guarded') and _sr.get('entity') in _SERVICES:",
                "                    # route through the related entity's own transition() so ITS",
                "                    # transition table + guards apply (raises WorkflowError if blocked)",
                "                    if _rid is not None:",
                "                        _svc = _SERVICES[_sr['entity']](self.db)",
                "                        if _svc.transition(_rid, _sr['value']) is None:",
                "                            raise WorkflowError(f\"{_sr['entity']} {_rid} not found for guarded effect\")",
                "                else:",
                "                    _rel = self.db.get(_MODELS.get(_sr['entity']), _rid) if (_rid is not None and _sr.get('entity') in _MODELS) else None",
                "                    if _rel is not None:",
                "                        setattr(_rel, _sr.get('field', 'status'), _sr['value'])",
                "            elif 'create' in _eff:  # auto-create a child record (e.g. incident, maintenance)",
                "                _cr = _eff['create']; _vals = {}",
                "                for _k, _v in (_cr.get('values') or {}).items():",
                "                    _vals[_k] = getattr(obj, _v[1:], None) if (isinstance(_v, str) and _v.startswith('$')) else _v",
                "                if _cr.get('entity') in _MODELS:",
                "                    self.db.add(_MODELS[_cr['entity']](**_vals))",
                "        self.db.flush(); return obj", ""]
            tts = sm.get("time_transitions") or []
            if tts:
                L += [
                    "    def sweep(self, now=None):",
                    '        """Time-based transitions: advance rows whose deadline field has passed.',
                    "        Each move is applied THROUGH transition(), so the state machine's guards",
                    "        and effects still hold; a row whose guard is unmet is skipped. 'now'",
                    "        defaults to datetime.utcnow() (datetime deadlines); pass an explicit value",
                    '        (e.g. a day cursor) for non-datetime deadline fields. Returns moved ids."""',
                    "        from datetime import datetime as _dt",
                    f"        _TT = {tts!r}",
                    "        _done = []",
                    "        for _t in _TT:",
                    "            _cmp = now if now is not None else _dt.utcnow()",
                    f"            _q = select({n}).where(getattr({n}, {field!r}) == _t['from'], getattr({n}, _t['when']).is_not(None), getattr({n}, _t['when']) < _cmp)",
                    "            for _r in list(self.db.scalars(_q)):",
                    "                try:",
                    "                    self.transition(_r.id, _t['to']); _done.append(_r.id)",
                    "                except WorkflowError:",
                    "                    pass  # guard not satisfied for this row -> leave it",
                    "        self.db.flush(); return _done", ""]
    # many-to-many link services: existence-checked, idempotent attach + detach + list
    for lk in nlinks:
        cls, lcol, rcol = lk["cls"], lk["left_col"], lk["right_col"]
        left, right = lk["left"], lk["right"]
        L += [f"class {cls}Links:",
              f'    """Many-to-many link service for {lk["table"]} ({left} <-> {right})."""',
              "    def __init__(self, db: Session):",
              "        self.db = db", "",
              "    def attach(self, left_id: int, right_id: int):",
              f"        if self.db.get({left}, left_id) is None:",
              f"            raise DomainRuleError({('nonexistent ' + lcol)!r})",
              f"        if self.db.get({right}, right_id) is None:",
              f"            raise DomainRuleError({('nonexistent ' + rcol)!r})",
              f"        _ex = self.db.scalar(select({cls}).where({cls}.{lcol} == left_id, {cls}.{rcol} == right_id))",
              "        if _ex is not None:",
              "            return _ex  # idempotent: already linked",
              f"        _link = {cls}(**{{{lcol!r}: left_id, {rcol!r}: right_id}})",
              "        self.db.add(_link); self.db.flush(); return _link", "",
              "    def detach(self, left_id: int, right_id: int) -> bool:",
              f"        self.db.execute(delete({cls}).where({cls}.{lcol} == left_id, {cls}.{rcol} == right_id))",
              "        self.db.flush(); return True", "",
              "    def list_right(self, left_id: int):",
              f"        _ids = list(self.db.scalars(select({cls}.{rcol}).where({cls}.{lcol} == left_id)))",
              f"        return list(self.db.scalars(select({right}).where({right}.id.in_(_ids)))) if _ids else []", "",
              "    def list_left(self, right_id: int):",
              f"        _ids = list(self.db.scalars(select({cls}.{lcol}).where({cls}.{rcol} == right_id)))",
              f"        return list(self.db.scalars(select({left}).where({left}.id.in_(_ids)))) if _ids else []", ""]
    # service registry (defined after all classes) — used by guarded transition effects
    L += ["_SERVICES = {" + ", ".join(f"{e['name']!r}: {e['name']}Service" for e in entities) + "}", ""]
    return "\n".join(L)


def gen_routes(entities, wire=False, safe=False, policies=None, links=None) -> str:
    import re
    policies = policies or {}
    nlinks = _normalize_links(links)
    schema_imports = ", ".join(f"{e['name']}Create, {e['name']}Update, {e['name']}Read" for e in entities)
    svc_imports = ", ".join(f"{e['name']}Service" for e in entities)

    def entity_policy(e):
        """Resolve the effective policy: explicit declaration wins; else fall back
        to the sensitivity heuristic (auth + ownership if a user_id field exists)."""
        pol = policies.get(e["name"])
        has_uid = any(f["name"] == "user_id" for f in e["fields"])
        if pol is not None:
            return {"auth": pol.get("requires_auth", safe) or bool(pol.get("write_role")),
                    "owner_field": pol.get("owner_field"),
                    "write_role": pol.get("write_role"),
                    "audit": set(pol.get("audit") or [])}
        if safe:
            return {"auth": True, "owner_field": "user_id" if has_uid else None, "write_role": None, "audit": set()}
        return {"auth": False, "owner_field": None, "write_role": None, "audit": set()}

    eps = {e["name"]: entity_policy(e) for e in entities}
    any_auth = any(p["auth"] for p in eps.values())
    any_write_role = any(p.get("write_role") for p in eps.values())
    owner_models = [n for n, p in eps.items() if p["owner_field"]]
    any_audit = any(p["audit"] for p in eps.values())

    L = ['"""Generated FastAPI routers."""',
         "from __future__ import annotations",
         "from fastapi import APIRouter, Depends, HTTPException",
         "from sqlalchemy.orm import Session",
         "from sqlalchemy import select",
         f"from .schemas import {schema_imports}",
         f"from .services import {svc_imports}"]
    if any(_state_machine(e) for e in entities):
        L.append("from .services import WorkflowError")
    if any((_state_machine(e) or {}).get("time_transitions") for e in entities):
        L.append("from datetime import datetime  # for time-based sweep deadlines")
    if nlinks:
        L.append("from .services import " + ", ".join(f"{lk['cls']}Links" for lk in nlinks))
    if owner_models:
        L.append(f"from .models import {', '.join(owner_models)}")
    if wire:
        L += ["from scrapyard.database.db_session import get_db  # wired to the real session factory"]
    else:
        L += ["def get_db() -> Session:  # pragma: no cover",
              '    raise NotImplementedError("wire get_db to your session factory")']
    if any_auth:
        L += ["from fastapi import Header",
              "from scrapyard.identity.session_manager import SessionManager", ""]
        if any_audit:
            L.append("from scrapyard.admin.audit_logs import record as _audit")
        L += ["def current_user_id(x_session: str | None = Header(None, alias='X-Session'),",
              "                    db: Session = Depends(get_db)) -> int:",
              "    \"\"\"Resolve the authenticated user from the X-Session header; 401 if absent/invalid.\"\"\"",
              "    uid = SessionManager(db).user_id_for(x_session) if x_session else None",
              "    if not uid:",
              "        raise HTTPException(401, 'authentication required')",
              "    return uid"]
        if any_write_role:
            L += ["", "def require_role(role: str):",
                  '    """Dependency factory: authenticate, then 403 unless the user holds the role',
                  '    (or a superuser role). Used to gate write actions on role-managed entities."""',
                  "    def _dep(uid: int = Depends(current_user_id), db: Session = Depends(get_db)) -> int:",
                  "        from scrapyard.authorization.roles import has_role",
                  "        if not has_role(db, uid, role):",
                  "            raise HTTPException(403, f'requires role: {role}')",
                  "        return uid",
                  "    return _dep"]
    L += ["", "router = APIRouter()", ""]
    for e in entities:
        n = e["name"]
        pol = eps[n]
        plural = _plural(n)
        singular = re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower()
        owner = pol["owner_field"]
        auth = pol["auth"]
        write_role = pol.get("write_role")
        if write_role:
            owner = None  # role-managed: not owner-scoped; writes gated by the role
        audit = pol["audit"]
        authdep = ", uid: int = Depends(current_user_id)" if auth else ""
        # writes on a role-managed entity require the role; otherwise same as reads
        write_dep = f", uid: int = Depends(require_role({write_role!r}))" if write_role else authdep

        def audit_line(action, target_expr):
            return (f"    _audit(db, action='{singular}.{action}', actor_user_id=uid, target={target_expr})"
                    if action in audit else None)

        L.append(f"# --- {n} ---")
        if owner:
            # owner-scoped: each user only ever sees/affects their own rows
            create_audit = audit_line("create", f"f'{singular}:{{obj.id}}'")
            update_audit = audit_line("update", f"f'{singular}:{{id_}}'")
            delete_audit = audit_line("delete", f"f'{singular}:{{id_}}'")
            L += [
                f'@router.get("/{plural}", response_model=list[{n}Read])',
                f"def list_{plural}(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
                f"    return db.scalars(select({n}).where({n}.{owner} == uid).limit(limit).offset(offset)).all()", "",
                f'@router.get("/{plural}/{{id_}}", response_model={n}Read)',
                f"def get_{singular}(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
                f"    obj = {n}Service(db).get(id_)",
                f"    if not obj or obj.{owner} != uid:",
                "        raise HTTPException(404)",
                "    return obj", "",
                f'@router.post("/{plural}", response_model={n}Read, status_code=201)',
                f"def create_{singular}(payload: {n}Create, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
                f"    data = payload.model_dump(exclude_none=True); data['{owner}'] = uid  # force ownership",
                f"    obj = {n}Service(db).create(**data)"]
            if create_audit:
                L.append(create_audit)
            L += ["    db.commit(); return obj", "",
                  f'@router.put("/{plural}/{{id_}}", response_model={n}Read)',
                  f"def update_{singular}(id_: int, payload: {n}Update, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
                  f"    obj = {n}Service(db).get(id_)",
                  f"    if not obj or obj.{owner} != uid:",
                  "        raise HTTPException(404)",
                  f"    data = payload.model_dump(exclude_unset=True); data.pop('{owner}', None)  # owner is immutable",
                  f"    obj = {n}Service(db).update(id_, **data)"]
            if update_audit:
                L.append(update_audit)
            L += ["    db.commit(); return obj", "",
                  f'@router.delete("/{plural}/{{id_}}", status_code=204)',
                  f"def delete_{singular}(id_: int, db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
                  f"    obj = {n}Service(db).get(id_)",
                  f"    if not obj or obj.{owner} != uid:",
                  "        raise HTTPException(404)",
                  f"    {n}Service(db).delete(id_)"]
            if delete_audit:
                L.append(delete_audit)
            L += ["    db.commit()", ""]
        else:
            create_audit = audit_line("create", f"f'{singular}:{{obj.id}}'")
            update_audit = audit_line("update", f"f'{singular}:{{id_}}'")
            delete_audit = audit_line("delete", f"f'{singular}:{{id_}}'")
            L += [
                f'@router.get("/{plural}", response_model=list[{n}Read])',
                f"def list_{plural}(limit: int = 50, offset: int = 0, db: Session = Depends(get_db){authdep}):",
                f"    return {n}Service(db).list(limit=limit, offset=offset)", "",
                f'@router.get("/{plural}/{{id_}}", response_model={n}Read)',
                f"def get_{singular}(id_: int, db: Session = Depends(get_db){authdep}):",
                f"    obj = {n}Service(db).get(id_)",
                '    if not obj: raise HTTPException(404)',
                "    return obj", "",
                f'@router.post("/{plural}", response_model={n}Read, status_code=201)',
                f"def create_{singular}(payload: {n}Create, db: Session = Depends(get_db){write_dep}):",
                f"    obj = {n}Service(db).create(**payload.model_dump(exclude_none=True))"]
            if create_audit:
                L.append(create_audit)
            L += ["    db.commit(); return obj", "",
                  f'@router.put("/{plural}/{{id_}}", response_model={n}Read)',
                  f"def update_{singular}(id_: int, payload: {n}Update, db: Session = Depends(get_db){write_dep}):",
                  f"    obj = {n}Service(db).update(id_, **payload.model_dump(exclude_unset=True))",
                  "    if not obj: raise HTTPException(404)"]
            if update_audit:
                L.append(update_audit)
            L += ["    db.commit(); return obj", "",
                  f'@router.delete("/{plural}/{{id_}}", status_code=204)',
                  f"def delete_{singular}(id_: int, db: Session = Depends(get_db){write_dep}):"]
            if delete_audit:
                L += [f"    if not {n}Service(db).get(id_): raise HTTPException(404)",
                      f"    {n}Service(db).delete(id_)", delete_audit, "    db.commit()", ""]
            else:
                L += [f"    if not {n}Service(db).delete(id_): raise HTTPException(404)",
                      "    db.commit()", ""]

        # Workflow transition endpoint: POST /<plural>/{id}/transition {"to": "<state>"}
        sm = _state_machine(e)
        if sm:
            adep = ", uid: int = Depends(current_user_id)" if auth else authdep
            L += [
                f'@router.post("/{plural}/{{id_}}/transition", response_model={n}Read)',
                f"def transition_{singular}(id_: int, payload: dict, db: Session = Depends(get_db){adep}):",
                "    to_state = payload.get('to')",
                "    if not to_state:",
                "        raise HTTPException(422, \"missing target state 'to'\")",
                f"    obj = {n}Service(db).get(id_)",
                "    if not obj" + (f" or obj.{owner} != uid" if owner else "") + ":",
                "        raise HTTPException(404)",
                "    try:",
                f"        obj = {n}Service(db).transition(id_, to_state)",
                "    except WorkflowError as _e:",
                "        raise HTTPException(409, str(_e))"]
            ta = audit_line("update", f"f'{singular}:{{id_}}'") if auth else None
            if ta:
                L.append(ta)
            L += ["    db.commit(); return obj", ""]
            # Time-based sweep: POST /<plural>/sweep — advance rows past their deadline
            tts = sm.get("time_transitions") or []
            if tts:
                _ftypes = {f["name"]: f.get("type") for f in e["fields"]}
                _pt = {"int": "int", "datetime": "datetime"}.get(_ftypes.get(tts[0].get("when")), "str")
                L += [
                    f'@router.post("/{plural}/sweep")',
                    f"def sweep_{plural}(now: {_pt} | None = None, db: Session = Depends(get_db){adep}):",
                    '    """Scheduler-driven: advance rows whose deadline has passed (call periodically)."""',
                    f"    ids = {n}Service(db).sweep(now=now); db.commit()",
                    "    return {'transitioned': ids, 'count': len(ids)}", ""]

    # Data-subject rights: export + erasure for the authenticated user. Only meaningful
    # when there is user-owned data and authentication to identify the user.
    if owner_models and any_auth:
        L += [
            "# --- data subject rights (GDPR/CCPA: access, portability, erasure) ---",
            "# Module-scope import so DeletionRecord registers on the ORM base BEFORE the",
            "# boot-time create_all — a lazy in-route import would leave its table missing.",
            "import scrapyard.compliance.account_deletion  # noqa: F401  (model registration)",
            '@router.get("/privacy/export")',
            "def privacy_export(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
            '    """Export everything stored about the authenticated user (domain + identity)."""',
            "    from . import privacy as _p",
            "    from scrapyard.compliance.data_export import export_user_data as _identity_export",
            "    return {'user_id': uid, 'domain_data': _p.export_user_data(db, uid),",
            "            'identity_data': _identity_export(db, uid)}", "",
            '@router.get("/privacy/export/stream")',
            "def privacy_export_stream(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
            '    """Stream the user\'s domain data as NDJSON (one record per line), constant-',
            "    memory via a server-side cursor — portability that scales to large accounts",
            '    without buffering the whole export in memory."""',
            "    from fastapi.responses import StreamingResponse",
            "    from . import privacy as _p",
            "    return StreamingResponse(_p.stream_user_data(db, uid), media_type='application/x-ndjson',",
            "                             headers={'Content-Disposition': 'attachment; filename=\"export.ndjson\"'})", "",
            '@router.post("/privacy/delete-account")',
            "def privacy_delete_account(db: Session = Depends(get_db), uid: int = Depends(current_user_id)):",
            '    """Erase the authenticated user: domain-owned rows first, then identity',
            "    (sessions + user record), with an audit record. Right to erasure.\"\"\"",
            "    from . import privacy as _p",
            "    from scrapyard.compliance.account_deletion import delete_account as _delete_identity",
            "    domain = _p.delete_user_data(db, uid)   # domain tables (own ORM registry)",
            "    # confirm=True: without it delete_account is a SAFE-BY-DEFAULT dry run and",
            "    # the user row + sessions would survive (deleted account could log back in).",
            "    identity = _delete_identity(db, uid, confirm=True)  # library identity tables + user row",
            "    db.commit()",
            "    return {'deleted': True, 'domain': domain, 'identity': identity}", ""]
    # many-to-many link routes: attach (201, idempotent), detach (204), list linked
    link_authdep = ", uid: int = Depends(current_user_id)" if any_auth else ""
    for lk in nlinks:
        lp, rp = _plural(lk["left"]), _plural(lk["right"])
        cls, right = lk["cls"], lk["right"]
        tag = f"{lp}_{rp}"
        L += [f"# --- link: {lk['left']} <-> {lk['right']} ({lk['table']}) ---",
              f'@router.post("/{lp}/{{id_}}/{rp}/{{rid}}", status_code=201)',
              f"def attach_{tag}(id_: int, rid: int, db: Session = Depends(get_db){link_authdep}):",
              f"    {cls}Links(db).attach(id_, rid); db.commit(); return {{'linked': True}}", "",
              f'@router.delete("/{lp}/{{id_}}/{rp}/{{rid}}", status_code=204)',
              f"def detach_{tag}(id_: int, rid: int, db: Session = Depends(get_db){link_authdep}):",
              f"    {cls}Links(db).detach(id_, rid); db.commit()", "",
              f'@router.get("/{lp}/{{id_}}/{rp}", response_model=list[{right}Read])',
              f"def list_{tag}(id_: int, db: Session = Depends(get_db){link_authdep}):",
              f"    return {cls}Links(db).list_right(id_)", ""]
    # role administration: admin-gated self-serve grant/revoke/list (closes the gap
    # where roles could only be assigned via the trusted roles.grant() path)
    if any_write_role:
        _ra = "_audit(db, action='role.{0}', actor_user_id=uid, target=f'user:{{int(target)}}')" if any_audit else None
        L += ["# --- role administration (admin-gated) ---",
              '@router.post("/admin/roles/grant")',
              "def admin_grant_role(payload: dict, uid: int = Depends(require_role('admin')), db: Session = Depends(get_db)):",
              '    """Grant a role to a user. Requires the admin role (an owner/superuser also qualifies)."""',
              "    target = payload.get('user_id'); role = payload.get('role')",
              "    if not target or not role:",
              "        raise HTTPException(422, 'user_id and role are required')",
              "    from scrapyard.authorization.roles import grant as _grant, ROLE_PERMISSIONS",
              "    if role not in ROLE_PERMISSIONS:",
              "        raise HTTPException(422, f'unknown role: {role}')",
              "    _grant(db, int(target), role)"]
        if _ra:
            L.append("    " + _ra.format("grant"))
        L += ["    db.commit(); return {'granted': True, 'user_id': int(target), 'role': role}", "",
              '@router.post("/admin/roles/revoke")',
              "def admin_revoke_role(payload: dict, uid: int = Depends(require_role('admin')), db: Session = Depends(get_db)):",
              '    """Revoke a role from a user. Requires the admin role."""',
              "    target = payload.get('user_id'); role = payload.get('role')",
              "    if not target or not role:",
              "        raise HTTPException(422, 'user_id and role are required')",
              "    from scrapyard.authorization.roles import revoke as _revoke",
              "    _revoke(db, int(target), role)"]
        if _ra:
            L.append("    " + _ra.format("revoke"))
        L += ["    db.commit(); return {'revoked': True, 'user_id': int(target), 'role': role}", "",
              '@router.get("/admin/roles/{user_id}")',
              "def admin_list_roles(user_id: int, uid: int = Depends(require_role('admin')), db: Session = Depends(get_db)):",
              '    """List the roles held by a user. Requires the admin role."""',
              "    from scrapyard.authorization.roles import roles_for",
              "    return {'user_id': user_id, 'roles': sorted(roles_for(db, user_id))}", ""]
    return "\n".join(L)


def gen_privacy(entities, policies=None) -> str:
    """Emit data-subject helpers for the GENERATED domain tables. These models live in
    their own ORM registry, so the library-level export/deletion (which walks the
    identity registry) cannot see them — without this, 'delete my data' would orphan
    every domain row. Returns '' when no entity is user-owned."""
    policies = policies or {}
    owned = [(e["name"], (policies.get(e["name"]) or {}).get("owner_field")) for e in entities]
    owned = [(n, of) for n, of in owned if of]
    if not owned:
        return ""
    names = ", ".join(n for n, _ in owned)
    L = ['"""Generated data-subject helpers (export + erasure) for domain-owned tables.',
         "The domain models live in their own DeclarativeBase registry, invisible to the",
         'library identity export/deletion; this module closes that gap."""',
         "from __future__ import annotations",
         "from sqlalchemy import select, delete, inspect as _inspect",
         f"from .models import {names}", "", "",
         f"OWNED = [{', '.join(f'({n}, {of!r})' for n, of in owned)}]", "", "",
         "def _ser(v):",
         "    from datetime import datetime, date",
         "    return v.isoformat() if isinstance(v, (datetime, date)) else v", "", "",
         "def export_user_data(db, user_id: int) -> dict:",
         '    """All domain rows owned by the user, keyed by table (DSAR / portability)."""',
         "    out = {}",
         "    for model, owner in OWNED:",
         "        rows = db.scalars(select(model).where(getattr(model, owner) == user_id)).all()",
         "        if rows:",
         "            out[model.__tablename__] = [",
         "                {c.key: _ser(getattr(r, c.key)) for c in _inspect(model).columns} for r in rows]",
         "    return out", "", "",
         "def stream_user_data(db, user_id: int):",
         '    """Stream every domain row owned by the user as NDJSON — one JSON record per',
         "    line, pulled with a server-side cursor (yield_per) so memory stays bounded",
         '    regardless of account size. Each line carries its source table as \'_table\'."""',
         "    import json",
         "    for model, owner in OWNED:",
         "        cols = [c.key for c in _inspect(model).columns]",
         "        q = select(model).where(getattr(model, owner) == user_id).execution_options(yield_per=200)",
         "        for r in db.scalars(q):",
         "            rec = {'_table': model.__tablename__}",
         "            for k in cols:",
         "                rec[k] = _ser(getattr(r, k))",
         "            yield json.dumps(rec, default=str) + '\\n'", "", "",
         "def delete_user_data(db, user_id: int) -> dict:",
         '    """Erase all domain rows owned by the user (right to erasure). Per-table counts."""',
         "    counts = {}",
         "    for model, owner in OWNED:",
         "        res = db.execute(delete(model).where(getattr(model, owner) == user_id))",
         "        counts[model.__tablename__] = res.rowcount or 0",
         "    db.flush()",
         "    return counts"]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    domain_name, out = argv[0], argv[1]
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import resolve as R
    domain = R.load_domain(domain_name)
    if not domain:
        print(f"unknown domain: {domain_name}")
        return 1
    entities = [{"name": e["name"], "fields": norm_fields(e),
                 **({"state_machine": e["state_machine"]} if e.get("state_machine") else {}),
                 **({"reference_rules": e["reference_rules"]} if e.get("reference_rules") else {}),
                 **({"no_overlap": e["no_overlap"]} if e.get("no_overlap") else {})}
                for e in domain.get("entities", [])]
    if not entities:
        print("domain has no entities")
        return 1
    chain = domain.get("extends_chain", [domain_name])
    tier = domain.get("data_sensitivity") or "low"
    eps = effective_policies(entities, domain)               # tier defaults + explicit overrides
    protected = {n: p for n, p in eps.items() if p}          # entities with any policy
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "__init__.py"), "w", encoding="utf-8").write("")
    links = domain.get("many_to_many") or []
    open(os.path.join(out, "models.py"), "w", encoding="utf-8").write(gen_models(entities, policies=eps, links=links))
    open(os.path.join(out, "schemas.py"), "w", encoding="utf-8").write(gen_schemas(entities))
    open(os.path.join(out, "services.py"), "w", encoding="utf-8").write(gen_services(entities, links=links))
    open(os.path.join(out, "routes.py"), "w", encoding="utf-8").write(gen_routes(entities, wire="--wire" in argv, policies=eps, links=links))
    priv = gen_privacy(entities, policies=eps)
    if priv:
        open(os.path.join(out, "privacy.py"), "w", encoding="utf-8").write(priv)
    explicit = set(domain.get("route_policies") or {})
    if protected:
        src = "explicit policies" if explicit else f"'{tier}' tier defaults"
        tag = f"  [security: {tier} — {len(protected)}/{len(entities)} entities protected via {src}]"
    else:
        tag = f"  [security: {tier} — generic CRUD]"
    print(f"generated {len(entities)} entities -> {out}/  "
          f"(models, schemas, services, routes)" + tag
          + (f"  [merged via {' <- '.join(chain)}]" if len(chain) > 1 else "") + ": "
          + ", ".join(e["name"] for e in entities))
    for w in sensitivity_warnings(entities, domain):
        print(f"  [WARN security] {w}")
    renamed = [(e["name"], _table_name(e["name"])) for e in entities if _plural(e["name"]) in RESERVED_TABLES]
    for ename, tname in renamed:
        print(f"  [collision-safe] {ename} table -> '{tname}' (avoids library-owned '{_plural(ename)}'); route stays /{_plural(ename)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
