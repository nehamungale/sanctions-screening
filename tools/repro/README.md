# Reproducibility report

`python -m tools.repro` compares two or more screening runs and writes `repro.json` for the static UI. Python 3 standard library only. It does not decide hits. Neha's rule (an LLM-read fact can never clear a hit; it can only push to `REVIEW` or support `SAME`) is enforced by the matcher, not here. This report shows which hits moved and whether a run used an LLM.

The judges' number is the share of hits with the same decision and reason code in every run. A stricter count also flags evidence, `customer_record_id`, and canonical trace facts.

## Run it

From the repo root, on output files (JSONL, one object per line, official fields: `hit_id`, `alert_id`, `decision`, `reason_code`, `customer_record_id`, `reason`, `evidence`):

```bash
python -m tools.repro \
  --outputs run1.jsonl run2.jsonl run3.jsonl run4.jsonl run5.jsonl \
  --out repro.json
```

Traces are optional and paired by position with the outputs. A trace file is JSONL: one run-header object, then one record per hit (`trace_schema`, `hit_id`, `verdict`, `badges`, `steps`, and the rest of the design). Header fields the design names (`git_sha` or `sha`, `rules_version`, `hashes.policy`, `hashes.name_variants`, `hashes.prompts`, `hashes.input`, `model`, `provider` / `served_provider`, `python_version` / `python`) are read from whichever alias is present.

```bash
python -m tools.repro \
  --outputs run1.jsonl run2.jsonl run3.jsonl run4.jsonl run5.jsonl \
  --traces trace1.jsonl trace2.jsonl trace3.jsonl trace4.jsonl trace5.jsonl \
  --llm-off-output llm-off.jsonl \
  --out repro.json
```

Traces alone are enough. The verdict block supplies the decision. Pass at least two runs. File order is run order.

Rerun `system/run` N times (default 5), then build the report. With `--capture-traces`, each child gets `TRACE_PATH` set to that run's trace file and `PYTHONHASHSEED=0`. `--llm-off` adds one more call with `USE_LLM_NOTES=0` and `SANCTIONS_LLM=0` (see the gaps below). The N runs otherwise inherit your environment, so turn the LLM on there if you want an on-versus-off comparison.

```bash
python -m tools.repro --run \
  --data /path/to/data \
  --n 5 \
  --work-dir repro-work \
  --capture-traces \
  --llm-off \
  --out repro.json
```

`repro-work/` holds the per-run files. Do not commit it, or any real trace. `meta.generated_at` is the only timestamp; pass `--generated-at` when you need a fixed one.

Tests:

```bash
python -m unittest discover -s tools/repro/tests -v
```

`tools/repro/repro.example.json` is a synthetic five-run report (no real customers). Schema for the UI: `tools/repro/repro.schema.json`.

## What the UI reads

- **Run strip.** `hits[].per_run[i]` is `[decision, reason_code]`, or `null` if that run has no line. Colour the dot with `ui.decision_legend` (`clear`, `match`, `review`, `missing`). The hover text is the reason code. `meta.run_labels[i]` is the column title. Grey the row when `stable` is true; highlight it otherwise.
- **Flipped only.** `ui.filters.flipped_only`. Narrower lists: `decision_flip`, `code_flip`, `evidence_flip`, `missing`, `llm_sensitive`, `thin_clearances` (modal `DIFFERENT_ENTITY` and fragility `thin`), `thin_or_borderline_and_llm`.
- **Flip panel.** `changes` says what moved. `evidence_per_run` and `customer_record_id_per_run` are the output fields. `first_divergent_step` is the first step, in the stable rule order, whose `rule` / `result` / `why` differs, with `values_per_run` aligned to the runs. `first_divergent_fact` is the first canonical fact that differs. `llm_calls` are not copied (they can hold quotes). Join them from that run's trace by `hit_id`.
- **Heatmap.** `heatmap.hit_ids` by `heatmap.run_labels`. `heatmap.decisions[row][column]` is the decision or `null`.

