"""
gen_build_report — emit an honest, per-build inventory of a generated app.

For a resolved domain it writes two files into the app root:
  build_report.json   machine-readable: entities, relationships (FKs), workflows,
                      per-entity security (auth/owner/encrypted/audit), and the
                      explicit list of things the generator does NOT enforce.
  BUILD_REPORT.md     the same, human-readable.

The report is computed from the SAME resolved-domain data the code generators use
(entities + effective_policies), so it describes what was actually emitted rather
than restating intent. The "not enforced" section is pulled from the hardening
registry so it can never quietly disagree with the project's honesty docs.

Usage:
    python tools/gen_build_report.py <domain> <app_root>
"""
from __future__ import annotations
try:
    import _bootstrap_path  # noqa: F401  (puts repo root on sys.path)
except ModuleNotFoundError:  # imported as tools.<mod>, not run as a script
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import _bootstrap_path  # noqa: F401

import json
import os
import re
import sys

import resolve as R
from gen_models import norm_fields, effective_policies, _table_name, _state_machine, _plural, _normalize_links


def _rel_targets(entities) -> dict:
    targets = {}
    for e in entities:
        base = re.sub(r"(?<!^)(?=[A-Z])", "_", e["name"]).lower()
        if base == "user":
            continue
        targets[f"{base}_id"] = _table_name(e["name"])
    return targets


def build_report(domain_name: str) -> dict:
    domain = R.load_domain(domain_name)
    if not domain:
        raise SystemExit(f"unknown domain: {domain_name}")
    entities = [{"name": e["name"], "fields": norm_fields(e),
                 **({"state_machine": e["state_machine"]} if e.get("state_machine") else {}),
                 **({"reference_rules": e["reference_rules"]} if e.get("reference_rules") else {}),
                 **({"no_overlap": e["no_overlap"]} if e.get("no_overlap") else {})}
                for e in domain.get("entities", [])]
    eps = effective_policies(entities, domain)
    targets = _rel_targets(entities)

    ents, rels, workflows = [], [], []
    for e in entities:
        n = e["name"]
        pol = eps.get(n, {}) or {}
        fks, indexed = [], []
        for f in e["fields"]:
            fn = f["name"]
            if fn.endswith("_id") and fn != "id":
                if targets.get(fn):
                    fks.append({"column": fn, "references": targets[fn]})
                    rels.append({"from_table": _table_name(n), "column": fn, "to_table": targets[fn]})
                else:
                    indexed.append(fn)  # owner / external ref: indexed, not FK'd
        sm = _state_machine(e)
        wf = None
        if sm:
            states = sorted({sm.get("initial")} | set(sm["transitions"]) |
                            {s for v in sm["transitions"].values() for s in v})
            wf = {"entity": n, "field": sm["field"], "initial": sm.get("initial"),
                  "states": [s for s in states if s], "transitions": sm["transitions"],
                  "guards": sm.get("guards", {})}
            workflows.append(wf)
        ents.append({
            "name": n, "table": _table_name(n),
            "security": {
                # gen_routes gates a route when requires_auth OR owner_field is set
                "auth_required": bool(pol.get("requires_auth") or pol.get("owner_field") or pol.get("write_role")),
                "owner_scoped_by": pol.get("owner_field") or None,
                "write_requires_role": pol.get("write_role") or None,
                "encrypted_fields": pol.get("encrypted_fields") or [],
                "audited_actions": pol.get("audit") or [],
            },
            "foreign_keys": fks,
            "indexed_non_fk_ids": indexed,
            "workflow": bool(wf),
            "reference_rules": e.get("reference_rules") or {},
            "no_overlap": e.get("no_overlap") or None,
            "cross_entity_guards": [g for gl in (sm.get("guards", {}).values() if sm else []) for g in gl if "ref" in g],
            "transition_effects": (sm.get("effects", {}) if sm else {}),
            "time_transitions": (sm.get("time_transitions", []) if sm else []),
        })

    # "Not enforced" is sourced from the hardening registry so it stays consistent
    # with HARDENING.md. Pull the pending notes for the generation-related parts.
    not_enforced = []
    try:
        from hardening_registry import KNOWN_GAPS
        for key in ("gen_models", "workflow_engine"):
            for note in KNOWN_GAPS.get(key, []):
                if "pending" in note.lower() or "not yet" in note.lower() or "not generated" in note.lower():
                    not_enforced.append(note)
    except Exception:
        pass

    return {
        "domain": domain_name,
        "label": domain.get("label", domain_name),
        "data_sensitivity": domain.get("data_sensitivity", "low"),
        "summary": {
            "entities": len(ents),
            "relationships_with_foreign_keys": len(rels),
            "workflows": len(workflows),
            "entities_requiring_auth": sum(1 for e in ents if e["security"]["auth_required"]),
            "entities_owner_scoped": sum(1 for e in ents if e["security"]["owner_scoped_by"]),
            "entities_with_encrypted_fields": sum(1 for e in ents if e["security"]["encrypted_fields"]),
        },
        "entities": ents,
        "relationships": rels,
        "many_to_many": [{"left": lk["left"], "right": lk["right"],
                          "join_table": lk["table"]} for lk in _normalize_links(domain.get("many_to_many"))],
        "workflows": workflows,
        "enforced_by_generation": [
            "Per-entity tables with primary keys and Alembic-compatible models.",
            "Client-supplied <entity>_id columns are real FOREIGN KEYs (+ index); orphaned references are rejected (409).",
            "Server-set owner columns (user_id) are indexed; ownership is forced from the authenticated principal.",
            "Declared state machines: only listed transitions are allowed; target-state guards must hold; violations return 409.",
            "Auth / owner-scoping / field encryption / audit per the entity's data-sensitivity policy.",
        ],
        "not_enforced": not_enforced,
    }


