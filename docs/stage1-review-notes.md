# Stage 1 design review notes

**Date:** 21 Nov 2026
**Reviewed:** branch `docs/stage1-design`, commit `11323e5`: `README.md` and `docs/stage1-customer-golden-record.md` ("the doc" below; line numbers refer to that commit)
**Checked against:** `POLICY.md` principles P2–P9, `BRIEF.md`, and `validate.py`
**Review by:** Neha's team (Ideas Partner, informed by the Compliance & Security and Eval & Reproducibility reviews)

---

## Summary

This is a strong foundation. The merge rules, "verified beats declared", the country set and the day-first parsing of customer dates already follow the policy closely, and the fact-level `source_id` design makes good explanations easy later.

There's **one safety bug** to fix before building: the greedy name matcher (doc line 169) can miss a valid pairing of name parts, so two names that agree under P8 can look like they disagree. That would give a wrong `NAME_MISMATCH_VERIFIED`, which clears a true match and costs 60 points. The other notes below are mostly about writing down rules the next stages will rely on.

---

## Keep: what's already right

| What | Where in the doc | Policy |
|---|---|---|
| Merge only on phone plus the same full date of birth, or the same document number on approved checks, carried through chains (union-find). Never on a shared phone alone, a shared address, a surname, a joint account or a rejected or expired check. | lines 14, 239, 252–257; tests at 474–479 | P3 |
| Verification events combine approved KYC checks **and** verification notes. The latest approved event wins; ties go to KYC, then the smaller ID. | lines 320, 329–331 | P4 |
| Rejected and expired checks are kept for audit only, never as evidence. | lines 15, 387; tests at 481–482 | P4 |
| The country set covers residence and nationality on all records, document countries from **all** approved checks, and residence notes. City is excluded, and territories count as their own country. | lines 197–200, 384, 395 | P6 (location) |
| Customer slash dates are day-first, every date carries its precision, and anything unparsed is flagged, never guessed. | lines 171–185 | P6, P7 |
| Name normalisation (accents, brackets, initials, placeholders, legal forms, each part counted once) follows P8, and `name_variants.json` is a lookup table rather than hard-coded. | lines 156–169 | P8 |
| Every fact is stored as `{value, precision, source_id}`, merge edges are recorded, and output is sorted, so runs are byte-identical. | lines 23, 403–451 | P9, reproducibility |
| "Unknown stays unknown." Missing data pushes towards `REVIEW`. | line 16, README line 63 | P6/P7 default |

---

## Improvements, in priority order

| # | Change | Doc line | Policy | Risk if not fixed |
|---|---|---|---|---|
| 1 | **Replace the greedy name matcher with an exhaustive one.** Greedy longest-first matching can miss a valid one-to-one pairing, so names that agree look like they don't. Names have few parts, so an exhaustive search over pairings (with a fixed tie-break for the trace) is cheap. Apply written-together/apart joining on **both** sides and across variant groups. Add a test for dotted initials that collapse into a 2-letter part (e.g. an invented "J.R. Example" → `jr`, via the punctuation rule at line 158). | 158, 168–169 | P8 | **Unsafe clearance** (`NAME_MISMATCH_VERIFIED` on a true match) |
| 2 | **Never clear on an unverified name.** With no verification event, `legal_name` falls back to the record's full name with the `UNVERIFIED` flag. The matching stage must never give `NAME_MISMATCH_VERIFIED` when that flag is set. Please write this into the `legal_name` contract. | 335, 380, 458 | P4, P6 (name) | **Unsafe clearance** on a nickname or typo |
| 3 | **Flags block `LOCATION_MISMATCH`.** Service noise is "a closed set of fixed sentences, matched exactly", and unseen data is worded differently. Any `NOTE_FLAGGED:*` or `UNMAPPED_COUNTRY` on a person should block a location clear for that person, because the country set may be incomplete. | 290, 304, 463–464 | P6 (location: "places the notes say they lived") | **Unsafe clearance** when an unread note held a matching country |
| 4 | **Rule for declared birth dates that disagree.** Today the declared date of birth is used only when all records agree; otherwise `dob` is empty. Suggested rule for the matching stage: with no verified date of birth, give `DOB_MISMATCH` only when **every** entry in `declared_dobs` contradicts the hit. Any declared date that agrees, or can't be compared, blocks the clear. | 341, 381–382 | P4, P6 (date of birth) | Missed safe clears now; an unsafe clear if someone later "picks one" declared date |
| 5 | **Write the AMBIGUOUS contract for Stage 2.** If several persons fit an alert, decide the hit for each. If they all lead to the same decision, give it. Otherwise give `REVIEW` with `AMBIGUOUS_CUSTOMER_RECORD`. In both cases `customer_record_id` is `"AMBIGUOUS"` (write it explicitly, not `null`). With one person, output one of that person's `CUS-` record IDs, never the internal `P-…` ID. | 377, 507 | P3 | Wrong reason code and customer record (25% of each set's score); validator errors on `P-` IDs |
| 6 | **Hit-side dates are not day-first.** The day-first rule is right for customer data, but hit dates are "written as the provider wrote them". On the hit side, a slash date with both parts 12 or under should be UNKNOWN (and lead to `REVIEW`), not parsed day-first. Keep `parse_date` customer-only, or give it a mode argument. | 178 | P5 | A wrong `DOB_MISMATCH` clear on a swapped hit date |
| 7 | **Name-length rule scope.** P8 says "whose **names** have fewer than two real parts". `NAME_TOO_SHORT` is computed on `legal_name` only, so please state which names it checks (`names_all`, or legal name only) and why. | 163, 459 | P8 | Confirming or clearing on a placeholder-only name |
| 8 | **Evidence and trace.** Carry `source_id` through to the output, but cite only the records that **decided** the hit, not everything consulted. Log consulted IDs and deciding IDs separately in the trace. The hit's own fields can be cited as `H-XXXXXX#field` (`validate.py` lines 77–79 accept this, e.g. `#dob`). Add the rule fired and a rule/policy version to each trace line. | 23, 403–451 | P9; brief "Reasons" | Lower evidence precision; harder to explain to judges |
| 9 | **LLM safeguards if the fallback is ever switched on.** An LLM-filled verified name or date of birth could drive a clear. Require: the quote check (already at line 312), **3 agreeing calls**, a per-call timeout, bounded retries, a global time cap, and any failure → UNKNOWN (never a clear). Also note that the SHA-256 cache won't exist on the judges' machine, so it can't be relied on for reproducibility or speed. | 306–314 | P4; brief: 5 runs, under 30 min | Unsafe clear from a hallucinated fact; runs that differ or overrun |

