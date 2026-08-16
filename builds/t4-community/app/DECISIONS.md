# Architecture decisions

- Pattern: **basic_saas**
- Domain: **community_platform**
- Stage: **mvp**
- Date: 2026-08-16

## Strategy choices

### authentication: chose **Managed auth (Clerk/Auth0-style)** (score 4.67 @ mvp)
- Why: Fastest to ship and offloads security; recurring cost and vendor lock-in; outside the yard.
- Alternatives: Delegated OAuth / social login (4.0), Server session cookies (3.83), Stateless JWT (3.33)

### password_hashing: chose **bcrypt** (score 4.5 @ mvp)
- Why: Battle-tested and ubiquitous; weaker against GPU attacks than Argon2.
- Alternatives: Argon2id (4.33)
