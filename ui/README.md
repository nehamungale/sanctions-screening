# Screening reviewer UI

Read-only reviewer UI for the per-hit trace (`docs/explainability-and-reproducibility.md` §1, §7), the alert roll-up
(`docs/stage4-notes.md` §1) and the reproducibility report (`tools/repro`). Local files only; no network calls; all text
rendered as plain text. Field-by-field contract: [TRACE_CONTRACT.md](TRACE_CONTRACT.md).

    npm ci
    npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
    npm test                    # unit tests + real-format ID check on fixtures/ and dist/
    npm run test:dom            # headless Chrome: no internal status names on any screen (dev server, or pass a file:// URL)
    npm run build               # dist/index.html opens from file://, strict CSP injected
    npm run check:repro-build   # two clean builds must be byte-identical

Screens: **Overview** (alert roll-up, repro card, totals), **Analyst queue** (REVIEW, then no decision, then SAME_ENTITY),
**Audit** (all hits, filters in the URL). All open the shared `HitPanel`.

URL: `?sample=1` | `trace` | `summaries` (+ `&repro=flipped`), `screen=queue|audit`, `status=cleared|compliance|review|not-verified`,
`alert=A-…`, `hit=H-…`, Audit filters `verdict=`, `code=`, `fragility=`, `unstable=1`, `llm=yes|no`.

Fixtures (`fixtures/*.sample.*`) are synthetic (IDs like `H-SYN001`). `tests/make-alert-summaries.ts` and
`tests/make-repro-samples.py` regenerate the derived ones.
