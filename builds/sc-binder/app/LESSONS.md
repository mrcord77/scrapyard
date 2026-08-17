# Lessons from past builds — apply these

## L003 — JWTs need short TTL + revocation at scale
**Problem:** Long-lived stateless JWTs can't be revoked, a liability as user count grows.

**Fix:** Keep access tokens short-lived, issue refresh tokens, and maintain a revocation list once past MVP.

