# Stage 1 hardening

Missing, unread, or unmappable evidence blocks a clear. It never causes one. Stage 1 still does not decide hits. Each person carries flags and a `contracts` object that later stages must honour.

## What changed

- Name agreement is an exhaustive one-to-one pairing (`shared.names.agree_parts`), with a fixed tie-break. Joins are tried on both sides and across variant groups. Dotted initials collapse without a space: `J.R.` becomes the part `jr`.
- `parse_date(value, mode="customer"|"hit")`. Customer slash dates stay day-first. A hit slash date with both parts 12 or under is `UNKNOWN_DATE`, not a guessed day.
- One country table for both tracks. It covers ISO codes, English names, demonyms, and watchlist spellings (`Palestina`, `Macao Special Administrative Region of China`, `Czech Republic`, `Côte d'Ivoire`, `North Korea`, `Turkey`, `Russia`, `Kosovo`, and the rest). Address tags such as `[Business]` are stripped. `International` and `Europe` are not countries and are dropped without `UNMAPPED_COUNTRY`.
- `declared_dobs` lists every record in the cluster, with `source_id` and `comparable`. A missing or unparsed date stays in the list.
- `customer_record_ids` repeats the `CUS-` ids. Decision output must use one of those, never `person_id`.
- Each decisive fact keeps `source_id`. Verified regex facts use `method: "regex"`. LLM facts use `method: "llm"` and `may_solely_support_different_entity: false`.
- The OpenRouter client lives in `shared/llm_client.py` (stdlib `urllib` only). It is off unless `USE_LLM_NOTES=1`. Free models only: the pinned default is `google/gemma-4-31b-it:free`, and any slug that does not end in `:free` is refused with no network call (the fact stays UNKNOWN). It sends a fixed provider order (`Google AI Studio`) with `allow_fallbacks: false`, `temperature: 0`, and a fixed seed, requests a strict JSON schema, checks that every string appears verbatim in the source, and requires 3 identical calls. HTTP 429 is retried with a short bounded backoff, then UNKNOWN. A timeout, retry exhaustion, disagreement, quote miss, call budget, or the 90 second time cap also yields UNKNOWN. Nothing is cached.

## Flags later stages must obey

| Flag | Do not emit |
|---|---|
| `BLOCK_NAME_MISMATCH_VERIFIED` | `NAME_MISMATCH_VERIFIED`. Set when `legal_name.verified` is false, or the legal name came only from the LLM. |
| `BLOCK_NAME_CLEAR` / `NAME_TOO_SHORT` | Any name-based confirm or clear. `NAME_TOO_SHORT` is the legal name of an individual with fewer than two real parts. Every name form in `names_all` also has `blocks_name_clear` and `real_part_count`; a later stage must not match on a form that blocks, even when the legal name itself is long enough. A placeholder-only name blocks. |
| `BLOCK_DOB_AGE_NAME_CLEAR` | `DOB_MISMATCH`, `TEMPORAL_IMPOSSIBILITY`, and `NAME_MISMATCH_VERIFIED`. Set when a note looks like a verification but did not fully parse (name, date of birth, and one document country). |
| `BLOCK_LOCATION_MISMATCH` | `LOCATION_MISMATCH`. Set when any non-noise note failed to parse, a note's places are not exactly one mapped country, a note is `NOTE_FLAGGED`, or a structured country is `UNMAPPED_COUNTRY`. Every mapped country found in a non-noise note is still stored. |
| `UNMAPPED_COUNTRY` | `LOCATION_MISMATCH`, as well. The raw normalised text is kept. |

`DOB_MISMATCH` is allowed only when every `declared_dobs` entry is comparable and contradicts the hit. One agreeing date, or any date that cannot be compared, blocks it. `contracts.dob_mismatch_only_if_every_declared_contradicts` is always true.

An LLM fact (`method: "llm"`) may support a confirmation or push the hit toward `REVIEW`. It must never be the sole ground for `DIFFERENT_ENTITY`.
