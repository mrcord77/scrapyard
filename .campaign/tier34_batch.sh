#!/bin/bash
cd "$(dirname "$0")/.."
export PQ_TMP=$(py -c "from scrapyard.security.pq_field_encryption import generate_recipient_hex as g; a,b=g(); print(a+' '+b)")
export PQ_FIELD_PUBLIC=$(echo $PQ_TMP | cut -d' ' -f1)
export PQ_FIELD_SECRET=$(echo $PQ_TMP | cut -d' ' -f2)
bash .campaign/run_build.sh b-healthcare saas_subscription_app healthcare 8111 > builds/.b-healthcare.run.log 2>&1
bash .campaign/run_build.sh c-saas saas_subscription_app saas 8112 > builds/.c-saas.run.log 2>&1
bash .campaign/run_build.sh t3-marketplace marketplace ecommerce 8113 > builds/.t3-marketplace.run.log 2>&1
bash .campaign/run_build.sh t4-oilgas ticketing_system oil_and_gas 8114 > builds/.t4-oilgas.run.log 2>&1
bash .campaign/run_build.sh t4-workbench agent_platform research_workbench 8115 > builds/.t4-workbench.run.log 2>&1
bash .campaign/run_build.sh t4-community basic_saas community_platform 8116 > builds/.t4-community.run.log 2>&1
echo BATCH34 DONE
