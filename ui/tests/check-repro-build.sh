#!/usr/bin/env bash
# Builds twice from scratch and fails unless every file in dist/ is byte-identical.
set -euo pipefail
cd "$(dirname "$0")/.."
hashes() { (cd dist && find . -type f -print0 | sort -z | xargs -0 sha256sum); }
rm -rf dist && npm run build --silent >/dev/null
first=$(hashes)
rm -rf dist && npm run build --silent >/dev/null
second=$(hashes)
echo "$second"
if [ "$first" = "$second" ]; then echo "check:repro-build OK: two clean builds are byte-identical"; else
  echo "check:repro-build FAILED"; diff <(echo "$first") <(echo "$second") || true; exit 1; fi
