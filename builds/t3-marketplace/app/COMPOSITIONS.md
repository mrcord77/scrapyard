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
