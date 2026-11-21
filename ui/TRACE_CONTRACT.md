# Trace contract: what the reviewer UI reads

Every field the UI reads, where it comes from, and what happens when it is missing or malformed.
This matches the **real Stage 4 trace** (`system/stage4/trace.py`, `rollup.py`, `build.py`; `trace_schema` 1,
`rules_version` `stage4-r1`). The pipeline does not change for the UI; the UI adapts.
**Emitted** means the stage4 code writes it. **Not emitted** marks a field the UI once proposed or read that stage4 does
not write; the UI copes without it.
All IDs below are synthetic (`H-SYN…`, `A-SYN…`, `CUS-SYN…`, `KYC-SYN…`).

General rules: all free text is rendered as plain text (React text nodes; never `innerHTML`).
A line that is not valid JSON, or a record that fails validation, is listed as a problem and skipped;
nothing throws. Anything that would make a hit or alert look safer than the data supports fails closed
(the hit has no decision, the alert can't be cleared).

`fixtures/trace-pipeline.sample.jsonl` is a trace written by `system/run` itself on a small synthetic data folder
(`tests/make-real-trace.py`; IDs rewritten to the synthetic form afterwards). `fixtures/trace.sample.jsonl` is hand-written
in the same shape (a test checks its field names against the pipeline's), with the alert summaries appended by the repo's
own `stage4.rollup.roll_up` (`tests/make-trace-sample.py`). `fixtures/trace-crosscheck.sample.jsonl` is the same trace with
the A-SYN009 summary deliberately wrong (says CLEARED), for the cross-check demo (`?sample=crosscheck`).

## 1. `trace.jsonl`: one line per hit, then one line per alert

Stage 4 writes the hit lines first, then appends its alert summaries **to the same file** (§3). A line with
`alert_status` and no `hit_id` is a summary; every other line must be a hit record. Keys are sorted.

| Field | Type | Status | Example | If missing / invalid |
|---|---|---|---|---|
| `trace_schema` | `1` | Emitted | `1` | Record rejected; hit has no decision |
| `hit_id` | string | Emitted | `"H-SYN001"` | Line rejected |
| `alert_id` | string | Emitted | `"A-SYN001"` | Hit counts as undecided for any alert that lists it (must match the listing alert) |
| `verdict.decision` | `DIFFERENT_ENTITY` \| `SAME_ENTITY` \| `REVIEW` | Emitted | `"DIFFERENT_ENTITY"` | Record rejected; hit has no decision |
| `verdict.reason_code` | one of the codes that belong to the decision | Emitted | `"DOB_MISMATCH"` | Record rejected if the code doesn't belong to the decision |
| `verdict.reason` | string | Emitted | `"The customer's date of birth is 1990-04-02 (KYC-SYN101) but …"` | "No reason text." |
| `verdict.evidence` | string[] | Emitted (customer-side record ids only; hit fields are not cited) | `["CUS-SYN001", "KYC-SYN101"]` | Empty list; non-strings dropped |
| `verdict.customer_record_id` | `CUS-…` \| `"AMBIGUOUS"` \| null | Emitted | `"CUS-SYN001"` | "no customer record found" |
| `not_decided` | boolean | Emitted (top level) | `false` | `true`: the hit counts as **no decision** (blocks its alert), even though its verdict is a placeholder `REVIEW` / `INSUFFICIENT_DATA`; left out of the decision totals |
| `badges.fragility` | `solid` \| `thin` \| `borderline` | Emitted | `"thin"` | Shown as "unknown" |
| `badges.llm_used` | boolean | Emitted | `false` | Shown as "unknown" |
| `badges.rules_version` | string | Emitted | `"stage4-r1"` | Shown as "unknown" |
| `deciding_dims` | string[] of comparison dims | Emitted, **top level** (sibling of `verdict`); `[]` for REVIEW codes | `["dob"]` | Empty/invalid: derived from the reason code (below) |
| `tipping_point` | string \| null | Emitted | `"Without the DOB_MISMATCH ground this would be REVIEW (INSUFFICIENT_DATA)."` | "No tipping point recorded in the trace." |
| `comparison[]` | `{dim, customer, hit, status, src[], llm_used}` | Emitted: 6 rows in this order `name`, `dob`, `country`, `type`, `death`, `earliest_report` | `{"dim":"dob","customer":"1990-04-02","hit":"…1961-07-15","status":"contradict","src":["KYC-SYN101"],"llm_used":false}` | A missing row shows as can't compare. **`[]` when no customer fits the alert or the hit was not decided**: the panel shows "No comparison: why" (no matching customer record / the hit has no decision) instead of a table |
| `comparison[].status` | `agree` \| `contradict` \| `unknown` | Emitted | `"contradict"` | Plain English (agrees / contradicts / can't compare). Other values shown as-is. `no_conflict` is **not emitted** (still labelled if it appears) |
| `comparison[].customer` / `.hit` | any JSON (country is a list) | Emitted | `"1990-04-02"`, `["Ireland"]`, `null` | Null/empty: "not in customer records" / "not on list profile" |
| `comparison[].src` | string[] | Emitted | `["CUS-SYN001", "KYC-SYN101"]` | "—" |
| `comparison[].llm_used` | boolean | Emitted | `false` | `true` adds a small "(model-read)" note next to the status |
| `identity.person_id` | string \| null | Emitted | `"P-CUS-SYN001"` | "—" |
| `identity.merged[]` | `{rule, records[]}` | Emitted (Stage 1 cluster edges) | `{"rule":"P3","records":["CUS-SYN002","CUS-SYN014"]}` | "none". Extra keys are shown as `key: value` |
| `identity.facts` | map `dob` / `name` / `entity_type` → `{value, source_id}`; `verified` only on `dob` and `name` | Emitted; **`{}`** when there is no comparison | `{"dob":{"value":"1990-04-02","verified":true,"source_id":"KYC-SYN101"}}` | Table omitted |
| `identity.facts.dob.verified` | boolean | Emitted | `true` | Shown as "verified" / "declared" |
| `identity.facts.name.verified` | boolean | Emitted. **Means only "a name comparison was computed"**, not a KYC-verified legal name | `true` | Shown as "compared with the hit" / "not compared". The word "verified" is never used for the name (DOM check enforces it) |
| `identity.facts.*.source_kind` | | **Not emitted** | | Not read |
| `identity.flags[]`, `identity.ignored_checks[]` | string[] | Emitted | `["UNVERIFIED"]` | "none" |
| `identity.candidates[]` | see §1a | Emitted (every Stage 3 candidate, also when there is one) | | AMBIGUOUS panel says the trace doesn't list the candidates |
| `steps[]` | `{rule, result, llm_used, why}`; `result` `fired` \| `not_fired` \| `blocked`; the six clear rules then `CONFIRM` | Emitted | `{"rule":"DOB_MISMATCH","result":"fired","llm_used":false,"why":null}` | Empty table |
| `llm_calls[]` | object[] | Emitted, **always `[]`** (model off by default) | `[]` | Empty is normal: the "LLM calls" section is hidden. If calls ever appear, every key is shown as `key: value` |
| run header / `run_id` | | **Not emitted** | | A legacy `run_id` line without `hit_id` is skipped, not an error |

**Duplicates.** Several records for one `hit_id`: identical ones (same JSON once keys are sorted) are merged with a note.
If they differ, or any is invalid, the hit has no decision.

**Deciding rows** (comparison rows highlighted as "deciding"). `deciding_dims` when non-empty and valid; otherwise from the
reason code: `TEMPORAL_IMPOSSIBILITY`→earliest_report, `DOB_MISMATCH`→dob, `LOCATION_MISMATCH`→country,
`NAME_MISMATCH_VERIFIED`→name, `ENTITY_TYPE_MISMATCH`→type, `DECEASED`→death, `NAME_DOB_LOCATION_MATCH`→name+dob+country,
`NAME_DOB_MATCH`→name+dob, `NAME_LOCATION_MATCH`→name+country; REVIEW codes → none. For a clear, stage4 lists every clear
ground that passed (e.g. `["dob","name","country"]`), not only the reason code's.

**AMBIGUOUS.** stage4 fills `comparison` and `identity.facts` from the **first** candidate. The panel says so above the
table ("The customer column shows the first candidate, CUS-…") and lists every candidate with its own outcome.

### 1a. `identity.candidates[]`

| Field | Type | Example | If missing / null |
|---|---|---|---|
| `customer_record_id` | string | `"CUS-SYN004"` | Candidate dropped |
| `person_id` | string | `"P-CUS-SYN004"` | — |
| `name`, `dob` | string \| null | `"Tamsin Grovewell"`, `"1990-07-12"` | "name not in the trace" / "not in the trace" |
| `country` | one comma-joined string \| null | `"GB, IE"` | "not in the trace" |
| `why_fits` | string (Stage 3 resolution method) | `"link_account"` | omitted |
| `would_decide` | `{decision, reason_code}` | `{"decision":"SAME_ENTITY","reason_code":"NAME_DOB_LOCATION_MATCH"}` | omitted |

### 1b. `llm_calls[]`

Always `[]` today. The design's field list (`step`, `attribute`, `source_id`, `prompt_sha256`, `model`, `provider`,
`response_id`, `quote`, `parsed_value`) is **not emitted**. LLM information stays small: the `llm_used` badge, a
"(model-read)" note on a comparison row, and a collapsed section that only appears when there are calls.

## 2. `alerts.jsonl` (the dataset's alert file) — the only source that can make an alert Cleared

| Field | Type | Source | If missing / invalid |
|---|---|---|---|
| `alert_id` | string | Dataset | Line unreadable |
| `hit_ids` | string[] | Dataset | Line unreadable |

Other dataset fields (`customer`, `account_ref`, …) are ignored. Also accepted as a JSON array.
- **Unreadable lines** (bad JSON, missing fields): a red banner counts them and every clear is withheld (shown as Not verified).
- **Several lines for one `alert_id`**: identical → merged with a note. Different → hit lists combined (a hit with no trace
  record then blocks as missing), the alert can't be cleared, and a red warning names the alert and its line numbers.
- **No alerts.jsonl**: alerts are rebuilt from the trace's alert summaries (or, with none, from each hit's `alert_id`);
  nothing shows as Cleared ("Not verified" instead).

## 3. Alert summaries (appended to `trace.jsonl`) — a cross-check only

Stage 4 appends one line per alert to `trace.jsonl`. There is **no separate `alerts.trace.jsonl`** (not emitted). For
back-compat a separate summaries file can still be opened with "Open alerts…"; it then takes the place of the trace's
summary lines for the cross-check. Neither ever makes an alert Cleared.

| Field | Type | Status | Use |
|---|---|---|---|
| `alert_id` | string | Emitted | match |
| `alert_status` | `CLEARED` \| `ESCALATED` \| `NEEDS_REVIEW` | Emitted | compared with the UI roll-up; differences shown in red. Internal names are never displayed |
| `hits[]` | `{hit_id, decision, reason_code, fragility, missing?, undecided?}` | Emitted; an undecided hit has `decision: null`, `reason_code: "HIT_NOT_DECIDED"`, `undecided: "missing"` \| `"errored"` | `hit_id` → hit list |
| `blocking_hit_ids`, `undecided_hit_ids` | string[] | Emitted | added to the hit list |

The UI recomputes every alert from the hit lines (and alerts.jsonl). Pipeline CLEARED against UI "Not verified" is not
a disagreement; pipeline CLEARED against UI "Needs review" is, and the note says a pipeline summary never clears an alert.
Duplicate summary lines that differ are flagged. A bad summary line is listed under the trace with its real line number.

## 4. `repro.json` (`tools/repro`, `schema_version: 1`)

| Field | Use | If missing / invalid |
|---|---|---|
| `schema_version` | must be `1` | File rejected |
| `summary.n_runs`, `meta.run_labels` | strip length and dot tooltips | `n_runs` from labels; fewer than 2 runs → rejected |
| `hits[].hit_id`, `per_run`, `stable`, `flip_type` | strip, unstable list, recomputed metrics | Row dropped with a problem line |
| `hits[].modal_decision`, `modal_reason_code`, `alert_id`, `llm_used`, `fragility` | display, link to the hit panel | shown empty |
| `summary.n_hits`, `summary.judges_stable_hits` | cross-checked against the rows | mismatch shown as a warning |
| `config_check.all_identical` | ✓/✗ per config field | "config cannot be compared" |
| `meta.generated_at` | shown | omitted |

No repro fields changed; only how the UI reads `per_run` did. `per_run[i] === null` means the hit is
**missing in run i+1** (dot tooltip, legend and list say exactly that). `missing_from_runs` and `flip_type` are not used for the
counts; everything is recomputed from `per_run`:

- **Reproducibility (headline, official)**: the brief's measure, "the same decision and reason code in all five runs". A hit
  counts only if it is present in every run with one decision and one reason code. Must equal `summary.judges_stable_hits`.
- **Same decision in all runs (secondary)**: present in every run with one decision; the reason code may differ.
- **Clear that ever flipped** (must be 0, red otherwise): the decision differs between runs and at least one run said
  `DIFFERENT_ENTITY`, **or** the hit is missing from a run and every run that produced it said `DIFFERENT_ENTITY`.
- **Missing output** (counted separately, red-flagged as broken output): missing from at least one run and not a flipped clear.
  Unstable, but not a flip.
- **Reason code changed**: same decision wherever present, different reason code. Counts against the official rate, not a flip.
- **Unstable** (`getUnstableHitIds`, `useUnstableFilter`, Audit "Not identical in all runs only") = **not officially
  reproducible** (the headline definition). Hits with `stable: false` but identical verdicts in every run (evidence or other
  trace changes) are *not* unstable; the card lists them in one muted "not counted" line.
