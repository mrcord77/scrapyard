# Contributing to Scrapyard

Scrapyard accepts small, reviewable application parts and improvements to the
verification system around them. Breadth is not the goal: a smaller module with
an explicit boundary and a falsifiable check is preferable to a large module
that merely looks complete.

## Acceptance bar

A new or materially changed part must:

1. expose a focused public API;
2. include valid `PART-META-JSON` with concrete inputs, outputs, dependencies,
   examples, and module-specific security notes;
3. define `_selftest()` with at least one positive and one negative assertion;
4. run through `python -m scrapyard.<layer>.<part>` without network access;
5. avoid hidden fallbacks that make production behavior look successful;
6. use safe parameterization and argument-vector subprocess calls when handling
   untrusted data; and
7. state what remains unverified or requires external infrastructure.

Importability is necessary but is not sufficient evidence of correctness.
Security-sensitive changes should also add a cross-module regression under
`tests/` or a behavior contract in `tools/verify_build.py`.

## Local checks

Install the development environment:

```bash
python -m pip install -e ".[dev]"
```

Run the offline release checks:

```bash
python tools/index_catalog.py --out .verification/catalog
python tools/verify_part_selftests.py --jobs 4
python tools/ui_lint.py
python tests/security_regression.py
```

The full integration gate additionally requires PostgreSQL and Redis configured
through `SCRAPYARD_TEST_PG_URL` and `SCRAPYARD_TEST_REDIS_URL`.

## Pull requests

Keep pull requests scoped. Explain the behavior being changed, the failure mode
the test proves, and any production boundary that remains. Do not describe an
AI-generated implementation as reviewed merely because it imports or generated
plausible output.

Generated metadata and indexes should be refreshed in the same change:

```bash
python tools/index_catalog.py
python tools/verification_coverage.py
```
