"""Run Stage 4: one decision per hit, then the alert roll-up in the trace."""

from __future__ import annotations

import json
import os
import time

from stage1.normalise import NameTools

from stage4.ambiguity import decide_hit
from stage4.clearance_log import dumps_summary, rows_for, summary as log_summary, write_csv
from stage4.evidence import customer_record_for_output
from stage4.load import load_stage4
from stage4.model import RULES_VERSION
from stage4.output import dumps_jsonl, line_from
from stage4.reasons import render
from stage4.rollup import roll_up
from stage4.trace import dumps_trace, hit_trace
from stage4.veto import apply_veto, enabled as veto_enabled

_COST = {
    "DIFFERENT_ENTITY": {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 3, "REVIEW": 3},
    "SAME_ENTITY": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 0, "REVIEW": 2},
    "REVIEW": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 2, "REVIEW": 0},
}


def run_stage4(data_folder: str, cache_dir: str, output_file: str, client=None) -> dict:
    """Write the official JSONL file and a trace under the cache (or TRACE_PATH)."""
    started = time.perf_counter()
    bundle = load_stage4(data_folder, cache_dir)
    tools = NameTools(bundle["variants"])
    known = bundle["known_ids"]
    prepared = []
    log_rows = []
    for hit in sorted(bundle["hits"], key=lambda row: row["hit_id"]):
        profile = _profile(hit, bundle["profiles"].get(hit["hit_id"]))
        alert = bundle["alerts_by_id"].get(hit["alert_id"]) or {
            "alert_id": hit.get("alert_id"),
            "customer": {},
            "hit_ids": [hit["hit_id"]],
        }
        resolution = bundle["resolutions"].get(hit.get("alert_id"))
        try:
            decision = decide_hit(profile, alert, resolution, bundle["persons"], tools)
        except Exception as error:
            decision = decide_hit(
                {"hit_id": hit["hit_id"], "alert_id": hit.get("alert_id"), "_missing_profile": True},
                alert,
                None,
                {},
                tools,
            )
            decision.errored = True
            decision.not_decided = True
            decision.missing = type(error).__name__
        _restrict(decision, known, hit, alert)
        prepared.append({
            "hit": hit,
            "profile": profile,
            "alert": alert,
            "resolution": resolution,
            "decision": decision,
            "hit_id": hit["hit_id"],
            "texts": _veto_texts(hit, bundle["persons"], resolution),
        })
    if veto_enabled():
        apply_veto(prepared, transport=None)
    elif client is not None and veto_enabled():
        apply_veto(prepared, transport=None)

    lines = []
    traces = []
    roll_decisions = {}
    for item in prepared:
        decision = item["decision"]
        hit = item["hit"]
        lines.append(line_from(
            hit["hit_id"],
            hit.get("alert_id"),
            decision.decision,
            decision.reason_code,
            decision.record,
            decision.reason,
            decision.evidence,
        ))
        traces.append(_trace(item, bundle["persons"]))
        roll_decisions[hit["hit_id"]] = {
            "decision": decision.decision,
            "reason_code": decision.reason_code,
            "fragility": decision.fragility,
            "missing": decision.missing,
            "not_decided": decision.not_decided,
            "errored": decision.errored,
        }
        log_rows.extend(rows_for(hit, item["resolution"], decision, decision.person_id))

    alerts = bundle["alerts"]
    summaries = roll_up(alerts, roll_decisions)
    for summary_row in summaries:
        traces.append(summary_row)

    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = dumps_jsonl(lines)
    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(payload)

    trace_path = os.environ.get("TRACE_PATH") or os.path.join(cache_dir, "trace.jsonl")
    trace_parent = os.path.dirname(trace_path)
    if trace_parent:
        os.makedirs(trace_parent, exist_ok=True)
    with open(trace_path, "w", encoding="utf-8") as handle:
        handle.write(dumps_trace(traces))

    practice = _practice(data_folder, lines)
    for row in log_rows:
        if practice and row["hit_id"] in practice["by_id"]:
            label = practice["by_id"][row["hit_id"]]
            row["label_decision"] = label["decision"]
            row["label_codes"] = ";".join(label["reason_codes"])
            row["unsafe"] = "1" if label["decision"] != "DIFFERENT_ENTITY" and row["final_decision"] == "DIFFERENT_ENTITY" else "0"
    write_csv(os.path.join(cache_dir, "clearance_log.csv"), log_rows)
    counts = log_summary(log_rows, lines, _practice_public(practice))
    with open(os.path.join(cache_dir, "clearance_summary.json"), "w", encoding="utf-8") as handle:
        handle.write(dumps_summary(counts))

    elapsed = round(time.perf_counter() - started, 3)
    return {
        "elapsed_seconds": elapsed,
        "hits": len(lines),
        "decisions": counts["decisions"],
        "review_rate": counts["review_rate"],
        "practice": _practice_public(practice),
        "rules_version": RULES_VERSION,
        "trace": trace_path,
        "llm_veto": veto_enabled(),
        "output_sha256": _sha256(payload.encode("utf-8")),
    }


