# Scrapyard

Scrapyard is a catalog of small Python building blocks for web applications.
Instead of adopting another framework, you select a capability, inspect its
contract, and copy the implementation into your project.

The catalog currently contains **582 documented modules across 60 capability
layers**. The structural verifier currently classifies **all 582 as core, with
zero explicit placeholders**. That is a narrow structural result—metadata,
imports, and placeholder scanning—not a claim that every branch is complete or
production-ready. The collection is strongest in backend application infrastructure:
configuration, APIs, identity, authorization, databases, security, billing,
jobs, operations, and server-rendered UI.

> **Release status: 0.1 alpha.** Scrapyard is a source catalog, not a promise that
> every module is production-ready. The repository distinguishes import checks,
> module self-tests, behavior contracts, runtime integration, and production
> hardening. See [How verification works](docs/VERIFICATION.md).

## Why this exists

Application projects repeatedly rebuild the same infrastructure. Large
frameworks solve that problem by owning the application. Scrapyard takes the
opposite approach: each part is ordinary Python with an explicit API, dependency
list, example, security notes, and a local self-test. You keep the code you choose.

This makes Scrapyard useful as:

- a searchable reference implementation library;
- a starting point for code you intend to own and adapt;
- an input catalog for code-generation or agent-assisted development; and
- an experimental test bed for making generated code auditable.

## Start with one part

Clone the repository and install the verification environment:

```bash
python -m pip install -e ".[dev]"
```

Run one module's local behavioral check:

```bash
python -m scrapyard.security.rate_limiting
```

Then inspect and use the implementation:

```python
from scrapyard.security.rate_limiting import get_rate_limiter

limiter = get_rate_limiter(capacity=30, refill_per_sec=0.5)
if not limiter.allow("user:123"):
    raise RuntimeError("rate limit exceeded")
```

For multi-process production deployments, configure the Redis backend. The
module refuses the in-memory backend when `APP_ENV=production`:

```bash
APP_ENV=production RATE_LIMIT_BACKEND=redis REDIS_URL=redis://localhost:6379/0
```

## Find parts locally

`catalog.json` is the generated machine-readable index. The local librarian adds
ranked text search without sending catalog contents to an external service:

```python
from scrapyard.curation.metadata_harvester import refresh
from scrapyard.curation.librarian_service import LibrarianService

refresh("curation_catalog.db", "scrapyard")
library = LibrarianService("curation_catalog.db", root_dir="scrapyard")
for part in library.get_parts("distributed rate limiting")[:3]:
    print(part.part_id, part.score)
```

## Reproduce the evidence

The short, offline checks are:

```bash
python tools/index_catalog.py --out .verification/catalog
python tools/verify_part_selftests.py --jobs 4
python tools/ui_lint.py
python tests/security_regression.py
```

They establish different things:

| Check | What it establishes | What it does not establish |
|---|---|---|
| Catalog verifier | Metadata parses, modules import, and explicit hollow markers are reported | Correctness of every API or detection of semantic no-ops |
| Module self-tests | Each module's author-defined positive and negative sanity cases pass | Exhaustive coverage or production fitness |
| UI lint | Shared-token usage and server-rendered composition | Bespoke visual quality or browser-matrix coverage |
| Security regressions | Previously discovered exploit classes stay closed | A professional independent security audit |

The deeper CI gate uses PostgreSQL and Redis to exercise behavior contracts,
generated applications, migrations, request-level isolation, and Docker builds.
Current coverage and remaining gaps are recorded in
[VERIFICATION_COVERAGE.md](VERIFICATION_COVERAGE.md) and
[HARDENING.md](HARDENING.md).

## Build from a product description

Scrapyard also contains an experimental assembly layer. It resolves product
patterns and domains into a generated application:

```bash
python tools/resolve.py --list
python tools/resolve.py saas_subscription_app --domain sobriety
python tools/eos.py --request specs/examples/sobriety_journal.json --out ../example-app
```

Treat generated output as a reviewed starting point. Generation does not make an
application secure, compliant, legally sufficient, or operationally ready.

## Repository layout

```text
scrapyard/                 reusable modules grouped by capability
tools/                     catalog, assembly, generation, and verification tools
tests/                     cross-module security regressions
patterns/ and domains/     experimental application-resolution inputs
templates/                 fixed assembly recipes
catalog.json               generated module index
HARDENING.md               known production-readiness gaps
VERIFICATION_COVERAGE.md   measured verification depth
```

Every module contains a `PART-META-JSON` block describing its purpose, public
surface, dependencies, example, and security boundaries. The catalog generator
derives verification status rather than trusting the module's declared status.

## Scope and limitations

- Scrapyard is Python-first and FastAPI/SQLAlchemy-oriented.
- The UI layer renders HTML with shared design tokens; it is not a React component
  library.
- Some integrations are deliberately offline or adapter-only until configured.
- The Stripe API call path is not wired; webhook and lifecycle logic are tested,
  but the repository does not create real charges.
- Local post-quantum implementations are reference implementations, not
  constant-time or independently audited.
- Runtime and workflow verification cover a smaller subset than module-level
  checks. The exact numbers are published rather than collapsed into one badge.

## AI assistance and provenance

Scrapyard was built with substantial AI assistance and human direction. That is
why the repository emphasizes executable checks, explicit limitations, and
reviewable source instead of claiming that authorship implies quality. A Codex
adversarial review found concrete defects; those cases were converted into
regression tests. This was useful engineering feedback, **not an independent
professional security audit**.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the acceptance bar and
[SECURITY.md](SECURITY.md) for responsible disclosure.

## License

MIT. See [LICENSE](LICENSE).
