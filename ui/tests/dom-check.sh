#!/usr/bin/env bash
# Renders key views in headless Chrome and fails if internal status names reach the page, or if the
# name fact (identity.facts.name) is labelled "verified" (stage4's name.verified only means a name comparison ran).
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
  "?sample=1&alert=A-SYN003&hit=H-SYN999" "?sample=1&screen=audit&hit=H-SYN999" "?sample=1&screen=queue&hit=H-SYN999"
  "?sample=trace&status=cleared" "?sample=summaries&status=cleared" "?sample=1&screen=audit&code=HIT_NOT_DECIDED"
  "?sample=1&alert=A-SYN001&hit=H-SYN001" "?sample=1&alert=A-SYN008&hit=H-SYN013" "?sample=1&alert=A-SYN009&hit=H-SYN014"
  "?sample=1&screen=queue&alert=A-SYN008&hit=H-SYN013" "?sample=trace&status=review"
  "?sample=pipeline" "?sample=pipeline&alert=A-SYN101&hit=H-SYN101" "?sample=pipeline&alert=A-SYN103&hit=H-SYN105"
  "?sample=pipeline&alert=A-SYN104&hit=H-SYN107" "?sample=pipeline&alert=A-SYN105&hit=H-SYN109" "?sample=pipeline&screen=audit"
  "?sample=crosscheck" "?sample=crosscheck&alert=A-SYN009&hit=H-SYN014" "?sample=crosscheck&status=review"
)
# Text that must be on a page (path|text).
expects=(
  "?sample=1|missing in run 3"
  "?sample=1|Same decision and reason code in all 5 runs"
  "?sample=1&repro=flipped|missing in run 4"
  "?sample=1&alert=A-SYN003&hit=H-SYN999|is not in alert"
  "?sample=1&screen=audit&hit=H-SYN999|is not in the loaded files"
  "?sample=1&screen=queue&hit=H-SYN999|is not in the loaded files"
  "?sample=trace|No original alerts file loaded, so nothing can be shown as Cleared"
  "?sample=summaries|No original alerts file loaded, so nothing can be shown as Cleared"
  "?sample=summaries&status=cleared|Not available until the alerts file is loaded"
  "?sample=1&alert=A-SYN005&hit=H-SYN009|Hit has no decision"
  "?sample=1|agree with this view"
  "?sample=trace|agree with this view"
  "?sample=crosscheck|a pipeline summary never clears an alert here"
  "?sample=crosscheck|deliberately wrong"
  "?sample=crosscheck&alert=A-SYN009&hit=H-SYN014|Hit has no decision"
  "?sample=1&alert=A-SYN001&hit=H-SYN001|compared with the hit"
  "?sample=1&alert=A-SYN008&hit=H-SYN013|No comparison"
  "?sample=1&alert=A-SYN008&hit=H-SYN013|no matching customer record"
  "?sample=1&alert=A-SYN009&hit=H-SYN014|Hit has no decision"
  "?sample=1&alert=A-SYN009&hit=H-SYN014|the hit has no decision, so it was never compared"
  "?sample=1&alert=A-SYN004&hit=H-SYN007|name not in the trace"
  "?sample=1&alert=A-SYN004&hit=H-SYN007|The customer column shows the first candidate, CUS-SYN004"
  "?sample=pipeline|agree with this view"
  "?sample=pipeline|written by system/run"
  "?sample=pipeline&alert=A-SYN104&hit=H-SYN107|No comparison"
  "?sample=pipeline&alert=A-SYN103&hit=H-SYN105|compared with the hit"
)
# Pages that must show no cross-check disagreement (the default demo is clean).
clean_pages=("?sample=1" "?sample=trace" "?sample=pipeline")
# Pages that must show the name fact row (so the "verified" check below is not vacuous).
name_fact_pages=("?sample=1&alert=A-SYN001&hit=H-SYN001" "?sample=pipeline&alert=A-SYN101&hit=H-SYN101" "?sample=pipeline&alert=A-SYN103&hit=H-SYN105")
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
  elif grep -q 'HIT_NOT_DECIDED' <<<"$text"; then
    # allowed only in attributes (tooltips, option values) and the collapsed raw trace, never as visible text
    echo "FAIL (HIT_NOT_DECIDED shown as text): $p"; fail=1
  else
    echo "ok   $p"
  fi
  # The name fact row must never say "verified".
  name_row=$(perl -0ne 'print "$1\n" while /(<tr[^>]*data-fact="name"[^>]*>.*?<\/tr>)/gs' <<<"$dom")
  if grep -qi 'verified' <<<"$name_row"; then echo "FAIL (name fact labelled verified): $p"; fail=1; fi
  for n in "${name_fact_pages[@]}"; do
    if [[ "$n" == "$p" && -z "$name_row" ]]; then echo "FAIL (no name fact row to check): $p"; fail=1; fi
  done
  for c in "${clean_pages[@]}"; do
    if [[ "$c" == "$p" ]] && grep -q 'disagree with this view' <<<"$text"; then echo "FAIL (cross-check disagreement on the default demo): $p"; fail=1; fi
  done
  for e in "${expects[@]}"; do
    if [[ "${e%%|*}" == "$p" ]] && ! grep -qF "${e#*|}" <<<"$text"; then echo "FAIL (missing text '${e#*|}'): $p"; fail=1; fi
  done
done
exit $fail
