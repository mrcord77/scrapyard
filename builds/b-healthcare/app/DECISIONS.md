# Architecture decisions

- Pattern: **saas_subscription_app**
- Domain: **healthcare**
- Stage: **growth**
- Date: 2026-08-16

## Strategy choices

### authentication: chose **Managed auth (Clerk/Auth0-style)** (score 4.67 @ growth)
- Why: Fastest to ship and offloads security; recurring cost and vendor lock-in; outside the yard.
- Alternatives: Delegated OAuth / social login (4.0), Server session cookies (3.67), Stateless JWT (3.67)

### password_hashing: chose **Argon2id** (score 4.33 @ growth)
- Why: Current best practice; memory-hard; the yard's default.
- Alternatives: bcrypt (4.33)
