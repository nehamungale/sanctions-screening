#!/usr/bin/env bash
# Renders key views in headless Chrome and fails if internal status names reach the page.
# Usage: tests/dom-check.sh [base-url]   (default: the dev server; pass file:///…/dist/index.html for the build)
set -euo pipefail
BASE="${1:-http://127.0.0.1:5173/}"
CHROME="${CHROME:-google-chrome}"
paths=(
  "?sample=1" "?sample=1&repro=flipped" "?sample=trace" "?sample=summaries"
  "?sample=1&status=cleared" "?sample=1&status=compliance" "?sample=1&status=review" "?sample=summaries&status=not-verified"
  "?sample=1&alert=A-SYN002&hit=H-SYN003" "?sample=1&alert=A-SYN003&hit=H-SYN006"
  "?sample=1&alert=A-SYN004&hit=H-SYN007" "?sample=1&alert=A-SYN005&hit=H-SYN009"
  "?sample=1&screen=queue" "?sample=1&screen=queue&alert=A-SYN003&hit=H-SYN006" "?sample=1&screen=queue&alert=A-SYN005&hit=H-SYN009"
  "?sample=1&screen=audit" "?sample=1&screen=audit&verdict=REVIEW" "?sample=1&screen=audit&unstable=1"
  "?sample=1&screen=audit&code=DOB_MISMATCH&alert=A-SYN001&hit=H-SYN001" "?sample=1&screen=audit&verdict=none"
  "?screen=queue" "?screen=audit"
)
fail=0
for p in "${paths[@]}"; do
  # The dev server serves many small modules; retry a page that has not rendered yet.
  for attempt in 1 2 3; do
    dom=$("$CHROME" --headless=new --no-sandbox --disable-gpu --virtual-time-budget=6000 --dump-dom "${BASE}${p}" 2>/dev/null || true)
    grep -q 'Screening reviewer' <<<"$dom" && break
  done
  # Strip tags so only rendered text (and attributes) are checked.
  text=$(printf '%s' "$dom" | sed -e 's/<[^>]*>/ /g')
  # (here-strings, not pipes: grep -q closing a pipe early trips pipefail)
  if ! grep -q "Screening reviewer" <<<"$text"; then echo "FAIL (did not render): $p ($(printf "%s" "$dom" | wc -c) bytes)"; fail=1; continue; fi
  if grep -Eq 'ESCALATED|NEEDS_REVIEW|NOT_VERIFIED' <<<"$dom"; then
    echo "FAIL (internal name on page): $p"; fail=1
  else
    echo "ok   $p"
  fi
done
exit $fail
