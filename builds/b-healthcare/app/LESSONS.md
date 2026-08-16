# Lessons from past builds — apply these

## L001 — Verify Stripe webhook signatures before trusting events
**Problem:** Unverified webhooks let attackers forge subscription state.

**Fix:** In stripe_webhooks, check the Stripe-Signature header against STRIPE_WEBHOOK_SECRET before mutating subscription_status.

## L003 — JWTs need short TTL + revocation at scale
**Problem:** Long-lived stateless JWTs can't be revoked, a liability as user count grows.

**Fix:** Keep access tokens short-lived, issue refresh tokens, and maintain a revocation list once past MVP.

