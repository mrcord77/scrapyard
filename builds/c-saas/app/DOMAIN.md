# Domain: Generic B2B/B2C SaaS

## Terminology
- **account** — billable customer org or person
- **seat** — a user slot in a plan
- **plan** — priced tier of entitlements
- **workspace** — tenant boundary

## Entities to scaffold
- **Account**: id, name, plan_id, status, created_at  _(billable tenant)_
- **Member**: id, account_id, user_id, role, invited_at
- **Plan**: id, name, price_cents, interval, entitlements
- **Invitation**: id, account_id, email, role, token, expires_at

## Workflows
- sign up -> create account -> invite team
- upgrade/downgrade plan
- seat assignment
- trial -> paid conversion
- cancel + retention offer

## Permissions
- account.manage
- member.invite
- member.remove
- billing.manage
- settings.edit

## Reports
- MRR / ARR
- churn rate
- seat utilization
- trial conversion
- plan distribution
