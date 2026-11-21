"""Local tuning log. Counts only belong in the summary; the CSV stays in the cache."""

from __future__ import annotations

import csv
import json
from collections import Counter


COLUMNS = (
    "hit_id", "alert_id", "person_id", "resolution_status", "resolution_method",
    "resolution_clean", "code", "is_primary", "final_decision", "final_code",
    "gate_passed", "gate_flags", "sole_blocker", "frag_note_only_country",
    "frag_sentence_dob", "frag_search_result_dob", "frag_fuzzy_name",
    "frag_partial_date_edge", "frag_single_source", "fragility", "llm_used",
    "veto", "evidence_n", "label_decision", "label_codes", "unsafe",
)


def rows_for(hit: dict, resolution: dict | None, decision, person_id: str | None) -> list[dict]:
    if decision.cmp is None or not decision.fired:
        return []
    out = []
    for code in decision.fired:
        flags = decision.blocked.get(code) or []
        passed = code in (decision.passed or [])
        dim = decision.cmp.dim(code)
        out.append({
            "hit_id": hit.get("hit_id"),
            "alert_id": hit.get("alert_id"),
            "person_id": person_id or "",
            "resolution_status": (resolution or {}).get("resolution_status") or "",
            "resolution_method": (resolution or {}).get("resolution_method") or "",
            "resolution_clean": "1" if (resolution or {}).get("resolution_clean") else "0",
            "code": code,
            "is_primary": "1" if decision.reason_code == code else "0",
            "final_decision": decision.decision,
            "final_code": decision.reason_code,
            "gate_passed": "1" if passed else "0",
            "gate_flags": ";".join(flags),
            "sole_blocker": flags[0] if len(flags) == 1 else "",
            "frag_note_only_country": "1" if decision.cmp.location.detail.get("note_only") else "0",
            "frag_sentence_dob": "1" if any((c.get("source") == "profile_note") for c in (decision.cmp.dob.detail.get("candidates") or [])) else "0",
            "frag_search_result_dob": "1" if any((c.get("source") == "search_result") for c in (decision.cmp.dob.detail.get("candidates") or [])) else "0",
            "frag_fuzzy_name": "1" if decision.cmp.name.detail.get("fuzzy") else "0",
            "frag_partial_date_edge": "1" if decision.fragility == "borderline" and code == "DOB_MISMATCH" else "0",
            "frag_single_source": "1" if len(set(dim.sources)) <= 1 else "0",
            "fragility": decision.fragility,
            "llm_used": "1" if dim.llm_used else "0",
            "veto": "none",
            "evidence_n": str(len(decision.evidence or [])),
            "label_decision": "",
            "label_codes": "",
            "unsafe": "",
        })
    return out


def write_csv(path: str, rows: list[dict]) -> None:
    ordered = sorted(rows, key=lambda row: (row.get("hit_id") or "", row.get("person_id") or "", row.get("code") or ""))
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in ordered:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


def summary(rows: list[dict], decisions: list[dict], practice: dict | None) -> dict:
    by_code: dict[str, dict] = {}
    for row in rows:
        slot = by_code.setdefault(row["code"], {
            "fired": 0, "passed": 0, "primary": 0, "blocked_by": Counter(), "sole_blocked_by": Counter(),
        })
        slot["fired"] += 1
        if row["gate_passed"] == "1":
            slot["passed"] += 1
        if row["is_primary"] == "1":
            slot["primary"] += 1
        for flag in filter(None, (row.get("gate_flags") or "").split(";")):
            slot["blocked_by"][flag] += 1
        if row.get("sole_blocker"):
            slot["sole_blocked_by"][row["sole_blocker"]] += 1
    codes = {}
    for code in sorted(by_code):
        slot = by_code[code]
        codes[code] = {
            "fired": slot["fired"],
            "passed": slot["passed"],
            "primary": slot["primary"],
            "blocked_by": dict(sorted(slot["blocked_by"].items())),
            "sole_blocked_by": dict(sorted(slot["sole_blocked_by"].items())),
        }
    counts = Counter(row.get("decision") for row in decisions)
    payload = {
        "by_code": codes,
        "decisions": {key: counts[key] for key in ("DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW")},
        "hits": len(decisions),
        "review_rate": round(counts["REVIEW"] / len(decisions), 4) if decisions else 0,
    }
    if practice:
        payload["practice"] = practice
    return payload


def dumps_summary(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
