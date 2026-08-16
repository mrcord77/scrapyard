#!/bin/bash
# One-shot build pipeline: EOS -> boot -> smoke -> shutdown. Logs to builds/<name>/.
# Usage: run_build.sh <name> <pattern> <domain> <port> [--public-ok] [-- extra eos args]
set -u
NAME=$1; PATTERN=$2; DOMAIN=$3; PORT=$4; shift 4
PUBLIC_OK=""
EXTRA=()
for a in "$@"; do
  if [ "$a" = "--public-ok" ]; then PUBLIC_OK="--public-ok"; else EXTRA+=("$a"); fi
done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BDIR="builds/$NAME"
mkdir -p "$BDIR"

echo "=== [$NAME] EOS generate ==="
py tools/eos.py --pattern "$PATTERN" --domain "$DOMAIN" --out "$BDIR/app" --gate ${EXTRA[@]+"${EXTRA[@]}"} > "$BDIR/eos.log" 2>&1
EOS_RC=$?
tail -3 "$BDIR/eos.log"
if [ $EOS_RC -ne 0 ]; then echo "[$NAME] EOS FAILED rc=$EOS_RC"; exit 2; fi

echo "=== [$NAME] boot on :$PORT ==="
cd "$BDIR/app"
rm -f app.db
py -m uvicorn main:app --port "$PORT" > ../boot.log 2>&1 &
SRV=$!
cd "$ROOT"
ok=""
for i in $(seq 1 30); do
  sleep 1
  if curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz" | grep -q 200; then ok=1; break; fi
done
if [ -z "$ok" ]; then echo "[$NAME] BOOT FAILED"; tail -20 "$BDIR/boot.log"; kill $SRV 2>/dev/null; exit 3; fi
echo "[$NAME] healthy"

echo "=== [$NAME] smoke ==="
py .campaign/smoke.py --base "http://127.0.0.1:$PORT" --out "$BDIR/smoke_results.json" $PUBLIC_OK > "$BDIR/smoke.log" 2>&1
SMOKE_RC=$?
tail -1 "$BDIR/smoke.log"
grep -E "\[FAIL\]" "$BDIR/smoke.log" | head -10

kill $SRV 2>/dev/null
exit $SMOKE_RC
