"""Alert roll-up. Trace only. Never changes the per-hit output.

CLEARED only when every hit is DIFFERENT_ENTITY.
ESCALATED when any hit is SAME_ENTITY, and that wins over NEEDS_REVIEW.
A missing or errored hit is HIT_NOT_DECIDED and its alert cannot clear.
"""

from __future__ import annotations


def roll_up(alerts: list[dict], decisions: dict[str, dict]) -> list[dict]:
    """``decisions`` maps hit_id to decision, reason_code, fragility, missing, not_decided, errored."""
    summaries = []
    ordered = sorted(alerts, key=lambda row: row.get("alert_id") or "")
    for alert in ordered:
        hit_ids = sorted({hit_id for hit_id in (alert.get("hit_ids") or []) if hit_id})
        hits = []
        for hit_id in hit_ids:
            row = decisions.get(hit_id)
            if row is None or row.get("not_decided") or row.get("errored"):
                hits.append({
                    "hit_id": hit_id,
                    "decision": None,
                    "reason_code": "HIT_NOT_DECIDED",
                    "fragility": None,
                    "missing": (row or {}).get("missing") or "hit not decided",
                    "undecided": "errored" if row and row.get("errored") else "missing",
                })
                continue
            item = {
                "hit_id": hit_id,
                "decision": row.get("decision"),
                "reason_code": row.get("reason_code"),
                "fragility": row.get("fragility"),
            }
            if row.get("decision") == "REVIEW" and row.get("missing"):
                item["missing"] = row["missing"]
            hits.append(item)
        undecided = [item["hit_id"] for item in hits if item.get("reason_code") == "HIT_NOT_DECIDED" or item.get("decision") is None]
        blocking = [item["hit_id"] for item in hits if item.get("decision") != "DIFFERENT_ENTITY"]
        if any(item.get("decision") == "SAME_ENTITY" for item in hits):
            status = "ESCALATED"
        elif hits and not blocking:
            status = "CLEARED"
        else:
            status = "NEEDS_REVIEW"
        summaries.append({
            "alert_id": alert.get("alert_id"),
            "alert_status": status,
            "hits": hits,
            "blocking_hit_ids": blocking,
            "undecided_hit_ids": undecided,
        })
    return summaries
