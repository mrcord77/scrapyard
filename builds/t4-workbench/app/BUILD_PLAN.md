# Build plan — agent_platform + research_workbench
Stage **mvp**, mode **GATE**.

- Pattern inheritance: agent_platform
- Domain inheritance: research_workbench
- Parts resolved: 46

## Requirements enforcement
- must_have: none — **HONORED**
- must_not: none — **HONORED**
- Gate findings: none

## Verdicts
- Validation: **FAIL**
- Fitness: **FIT**
- Behavior verification: VERIFIED (21 behaviors proven, 0 failed)
- Workflow verification: **4 verified**, 0 blocked (stub-dependent), 0 failed
- Plan confidence: avg **0.79** (proven 43, unknown 3)

## Active lessons (mitigations missing from this plan)
- none — all applicable lesson mitigations present

## Generated code wiring
- Generated routers mounted via `main.py` (create_app(routers=[...])).

## Dossier
- [START.md](START.md)
- [CAPABILITIES.md](CAPABILITIES.md)
- [DOMAIN.md](DOMAIN.md)
- [LESSONS.md](LESSONS.md)
- [CONFIDENCE.md](CONFIDENCE.md)
- [OPERATIONS.md](OPERATIONS.md)
- [OPERATIONS_REASONING.md](OPERATIONS_REASONING.md)
- [FITNESS.md](FITNESS.md)
- [SIMULATION.md](SIMULATION.md)
- [DECISIONS.md](DECISIONS.md)
- [RISK_REGISTER.md](RISK_REGISTER.md)
- [COST.md](COST.md)
- [main.py](main.py)

## Next
1. `pip install -r requirements.txt`
2. All parts are implemented; see CONFIDENCE.md (contract-tested vs. needs hardening) and CAPABILITIES.md (endpoints, required config, local-only fallbacks).
3. Address FITNESS.md / SIMULATION.md findings before launch.
4. Configure secrets from the validation output.