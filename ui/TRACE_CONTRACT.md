# Trace contract: what the reviewer UI reads

Every field the UI reads, where it comes from, and what happens when it is missing or malformed.
**Design** means defined in `docs/explainability-and-reproducibility.md` (§1 per-hit record, §7 UI),
`docs/stage4-notes.md` (§1 alert roll-up) or `tools/repro/repro.schema.json`.
**UI-proposed** means invented by the UI and not yet agreed: the matching engine should emit it, or tell us a better name.
All IDs below are synthetic (`H-SYN…`, `A-SYN…`, `CUS-SYN…`, `KYC-SYN…`).

General rules: all free text is rendered as plain text (React text nodes; never `innerHTML`).
A line that is not valid JSON, or a record that fails validation, is listed as a problem and skipped;
nothing throws. Anything that would make a hit or alert look safer than the data supports fails closed
(the hit has no decision, the alert can't be cleared).

## 1. `trace.jsonl`: one record per hit

| Field | Type | Source | Example | If missing / invalid |
|---|---|---|---|---|
| `trace_schema` | `1` | Design | `1` | Record rejected; hit has no decision (`HIT_NOT_DECIDED`) |
| `hit_id` | string | Design | `"H-SYN001"` | Line rejected |
| `alert_id` | string | Design | `"A-SYN001"` | Hit counts as undecided for any alert that lists it (must match the listing alert) |
| `verdict.decision` | `DIFFERENT_ENTITY` \| `SAME_ENTITY` \| `REVIEW` | Design | `"DIFFERENT_ENTITY"` | Record rejected; hit has no decision |
| `verdict.reason_code` | one of the codes that belong to the decision (brief / POLICY table) | Design | `"DOB_MISMATCH"` | Record rejected if the code doesn't belong to the decision |
| `verdict.reason` | string | Design | `"Verified DOB year 1984 (KYC-SYN101) contradicts …"` | "No reason text." |
| `verdict.evidence` | string[] | Design | `["KYC-SYN101", "H-SYN001#dobs"]` | Empty list; non-strings dropped |
| `verdict.customer_record_id` | string \| `"AMBIGUOUS"` \| null | Design | `"CUS-SYN001"` | "no customer record found" |
| `badges.fragility` | `solid` \| `thin` \| `borderline` | Design | `"thin"` | Shown as "unknown" |
| `badges.llm_used` | boolean | Design | `false` | Shown as "unknown" |
| `badges.rules_version` | string | Design | `"r1.0"` | Shown as "unknown" |
| `tipping_point` | string \| null | Design | `"Without KYC-SYN101 this would be REVIEW (INSUFFICIENT_DATA)."` | "No tipping point recorded in the trace." |
| `comparison[]` | `{dim, customer, hit, status, src[]}` | Design | `{"dim":"dob","customer":"1984-03-02","hit":"1961; 1962","status":"contradict","src":["KYC-SYN101"]}` | Each of the 6 dims (`name`, `dob`, `country`, `type`, `death`, `earliest_report`) is always shown; a missing row shows as can't compare. Extra dims are shown after the six |
| `comparison[].status` | `agree` \| `contradict` \| `no_conflict` \| `unknown` | Design | `"no_conflict"` | Shown in plain English (agrees / contradicts / no conflict / can't compare); raw value in the tooltip and the raw trace. Unknown values are shown as-is |
| `comparison[].customer` / `.hit` | any JSON | Design | `"GB"`, `["GB","IE"]`, `null` | Null/empty: "not in customer records" / "not on list profile" ("differs by candidate" for an AMBIGUOUS customer) |
| `identity.person_id` | string | Design | `"P-CUS-SYN001"` | "—" |
| `identity.merged[]` | `{rule, records[], …}` | Design | `{"rule":"P3 phone+full DOB","records":["CUS-SYN002","CUS-SYN014"]}` | "none". Extra keys are shown as `key: value` |
| `identity.facts` | `{name: {value, verified, source_id, source_kind}}` | Design (Stage 1 mapping) | `{"dob":{"value":"1984-03-02","verified":true,"source_id":"KYC-SYN101"}}` | Table omitted |
| `identity.flags[]`, `identity.ignored_checks[]` | string[] | Design | `["UNVERIFIED"]` | "none" |
| `steps[]` | `{rule, result, llm_used, why?}` | Design | `{"rule":"DOB_MISMATCH","result":"fired","llm_used":false}` | Empty table |
| `llm_calls[]` | object[] | Design (content listed, field names not) | see §1b | "No LLM calls for this hit." |
| `deciding_dims` | string[] of comparison dims | **UI-proposed** | `["dob"]` | Derived from the reason code (below). Invalid entries → derived |
| `identity.candidates[]` | see §1a | **UI-proposed** | | AMBIGUOUS panel says the trace doesn't list the candidates |

Records with `alert_status` (alert summaries) or a `run_id` without `hit_id` (run header) are skipped, not errors.

**Duplicates.** Several records for one `hit_id`: identical ones (same JSON once keys are sorted) are merged with a note.
If they differ, or any is invalid, the hit has no decision.

**Deciding rows** (comparison rows highlighted as "deciding"). `deciding_dims` when valid; otherwise from the reason code:
`TEMPORAL_IMPOSSIBILITY`→earliest_report, `DOB_MISMATCH`→dob, `LOCATION_MISMATCH`→country, `NAME_MISMATCH_VERIFIED`→name,
`ENTITY_TYPE_MISMATCH`→type, `DECEASED`→death, `NAME_DOB_LOCATION_MATCH`→name+dob+country, `NAME_DOB_MATCH`→name+dob,
`NAME_LOCATION_MATCH`→name+country; REVIEW codes → none. Kept outside `verdict` on purpose: `dev.jsonl` is copied from the
verdict block and must stay exactly to `output.schema.json`.

### 1a. `identity.candidates[]` (UI-proposed, for `AMBIGUOUS_CUSTOMER_RECORD`)

| Field | Type | Example | If missing |
|---|---|---|---|
| `customer_record_id` | string (required) | `"CUS-SYN004"` | Candidate dropped |
| `person_id` | string | `"P-CUS-SYN004"` | — |
| `name`, `dob`, `country` | string | `"Tamsin Grovewell"`, `"1990-07-12"`, `"GB"` | "—" |
| `why_fits` | string | `"name and email domain match the alert"` | omitted |
| `would_decide` | `{decision, reason_code}` | `{"decision":"SAME_ENTITY","reason_code":"NAME_DOB_LOCATION_MATCH"}` | omitted |

### 1b. `llm_calls[]` (field names UI-proposed; the design lists the content)

`step`, `attribute`, `source_id`, `prompt_sha256`, `model`, `provider` (served provider), `response_id`, `quote`, `parsed_value`.
The UI shows every key of each call as `key: value` text, so other names also display. Never the API key or headers.
LLM information is deliberately small: one `llm_used` badge and this collapsed section.

## 2. `alerts.jsonl` (the dataset's alert file) — the only source that can make an alert Cleared

| Field | Type | Source | If missing / invalid |
|---|---|---|---|
| `alert_id` | string | Dataset | Line unreadable |
| `hit_ids` | string[] | Dataset | Line unreadable |

Other dataset fields (`customer`, `account_ref`, …) are ignored. Also accepted as a JSON array.
- **Unreadable lines** (bad JSON, missing fields): a red banner counts them and every clear is withheld (shown as Not verified).
- **Several lines for one `alert_id`**: identical → merged with a note. Different → hit lists combined (a hit with no trace
  record then blocks as missing), the alert can't be cleared, and a red warning names the alert and its line numbers.
- **No alerts.jsonl**: alerts are rebuilt from `alerts.trace.jsonl` or from each hit's `alert_id`; nothing shows as Cleared
  ("Not verified" instead).

## 3. `alerts.trace.jsonl` (Stage 4 alert summaries) — a cross-check only

| Field | Type | Source | Use |
|---|---|---|---|
| `alert_id` | string | Design (Stage 4) | match |
| `alert_status` | `CLEARED` \| `ESCALATED` \| `NEEDS_REVIEW` | Design | compared with the UI roll-up; differences shown in red. Internal names are never displayed |
| `hits[].hit_id` | string | Design | hit list (with `undecided_hit_ids`, `blocking_hit_ids`) |

Pipeline CLEARED against UI "Not verified" is not a disagreement. Duplicate summary lines that differ are flagged.

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
