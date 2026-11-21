# Stage 2 and Stage 3 design review notes

Review of `docs/stage2-hit-golden-profile.md` and `docs/stage3-alert-resolution.md` (merged in #6), checked against the explainability and reproducibility design on branch `docs/explainability-repro` and Stage 1's `system/shared/llm_client.py`. These are open items to settle before Stage 2/3 code is built. No code changes here.

## 1. LLM facts and clearing a hit

**Stage 2 says:** "An LLM-only fact can never be the sole ground for `DIFFERENT_ENTITY`."

**Agreed team rule (stricter):** a fact the LLM read can never be the reason we clear a hit. It can only push a hit to `REVIEW` or support a `SAME_ENTITY` confirmation.

The gap: "sole ground" still allows a clear where an LLM-read fact is one of several deciding facts. Under the team rule, an LLM-read fact must not count toward a `DIFFERENT_ENTITY` decision at all.

**Suggested change:** reword the Stage 2 guardrail to "A fact with `method: "llm"` can never contribute to a `DIFFERENT_ENTITY` decision. It can only push a hit to `REVIEW` or support `SAME_ENTITY`." Stage 4 enforces this, and the eval gate counts 0 clears whose deciding facts include an LLM-read fact.

## 2. One LLM on/off switch

There are currently three switches:

| Where | Switch |
|---|---|
| Stage 1 (`system/stage1`) | `USE_LLM_NOTES` |
| Stage 2 design | `USE_LLM_HITS` |
| Repro report tool (`tools/repro`, on `docs/explainability-repro`) | sets `USE_LLM_NOTES=0` and `SANCTIONS_LLM=0` for its LLM-off run |

The repro tool's LLM-off run would not switch Stage 2 off. The LLM-sensitivity metric (LLM on versus off) would then be wrong.

**Suggested change:** pick one master switch (for example `SANCTIONS_LLM`, default off) that turns every LLM step off. Per-stage switches may stay, but only to narrow what the master switch turns on. Record the effective setting in the trace run header.

## 3. Call budget across stages

Stage 1's client caps the whole run at 48 LLM calls (`llm_client.py`, line 47) and 90 seconds (line 48). Stage 2 needs 3 agreeing calls per unresolved birth sentence.

Open questions:

- Is the 48-call budget shared by Stage 1 and Stage 2, or does each stage get its own?
- If the budget runs out part-way, which hits lose their LLM step? It must be the same hits on every run (a fixed order, such as sorted `hit_id`), not whichever came first in time.
- A hit whose LLM step was skipped for budget must be traced as `llm_skipped: budget`. It gets the same verdict as with the LLM off, never a clear that depends on the missing fact.

**Suggested change:** give each stage a fixed call budget, spent in sorted ID order, and log budget use in the trace run header. Replace the wall-clock cap with the fixed budget, as the reproducibility design already proposes.

## Smaller notes

- Stage 3 sets `customer_record_id` to `null` for NOT_FOUND. The trace design should allow `null` alongside a `CUS-` ID and `AMBIGUOUS`.
- In Stage 3's ambiguity hand-off, a hit is cleared when every candidate person gives `DIFFERENT_ENTITY`. That clear must cite each candidate's deciding records, and the unsafe-clearance gate should test it with a synthetic AMBIGUOUS fixture.
