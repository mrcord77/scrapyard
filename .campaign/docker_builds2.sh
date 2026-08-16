#!/bin/bash
cd "$(dirname "$0")/.."
for b in b-healthcare a-sobriety t4-workbench; do
  (cd builds/$b/app && docker build -t scrapyard-$b:test . > ../docker_build.log 2>&1 && echo "$b IMAGE OK" || (echo "$b IMAGE FAILED"; tail -5 ../docker_build.log))
done
echo RETRY-DONE
