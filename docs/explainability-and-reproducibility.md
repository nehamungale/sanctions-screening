# Explainability and reproducibility design

Status: agreed design. The reproducibility report in `tools/repro` is built. The per-hit trace, the citation gate and the decision rules are Stage 4 and are not built. Reviewed by the Compliance & Security and Eval & Reproducibility bots. Builds on Stages 1–3.

Judging order: explainability first, reproducibility second, accuracy third. Clearing a hit that is the customer costs 60; when in doubt, REVIEW.

## 1. One trace record per hit

Every decision leaves a structured trace. The UI, the evals, the replay script and self-improvement all read the same record.

- Written to `output/trace.jsonl`, separate from `output/dev.jsonl`.
- `dev.jsonl` stays exactly to `output.schema.json`; each line is copied from the trace's `verdict` block, so the answer and its explanation cannot drift apart.
- `system/run <data> <output>` writes **only** the output file by default (brief: it "writes one line per hit"). The trace is written only when `TRACE_PATH` is set locally.
- `trace.jsonl` and any UI data files are in `.gitignore`. They hold identity facts from the participant-only data.
- Schema is versioned: `trace_schema: 1`.

### Run header (one record per run, or `run.json`)

`run_id`, timestamp, git SHA, `rules_version`, hashes of POLICY, name_variants, every prompt and the input folder (sha256 over sorted file names and contents), Python version, model, and the provider OpenRouter actually served. Everything that changes between runs lives here, so per-hit records can be compared directly.

### Per-hit record (example data, IDs invented)

```json
{
  "trace_schema": 1,
  "hit_id": "H-SYN123", "alert_id": "A-000045",
  "verdict": {
    "decision": "DIFFERENT_ENTITY", "reason_code": "DOB_MISMATCH",
    "reason": "Verified DOB year 1984 (KYC-0091) contradicts every DOB on the hit (1971, 1972).",
    "evidence": ["KYC-0091", "H-SYN123#dobs"],
    "customer_record_id": "CUS-00812"
  },
  "badges": { "fragility": "thin", "llm_used": false, "rules_version": "r1.0" },
  "tipping_point": "Without KYC-0091 this would be REVIEW (INSUFFICIENT_DATA).",
  "comparison": [
    {"dim": "name",    "customer": "Ali Hassan", "hit": "Aly Hasan",  "status": "agree",      "src": ["KYC-0091", "H-SYN123#names"]},
    {"dim": "dob",     "customer": "1984-03-02", "hit": "1971; 1972", "status": "contradict", "src": ["KYC-0091", "H-SYN123#dobs"]},
    {"dim": "country", "customer": "GB",         "hit": null,         "status": "unknown",    "src": []},
    {"dim": "type",    "customer": "Individual", "hit": "Individual", "status": "agree",      "src": ["CUS-00812", "H-SYN123"]},
    {"dim": "death",   "customer": null,         "hit": null,         "status": "unknown",    "src": []},
    {"dim": "earliest_report", "customer": null, "hit": "2009-05-01", "status": "no_conflict","src": ["H-SYN123#sources"]}
  ],
  "identity": {
    "person_id": "P-CUS-00812",
    "merged": [{"rule": "P3 phone+full DOB", "records": ["CUS-00812", "CUS-00907"]}],
    "facts": {"dob": {"value": "1984-03-02", "verified": true, "source_id": "KYC-0091"}},
    "flags": [], "ignored_checks": []
  },
  "steps": [
    {"rule": "ENTITY_TYPE_MISMATCH",   "result": "not_fired", "llm_used": false, "why": "both Individual"},
    {"rule": "DECEASED",               "result": "not_fired", "llm_used": false, "why": "no date of death on hit"},
    {"rule": "TEMPORAL_IMPOSSIBILITY", "result": "not_fired", "llm_used": false, "why": "customer 25 at earliest report"},
    {"rule": "DOB_MISMATCH",           "result": "fired",     "llm_used": false}
  ],
  "llm_calls": []
}
```

### Mapping to Stage 1 (`person_golden.jsonl`)

| Trace | Stage 1 field |
|---|---|
| `identity.person_id` | `person_id` (internal, `P-` prefix) |
| `verdict.customer_record_id` | a `CUS-` ID from `record_ids` (the record the alert resolves to), or `AMBIGUOUS`. Never a `P-` ID |
| `identity.merged` | `cluster_edges` (rule, records, phone or document number) |
| `identity.facts` | `legal_name`, `dob`, `countries`, `entity_type` (`value`, `source_id`, `verified`, `source_kind`) |
| unknowns in `comparison` / `identity.flags` | `UNVERIFIED`, `PLACEHOLDER_NAME`, `NAME_TOO_SHORT`, `ignored_checks` |

