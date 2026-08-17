# Integration recipes for this app

These capabilities are present together and need glue. Wire them as below.

## users_audit_logs — users + audit_logs
_Sensitive actions need an immutable record of who did what, when._

**Glue:** A write-path hook records actor (user id from auth), action, target, and timestamp into the audit_logs store; reads are admin-gated.

**Steps:**
1. Wrap sensitive service methods so they emit an audit event with the current user id.
2. audit_logs persists append-only rows (audit_mixin or a dedicated table).
3. Expose audit reads only behind admin_access.

**Shared data:** `audit_log.actor_user_id`
