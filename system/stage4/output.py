"""Official output lines. Fixed key order, sorted by hit_id, no run metadata."""

from __future__ import annotations

import json

from stage4.model import OUTPUT_KEYS


def line_from(hit_id: str, alert_id: str, decision: str, reason_code: str, record, reason: str, evidence: list) -> dict:
    return {
        "hit_id": hit_id,
        "alert_id": alert_id,
        "decision": decision,
        "reason_code": reason_code,
        "customer_record_id": record,
        "reason": reason,
        "evidence": list(evidence),
    }


def dumps_line(row: dict) -> str:
    ordered = {key: row.get(key) for key in OUTPUT_KEYS}
    return json.dumps(ordered, ensure_ascii=False, separators=(", ", ": "))


def dumps_jsonl(rows: list[dict]) -> str:
    ordered = sorted(rows, key=lambda row: row.get("hit_id") or "")
    body = "".join(dumps_line(row) + "\n" for row in ordered)
    return body
