# Screening reviewer UI (steps 1–2: Overview + hit panel)

Read-only reviewer UI for the per-hit trace (`docs/explainability-and-reproducibility.md` §1, §7)
and the alert roll-up (`docs/stage4-notes.md` §1). Local files only; no network calls; all text
rendered as React text nodes (no `innerHTML` / `dangerouslySetInnerHTML` in our source).

    npm ci
    npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
    npm test            # roll-up, parser, labels (node:test, no extra deps)
    npm run test:dom    # headless Chrome: no internal status names on screen (needs the dev server, or pass a file:// URL)
    npm run build       # dist/index.html opens straight from disk (file://), strict CSP injected

URL params: `?sample=1` (both sample files), `?sample=trace` (trace only → "Not verified"),
`status=cleared|compliance|review|not-verified`, `alert=A-…`, `hit=H-…`, `screen=queue|audit`.

Files: alerts picker takes `alerts.jsonl`, `alerts.trace.jsonl` (Stage 4 summaries) or a JSON array.
Duplicates: identical records for a hit are deduplicated (info note); differing or invalid ones leave the hit undecided.
Build: one classic deferred IIFE script + one CSS file (Chrome blocks module scripts over file://).
Roll-up: `src/lib/rollup.ts`. Wording: `src/lib/labels.ts`. Panel: `src/components/HitPanel.tsx`.
Fixtures are invented; `tests/make-alert-summaries.ts` regenerates `fixtures/sample.alerts.trace.jsonl`.