---

## Beyond Stage 1: what Stage 2 and matching will need

The README marks Stage 2 as "Next" and hit profile + matching as "Planned" (README lines 55–56). From our plan, the parts the team will need:

- **Hit facts per P5, regex first.** The `dobs` field. Age sentences in the profile's **first paragraph** (an age at a date gives two possible birth years, computed in code). Dated reports only in the exact form "According to …; Month D, YYYY: …". Search results only when the hit has no date of birth elsewhere **and** the result uses the category's listing phrase **and** names a country tied to the hit. "International" and "Europe" are not countries. For companies, only `dobs` is an incorporation date.
- **Decision order.** Contradictions first (type, time/deceased, date of birth, location, verified name), then confirmations (P7), otherwise `REVIEW`. A country difference never clears a hit whose name and date of birth agree. Pick the reason code in a fixed order.
- **Evals and gates.** Zero unsafe clearances on practice labels (hard gate). The official cost-based score. Reason-code accuracy and evidence precision. Identical decision and reason code across 5 runs. A run with the LLM switched off that completes safely. A timed run under 30 minutes. About 15 practice labels held out from tuning. Small hand-made cases for rare codes (`ENTITY_TYPE_MISMATCH`, `DECEASED`, `AMBIGUOUS_CUSTOMER_RECORD`).
- **Trace and LLM log formats.**
  - Trace (one line per hit): `hit_id`, persons considered, merge edges, a list of facts `{side, attr, value, tier, source_id, method, quote}`, a list of comparisons `{attr, status: AGREE|CONTRADICT|UNKNOWN, deciding}`, `rule_fired`, rule and policy version, `consulted_ids`, `deciding_ids`.
  - LLM log (one line per call): `hit_id`, job, prompt hash, model, provider, quote, value, whether the quote check passed, votes, whether it changed the verdict, and any error.
  - Keep both out of the public `output/` folder and never put verbatim KYC or note text in them.
- **Safety report.** Before each submission, list every `DIFFERENT_ENTITY` with its deciding fact and source.
- **A simple static UI.** One `ui/index.html` (not part of `system/run`) that loads the output, traces and practice labels. Build it in this order: summary counts and cost score, then a filterable hits table with label mismatches and every clear highlighted, then a per-hit view of customer facts against hit facts, then the LLM log, then a 5-run diff.

---

## Things your plan does better (we're adopting these)

- **Declared date of birth for merging, verified date for comparing** (lines 259, 480), with the reason backed by the practice labels.
- **LLM off by default for customer notes,** with regex coverage measured on dev (lines 25, 308).
- **Document countries from all approved checks,** not only the latest one (line 395). It's the conservative choice.
- **Data observations** that justify the rules (lines 139–144, 261). For example, a newer non-approved check often sits on top of an older approved one, and many shared-phone groups are families.
- The `person_golden` schema and flag list (lines 403–464), the explicit letter map for letters NFKD doesn't decompose (line 156), flagging notes that contain negative wording (line 302), and the 28 edge-case tests (lines 472–501).

---

## Suggested next tests

Use synthetic fixtures only (invented names and IDs).

1. A name pair where greedy matching fails but an exhaustive pairing agrees → names agree, no clear.
2. A person with no verification event whose record name disagrees with the hit → no `NAME_MISMATCH_VERIFIED`.
3. A person with a flagged note and countries that all differ from the hit → no `LOCATION_MISMATCH`.
4. Unverified person, two declared dates of birth: one agrees with the hit, one contradicts → no `DOB_MISMATCH`. Both contradict → `DOB_MISMATCH` is allowed.
5. Two persons fit an alert with different decisions → `REVIEW` with `AMBIGUOUS_CUSTOMER_RECORD`, `customer_record_id: "AMBIGUOUS"`. Same decision for both → that decision with `"AMBIGUOUS"`.
6. A hit date `03/04/1980` against a customer born 4 March 1980 → UNKNOWN, not `DOB_MISMATCH`.
7. Dotted initials ("J.R.") and a placeholder-only name → handled per P8, never a name-based clear.
8. Output never contains a `P-` ID. Evidence lists only deciding IDs, and `H-XXXXXX#field` entries pass `validate.py`.
9. With the LLM forced to fail or time out → every hit still has one line, and nothing clears on a missing LLM fact.
