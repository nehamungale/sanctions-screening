# Stage 2 and Stage 3 design review notes

Review of `docs/stage2-hit-golden-profile.md` and `docs/stage3-alert-resolution.md` (merged in #6), checked against the explainability and reproducibility design and Stage 1's `system/shared/llm_client.py`. Stages 2 and 3 are now on main. Status lines below were checked against `9981431`.

## 1. LLM facts and clearing a hit

**Status:** Fixed (PR #10) for the Stage 2 wording. The Stage 2 design now says an LLM fact can never contribute to a `DIFFERENT_ENTITY` clearance, not only that it cannot be the sole ground. On main at `9981431` the status was: Open, fix pending in PR #10 for the Stage 2 wording (main still says an LLM fact cannot be the sole ground). **Status:** Open, Stage 4 for enforcing that an LLM-read fact cannot contribute to `DIFFERENT_ENTITY` at all.

**Stage 2 says:** "An LLM-only fact can never be the sole ground for `DIFFERENT_ENTITY`."

**Agreed team rule (stricter):** a fact the LLM read can never be the reason we clear a hit. It can only push a hit to `REVIEW` or support a `SAME_ENTITY` confirmation.

The gap: "sole ground" still allows a clear where an LLM-read fact is one of several deciding facts. Under the team rule, an LLM-read fact must not count toward a `DIFFERENT_ENTITY` decision at all.

**Suggested change:** reword the Stage 2 guardrail to "A fact with `method: "llm"` can never contribute to a `DIFFERENT_ENTITY` decision. It can only push a hit to `REVIEW` or support `SAME_ENTITY`." Stage 4 enforces this, and the eval gate counts 0 clears whose deciding facts include an LLM-read fact.

## 2. One LLM on/off switch

**Status:** Fixed (on main before PRs #7 to #9) for Stage 2: `SANCTIONS_LLM=0` forces `USE_LLM_HITS` off (`system/stage2/llm.py`). The repro tool already sets `SANCTIONS_LLM=0` on its LLM-off run, so that run does turn Stage 2 off. **Status:** Fixed (PR #10) for Stage 1. `SANCTIONS_LLM=0` turns Stage 1 and Stage 2 off; `USE_LLM_NOTES` and `USE_LLM_HITS` only narrow that. On main at `9981431` the Stage 1 status was: Open, fix pending in PR #10, because Stage 1 still looked only at `USE_LLM_NOTES`.

There are currently three switches:

| Where | Switch |
|---|---|
| Stage 1 (`system/stage1`) | `USE_LLM_NOTES` |
| Stage 2 design | `USE_LLM_HITS` |
| Repro report tool (`tools/repro`) | sets `USE_LLM_NOTES=0` and `SANCTIONS_LLM=0` for its LLM-off run |

When this note was written, that LLM-off run did not set `USE_LLM_HITS`, so it would have left Stage 2 on. On main, `SANCTIONS_LLM=0` turns Stage 2 off. Stage 1 was the remaining gap at `9981431`. PR #10 closes it: `SANCTIONS_LLM=0` turns Stage 1 off as well, and `USE_LLM_NOTES` and `USE_LLM_HITS` only narrow that.

**Suggested change:** pick one master switch (for example `SANCTIONS_LLM`, default off) that turns every LLM step off. Per-stage switches may stay, but only to narrow what the master switch turns on. Record the effective setting in the trace run header.

## 3. Call budget across stages

**Status:** Fixed (PR #10). Stages share one client: run budget 48, 12 calls per extraction, a 20 minute backstop, and sorted id order so a skipped call is the same hit every run. On main at `9981431` the status was: Open, fix pending in PR #10. The two stages did not share a client. Stage 1's default cap was 90 seconds and 48 calls. Stage 2, if it built its own client, used 48 calls and 1,200 seconds. A Stage 2 hit skipped for the cap is flagged `LLM_SKIPPED_BUDGET`. Hits are visited in sorted `hit_id` order.

Stage 1's client caps the whole run at 48 LLM calls (`llm_client.py`, line 47) and 90 seconds (line 48). Stage 2 needs 3 agreeing calls per unresolved birth sentence.

Open questions:

- Is the 48-call budget shared by Stage 1 and Stage 2, or does each stage get its own?
- If the budget runs out part-way, which hits lose their LLM step? It must be the same hits on every run (a fixed order, such as sorted `hit_id`), not whichever came first in time.
- A hit whose LLM step was skipped for budget must be traced as `llm_skipped: budget`. It gets the same verdict as with the LLM off, never a clear that depends on the missing fact.

**Suggested change:** give each stage a fixed call budget, spent in sorted ID order, and log budget use in the trace run header. Replace the wall-clock cap with the fixed budget, as the reproducibility design already proposes.

## Smaller notes

- **Status:** Fixed (PR #9, Stage 3). `not_found` (including `UNRESOLVED_LINK`) sets `customer_record_id` to `null`. `AMBIGUOUS` stays the string `AMBIGUOUS`. **Status:** Open, Stage 4 for the trace schema that has to accept all three.
- **Status:** Open, Stage 4. Clearing an ambiguous alert only when every candidate is `DIFFERENT_ENTITY`, citing each candidate's deciding records, is not implemented. Stage 3 keeps every candidate.
