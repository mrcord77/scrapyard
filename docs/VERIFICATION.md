# How Scrapyard verification works

Scrapyard uses several evidence levels because one green number would hide more
than it explains.

## Evidence levels

### 1. Catalog integrity

`tools/index_catalog.py` parses each module's metadata, imports the module, and
AST-scans for non-abstract `NotImplementedError`, `pass`, and ellipsis
placeholders. It computes catalog status from those observations instead of
trusting the module's own label. The scan cannot identify every semantic no-op.

This proves that the documented import surface is present in the verification
environment. It does not prove that every branch behaves correctly.

### 2. Module self-tests

Every catalog module defines `_selftest()` and exposes it through:

```bash
python -m scrapyard.<layer>.<part>
```

`tools/verify_part_selftests.py` runs those checks in isolated child processes.
The checks are intended to be offline and to include at least one negative case.
They are small contract examples, not comprehensive unit-test suites.

### 3. Behavior contracts

`tools/verify_build.py` maps product capabilities to behavior checks. These
exercise interactions such as password verification, token rejection,
persistence, authorization, generated CRUD, and production fallback gates.

Some contracts require live PostgreSQL and Redis. A skipped external-service
contract is not equivalent to a pass and must be reported separately.

### 4. Workflow and runtime verification

Workflow checks exercise sequences across multiple capabilities. Runtime checks
boot generated applications and make requests through the resulting HTTP
surface. These are deeper than module checks and intentionally cover fewer
capabilities. `VERIFICATION_COVERAGE.md` publishes that difference.

### 5. Hardening and operations

`HARDENING.md` records evidence still needed for production deployment: key
rotation, recovery, tamper resistance, failure behavior, live-provider paths,
and operational ownership. “Core” or “verified” never means “safe to deploy
unchanged.”

## Security review terminology

An automated adversarial review found exploitable defects.
The fixes are preserved as regression tests. This is evidence of a useful review
cycle, but it is not independent professional assurance. The project will use
“independent audit” only if an unaffiliated qualified reviewer performs one and a
public report is available.

## Reproducing results

Install `.[dev]` first. That extra intentionally includes the catalog's broad
verification environment; consumers who copy one part should install only the
dependencies declared by that part.

Offline:

```bash
python tools/index_catalog.py --out .verification/catalog
python tools/verify_part_selftests.py --jobs 4
python tools/ui_lint.py
python tests/security_regression.py
```

Full CI substrate:

```bash
python tools/migrate.py upgrade head
python tools/migrate.py check
python tools/verify_build.py all
python tools/build_matrix.py
python tools/verify_runtime.py --domain healthcare --secure
python tools/verify_runtime.py --domain sobriety --fullstack
```

The full commands require the dependencies and services configured in
`.github/workflows/ci.yml`.
