"""Per-hit trace for the reviewer UI. Not the official output file.

Shape (trace_schema 1), written only under the cache or TRACE_PATH:

- verdict: the official line
- deciding_dims: dimensions that decided the verdict
- comparison: one row per dimension (agree / contradict / unknown)
- identity.candidates: each Stage 3 candidate and the decision it would get
- steps: every rule, with llm_used true when an input fact has method llm
- llm_calls: model calls for this hit (empty on the default path)
- badges.fragility, badges.llm_used, badges.rules_version
"""

from __future__ import annotations

import json

from stage4.model import PRIORITY, RULES_VERSION, Decision


def hit_trace(
    hit: dict,
    alert: dict,
    resolution: dict | None,
    decision: Decision,
    candidates: list[dict] | None = None,
    person: dict | None = None,
) -> dict:
    cmp = decision.cmp
    return {
        "trace_schema": 1,
        "hit_id": hit.get("hit_id"),
        "alert_id": hit.get("alert_id") or alert.get("alert_id"),
        "verdict": {
            "decision": decision.decision,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "evidence": list(decision.evidence),
            "customer_record_id": decision.record,
        },
        "badges": {
            "fragility": decision.fragility,
            "llm_used": bool(decision.llm_used),
            "rules_version": RULES_VERSION,
        },
        "deciding_dims": _deciding(decision),
        "tipping_point": _tipping(decision),
        "comparison": _comparison(cmp) if cmp else [],
        "identity": {
            "person_id": decision.person_id,
            "merged": list((cmp and []) or []),
            "facts": _facts(cmp, person),
            "flags": [],
            "ignored_checks": [],
            "candidates": candidates or [],
        },
        "steps": _steps(decision),
        "llm_calls": [],
        "not_decided": bool(decision.not_decided or decision.errored),
    }


def _tipping(decision: Decision) -> str | None:
    if decision.errored or decision.not_decided or _exception_text(decision.missing):
        return "The hit could not be decided."
    if decision.decision == "DIFFERENT_ENTITY":
        return f"Without the {decision.reason_code} ground, this hit would be left for review."
    if decision.decision == "SAME_ENTITY":
        return "If the agreeing name or date were missing, this hit would be left for review."
    if decision.missing:
        text = " ".join(str(decision.missing).split()).strip().rstrip(".")
        if not text or _exception_text(text):
            return "The hit could not be decided."
        return f"The hit is left for review because {text}."
    return "The records do not settle this hit, so it is left for review."


def _exception_text(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    head = text.split(":", 1)[0].strip()
    return head.endswith("Error") or head.endswith("Exception")


def _deciding(decision: Decision) -> list[str]:
    if decision.decision == "DIFFERENT_ENTITY":
        mapping = {
            "ENTITY_TYPE_MISMATCH": "type",
            "DECEASED": "death",
            "TEMPORAL_IMPOSSIBILITY": "earliest_report",
            "DOB_MISMATCH": "dob",
            "NAME_MISMATCH_VERIFIED": "name",
            "LOCATION_MISMATCH": "country",
        }
        return [mapping[code] for code in decision.passed if code in mapping]
    if decision.reason_code == "NAME_DOB_LOCATION_MATCH":
        return ["name", "dob", "country"]
    if decision.reason_code == "NAME_DOB_MATCH":
        return ["name", "dob"]
    if decision.reason_code == "NAME_LOCATION_MATCH":
        return ["name", "country"]
    return []


def _comparison(cmp) -> list[dict]:
    rows = []
    for dim, label in (
        ("name", cmp.name),
        ("dob", cmp.dob),
        ("country", cmp.location),
        ("type", cmp.entity_type),
        ("death", cmp.death),
        ("earliest_report", cmp.time),
    ):
        row = {
            "dim": dim,
            "customer": label.customer,
            "hit": label.hit,
            "status": label.status.lower(),
            "src": list(label.sources),
            "llm_used": bool(label.llm_used),
        }
        if dim == "death":
            row["customer"] = None
            row["screening_date"] = label.detail.get("screening_date")
            if row["screening_date"]:
                row["note"] = f"Screening date {row['screening_date']}."
        elif dim == "dob" and label.detail.get("phrase"):
            row["note"] = label.detail.get("phrase")
        rows.append(row)
    return rows


def _facts(cmp, person: dict | None) -> dict:
    if cmp is None:
        return {}
    person = person or {}
    legal = person.get("legal_name") or {}
    name_source = legal.get("source_id")
    name_verified = bool(
        legal.get("verified") and legal.get("source_kind") == "kyc_check" and name_source
    )
    dob_raw = person.get("dob") or {}
    dob_source = dob_raw.get("source_id")
    dob_verified = bool(dob_raw.get("verified") and dob_source)
    return {
        "dob": {
            "value": dob_raw.get("value") or cmp.dob.customer,
            "verified": dob_verified,
            "source_id": dob_source,
            "source_kind": dob_raw.get("source_kind"),
        },
        "name": {
            "value": legal.get("value") or cmp.name.customer,
            "verified": name_verified,
            "source_id": name_source,
            "source_kind": legal.get("source_kind"),
        },
        "entity_type": {
            "value": cmp.entity_type.customer,
            "verified": False,
            "source_id": (person.get("entity_type") or {}).get("source_id"),
            "source_kind": (person.get("entity_type") or {}).get("source_kind"),
        },
    }


def _steps(decision: Decision) -> list[dict]:
    cmp = decision.cmp
    steps = []
    blocked = decision.blocked or {}
    for code in PRIORITY:
        if cmp is None:
            result = "not_fired"
            used = False
            why = "no comparison"
        elif code in decision.passed:
            result = "fired"
            used = bool(cmp.dim(code).llm_used)
            why = None
        elif code in blocked:
            result = "blocked"
            used = bool(cmp.dim(code).llm_used)
            why = ", ".join(blocked[code])
        elif cmp.contradiction(code):
            result = "fired"
            used = bool(cmp.dim(code).llm_used)
            why = None
        else:
            result = "not_fired"
            used = bool(cmp.dim(code).llm_used)
            why = _why_not(code, cmp)
        steps.append({"rule": code, "result": result, "llm_used": used, "why": why})
    steps.append({
        "rule": "CONFIRM",
        "result": "fired" if decision.decision == "SAME_ENTITY" else "not_fired",
        "llm_used": bool(decision.llm_used and decision.decision == "SAME_ENTITY"),
        "why": None if decision.decision == "SAME_ENTITY" else decision.missing or None,
    })
    return steps


def _why_not(code: str, cmp) -> str:
    if code == "DECEASED":
        return "no date of death before screening"
    if code == "DOB_MISMATCH":
        return f"date of birth is {cmp.dob.status.lower()}"
    if code == "LOCATION_MISMATCH":
        return f"location is {cmp.location.status.lower()}"
    if code == "NAME_MISMATCH_VERIFIED":
        return f"name is {cmp.name.status.lower()}"
    if code == "ENTITY_TYPE_MISMATCH":
        return f"type is {cmp.entity_type.status.lower()}"
    if code == "TEMPORAL_IMPOSSIBILITY":
        return "the dates do not make the listed activity impossible"
    return None


def dumps_trace(records: list[dict]) -> str:
    lines = []
    for record in records:
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")
