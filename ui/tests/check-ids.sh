#!/usr/bin/env bash
# Fails if fixtures/ or dist/ contain an ID in a real-data format, e.g. H-0a1b2c, CUS-000001.
# Synthetic IDs look like H-SYN001, CUS-SYN001, KYC-SYN101.
set -euo pipefail
cd "$(dirname "$0")/.."
targets=(fixtures)
[ -d dist ] && targets+=(dist) || echo "check-ids: no dist/ yet, checking fixtures only"
if grep -rEn --binary-files=without-match '\b(H|CUS|KYC|NOTE)-[0-9a-fA-F]{6}\b|CUS-000001' "${targets[@]}"; then
  echo "check-ids FAILED: real-format IDs found above"; exit 1
fi
echo "check-ids OK: no real-format IDs in ${targets[*]}"
