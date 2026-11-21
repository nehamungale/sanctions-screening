# Screening system

`system/run <data folder> <output file>` reads only that folder and writes one JSON line per hit. The line order and the key order are fixed. A second run of the same folder is byte-identical when the model is off, which is the default.

No model is called unless `USE_LLM_NOTES=1`, `USE_LLM_HITS=1` or `USE_LLM_VETO=1` is set, together with `SANCTIONS_LLM=1` and `OPENROUTER_API_KEY` for the veto. The default path costs $0.

## Architecture

```text
alerts, customers, accounts, onboarding, kyc, notes
        │
        ▼
Stage 1  person_golden.jsonl          who the customer records are
        │
hits, search results
        ▼
Stage 2  hit_golden.jsonl             who the listed person is
        │
        ▼
Stage 3  alert_resolution.jsonl       which customer the alert points at
        │
        ▼
Stage 4  <output file>                one decision per hit
         trace.jsonl                   comparison, steps, alert roll-up
```

Stage 1 clusters customer records (same phone and full date of birth, or the same document number on approved checks) and keeps the latest approved check as the legal name, date of birth and document country. Stage 2 reads hit names, countries, dates of birth (field, then the first paragraph, then search results), dated reports and death. Stage 3 follows the alert's account, login or email, picks a joint-account holder with the screened details, and otherwise searches by name. Stage 4 compares the two sides with the rules below. Cache files go to `SANCTIONS_CACHE` (default `working/`). The run summary is `run_summary.json` in that cache. The output file is only the per-hit JSONL.

## How a hit is decided

Contradictions, in this order: entity type, death before screening, activity before the customer could have been 16 (or before a company existed), date of birth more than a year apart, verified name, location. The first one that passes the safety gate is the reason code. A country difference does not clear a hit whose name and date of birth agree. If nothing contradicts, an individual is confirmed when the name and date of birth agree, and a company when the name and a country agree. Anything else is `REVIEW`.

An alert summary is written to the trace only. The alert is `CLEARED` only when every hit is `DIFFERENT_ENTITY`. Any `SAME_ENTITY` makes it `ESCALATED`. A missing or errored hit is `HIT_NOT_DECIDED` and the alert cannot clear.

## Evidence

Every fact keeps the id of the record it came from. The output cites only the records that decided the hit: the check or note for a verified date or name, the customer records and checks for countries, and search-result ids when a search result supplied the date. Hit fields are not cited. `customer_record_id` is a `CUS-` id, `AMBIGUOUS`, or null. It is never a `P-` id.

## Safety gate

Missing, unread, unmapped or model-read evidence can block a clearance. It cannot create one.

A fact with `method: "llm"` cannot be the basis of `DIFFERENT_ENTITY`, even if an upstream flag says it may. It can support `SAME_ENTITY` or leave the hit in `REVIEW`.

Other blocks, in short: unverified or too-short names cannot clear on name. `UNVERIFIED` is also set when the date of birth is missing, and then a name clearance is blocked even if the legal name itself is verified. A note we could not read for countries cannot clear on location. A declared date that agrees with the hit blocks a date-of-birth clear. A weak age pattern blocks a date-of-birth clear that depends on it. A fuzzy-only or note-only resolution blocks a clear. A joint-account tie-break, a candidate kept on a missing field, and a screened date of birth that matched only in part (`dob_partial_only`) each block every clearance, including location. Any non-Latin alias blocks a name clear.

## Determinism

`system/run` sets `PYTHONHASHSEED=0` before it imports the pipeline. Hits, alerts, evidence and countries are sorted. Reasons are templates. The default path has no model call and no timestamp in the output lines.

`output/dev.jsonl` comes from `system/run dev output/dev.jsonl` on the official dev folder. Two runs were byte-identical, sha256 `712f65ed3e7e07fbdcf9b609511e72de42f7aff80942d6dd76ee0101dbffbf8c`. `validate.py` reported 0 problems. Practice labels: 44/50 decisions, 0 unsafe clearances, and the reason code and customer record were right on every correct decision. Wall clock was about 37s with the model off.

## Model

No model on the default path.

If a note or hit fallback is switched on, calls go through `shared/llm_client.py`: `google/gemma-4-31b-it:free`, provider `Google AI Studio`, `allow_fallbacks` false, temperature 0, seed 0, three identical calls, verbatim quote. One client is shared for the run. Its emergency clock is 1,200 seconds and its run call budget is 48, with at most 12 calls for one extraction. `system/run` also stops model calls at 25 minutes so the process stays inside the 30-minute brief. The optional Stage 4 veto (`USE_LLM_VETO=1`) can only turn a clearance into `REVIEW`. It is off, and it was not needed for the practice score.

## Time and cost

Measured on this machine, model off, 72,265 customer records and 819 hits:

| Stage | Time |
|---|---|
| 1 customer golden record | 23 s |
| 2 hit profiles | 0.2 s |
| 3 alert resolution | 8 s |
| 4 decisions | 2.6 s |
| Wall clock | 34 s |

Cost is $0.

## Three cases

These ids are invented.

**Clear.** Jane Example, born 1990-04-02 (`KYC-0000A1`). The hit lists 1961-07-15. `DIFFERENT_ENTITY` / `DOB_MISMATCH`. Evidence is `KYC-0000A1`. The dates are more than a year apart, so the gate lets the clear through.

**Match.** The same customer, born 1975-09-30, linked to Portugal, and a hit whose profile says "aged 45 in May 2021" and is also linked to Portugal, with an agreeing name. `SAME_ENTITY` / `NAME_DOB_LOCATION_MATCH`.

**Review.** The name agrees and Ireland is shared only through a residence note. The hit has no date of birth. Nothing contradicts, and a missing date is not a mismatch, so the hit is `REVIEW` / `INSUFFICIENT_DATA`.

## Trace

The trace follows `ui/TRACE_CONTRACT.md`. It is not written into the official output. It is `$TRACE_PATH` or `$SANCTIONS_CACHE/trace.jsonl` (`trace_schema` 1). Each hit record has:

- `verdict` — the official line
- `deciding_dims` — the dimensions that decided it (`name`, `dob`, `country`, `type`, `death`, `earliest_report`)
- `tipping_point` — a full sentence. An errored hit says "The hit could not be decided."
- `comparison` — one row per dimension, status `agree` / `contradict` / `unknown`, with `src` and `llm_used`. `dob.hit` is the date values and `dob.note` is the sentence. `death.customer` is null unless the customer has a death fact; `death.screening_date` is the alert date.
- `identity.facts.name.verified` is true only for a legal name from an approved KYC check. `identity.facts.dob.verified` is true only when that fact has a `source_id`.
- `identity.candidates` — each Stage 3 candidate, its `customer_record_id`, and `would_decide`
- `steps` — every rule, each with `llm_used` true when an input fact was read by the model
- `llm_calls` — empty on the default path
- `badges.fragility`, `badges.llm_used`, `badges.rules_version`

Alert summaries follow the hit records in the same file: `alert_status` is `CLEARED`, `ESCALATED` or `NEEDS_REVIEW`, with `blocking_hit_ids` and `undecided_hit_ids`.

## Limitations

Non-Latin names are not transliterated, and any such alias blocks a name clear. A joint-account tie-break, a candidate kept on a missing field, or a screened date that matched only in part blocks every clearance. `UNVERIFIED` from a missing date of birth blocks a name clearance even when the legal name is verified. A weak age sentence ("was 45", "reached 45") does not clear a date of birth on its own. Those rules leave some true mismatches in review. Unseen note wording that the parsers do not recognise blocks a clear instead of being guessed. The veto is implemented and tested, and left off.