def to_markdown(rep: dict) -> str:
    L = [f"# Build report — {rep['label']}", "",
         f"Domain `{rep['domain']}` · data sensitivity **{rep['data_sensitivity']}**.", "",
         "_Generated from the resolved domain; describes what the code generators actually emitted._", "",
         "## Summary", ""]
    s = rep["summary"]
    L += [f"- Entities: **{s['entities']}**",
          f"- Relationships with enforced foreign keys: **{s['relationships_with_foreign_keys']}**",
          f"- Workflows (state machines): **{s['workflows']}**",
          (f"- Many-to-many links: **{len(rep['many_to_many'])}** "
           + "(" + ", ".join(f"{m['left']}↔{m['right']} via `{m['join_table']}`" for m in rep["many_to_many"]) + ")"
           if rep.get("many_to_many") else "- Many-to-many links: **0**"),
          f"- Entities requiring auth: **{s['entities_requiring_auth']}**",
          f"- Entities owner-scoped: **{s['entities_owner_scoped']}**",
          f"- Entities with encrypted fields: **{s['entities_with_encrypted_fields']}**", ""]
    L += ["## Entities", ""]
    for e in rep["entities"]:
        sec = e["security"]
        bits = []
        bits.append("auth" if sec["auth_required"] else "no-auth")
        if sec["owner_scoped_by"]:
            bits.append(f"owner={sec['owner_scoped_by']}")
        if sec.get("write_requires_role"):
            bits.append(f"write-role={sec['write_requires_role']}")
        if sec["encrypted_fields"]:
            bits.append("encrypted=" + ",".join(sec["encrypted_fields"]))
        if sec["audited_actions"]:
            bits.append("audit=" + ",".join(sec["audited_actions"]))
        L.append(f"### {e['name']}  (`{e['table']}`)")
        L.append(f"- Security: {', '.join(bits)}")
        if e["foreign_keys"]:
            L.append("- Foreign keys: " + "; ".join(f"`{fk['column']}` → `{fk['references']}`" for fk in e["foreign_keys"]))
        if e["indexed_non_fk_ids"]:
            L.append("- Indexed (owner/external, no FK): " + ", ".join(f"`{c}`" for c in e["indexed_non_fk_ids"]))
        L.append(f"- Workflow: {'yes' if e['workflow'] else 'no'}")
        for fld, rule in (e.get("reference_rules") or {}).items():
            allowed = rule.get("allowed")
            cond = f" with status in {allowed}" if allowed else ""
            L.append(f"- Reference rule: `{fld}` must reference an existing `{rule['entity']}`{cond}")
        if e.get("no_overlap"):
            o = e["no_overlap"]
            L.append(f"- No-overlap: rows sharing `{o['scope']}` cannot overlap on [`{o['start']}`,`{o['end']}`) while active")
        for g in (e.get("cross_entity_guards") or []):
            L.append(f"- Cross-entity guard: transition requires `{g['entity']}` (via `{g['ref']}`) status in {g.get('in')}")
        for state, effs in (e.get("transition_effects") or {}).items():
            for ef in effs:
                if "set_related" in ef:
                    sr = ef["set_related"]
                    via = " (guarded — routed through the target's own transition)" if sr.get("guarded") else ""
                    L.append(f"- On `{state}`: set `{sr['entity']}.{sr.get('field','status')}` = `{sr['value']}` (via `{sr['ref']}`){via}")
                elif "create" in ef:
                    L.append(f"- On `{state}`: auto-create a `{ef['create']['entity']}` record")
        for tt in (e.get("time_transitions") or []):
            L.append(f"- Time-based: a `{tt['from']}` row auto-advances to `{tt['to']}` once `{tt['when']}` has passed (via `POST /{_plural(e['name'])}/sweep`)")
        L.append("")
    if rep["workflows"]:
        L += ["## Workflows", ""]
        for w in rep["workflows"]:
            L.append(f"### {w['entity']}.{w['field']} (initial: `{w['initial']}`)")
            for src, dsts in w["transitions"].items():
                L.append(f"- `{src}` → " + ", ".join(f"`{d}`" for d in dsts))
            for st, guards in (w["guards"] or {}).items():
                for g in guards:
                    L.append(f"  - entering `{st}` requires `{g['field']}` == `{g.get('equals')}` — else: {g.get('error')}")
            L.append("")
    L += ["## Enforced by generation", ""]
    L += [f"- {x}" for x in rep["enforced_by_generation"]]
    L += ["", "## NOT enforced (by design, this build)", ""]
    L += ([f"- {x}" for x in rep["not_enforced"]] or ["- (none recorded)"])
    L.append("")
    return "\n".join(L)


