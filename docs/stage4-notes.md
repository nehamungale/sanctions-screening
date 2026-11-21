# Stage 4: Decision rules (notes)

> **Status: open.** Stage 4 is not designed yet. This file collects notes for whoever builds it, and anyone can add to it. Each section is one part of the design, not the whole thing.
>
> Part of the 4-stage architecture: **1** customer golden record · **2** hit golden profile · **3** alert → person resolution · **4** decision rules (this doc).

---

## 1. Alert roll-up

**Policy:** "An alert is cleared only when every hit in it is `DIFFERENT_ENTITY`."

The official output and the scoring are per hit, so nothing in the pipeline currently checks the alert-level result. Analysts work alerts, not hits, so we add a small deterministic step after the per-hit decisions. It writes an **alert summary into the trace only**. It never changes the official per-hit output.

### Alert status

| Status | When | What the summary lists |
|---|---|---|
| `CLEARED` | Every hit in the alert is `DIFFERENT_ENTITY` | Each hit with its reason code and fragility (a clear is only as strong as its weakest hit) |
| `ESCALATED` | At least one hit is `SAME_ENTITY` | The `SAME_ENTITY` hit(s); the alert goes to compliance |
| `NEEDS_REVIEW` | Otherwise (no `SAME_ENTITY`, at least one hit not `DIFFERENT_ENTITY`) | The **blocking hits**: each hit that stops the clear, with its code and what is missing |

`ESCALATED` takes priority over `NEEDS_REVIEW` when both apply.

### Completeness check

Before computing the status, compare the alert's `hit_ids` (from `alerts.jsonl`) with the hits we actually decided.

- A hit that is **missing** from our results, or **errored**, counts as a blocking hit with the reason `HIT_NOT_DECIDED`.
- An alert with any undecided hit can **never** be `CLEARED`. It is `NEEDS_REVIEW` (or `ESCALATED` if another hit is `SAME_ENTITY`).
- This stops a silent failure from looking like a clean alert.

### Trace shape (sketch)

```json
{
  "alert_id": "A-000001",
  "alert_status": "NEEDS_REVIEW",
  "hits": [
    {"hit_id": "H-000001", "decision": "DIFFERENT_ENTITY", "reason_code": "DOB_MISMATCH", "fragility": "solid"},
    {"hit_id": "H-000002", "decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA", "missing": "no birth date on hit"}
  ],
  "blocking_hit_ids": ["H-000002"],
  "undecided_hit_ids": []
}
```

Synthetic IDs only. Written to the trace file (gitignored), one record per alert, sorted by `alert_id`.

### Tests

- All hits `DIFFERENT_ENTITY` → `CLEARED`.
- One `SAME_ENTITY` and one `REVIEW` → `ESCALATED`, both listed.
- One `REVIEW` among clears → `NEEDS_REVIEW`, that hit blocking.
- One hit missing from the results → `NEEDS_REVIEW`, `undecided_hit_ids` set, never `CLEARED`.
- The roll-up is identical across reruns (sorted, no LLM).

### UI

The overview counts alerts as well as hits (cleared, escalated, needs review). The analyst queue groups `REVIEW` hits by alert and shows the blocking hits first.