Hit side, `comparison`, `steps`, `tipping_point` and `badges` come from Stage 4 (not built). Stage 2 already stores the hit facts those steps will read. Stage 3 stores who the alert resolved to.

## 2. Explainability beyond "rules step by step"

- **Four layers, one click deeper each:** verdict line, comparison card (6 dimensions, agree / contradict / unknown with source IDs), who is who (merged records and fact provenance), raw trace (`steps`, `llm_calls`).
- **Unknown stays unknown.** Gaps are named ("no verified DOB; customer declared 1984"), matching the judges' check that explanations are honest about what is missing.
- **Tipping point ("what would change it").** Re-run the rules with the deciding fact removed, or a missing fact supplied. Computed after the verdict, from already-extracted facts, with no LLM calls. It never changes the verdict.
- **Fragility badge**, from the same re-run: `solid` (2+ independent facts, removing one doesn't flip it), `thin` (rests on one fact or record), `borderline` (at a rule edge: exactly 2 edits, partial date, or an LLM-read value).
- **`steps` lists every rule evaluated**, including ones that didn't fire and why. For REVIEW it names exactly which fact was missing.
- **Each step carries `llm_used`** (true if any input fact to that rule has `method: "llm"`). The repro report uses it to split flips into LLM steps and rule steps, and the eval gate uses it to check that no `DIFFERENT_ENTITY` step that fired used an LLM-read fact.
- Counterfactuals are reviewer-only and stay in the local trace, never in public output. In a real deployment they would be limited to compliance staff.
- **Alert roll-up.** The trace also gets one summary per alert: `CLEARED` only when every hit is `DIFFERENT_ENTITY`, `ESCALATED` if any hit is `SAME_ENTITY`, otherwise `NEEDS_REVIEW` with the blocking hits named. A hit missing from the results blocks the clear. See [Stage 4 notes](stage4-notes.md#1-alert-roll-up).

## 3. Reasons and citations

- **Templated reasons**, one template per reason code. The LLM never writes the reason sentence.
- **Lean public reasons:** cite record IDs and the deciding facts at minimum precision (years, countries). No verbatim note text, full DOBs or document numbers in `dev.jsonl`. Full values live in the local trace. (Judges score that the reason states the real grounds with this hit's own facts, so don't strip facts entirely.)
- **Reason-code priority:** when several codes apply, Stage 4 picks the most robust one that passed the gate (type, death, time, date of birth, verified name, location). The order is fixed, so the code cannot flip between runs.
- **Citation gate (grounding), a hard eval gate:**
  1. Exists: every evidence ID is in the input files.
  2. Belongs: it belongs to this hit or to the resolved person's own merged records. Never another customer, a rejected or expired check, or a namesake search result as evidence for a clear.
  3. Says it: the value in the reason or comparison matches what that record holds. An LLM quote must appear verbatim in the source, or the fact becomes UNKNOWN.
- **Optional LLM reason-checker:** flag-only, offline only (never in `system/run`), trialled on the 50 practice hits and kept only if it catches problems our checks miss.

## 4. LLM rules

- Used only for free text that regex and structured fields can't read. Regex first.
- Temperature 0, seed, pinned provider, no fallbacks. Those are in `shared/llm_client.py`. `data_collection: deny` is not sent. **Status:** Open, Stage 4 if the trace header must record it; the request flag itself is not on main.
- The quote must be verbatim in the source, and regex must parse the value from it.
- Any failure (timeout, bad JSON, quote not found, budget used up) gives UNKNOWN, which leads to REVIEW.
- **Decision (Neha): a fact the LLM read can never be the reason we clear a hit.** It can only push a hit to REVIEW or support SAME. **Status:** Stage 4 enforces this in the gate (`LLM_FACT`), including when an upstream flag says the fact may solely support a clearance. `may_solely_support_different_entity` stays false on model facts.
- **Fixed budget, not a wall-clock cap:** max calls per hit and per run, fixed per-call timeout, fixed retries, hits processed in sorted order. A wall-clock limit stays only as an emergency backstop. **Status:** PR #10 shares one client across stages with `DEFAULT_TIME_CAP_SECONDS = 1200` (20 minutes, under the 30-minute brief) plus a per-extraction call cap. `system/run` also arms a 25-minute run deadline so a second client cannot use another 1,200 seconds. The default path does not call a model. Hits are processed in `hit_id` order, and a skipped Stage 2 call is flagged `LLM_SKIPPED_BUDGET`.
- Votes: measure per-fact agreement over 15 calls (5 runs x 3 calls) on dev before keeping 3 unanimous votes. 1 call plus the verbatim and regex checks may be enough. **Status:** Open (FDE owns these). The client still requires 3 unanimous calls. The 15-call check and the LLM-on delta test have not been run.
- `llm_calls` logs prompt hash, model, served provider, OpenRouter response ID, quote and parsed value. Never the API key or request headers.
- LLM-off switch, to measure how much the LLM moves results.

## 5. Reproducibility

### Metrics

- **Judges' metric:** same decision and reason code in all 5 runs.
- **Strict metric:** per-hit trace records identical across runs. Exact bytes for non-LLM steps; canonical facts (attribute, normalised value, source ID) for LLM steps, so a different quote span for the same value is not a flip.
- **Headline risk metric: LLM-sensitive hits**, whose decision or code changes between an LLM-on and an LLM-off run. If the provider fails during one judge run, these are the hits that flip. Work to shrink this set.
- The paraphrase test (reword note text, verdict holds) measures robustness and is reported separately.

### Determinism by construction

- `PYTHONHASHSEED=0` is set by `system/run` (it re-execs if the variable is unset) and by `tools/repro`.
- Stable sorts everywhere; sort every directory listing; never depend on set or dict iteration order.
- Name and country folding uses NFKD, then drops combining marks (`system/stage1/normalise_text.py`). Not NFKC.
- No concurrency whose completion order can reach output order.
- Explicit rounding on any float threshold.
- No timestamps or run IDs in per-hit records; all versions and hashes in the run header.

### Gates (block a merge or a submission)

- 0 unsafe clearances on practice labels.
- 0 flips across 5 runs on hits with no LLM involvement.
- No DIFFERENT_ENTITY resting on an LLM-only fact.
- Citation gate passes for every hit.
- Replay script: recompute decision and reason code from each trace record and `rules_version`; must match.

Nice to have: a provider-failure injection run (simulated outage halfway), per-fact 15-call agreement stats, replay in CI, repro gates in the regression suite so a rules change can't add flips.

## 6. Self-improvement (offline only)

Flips and wrong answers on practice labels become proposed rule changes. Neha approves each one, `rules_version` is bumped, and the regression suite (including repro gates) blocks anything that breaks an existing case. Nothing changes during a judged run.

## 7. Simple UI

A static `ui/index.html` with no data in it. It loads `trace.jsonl` and `repro.json` from local disk at runtime and renders all free text with `textContent`, never `innerHTML`.

- **Overview:** totals (alerts, hits, DIFFERENT / SAME / REVIEW split, alerts closed vs kept open); counts by reason code; groups by hit country, customer country, entity type, watchlist category and LLM-touched; safety (practice score, unsafe clearances). Every number is clickable and filters the hit list. Tables first, charts later.
- **Reproducibility card:** "Identical decision and reason code across 5 runs: X of N", "Flipped: k (all LLM-touched?)", "LLM-sensitive hits: m", plus a config row with ticks showing git SHA, `rules_version`, prompt, policy and input hashes and model were identical across all 5 runs.
- **Hit row:** verdict, reason code, fragility badge, short reason, and a run strip of five dots coloured by decision (code on hover). Identical shows grey; any difference highlights the row. Filters: flipped only, LLM-sensitive, thin clearances, thin or borderline plus LLM.
- **Hit drill-down:** comparison card with tipping point, then who is who, then raw trace.
- **Flip panel:** the five runs side by side, with the first trace step where they diverge highlighted and the `llm_calls` behind it.
- Optional hits x runs heatmap for the demo.
- A recorded `repro.json` (IDs, decisions, reason codes, flip flags only, no identity values) can be committed so the demo works without running anything.

## 8. Open items

- **Status:** Fixed (on main before PRs #7 to #9). Name agreement is exhaustive (`shared.names.agree_parts`), not greedy. Dotted initials collapse to one part (`J.R.` → `jr`).
- **Status:** Open, fix pending in PR #10. With equal part counts, `agree_parts` still requires full coverage of the left name only. Stage 3 calls it both ways and keeps a match only when both agree.
- **Status:** Open, Stage 4. The per-hit trace, `TRACE_PATH`, the citation gate and `output/dev.jsonl` are not produced. `tools/repro` already writes `repro.json` from output and trace files when those exist. The static UI is not built.
