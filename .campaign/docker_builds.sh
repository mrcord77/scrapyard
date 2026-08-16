#!/bin/bash
cd "$(dirname "$0")/.."
for b in b-healthcare a-sobriety c-saas t3-marketplace t4-workbench; do
  echo "=== docker build $b ==="
  (cd builds/$b/app && docker build -t scrapyard-$b:test . > ../docker_build.log 2>&1 && echo "$b IMAGE OK" || (echo "$b IMAGE FAILED"; tail -5 ../docker_build.log))
done
echo DOCKER-BUILDS-DONE
