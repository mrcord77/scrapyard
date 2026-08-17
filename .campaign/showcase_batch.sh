#!/bin/bash
cd "$(dirname "$0")/.."
KEYS=$(py -c "from scrapyard.security.pq_field_encryption import generate_recipient_hex as g; a,b=g(); print(a); print(b)")
export PQ_FIELD_PUBLIC=$(echo "$KEYS" | head -1)
export PQ_FIELD_SECRET=$(echo "$KEYS" | tail -1)
echo "$PQ_FIELD_PUBLIC" > builds/.showcase_pq_public.key
echo "$PQ_FIELD_SECRET" > builds/.showcase_pq_secret.key
bash .campaign/run_build.sh sc-overturn saas_subscription_app appeal_fighter 8151 > builds/.sc-overturn.run.log 2>&1
bash .campaign/run_build.sh sc-deposit basic_saas deposit_shield 8152 > builds/.sc-deposit.run.log 2>&1
bash .campaign/run_build.sh sc-binder basic_saas iep_binder 8153 > builds/.sc-binder.run.log 2>&1
bash .campaign/run_build.sh sc-care basic_saas care_circle 8154 > builds/.sc-care.run.log 2>&1
echo SHOWCASE-BATCH-DONE
for b in sc-overturn sc-deposit sc-binder sc-care; do tail -2 builds/.$b.run.log | head -1; done