Headline card: "`judges_stable_hits` of `n_hits`" from `summary`, flipped = `judges_flip_hits` (and `judges_flips_all_llm_used`), LLM-sensitive = `llm_sensitivity.n_sensitive`, config ticks = `config_check.all_identical`.

## Fields

### `summary`

| Field | Meaning |
|---|---|
| `n_runs` | How many runs were compared. |
| `n_hits` | Distinct `hit_id`s across those runs. |
| `judges_metric` | `judges_stable_hits / n_hits`. Null if there are no hits. |
| `judges_stable_hits` | Present in every run with one decision and one reason code. |
| `judges_flip_hits` | Decision flips plus code-only flips. |
| `judges_flips_all_llm_used` | True when every one of those flips has `llm_used` true. Null if there are none, or if any of them has unknown `llm_used`. |
| `decision_flip_hits` | Hits whose decision is not the same in every run that contains them. |
| `code_only_flip_hits` | Decision agrees, reason code does not. |
| `strict_change_hits` | Hits where evidence, `customer_record_id`, canonical facts, or canonical steps differ. A judges-stable hit can still be in this count. |
| `strict_change_hit_ids` | Those hit ids, sorted. |
| `missing_hits` | Hits absent from at least one run. |
| `hits_missing_from_some_runs` | Those hit ids, sorted. |
| `decision_counts_per_run` | Per run, counts of `DIFFERENT_ENTITY`, `SAME_ENTITY`, and `REVIEW`. Hits that run does not contain are not counted. |
| `flips_by_llm_used` | Flip-type counts under `llm_used`, `not_llm_used`, and `unknown`. |

### `config_check`

Taken from trace run headers. `available` is false and every `all_identical` value is null when you pass outputs only.

Each `runs[]` entry has `run_index`, `run_label`, `git_sha`, `rules_version`, `policy_hash`, `name_variants_hash`, `prompt_hashes`, `input_hash`, `model`, `provider` (the provider that was actually served), and `python_version` when the header has it.

`all_identical.<field>` is true when every run shares that value and at least one value is non-null, false when they differ, and null when the field is missing from every header. Header `run_id` and timestamp are not copied. They are expected to change every run. `meta.generated_at` is the only timestamp in the file.

### `llm_sensitivity`

Null unless you passed an LLM-off output. A hit is listed when its LLM-off decision or reason code differs from the modal LLM-on result (see tie-breaks below), when it is missing from the LLM-off file, or when it appears only in the LLM-off file (`llm_on_modal_*` is then null).

### `hits[]` (sorted by `hit_id`)

| Field | Meaning |
|---|---|
| `hit_id`, `alert_id` | Identity of the row. `alert_id` is the modal id. `alert_id_conflict` is true when runs disagree. |
| `per_run` | The strip. `[decision, reason_code]` or null. |
| `stable` | `flip_type` is `none`. |
| `judges_stable` | Counts toward the judges' metric. |
| `flip_type` | `none`, `decision`, `code`, `evidence`, or `other`. First match wins: decision; else reason code; else evidence ids or `customer_record_id`; else anything else in `changes`. |
| `modal_decision` | Most common decision among runs that have the hit. Ties break toward `REVIEW`, then `SAME_ENTITY`, then `DIFFERENT_ENTITY`. |
| `modal_reason_code` | Most common code among runs with that modal decision. Ties break by the `POLICY.md` table order. |
| `llm_used` | True if any trace badge says true, false if a badge says false and none say true, null with no badge (outputs only). |
| `fragility` | Badge value. If runs disagree: `borderline`, else `thin`, else `solid`. `fragility_conflict` records the disagreement. |
| `missing_from_runs` | Run indexes with no line for this hit. |
| `evidence_per_run` | Evidence ids, sorted, or null if the hit is absent. `["B","A"]` and `["A","B"]` are the same. |
| `customer_record_id_per_run` | Customer record per run. Null inside a present run means no record. A null entry whose `per_run` entry is also null means the hit was absent. |
| `changes` | Booleans: `decision`, `reason_code`, `evidence`, `customer_record_id`, `canonical_facts`, `steps`, `missing`, `alert_id`, `output_trace_mismatch`. |
| `first_divergent_step` | On a flipped hit whose steps differ: `order_index` (0-based in the stable order below), `rule`, `occurrence`, and `values_per_run` (`rule`, `result`, `why` only). |
| `first_divergent_fact` | On a flipped hit whose canonical facts differ: `attribute` and `values_per_run` of `{value, source_id}`. |
| `output_trace_mismatch_runs` | Runs where the output line and the trace `verdict` disagree. The output wins. |
| `trace_present_per_run` | Whether that run contributed a trace record. |