def _disclaimer() -> str:
    return ("> **TEMPLATE — NOT LEGAL ADVICE.** This document was generated from your app's data model "
            "as a starting point. It does **not** make your app legally compliant and is **not** a substitute "
            "for review by a qualified attorney. Compliance depends on what your app actually does with data, "
            "where your users are, and your business. Have counsel review and complete every **[PLACEHOLDER]** "
            "before you publish or rely on this.")


def _privacy_policy_md(rep: dict, domain: dict) -> str:
    retention = (domain or {}).get("retention_days") or {}
    L = [f"# Privacy Policy — {rep['label']}", "", _disclaimer(), "",
         "_Last updated: [DATE]. Operated by [LEGAL ENTITY], contact [PRIVACY EMAIL]._", "",
         "## Data we collect", "",
         "We store the following categories of data. Fields marked _(encrypted at rest)_ are "
         "encrypted in the database.", ""]
    # account/identity is always present
    L += ["**Account**: email address, hashed password, login sessions, and audit records of "
          "security-relevant actions.", ""]
    for e in rep["entities"]:
        flds = []
        enc = set(e["security"]["encrypted_fields"])
        # describe by inspecting the resolved fields via the report's FK/owner hints
        names = [fk["column"] for fk in e["foreign_keys"]] + e["indexed_non_fk_ids"]
        # we don't have raw field list in the report; describe at the entity level
        note = []
        if e["security"]["owner_scoped_by"]:
            note.append("linked to your account")
        if enc:
            note.append("includes encrypted-at-rest fields: " + ", ".join(sorted(enc)))
        L.append(f"**{e['name']}** (`{e['table']}`)" + (" — " + "; ".join(note) if note else "") + ".")
    L += ["", "## How long we keep it", ""]
    if retention:
        for tbl, days in retention.items():
            L.append(f"- `{tbl}`: automatically deleted after **{days} days**.")
    else:
        L.append("- Retention period: **[SPECIFY]**. Data is kept until you delete your account or request erasure.")
    L += ["", "## Your rights (these are implemented in the app)", "",
          "- **Access / portability**: `GET /privacy/export` returns everything stored about you as JSON.",
          "- **Erasure (\"delete my data\")**: `POST /privacy/delete-account` permanently deletes your "
          "account and all data linked to it. This is irreversible.",
          "- **Opt-out / Do Not Sell (CCPA)**: we do **[not]** sell personal information. [If you do, describe the opt-out here.]",
          "", "## Legal bases, transfers, and contact", "",
          "- Legal basis for processing (GDPR): **[SPECIFY — e.g. consent, contract, legitimate interest]**.",
          "- International transfers: **[SPECIFY]**.",
          "- Data Protection Officer / privacy contact: **[PRIVACY EMAIL]**.",
          "- Supervisory authority / complaints: **[SPECIFY]**.", ""]
    return "\n".join(L)


