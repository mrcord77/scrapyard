# Release process

## Repository boundary

The public repository root is this `scrapyard-library/` directory. Do not publish
the surrounding `scrapyard-library-v73-migration-substrate/` workspace: it
contains historical migration material and separately sourced agent-skill packs
that are not part of Scrapyard's MIT-licensed distribution.

## Checklist

1. Start from a clean worktree and use Python 3.12.
2. Install with `python -m pip install -e ".[dev]"`.
3. Run the offline evidence gates:

   ```bash
   python tools/index_catalog.py --out .verification/catalog
   python tools/verify_part_selftests.py --jobs 4 \
     --json .verification/part-selftests.json
   python tools/ui_lint.py
   python tests/security_regression.py
   ```

4. Run the full GitHub Actions gate with PostgreSQL, Redis, and Docker.
5. Confirm `HARDENING.md` and `VERIFICATION_COVERAGE.md` match the claims in the
   README.
6. Build the distribution without network access:

   ```bash
   python -m pip wheel . --no-deps --no-build-isolation --no-cache-dir \
     --wheel-dir dist
   ```

7. Inspect the wheel contents and verify it in a fresh virtual environment.
8. Update `CHANGELOG.md`, tag the exact green commit, and publish checksums.

Generated databases, assembled output directories, local verification reports,
and `.env` files are intentionally ignored and must not be added to a release.
