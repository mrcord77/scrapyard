# Security policy

Scrapyard is an alpha source catalog. Its modules must be reviewed in the context
of the application that adopts them. A passing local check is not a security
certification, and the project has not received an independent professional
security audit.

## Supported version

Security fixes currently target the latest commit on the default branch. A
stable support window will be defined after the first non-alpha release.

## Reporting a vulnerability

Please do not open a public issue for an exploitable vulnerability. Use GitHub's
private vulnerability reporting feature when enabled, or contact the repository
owner privately through the address in the commit metadata. Include:

- the affected module and public function;
- a minimal reproduction;
- expected and observed behavior;
- likely impact and required attacker control; and
- whether the issue is already public.

Reports will be acknowledged as soon as practical. Confirmed issues should be
fixed with a regression test that reproduces the exploit before the patch and
stays closed afterward.

## Security boundaries

- Module self-tests are narrow sanity checks, not penetration tests.
- `tests/security_regression.py` covers previously discovered exploit classes,
  not every possible vulnerability.
- Local cryptographic reference implementations are not constant-time or
  independently audited.
- External-service adapters require deployment-specific authentication,
  authorization, secret storage, timeout, and retry policies.
- Generated legal, privacy, tax, and compliance documents are templates, not
  professional advice or proof of compliance.
