# Scrapyard agent guide

This is a concise operating guide for coding agents. It does not duplicate the
catalog or make release claims. Humans should start with `README.md`.

## Project model

- `scrapyard/<layer>/<part>.py` contains reusable source parts.
- `catalog.json` is the generated machine-readable index.
- Every part has a `PART-META-JSON` header, `_selftest()`, and a `python -m`
  entry point.
- `tools/` contains catalog, assembly, generation, and verification commands.
- `HARDENING.md` and `VERIFICATION_COVERAGE.md` define evidence boundaries.

## Required checks

For a changed part, run its module self-test and the catalog verifier. Before a
release, run:

```bash
python tools/index_catalog.py --out .verification/catalog
python tools/verify_part_selftests.py --jobs 4
python tools/ui_lint.py
python tests/security_regression.py
python tools/verify_build.py all
```

The complete CI gate additionally uses PostgreSQL, Redis, npm, and Docker.

## Change rules

- Preserve focused, copyable modules and public API compatibility where practical.
- Do not call a part verified merely because it imports.
- Add positive and negative assertions for behavioral changes.
- Keep module-specific security notes accurate.
- Never hide missing services behind successful offline fallbacks in production.
- Do not edit `catalog.json` by hand; regenerate it with `tools/index_catalog.py`.
- Treat generated applications as reviewed starting points, not finished products.

See `CONTRIBUTING.md` and `docs/VERIFICATION.md` for the public acceptance bar.
