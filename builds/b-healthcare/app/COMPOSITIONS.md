# Integration recipes for this app

These capabilities are present together and need glue. Wire them as below.

## authentication_billing — authentication + billing_stripe
_A paying user must map to both an auth principal and a Stripe customer, and the two must stay in sync._

**Glue:** On user signup, lazily create a Stripe customer and store stripe_customer_id on the user. On Stripe webhooks, resolve events back to the user by that id.

**Steps:**
1. Add stripe_customer_id (nullable) to the users model.
2. In auth_routes signup (or first checkout), call stripe_checkout to create/fetch the customer and persist the id.
3. In stripe_webhooks, look up the user by stripe_customer_id before mutating subscription_status.
4. Guard billing routes with the authentication dependency so only the owner acts on their subscription.

**Shared data:** `users.stripe_customer_id, subscriptions.user_id`

## authentication_rbac — authentication + authorization_rbac
_The auth layer proves *who* you are; RBAC decides *what* you may do. The permission check needs the authenticated principal._

**Glue:** Resolve the current principal from the session/JWT, attach roles, and feed it into the permissions dependency (overriding the _current_principal_placeholder).

**Steps:**
1. Override permissions._current_principal_placeholder to read the user from the auth dependency.
2. Load the user's roles (roles part) when building the principal.
3. Use require('perm') as a FastAPI dependency on protected routes.

**Shared data:** `roles.user_id, role_permissions`

## users_audit_logs — users + audit_logs
_Sensitive actions need an immutable record of who did what, when._

**Glue:** A write-path hook records actor (user id from auth), action, target, and timestamp into the audit_logs store; reads are admin-gated.

**Steps:**
1. Wrap sensitive service methods so they emit an audit event with the current user id.
2. audit_logs persists append-only rows (audit_mixin or a dedicated table).
3. Expose audit reads only behind admin_access.

**Shared data:** `audit_log.actor_user_id`

## users_notifications — users + notification_center
_Notifications must target users, respect their channel preferences, and honor unsubscribe._

**Glue:** notification_center resolves recipient users, checks per-user channel prefs + unsubscribe state, then dispatches via comms_core (email/push/sms).

**Steps:**
1. Add notification_preferences to the users model (or a side table).
2. notification_center filters recipients by prefs and unsubscribe_handling state.
3. Dispatch through email/sms/push parts; record delivery.

**Shared data:** `notification_preferences, notifications.user_id`
