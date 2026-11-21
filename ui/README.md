# Screening reviewer UI

Read-only reviewer UI for the Stage 4 trace (`system/stage4/trace.py`: one line per hit, then the alert summaries in the
same file), the alerts file and the reproducibility report (`tools/repro`). Local files only; no network calls; all text
rendered as plain text. Field-by-field contract: [TRACE_CONTRACT.md](TRACE_CONTRACT.md).

    npm ci
    npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
    npm test                    # unit tests + real-format ID check on fixtures/ and dist/
    STAGE4_REPO=../ npm test    # also runs system/run on synthetic data and loads its trace
    npm run test:dom            # headless Chrome: no internal status names on any screen (dev server, or pass a file:// URL)
    npm run build               # dist/index.html opens from file://, strict CSP injected
    npm run check:repro-build   # two clean builds must be byte-identical

Screens: **Overview** (alert roll-up, repro card, totals), **Analyst queue** (REVIEW, then no decision, then SAME_ENTITY),
**Audit** (all hits, filters in the URL). All open the shared `HitPanel`.

URL: `?sample=1` | `trace` (alias `summaries`) | `pipeline` | `crosscheck` (A-SYN009's pipeline summary wrongly says Cleared; the UI still shows Needs review) (+ `&repro=flipped`), `screen=queue|audit`, `status=cleared|compliance|review|not-verified`,
`alert=A-…`, `hit=H-…`, Audit filters `verdict=`, `code=`, `fragility=`, `unstable=1`, `llm=yes|no`.

Fixtures (`fixtures/*.sample.*`) are synthetic (IDs like `H-SYN001`). `trace-pipeline.sample.jsonl` was written by
`system/run` (`tests/make-real-trace.py <repo> <out>`). `tests/make-trace-sample.py` appends the alert summaries to
`trace.sample.jsonl` with the repo's own roll-up and writes `trace-crosscheck.sample.jsonl` (one summary broken); `tests/make-repro-samples.py` regenerates the repro samples.
