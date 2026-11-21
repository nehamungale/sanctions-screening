# tools/eval: grade outputs against the practice labels

Scores one or more screening output files (one JSON line per hit, the shape in
`output.schema.json`) against the 50 practice labels in the data folder, and checks
every output line for explainability. With 5 or more runs of the same input it also
reports the official reproducibility rate. Python 3 standard library only. It does not
run or change the system.

```bash
# One output file: accuracy + explainability
python -m tools.eval --data dev --outputs output/dev.jsonl

# Five runs: adds reproducibility; optionally write a report and metrics
python -m tools.eval --data dev --outputs runs/run1.jsonl runs/run2.jsonl runs/run3.jsonl runs/run4.jsonl runs/run5.jsonl \
    --report eval-report.md --metrics eval-metrics.json

# Tests (synthetic data only)
python -m unittest discover -s tools/eval/tests -v
```

Defaults: data folder `dev`, labels `<data>/practice_labels.jsonl`, name variants
`<data>/name_variants.json`. Use `--labels` / `--policy` to point elsewhere. Nothing is
written unless `--report` / `--metrics` is given. Reports and metrics quote names and
dates from the data folder, so **never commit them** (the data folder itself is
git-ignored). For 5-run repro files for the UI, use `tools/repro` (this tool only scores).

## What it measures

**Accuracy (the 50 labelled hits; first output file if several).**

- **Official decision score** (brief section 6). Each labelled hit has a cost:

  | Truth \ Predicted | DIFFERENT_ENTITY | SAME_ENTITY | REVIEW |
  |---|---:|---:|---:|
  | DIFFERENT_ENTITY | 0 | 3 | 3 |
  | SAME_ENTITY | 60 (unsafe clearance) | 0 | 2 |
  | REVIEW | 60 (unsafe clearance) | 2 | 0 |

  `score = max(0, 1 - cost / cost_all_REVIEW)`. A labelled hit missing from the output is
  scored as REVIEW and listed.
- Decision accuracy; reason code accepted (any code listed on the label counts);
  evidence recall and precision (macro and micro) with the hits that cite extra IDs;
  **false clears** (label SAME_ENTITY or REVIEW, output DIFFERENT_ENTITY) by hit ID;
  **REVIEW over-use** (output REVIEW where the label is definitive);
  `customer_record_id` acceptance (any record of the same person; `AMBIGUOUS`).

**Explainability (every output line).** Reason not empty; every cited ID exists in the
data folder; the reason mentions at least one fact from this hit's records (hit, alert,
cited records or resolved customer: name parts, dates/years, countries, IDs); reason code
belongs to the decision; identical reason text on 3+ hits is flagged as boilerplate
(`--boilerplate-min`). Note: identical text can be legitimate when two hits share the
same facts, so treat boilerplate as a prompt to look, not a failure.

**Reproducibility (N ≥ 5 files from runs on the same input).** Official measure: share of
hits whose decision **and** reason code are identical in all runs. Every hit whose
decision, reason code, cited IDs or reason text differs is listed with per-run values.
Citation or wording changes are listed but do not lower the official rate.

**Error analysis.** The same accuracy metrics (cost, score, evidence precision) grouped by
evidence path (from the label `path`: account_ref / login_handle / email / unlinked link,
KYC, notes, one-person merge, search results, joint holders, multi-person fit) and by
edge-case tags derived from the data (placeholder names, joined name parts, name
variants, territories, multi-person matches).

## Input formats

Outputs: JSONL (preferred), a JSON array or `{"hits": [...]}`, or CSV. Field aliases are
accepted (`explanation`/`reason`, `verdict`, `cited_ids`, camelCase), so both the official
`reason` field and older `explanation` files grade. The data folder is read as
`<data>/<table>.jsonl`; a workbook export with `Customers.csv`, `Hits.csv`, ... also works.
