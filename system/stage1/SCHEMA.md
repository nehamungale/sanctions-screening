# Stage 1 artefacts

`system/run` writes these files under the cache directory (`working/` by default, or `SANCTIONS_CACHE`). JSON objects use sorted keys. JSONL rows are sorted by `record_id` or `person_id`. Lists of ids inside a row are sorted. The dev dataset is not part of this schema.

Person-level files: `person_golden.jsonl`, `index_record_id.json` (`record_id` → `person_id`), `index_account_id.json`, `index_login_handle.json`, and `index_email.json` (each key → a sorted list of `person_id`), `index_name.json` (`by_part` and `by_name_key` → sorted `person_id`s). The name index may include the verified legal name. Stage 3 name search must not use it for record-name matching.

`person_id` is `P-` plus the minimum `record_id` in the cluster. Decision output must use a `CUS-` id, not `person_id`.

## `record_view.jsonl`

One JSON object per customer `record_id`, sorted by `record_id`. Facts are this record only. The verified legal name is not on this row. Stage 3 matches `full_name`, `preferred_name`, and `login_name` separately.

| Field | Shape |
|---|---|
| `record_id` | `CUS-` id. |
| `person_id` | Cluster id. |
| `entity_type` | Always present. `{value, source_id}`. `value` is `Individual`, `Company`, or null. `source_id` is the `record_id`. |
| `full_name` | `{value, parts, real_part_count, source_id}`. `parts` is the normalised part list for `customers.full_name` only. `value` is null and `parts` is `[]` when the field is empty. |
| `preferred_name` | Same shape, for `customers.preferred_name` only. |
| `login_name` | Same shape, for `customers.login_name` only. |
| `dob` | `{value, precision, comparable, unparsed, role, source_kind, source_id}`. For an individual, `role` is `declared` and the value is `customers.dob` (`source_kind` `record`, `source_id` the `record_id`). For a company, `role` is `incorporation`: the latest approved registry-extract `verified_dob` (`source_kind` `registry_extract`, `source_id` the `check_id`) or, if there is none, `customers.dob`. `precision` is `day`, `month`, `year`, or null. `value` is `YYYY-MM-DD`, `YYYY-MM`, `YYYY`, or null. |
| `city` | `{raw, normalised, source_id}`. `raw` is the customer city text unchanged apart from trimming. `normalised` is `norm_text(raw)`. Both are null when the city is missing. City is not a country. |
| `address` | `{raw, normalised, source_id}`, same rules as `city`, for `customers.address`. |
| `postcode` | `{value, source_field, source_id}` or null. First present of `postcode`, `postal_code`, `zip`, `zip_code`. Dev customers have none, so this is null there. |
| `nationality` | `{value, unmapped, source_id}`. Canonical country for this record's nationality only, or null. Not merged with residence. |
| `residence_country` | `{value, unmapped, source_id}`. Canonical country for this record's residence only, or null. |
| `phone` | `{value, source_id}`. `norm_phone`, or null. |
| `email` | `{value, source_id}`. Trimmed and lowercased, or null. |
| `account_ids` | Sorted account ids whose `customer_id` is this record. |
| `login_handles` | Sorted login handles on those accounts. |
| `accounts` | Sorted `{account_id, login_handle, source_id}`. `source_id` is the account id. |

Name parts follow the shared normaliser: case, accents, brackets, punctuation (dots removed with no extra space, so `J.R.` is `jr`), initials, placeholders, and company legal forms. No variant expansion and no edit distance. `shared.names.agree_parts` agrees on equal part counts when either side is fully covered, so the result does not depend on argument order.

## `index_account_record_id.json`

Key: `account_id`. Value: sorted `record_id`s (`accounts.customer_id`). A joint account has more than one record. This is not `index_account_id.json`, which maps to `person_id`.

## `index_login_record_id.json`

Key: `login_handle`, trimmed. Value: sorted `record_id`s. This is not `index_login_handle.json`.

## `index_email_record_id.json`

Key: customer email, trimmed and lowercased. Value: sorted `record_id`s. This is not `index_email.json`, which maps to `person_id`.

## `index_name_part_record_id.json`

Key: one exact normalised part from `full_name.parts`, `preferred_name.parts`, or `login_name.parts`. Value: sorted `record_id`s that contain that part on any of those three names. Parts are not expanded through `name_variants.json` or edit distance. The verified legal name is not indexed. Variant and fuzzy matching is the consumer's job, using these keys.

A `kyc`-channel note with a negative or pending outcome (rejected, failed, expired, pending, declined, unable to verify, and the same family of phrases) is not a verification event. The person is flagged `BLOCK_DOB_AGE_NAME_CLEAR`.