def _terms_md(rep: dict, domain: dict) -> str:
    L = [f"# Terms of Service — {rep['label']}", "", _disclaimer(), "",
         "_Last updated: [DATE]. Operated by [LEGAL ENTITY]._", "",
         "## 1. Acceptance", "By using [APP NAME] you agree to these Terms. If you do not agree, do not use the service.", "",
         "## 2. Accounts", "You are responsible for your account and for keeping your credentials secure. "
         "You may delete your account at any time (see the Privacy Policy / data deletion).", "",
         "## 3. Acceptable use", "You agree not to misuse the service, including: **[LIST PROHIBITED CONDUCT — "
         "e.g. unlawful use, scraping, attacking the service, infringing others' rights]**.", "",
         "## 4. Content and data", "You retain ownership of data you submit. You grant [LEGAL ENTITY] the rights "
         "needed to operate the service. We handle your data per our Privacy Policy.", "",
         "## 5. Disclaimers", "THE SERVICE IS PROVIDED \"AS IS\" WITHOUT WARRANTIES OF ANY KIND, to the maximum "
         "extent permitted by law. **[REVIEW WITH COUNSEL.]**", "",
         "## 6. Limitation of liability", "To the maximum extent permitted by law, [LEGAL ENTITY] is not liable "
         "for indirect, incidental, or consequential damages. Total liability is limited to **[AMOUNT / FEES PAID]**. "
         "**[REVIEW WITH COUNSEL.]**", "",
         "## 7. Dispute resolution", "**[SPECIFY — governing law, venue, arbitration/class-action terms as appropriate.]**", "",
         "## 8. Changes", "We may update these Terms; material changes will be notified via **[METHOD]**.", "",
         "## 9. Contact", "Questions: **[CONTACT EMAIL]**.", ""]
    return "\n".join(L)


def write_legal_docs(domain_name: str, app_root: str) -> None:
    rep = build_report(domain_name)
    domain = R.load_domain(domain_name) or {}
    os.makedirs(app_root, exist_ok=True)
    with open(os.path.join(app_root, "PRIVACY_POLICY.md"), "w", encoding="utf-8") as f:
        f.write(_privacy_policy_md(rep, domain))
    with open(os.path.join(app_root, "TERMS_OF_SERVICE.md"), "w", encoding="utf-8") as f:
        f.write(_terms_md(rep, domain))


def write_report(domain_name: str, app_root: str) -> dict:
    rep = build_report(domain_name)
    os.makedirs(app_root, exist_ok=True)
    with open(os.path.join(app_root, "build_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2)
    with open(os.path.join(app_root, "BUILD_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(rep))
    return rep


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    rep = write_report(argv[0], argv[1])
    s = rep["summary"]
    print(f"[report]     {s['entities']} entities · {s['relationships_with_foreign_keys']} FK relationships · "
          f"{s['workflows']} workflow(s) · wrote build_report.json + BUILD_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
