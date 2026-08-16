# Risk register

Risks implied by the selected capabilities and domain.

## authentication
- account takeover
- session/token theft
- weak password reset

## auth_routes
- credential stuffing
- enumeration via login errors

## billing_stripe
- webhook replay
- entitlement mismatch
- cancellation inconsistency

## stripe_webhooks
- forged events if unsigned
- double-processing

- (domain high) sensitive data exposure
- (domain high) insufficient deletion/retention controls
- (domain high) over-collection of personal data