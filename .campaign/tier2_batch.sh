#!/bin/bash
cd "$(dirname "$0")/.."
bash .campaign/run_build.sh t2-crm crm ev_leads 8104 > builds/.t2-crm.run.log 2>&1
bash .campaign/run_build.sh t2-education course_platform education 8105 > builds/.t2-education.run.log 2>&1
bash .campaign/run_build.sh t2-realestate directory_site real_estate 8106 --public-ok > builds/.t2-realestate.run.log 2>&1
bash .campaign/run_build.sh t2-ticketing ticketing_system construction 8107 > builds/.t2-ticketing.run.log 2>&1
echo BATCH DONE
for b in t2-crm t2-education t2-realestate t2-ticketing; do tail -2 builds/.$b.run.log | head -1; done