Reason sentences are not stored. They can carry identity facts, and the judges' reproducibility score does not use them.

Stable step order, from the design's trace example and then the rest of the policy table: `ENTITY_TYPE_MISMATCH`, `DECEASED`, `TEMPORAL_IMPOSSIBILITY`, `DOB_MISMATCH`, `LOCATION_MISMATCH`, `NAME_MISMATCH_VERIFIED`, `NAME_DOB_LOCATION_MATCH`, `NAME_DOB_MATCH`, `NAME_LOCATION_MATCH`, `INSUFFICIENT_DATA`, `AMBIGUOUS_CUSTOMER_RECORD`, then any other rule name alphabetically. Input order does not matter.

Canonical facts are `identity.facts` and `comparison` rows, each reduced to attribute, NFKC-normalised value, and source id. `verified`, `source_kind`, comparison `status`, quote fields, and `llm_calls` are not compared. A different quote span for the same value is not a flip.

## Determinism

The report is byte-stable for the same inputs and the same `generated_at`: sorted object keys, hits sorted by `hit_id`, runs kept in the order you passed them. No per-hit timestamp.

## Do not commit

Real `dev/` data, trace files, API keys, or `.env` files. A `repro.json` built from real traces can contain normalised values and step text. The committed sample is `repro.example.json` only: synthetic hit ids, alert ids, decisions, reason codes, evidence ids, and flip flags.

## Gaps against the design doc

The design (`docs/explainability-and-reproducibility.md`) does not name a directory. This lives in `tools/repro/`.

- **Strict metric.** The design asks for exact bytes on non-LLM steps, and canonical facts on LLM steps. `steps[]` has no per-step LLM flag, so every step is compared the same way: `rule`, `result`, and `why`, after NFKC, with quote keys dropped. Extra step keys are ignored so an unexpected field cannot leak into the report or cause a flip. `tipping_point`, the reason sentence, comparison `status`, and `verified` / `source_kind` are not compared. `llm_calls` are ignored entirely. Facts that landed in `identity.facts` or `comparison` are compared as attribute + normalised value + source id.
- **`flip_type`.** `evidence` means the evidence id list or `customer_record_id` changed while decision and code did not. A step-only or fact-only change is `other`, and it still increments `strict_change_hits`. `other` is also a missing hit, an alert-id clash, or an output/trace verdict clash.
- **Missing hits** lower the judges' metric (they are not "the same in all runs") and are not counted as decision flips.
- **Recorded file name.** The design says a committed `repro.json`. The sample committed here is `tools/repro/repro.example.json`, so a local real report is not overwritten.
- **LLM-off switch.** The design does not name the environment variable for the full system. The runner turns off `USE_LLM_NOTES` (the Stage 1 switch) and sets `SANCTIONS_LLM=0` for the extra run only.
- **`system/run` today** writes the Stage 1 summary. It does not yet emit one JSON line per hit, and it does not read `TRACE_PATH`. The runner still calls `system/run <data> <output>` and sets `TRACE_PATH` for the matcher to pick up. Until that exists, point `--outputs` / `--traces` at files you already have.
- **Run header** is described in prose, not a schema. Aliases are accepted. `run_id` and the header timestamp are left out of `repro.json` on purpose.
- **Flip-panel `llm_calls`** stay in the trace file. Putting them in `repro.json` would copy quotes.
- **Clearing rule.** This tool does not block a `DIFFERENT_ENTITY` that rests on an LLM-only fact. `llm_used` and `llm_sensitivity` are what the UI and the gates can read.