def _profile(hit: dict, golden: dict | None) -> dict:
    if golden is None:
        return {
            "hit_id": hit["hit_id"],
            "alert_id": hit.get("alert_id"),
            "entity_type": hit.get("entity_type"),
            "_missing_profile": True,
            "names": [],
            "countries": [],
            "dob_candidates": [],
            "incorporation_dates": [],
            "deceased": {},
            "flags": [],
        }
    profile = dict(golden)
    profile["_profile_text"] = hit.get("profile_notes") or ""
    return profile


def _restrict(decision, known: set[str], hit: dict, alert: dict) -> None:
    decision.evidence = [item for item in decision.evidence if item in known]
    decision.record = customer_record_for_output(decision.record)
    if decision.record and decision.record != "AMBIGUOUS" and decision.record not in known:
        decision.record = None
    if decision.decision == "DIFFERENT_ENTITY" and not decision.evidence:
        decision.decision = "REVIEW"
        decision.reason_code = "INSUFFICIENT_DATA"
        decision.kind = "review_gate"
        decision.missing = "the deciding records could not be cited"
        decision.gate_note = "the deciding records could not be cited"
        decision.reason = render(decision, hit, {}, alert)


def _trace(item: dict, persons: dict) -> dict:
    decision = item["decision"]
    resolution = item["resolution"] or {}
    views = []
    for candidate in resolution.get("candidates") or []:
        person = persons.get(candidate.get("person_id")) or {}
        record = (candidate.get("matched_records") or [None])[0]
        if not record:
            continue
        countries = sorted({entry.get("value") for entry in (person.get("countries") or []) if entry.get("value")})
        alt = next((row for row in (decision.alternatives or []) if row.get("person_id") == candidate.get("person_id")), None)
        views.append({
            "customer_record_id": record,
            "person_id": candidate.get("person_id"),
            "name": (person.get("legal_name") or {}).get("value"),
            "dob": (person.get("dob") or {}).get("value"),
            "country": ", ".join(countries) or None,
            "why_fits": resolution.get("resolution_method"),
            "would_decide": {
                "decision": (alt or {}).get("decision") or decision.decision,
                "reason_code": (alt or {}).get("reason_code") or decision.reason_code,
            },
        })
    record = hit_trace(item["hit"], item["alert"], resolution, decision, views)
    person = persons.get(decision.person_id) or {}
    record["identity"]["merged"] = [
        {"rule": edge.get("rule") or "?", "records": list(edge.get("records") or [])}
        for edge in (person.get("cluster_edges") or [])
    ]
    record["identity"]["flags"] = list(person.get("flags") or [])
    record["identity"]["ignored_checks"] = [
        item.get("check_id") for item in (person.get("ignored_checks") or []) if item.get("check_id")
    ]
    return record


def _veto_texts(hit: dict, persons: dict, resolution: dict | None) -> dict:
    texts = {}
    if hit.get("profile_notes"):
        texts[hit["hit_id"]] = str(hit.get("profile_notes"))
    return texts


def _practice(data_folder: str, lines: list[dict]) -> dict | None:
    path = os.path.join(data_folder, "practice_labels.jsonl")
    if not os.path.isfile(path):
        return None
    labels = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                labels.append(_normalise_label(json.loads(line)))
    answers = {row["hit_id"]: row for row in lines}
    by_id = {row["hit_id"]: row for row in labels}
    right = 0
    unsafe = 0
    code_on_right = 0
    code_ok = 0
    record_on_right = 0
    cost = 0
    baseline = 0
    for label in labels:
        answer = answers.get(label["hit_id"], {})
        said = answer.get("decision", "REVIEW")
        cost += _COST[label["decision"]][said]
        baseline += _COST[label["decision"]]["REVIEW"]
        if said == "DIFFERENT_ENTITY" and label["decision"] != "DIFFERENT_ENTITY":
            unsafe += 1
        if answer.get("reason_code") in label["reason_codes"]:
            code_ok += 1
        if said == label["decision"]:
            right += 1
            if answer.get("reason_code") in label["reason_codes"]:
                code_on_right += 1
            record = answer.get("customer_record_id")
            if record in label["customer_record_ids"] or (
                label["customer_record_ids"] == ["AMBIGUOUS"] and record in (None, "", "AMBIGUOUS")
            ):
                record_on_right += 1
    return {
        "by_id": by_id,
        "labels": len(labels),
        "right": right,
        "unsafe": unsafe,
        "reason_codes": code_ok,
        "reason_codes_on_right": code_on_right,
        "records_on_right": record_on_right,
        "decision_score": round(100 * max(0.0, 1 - cost / baseline), 1) if baseline else 0,
    }


def _practice_public(practice: dict | None) -> dict | None:
    if not practice:
        return None
    return {key: practice[key] for key in (
        "labels", "right", "unsafe", "reason_codes", "reason_codes_on_right",
        "records_on_right", "decision_score",
    )}


def _normalise_label(row: dict) -> dict:
    codes = row.get("reason_codes")
    if isinstance(codes, str):
        codes = [part.strip() for part in codes.split(";") if part.strip()]
    records = row.get("customer_record_ids")
    if isinstance(records, str):
        records = [part.strip() for part in records.split(";") if part.strip()]
    row["reason_codes"] = list(codes or [])
    row["customer_record_ids"] = list(records or [])
    return row


def _sha256(payload: bytes) -> str:
    import hashlib
    return hashlib.sha256(payload).hexdigest()
