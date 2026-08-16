#!/bin/bash
# Phase 0: Scrapyard's own verification machinery. Each check logs separately; exit codes recorded.
cd "$(dirname "$0")/.."
LOG=.campaign/logs
SUMMARY=$LOG/phase0_summary.txt
: > "$SUMMARY"

run() {
  name="$1"; shift
  echo "=== $name: $* ==="
  start=$(date +%s)
  "$@" > "$LOG/$name.log" 2>&1
  rc=$?
  end=$(date +%s)
  echo "$name rc=$rc secs=$((end-start))" >> "$SUMMARY"
}

run index_catalog      py tools/index_catalog.py --out .campaign/catalog-check
run verify_selftests   py tools/verify_part_selftests.py --jobs 4
run ui_lint            py tools/ui_lint.py
run security_regression py tests/security_regression.py
run build_matrix       py tools/build_matrix.py
run runtime_healthcare py tools/verify_runtime.py --domain healthcare --secure
run runtime_sobriety   py tools/verify_runtime.py --domain sobriety --fullstack
echo DONE >> "$SUMMARY"
cat "$SUMMARY"
