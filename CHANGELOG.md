# Changelog

All notable public changes will be recorded here. Scrapyard follows Semantic
Versioning after the first stable release; pre-1.0 releases may refine public
interfaces while documenting migrations.

## [Unreleased]

### Changed

- Reframed verification claims around distinct, reproducible evidence levels.
- Added an isolated runner for all module self-tests.
- Rejected process-local rate limiting in production environments.
- Replaced shell-evaluated deployment smoke commands with argument-vector
  subprocess execution.
- Added Python packaging metadata and public contribution/security policies.

## [0.1.0] — 2026-08-09

### Added

- Initial alpha catalog with 582 documented modules across 60 layers.
- Computed catalog integrity checks, behavior contracts, generated-app runtime
  checks, UI composition linting, and security regression coverage.
