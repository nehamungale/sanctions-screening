# Review notes: LLM time cap and free-model setup

Reviewer: Ideas Partner (with input from the Eval & Reproducibility and Compliance & Security reviews). Scope: `system/shared/llm_client.py` as merged in PR #5 (Stage 1 hardening). Advice only; nothing in the code was changed.

The hardening is a big step forward: exhaustive name pairing, block flags, `CUS-` ids, and LLM facts that can never be the sole ground for `DIFFERENT_ENTITY`. Two settings in the shared LLM client work against reproducibility, which is 10% of the score and is judged as the same decision and reason code across five runs of the unseen set with Diligent's own key.

Today the LLM is off unless `USE_LLM_NOTES=1`, so these do not bite yet. They will as soon as the note fallback or the decision stage turns it on.

## 1. Wall-clock time cap (`DEFAULT_TIME_CAP_SECONDS = 90.0`, line 48)

**Fixed (PR #10).** One shared client per run, a per-extraction call budget of 12, a run budget of 48, notes and hits in sorted id order, and a single 20 minute backstop.

**Problem.** The cap starts when the client is built and applies across the whole run. Once 90 seconds have passed, every later call returns UNKNOWN (`time_or_budget_cap`). How far a run gets in 90 seconds depends on network speed, provider load and 429 backoffs, which differ between the judges' five runs. So the same hit can get a parsed fact in one run and UNKNOWN in another, and its decision or reason code flips.

The per-run call budget (`DEFAULT_CALL_BUDGET = 48`, line 47) has a milder form of the same issue: if retries or votes consume budget unevenly, later hits get starved in some runs and not others.

**Suggested fix.**
- Replace the wall-clock cap with a fixed budget that does not depend on speed: a maximum number of calls per hit, a fixed per-call timeout, a fixed number of retries, and hits processed in sorted id order.
- Allocate the run budget per hit up front (deterministic), rather than first-come-first-served.
- Keep a wall-clock limit only as an emergency backstop well under 30 minutes, and record in the run header if it ever fires, so a flip can be traced to it.

## 2. Free models only, one pinned provider, no fallbacks (lines 8-13, 41-43)

**Problem.** `google/gemma-4-31b-it:free` served only by `Google AI Studio` with `allow_fallbacks: false` is the right shape for determinism, but free endpoints are heavily rate-limited. During the judges' runs, 429s that outlast the bounded backoff (max 8 seconds) turn facts into UNKNOWN, so some runs see the fact and some do not. That is a flip source we cannot control, and it is likely to be worst exactly when many teams are being evaluated at once.

**Suggested fix (Neha to decide).**
- Measure first: run the client 5 times over dev with the LLM on, and count 429s, UNKNOWNs from rate limits, and hits whose decision or code changes between LLM-on and LLM-off. That LLM-sensitive set is the real exposure.
- If the exposure is not near zero, consider a small paid budget on a pinned paid model and provider (still `temperature: 0`, fixed seed, `allow_fallbacks: false`, `data_collection: deny`). Diligent runs with their own key, so check what model access that key is likely to have, and document the choice in the README.
- Whatever the model, keep regex and structured fields first so the LLM-sensitive set stays as small as possible.

## 3. Related checks

- Three identical calls at temperature 0: measure per-fact agreement over 15 calls (5 runs x 3) on dev before keeping it. If the model is deterministic the votes add cost and rate-limit pressure with no benefit; if it is not, unanimity itself can vary run to run.
- Log per call: prompt hash, model, provider actually served, OpenRouter response id, quote and parsed value. Never the key or request headers.
- Add an eval: LLM-on vs LLM-off decision diff, plus a simulated provider outage halfway through a run, with 0 flips on hits that do not touch the LLM as a hard gate.

See also `docs/explainability-and-reproducibility.md` on branch `docs/explainability-repro`, sections 4 and 5.
