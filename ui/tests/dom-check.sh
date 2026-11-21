#!/usr/bin/env bash
# Renders key views in headless Chrome and fails if internal status names reach the page.
# Usage: tests/dom-check.sh [base-url]   (default: the dev server; pass file:///…/dist/index.html for the build)
set -euo pipefail
BASE="${1:-http://127.0.0.1:5173/}"
CHROME="${CHROME:-google-chrome}"
paths=(
  "?sample=1"
  "?sample=1&status=cleared" "?sample=1&status=compliance" "?sample=1&status=review"
  "?sample=1&alert=A-000002&hit=H-000003" "?sample=1&alert=A-000003&hit=H-000006"
  "?sample=1&alert=A-000004&hit=H-000007" "?sample=1&alert=A-000005&hit=H-000009"
  "?screen=queue" "?screen=audit"
)
fail=0
for p in "${paths[@]}"; do
  dom=$("$CHROME" --headless=new --no-sandbox --disable-gpu --virtual-time-budget=4000 --dump-dom "${BASE}${p}" 2>/dev/null)
  # Strip tags so only rendered text (and attributes) are checked.
  text=$(printf '%s' "$dom" | sed -e 's/<[^>]*>/ /g')
  if ! printf '%s' "$text" | grep -q 'Screening reviewer'; then echo "FAIL (did not render): $p"; fail=1; continue; fi
  if printf '%s' "$dom" | grep -Eo 'ESCALATED|NEEDS_REVIEW|NOT_VERIFIED' | head -1 | grep -q .; then
    echo "FAIL (internal name on page): $p"; fail=1
  else
    echo "ok   $p"
  fi
done
exit $fail
