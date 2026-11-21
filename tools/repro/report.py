"""Compare repeated screening runs and build a deterministic ``repro.json``.

The judges' metric is the share of hits whose decision and reason code are
identical in every run. A stricter count also flags changes to evidence,
``customer_record_id``, or canonical trace facts. ``llm_calls`` and quote
text are ignored, so a different span for the same fact is not a flip.

Only ``meta.generated_at`` carries a timestamp. Hit rows have none.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
GENERATOR = "tools/repro"

DECISIONS = ("DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW")
# Safe tie-break when two decisions share the modal count.
DECISION_TIE = ("REVIEW", "SAME_ENTITY", "DIFFERENT_ENTITY")
# POLICY.md table order. Used only to break reason-code ties.
REASON_PRIORITY = (
    "TEMPORAL_IMPOSSIBILITY",
    "DOB_MISMATCH",
    "LOCATION_MISMATCH",
    "NAME_MISMATCH_VERIFIED",
    "ENTITY_TYPE_MISMATCH",
    "DECEASED",
    "NAME_DOB_LOCATION_MATCH",
    "NAME_DOB_MATCH",
    "NAME_LOCATION_MATCH",
    "INSUFFICIENT_DATA",
    "AMBIGUOUS_CUSTOMER_RECORD",
)
# Design-doc example order, then the remaining POLICY codes.
STEP_ORDER = (
    "ENTITY_TYPE_MISMATCH",
    "DECEASED",
    "TEMPORAL_IMPOSSIBILITY",
    "DOB_MISMATCH",
    "LOCATION_MISMATCH",
    "NAME_MISMATCH_VERIFIED",
    "NAME_DOB_LOCATION_MATCH",
    "NAME_DOB_MATCH",
    "NAME_LOCATION_MATCH",
    "INSUFFICIENT_DATA",
    "AMBIGUOUS_CUSTOMER_RECORD",
)
STEP_INDEX = {rule: index for index, rule in enumerate(STEP_ORDER)}
STEP_KEYS = ("rule", "result", "why")

CONFIG_FIELDS = (
    "git_sha",
    "rules_version",
    "policy_hash",
    "name_variants_hash",
    "prompt_hashes",
    "input_hash",
    "model",
    "provider",
    "python_version",
)
CONFIG_ALIASES = {
    "git_sha": ("git_sha", "sha", "commit", "git"),
    "rules_version": ("rules_version",),
    "policy_hash": ("policy_hash", "hashes.policy", "hashes.POLICY"),
    "name_variants_hash": ("name_variants_hash", "hashes.name_variants"),
    "prompt_hashes": ("prompt_hashes", "hashes.prompts", "hashes.prompt", "prompt_hash"),
    "input_hash": ("input_hash", "hashes.input", "hashes.input_folder"),
    "model": ("model",),
    "provider": ("provider", "served_provider", "provider_served"),
    "python_version": ("python_version", "python"),
}
HEADER_KINDS = {"run", "run_header", "header"}
HEADER_HINTS = {
    "run_id",
    "git_sha",
    "sha",
    "rules_version",
    "hashes",
    "model",
    "provider",
    "served_provider",
    "python_version",
    "input_hash",
    "policy_hash",
    "prompt_hashes",
}
FLIP_TYPES = ("none", "decision", "code", "evidence", "other")
FRAGILITY_SEVERITY = ("borderline", "thin", "solid")

_MISSING = object()


class ReproError(Exception):
    """A caller-facing problem with the inputs or a system run."""


def norm_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def norm_value(value):
    """NFKC strings and drop nothing here; callers strip quote keys first."""
    if isinstance(value, str):
        return norm_text(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, list):
        return [norm_value(item) for item in value]
    if isinstance(value, dict):
        return {key: norm_value(item) for key, item in sorted(value.items())}
    return norm_text(str(value))


def norm_source(source):
    if source is None:
        return None
    if isinstance(source, list):
        items = [norm_source(item) for item in source]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    if isinstance(source, str):
        return norm_text(source)
    return norm_value(source)


def as_evidence(value) -> list[str]:
    if not value:
        return []
    if not isinstance(value, list):
        value = [value]
    return sorted(norm_text(str(item)) for item in value)


def as_customer(value):
    if value is None:
        return None
    text = norm_text(str(value))
    return text or None


def as_decision(value):
    if value is None:
        return None
    text = norm_text(str(value))
    return text or None


def digest(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def mode(values: list, tie_break: tuple[str, ...]):
    present = [value for value in values if value is not None]
    if not present:
        return None
    counts: dict = {}
    for value in present:
        counts[value] = counts.get(value, 0) + 1
    best = max(counts.values())
    contenders = [value for value, count in counts.items() if count == best]
    if len(contenders) == 1:
        return contenders[0]
    rank = {value: index for index, value in enumerate(tie_break)}
    contenders.sort(key=lambda value: (rank.get(value, len(tie_break)), digest(value)))
    return contenders[0]


def load_jsonl(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReproError(f"file not found: {path}") from error
    rows: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReproError(f"{path}:{number}: not a JSON line ({error})") from error
        if not isinstance(row, dict):
            raise ReproError(f"{path}:{number}: expected a JSON object")
        rows.append(row)
    return rows


def _dig(row: dict, path: str):
    current = row
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def is_run_header(row: dict) -> bool:
    if row.get("hit_id"):
        return False
    kind = str(row.get("record_type") or row.get("kind") or row.get("record") or "").lower()
    if kind in HEADER_KINDS:
        return True
    return bool(set(row) & HEADER_HINTS)


def unwrap_sha(value):
    if isinstance(value, dict):
        for key in ("sha", "git_sha", "commit"):
            if value.get(key):
                return value[key]
    return value


def extract_config(header: dict | None) -> dict:
    extracted = {name: None for name in CONFIG_FIELDS}
    if not header:
        return extracted
    for name, aliases in CONFIG_ALIASES.items():
        for alias in aliases:
            found = _dig(header, alias)
            if found is _MISSING or found is None:
                continue
            if name == "git_sha":
                found = unwrap_sha(found)
            extracted[name] = norm_value(found)
            break
    return extracted


def identical_flag(values: list):
    if all(value is None for value in values):
        return None
    return all(value == values[0] for value in values)


def verdict_of(trace: dict | None) -> dict:
    if not trace:
        return {}
    verdict = trace.get("verdict")
    if isinstance(verdict, dict):
        return verdict
    return trace


def badges_of(trace: dict | None) -> tuple:
    if not trace or not isinstance(trace.get("badges"), dict):
        return None, None
    badges = trace["badges"]
    llm_used = badges.get("llm_used")
    if llm_used is not None and not isinstance(llm_used, bool):
        llm_used = bool(llm_used)
    fragility = badges.get("fragility")
    if fragility is not None:
        fragility = norm_text(str(fragility)) or None
    return llm_used, fragility


def pick_alert(output: dict | None, trace: dict | None):
    for source in (output, trace, verdict_of(trace) if trace else None):
        if not source:
            continue
        alert_id = source.get("alert_id")
        if alert_id:
            return norm_text(str(alert_id))
    return None


def verdicts_differ(output: dict, verdict: dict) -> bool:
    return (
        as_decision(output.get("decision")) != as_decision(verdict.get("decision"))
        or as_decision(output.get("reason_code")) != as_decision(verdict.get("reason_code"))
        or as_evidence(output.get("evidence")) != as_evidence(verdict.get("evidence"))
        or as_customer(output.get("customer_record_id")) != as_customer(verdict.get("customer_record_id"))
    )


@dataclass
class HitView:
    alert_id: str | None
    decision: str | None
    reason_code: str | None
    evidence: list[str]
    customer_record_id: str | None
    trace: dict | None
    llm_used: bool | None
    fragility: str | None
    output_trace_mismatch: bool


@dataclass
class Run:
    label: str
    header: dict | None
    hits: dict[str, HitView] = field(default_factory=dict)


def merge_hit(output: dict | None, trace: dict | None) -> HitView:
    verdict = verdict_of(trace)
    source = output if output is not None else verdict
    mismatch = bool(output and trace and verdicts_differ(output, verdict))
    llm_used, fragility = badges_of(trace)
    return HitView(
        alert_id=pick_alert(output, trace),
        decision=as_decision(source.get("decision")),
        reason_code=as_decision(source.get("reason_code")),
        evidence=as_evidence(source.get("evidence")),
        customer_record_id=as_customer(source.get("customer_record_id")),
        trace=trace,
        llm_used=llm_used,
        fragility=fragility,
        output_trace_mismatch=mismatch,
    )


def assemble_run(label: str, header: dict | None, outputs: dict[str, dict], traces: dict[str, dict]) -> Run:
    hits = {
        hit_id: merge_hit(outputs.get(hit_id), traces.get(hit_id))
        for hit_id in set(outputs) | set(traces)
    }
    return Run(label=label, header=header, hits=hits)


def parse_trace_rows(rows: list[dict], path: str) -> tuple[dict | None, dict[str, dict]]:
    header = None
    hits: dict[str, dict] = {}
    for row in rows:
        if is_run_header(row):
            if header is None:
                header = row
            continue
        hit_id = row.get("hit_id")
        if not isinstance(hit_id, str) or not hit_id.strip():
            raise ReproError(f"{path}: a trace line has no hit_id and is not a run header")
        hit_id = norm_text(hit_id)
        if hit_id in hits:
            raise ReproError(f"{path}: duplicate hit_id {hit_id}")
        hits[hit_id] = row
    return header, hits


def parse_output_rows(rows: list[dict], path: str) -> dict[str, dict]:
    hits: dict[str, dict] = {}
    for row in rows:
        hit_id = row.get("hit_id")
        if not isinstance(hit_id, str) or not hit_id.strip():
            raise ReproError(f"{path}: an output line has no hit_id")
        hit_id = norm_text(hit_id)
        if hit_id in hits:
            raise ReproError(f"{path}: duplicate hit_id {hit_id}")
        hits[hit_id] = row
    return hits


def labels_for(paths: list[Path] | None, count: int) -> list[str]:
    if not paths:
        return [f"run-{index + 1:02d}" for index in range(count)]
    names = [path.name for path in paths]
    if len(set(names)) == len(names):
        return names
    return [f"run-{index + 1:02d}" for index in range(count)]


def load_run_files(output_path: Path | None, trace_path: Path | None, label: str) -> Run:
    header = None
    outputs: dict[str, dict] = {}
    traces: dict[str, dict] = {}
    if trace_path is not None:
        header, traces = parse_trace_rows(load_jsonl(trace_path), str(trace_path))
    if output_path is not None:
        outputs = parse_output_rows(load_jsonl(output_path), str(output_path))
    return assemble_run(label, header, outputs, traces)


def canonical_steps(trace: dict | None) -> list[dict] | None:
    """Steps in the stable rule order, reduced to rule / result / why."""
    if trace is None:
        return None
    raw = trace.get("steps") or []
    if not isinstance(raw, list):
        return []
    ordered: list[tuple] = []
    seen: dict[str, int] = {}
    for step in raw:
        if not isinstance(step, dict):
            continue
        rule = norm_text(str(step.get("rule") or ""))
        occurrence = seen.get(rule, 0)
        seen[rule] = occurrence + 1
        reduced = {}
        for key in STEP_KEYS:
            if key not in step or step[key] is None:
                continue
            reduced[key] = norm_value(step[key])
        if "rule" not in reduced and rule:
            reduced["rule"] = rule
        group = STEP_INDEX.get(rule, len(STEP_ORDER))
        # Unknown rules sort by name after the policy rules. Occurrence keeps duplicates.
        ordered.append(((group, rule, occurrence), reduced))
    ordered.sort(key=lambda item: item[0])
    return [item[1] for item in ordered]


def _comparison_rows(trace: dict) -> list[dict]:
    raw = trace.get("comparison") or []
    if not isinstance(raw, list):
        return []
    rows = [row for row in raw if isinstance(row, dict)]
    rows.sort(key=lambda row: norm_text(str(row.get("dim") or row.get("attribute") or "")))
    return rows


def canonical_facts(trace: dict | None) -> dict | None:
    """Attribute, normalised value, and source id. Quotes and ``llm_calls`` are omitted."""
    if trace is None:
        return None
    facts: dict[str, dict] = {}
    identity = trace.get("identity") if isinstance(trace.get("identity"), dict) else {}
    raw_facts = identity.get("facts") if isinstance(identity.get("facts"), dict) else {}
    for attribute in sorted(raw_facts):
        item = raw_facts[attribute]
        if isinstance(item, dict):
            if "value" in item:
                value = item.get("value")
            elif "normalised" in item:
                value = item.get("normalised")
            else:
                value = item.get("normalized")
            source = item.get("source_id", item.get("source"))
        else:
            value, source = item, None
        facts[f"identity.{attribute}"] = {"source_id": norm_source(source), "value": norm_value(value)}
    seen: dict[str, int] = {}
    for row in _comparison_rows(trace):
        dim = norm_text(str(row.get("dim") or row.get("attribute") or "item"))
        seen[dim] = seen.get(dim, 0) + 1
        suffix = "" if seen[dim] == 1 else f"#{seen[dim]}"
        source = row.get("src") if "src" in row else row.get("source_id")
        source_id = norm_source(source)
        facts[f"comparison.{dim}{suffix}.customer"] = {
            "source_id": source_id,
            "value": norm_value(row.get("customer")),
        }
        facts[f"comparison.{dim}{suffix}.hit"] = {
            "source_id": source_id,
            "value": norm_value(row.get("hit")),
        }
    return facts


def _index_steps(steps: list[dict]) -> dict[tuple, dict]:
    counts: dict[str, int] = {}
    indexed: dict[tuple, dict] = {}
    for step in steps:
        rule = str(step.get("rule") or "")
        occurrence = counts.get(rule, 0)
        counts[rule] = occurrence + 1
        group = STEP_INDEX.get(rule, len(STEP_ORDER))
        indexed[(group, rule, occurrence)] = step
    return indexed


def first_divergent_step(per_run: list[list[dict] | None]) -> dict | None:
    indexed: list[dict[tuple, dict] | None] = []
    for steps in per_run:
        indexed.append(None if steps is None else _index_steps(steps))
    keys: set[tuple] = set()
    for mapping in indexed:
        if mapping:
            keys.update(mapping)
    for position, key in enumerate(sorted(keys)):
        comparable = []
        for mapping in indexed:
            if mapping is None:
                comparable.append(_MISSING)
            else:
                comparable.append(mapping.get(key))
        real = [value for value in comparable if value is not _MISSING]
        if len(real) >= 1 and any(value != real[0] for value in real):
            _group, rule, occurrence = key
            return {
                "occurrence": occurrence,
                "order_index": position,
                "rule": rule or None,
                "values_per_run": [None if value is _MISSING else value for value in comparable],
            }
    return None


def first_divergent_fact(per_run: list[dict | None]) -> dict | None:
    keys: set[str] = set()
    for facts in per_run:
        if facts:
            keys.update(facts)
    for attribute in sorted(keys):
        comparable = []
        for facts in per_run:
            if facts is None:
                comparable.append(_MISSING)
            else:
                comparable.append(facts.get(attribute))
        real = [value for value in comparable if value is not _MISSING]
        if len(real) >= 1 and any(value != real[0] for value in real):
            return {
                "attribute": attribute,
                "values_per_run": [None if value is _MISSING else value for value in comparable],
            }
    return None


def _maps_differ(values: list) -> bool:
    real = [value for value in values if value is not None]
    return len(real) >= 2 and any(value != real[0] for value in real[1:])


def _fragility(values: list[str | None]) -> tuple[str | None, bool]:
    present = [value for value in values if value]
    if not present:
        return None, False
    unique = set(present)
    if len(unique) == 1:
        return present[0], False
    for name in FRAGILITY_SEVERITY:
        if name in unique:
            return name, True
    return sorted(unique)[0], True


def _llm_used(values: list[bool | None]):
    if any(value is True for value in values):
        return True
    if any(value is False for value in values):
        return False
    return None


def _llm_bucket(llm_used) -> str:
    if llm_used is True:
        return "llm_used"
    if llm_used is False:
        return "not_llm_used"
    return "unknown"


def _classify(changes: dict) -> str:
    if changes["decision"]:
        return "decision"
    if changes["reason_code"]:
        return "code"
    if changes["evidence"] or changes["customer_record_id"]:
        return "evidence"
    if (
        changes["missing"]
        or changes["alert_id"]
        or changes["canonical_facts"]
        or changes["steps"]
        or changes["output_trace_mismatch"]
    ):
        return "other"
    return "none"


def _hit_row(hit_id: str, runs: list[Run]) -> dict:
    views = [run.hits.get(hit_id) for run in runs]
    present = [view for view in views if view is not None]
    decisions = [view.decision for view in present]
    codes = [view.reason_code for view in present]
    evidence = [view.evidence for view in present]
    customers = [view.customer_record_id for view in present]
    alerts = [view.alert_id for view in present if view.alert_id]
    decision_change = len(set(decisions)) > 1
    code_change = len(set(codes)) > 1
    evidence_change = len({tuple(item) for item in evidence}) > 1
    customer_change = len(set(customers)) > 1
    alert_conflict = len(set(alerts)) > 1
    missing = any(view is None for view in views)
    mismatch = any(view.output_trace_mismatch for view in present)
    step_lists = [canonical_steps(view.trace) if view else None for view in views]
    fact_maps = [canonical_facts(view.trace) if view else None for view in views]
    # A missing hit has no trace. Don't treat that as a fact/step change.
    steps_change = _maps_differ([steps if view is not None else None for steps, view in zip(step_lists, views)])
    facts_change = _maps_differ(fact_maps)
    changes = {
        "alert_id": alert_conflict,
        "canonical_facts": facts_change,
        "customer_record_id": customer_change,
        "decision": decision_change,
        "evidence": evidence_change,
        "missing": missing,
        "output_trace_mismatch": mismatch,
        "reason_code": code_change,
        "steps": steps_change,
    }
    flip_type = _classify(changes)
    judges_stable = not missing and not decision_change and not code_change
    divergent_step = None
    divergent_fact = None
    if flip_type != "none":
        if steps_change:
            divergent_step = first_divergent_step(step_lists)
        if facts_change:
            divergent_fact = first_divergent_fact(fact_maps)
    llm_per_run = [None if view is None else view.llm_used for view in views]
    fragility, fragility_conflict = _fragility([None if view is None else view.fragility for view in views])
    modal_decision = mode(decisions, DECISION_TIE)
    modal_codes = [view.reason_code for view in present if view.decision == modal_decision]
    return {
        "alert_id": mode(alerts, ()) if alerts else None,
        "alert_id_conflict": alert_conflict,
        "changes": changes,
        "customer_record_id_per_run": [None if view is None else view.customer_record_id for view in views],
        "evidence_per_run": [None if view is None else view.evidence for view in views],
        "first_divergent_fact": divergent_fact,
        "first_divergent_step": divergent_step,
        "flip_type": flip_type,
        "fragility": fragility,
        "fragility_conflict": fragility_conflict,
        "hit_id": hit_id,
        "judges_stable": judges_stable,
        "llm_used": _llm_used(llm_per_run),
        "llm_used_per_run": llm_per_run,
        "missing_from_runs": [index for index, view in enumerate(views) if view is None],
        "modal_decision": modal_decision,
        "modal_reason_code": mode(modal_codes, REASON_PRIORITY),
        "output_trace_mismatch_runs": [
            index for index, view in enumerate(views) if view is not None and view.output_trace_mismatch
        ],
        "per_run": [
            None if view is None else [view.decision, view.reason_code]
            for view in views
        ],
        "stable": flip_type == "none",
        "trace_present_per_run": [view is not None and view.trace is not None for view in views],
    }


def _decision_counts(run: Run) -> dict:
    counts = {decision: 0 for decision in DECISIONS}
    for view in run.hits.values():
        key = view.decision if view.decision in counts else view.decision or "MISSING_DECISION"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _empty_flip_buckets() -> dict:
    return {
        "llm_used": {"code": 0, "decision": 0, "evidence": 0, "other": 0},
        "not_llm_used": {"code": 0, "decision": 0, "evidence": 0, "other": 0},
        "unknown": {"code": 0, "decision": 0, "evidence": 0, "other": 0},
    }


def _config_check(runs: list[Run], traces_provided: bool) -> dict:
    flags = {name: None for name in CONFIG_FIELDS}
    if not traces_provided:
        return {"all_identical": flags, "available": False, "runs": None}
    extracted = [extract_config(run.header) for run in runs]
    for name in CONFIG_FIELDS:
        flags[name] = identical_flag([row[name] for row in extracted])
    listed = []
    for index, (run, row) in enumerate(zip(runs, extracted)):
        listed.append({"run_index": index, "run_label": run.label, **row})
    return {"all_identical": flags, "available": True, "runs": listed}


def _sensitivity(hits: list[dict], llm_off: Run | None) -> dict | None:
    if llm_off is None:
        return None
    rows = []
    known = {hit["hit_id"] for hit in hits}
    for hit in hits:
        off = llm_off.hits.get(hit["hit_id"])
        off_decision = None if off is None else off.decision
        off_code = None if off is None else off.reason_code
        differs = off is None or off_decision != hit["modal_decision"] or off_code != hit["modal_reason_code"]
        if not differs:
            continue
        rows.append(
            {
                "alert_id": hit["alert_id"] if off is None else (off.alert_id or hit["alert_id"]),
                "hit_id": hit["hit_id"],
                "llm_off_decision": off_decision,
                "llm_off_reason_code": off_code,
                "llm_on_modal_decision": hit["modal_decision"],
                "llm_on_modal_reason_code": hit["modal_reason_code"],
            }
        )
    for hit_id in sorted(set(llm_off.hits) - known):
        off = llm_off.hits[hit_id]
        rows.append(
            {
                "alert_id": off.alert_id,
                "hit_id": hit_id,
                "llm_off_decision": off.decision,
                "llm_off_reason_code": off.reason_code,
                "llm_on_modal_decision": None,
                "llm_on_modal_reason_code": None,
            }
        )
    rows.sort(key=lambda row: row["hit_id"])
    return {
        "compared": True,
        "hit_ids": [row["hit_id"] for row in rows],
        "hits": rows,
        "n_sensitive": len(rows),
    }


def _filters(hits: list[dict], sensitive_ids: list[str]) -> dict:
    def ids(predicate):
        return [hit["hit_id"] for hit in hits if predicate(hit)]

    return {
        "code_flip": ids(lambda hit: hit["flip_type"] == "code"),
        "decision_flip": ids(lambda hit: hit["flip_type"] == "decision"),
        "evidence_flip": ids(lambda hit: hit["flip_type"] == "evidence"),
        "flipped_only": ids(lambda hit: hit["flip_type"] != "none"),
        "llm_sensitive": list(sensitive_ids),
        "missing": ids(lambda hit: hit["changes"]["missing"]),
        "thin_clearances": ids(
            lambda hit: hit["modal_decision"] == "DIFFERENT_ENTITY" and hit["fragility"] == "thin"
        ),
        "thin_or_borderline_and_llm": ids(
            lambda hit: hit["llm_used"] is True and hit["fragility"] in {"thin", "borderline"}
        ),
    }


def _judges_flips_all_llm(hits: list[dict]):
    judged = [hit for hit in hits if hit["changes"]["decision"] or (hit["changes"]["reason_code"] and not hit["changes"]["decision"])]
    if not judged:
        return None
    if any(hit["llm_used"] is None for hit in judged):
        return None
    return all(hit["llm_used"] is True for hit in judged)


def build_report(runs: list[Run], llm_off: Run | None, generated_at: str, sources: dict) -> dict:
    if len(runs) < 2:
        raise ReproError(f"need at least 2 runs, got {len(runs)}")
    hit_ids = sorted({hit_id for run in runs for hit_id in run.hits})
    hits = [_hit_row(hit_id, runs) for hit_id in hit_ids]
    strict_ids = [
        hit["hit_id"]
        for hit in hits
        if hit["changes"]["evidence"]
        or hit["changes"]["customer_record_id"]
        or hit["changes"]["canonical_facts"]
        or hit["changes"]["steps"]
    ]
    missing_ids = [hit["hit_id"] for hit in hits if hit["changes"]["missing"]]
    judges_stable_hits = sum(1 for hit in hits if hit["judges_stable"])
    n_hits = len(hits)
    buckets = _empty_flip_buckets()
    for hit in hits:
        if hit["flip_type"] == "none":
            continue
        buckets[_llm_bucket(hit["llm_used"])][hit["flip_type"]] += 1
    sensitivity = _sensitivity(hits, llm_off)
    sensitive_ids = [] if sensitivity is None else sensitivity["hit_ids"]
    traces_provided = bool(sources.get("traces"))
    return {
        "config_check": _config_check(runs, traces_provided),
        "heatmap": {
            "decisions": [
                [None if pair is None else pair[0] for pair in hit["per_run"]]
                for hit in hits
            ],
            "hit_ids": hit_ids,
            "reason_codes": [
                [None if pair is None else pair[1] for pair in hit["per_run"]]
                for hit in hits
            ],
            "run_labels": [run.label for run in runs],
        },
        "hits": hits,
        "llm_sensitivity": sensitivity,
        "meta": {
            "generated_at": generated_at,
            "generator": GENERATOR,
            "run_labels": [run.label for run in runs],
            "sources": {
                "llm_off_output": bool(sources.get("llm_off_output")),
                "outputs": bool(sources.get("outputs")),
                "traces": traces_provided,
            },
        },
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "code_only_flip_hits": sum(
                1 for hit in hits if hit["changes"]["reason_code"] and not hit["changes"]["decision"]
            ),
            "decision_counts_per_run": [_decision_counts(run) for run in runs],
            "decision_flip_hits": sum(1 for hit in hits if hit["changes"]["decision"]),
            "flips_by_llm_used": buckets,
            "hits_missing_from_some_runs": missing_ids,
            "judges_flip_hits": sum(
                1
                for hit in hits
                if hit["changes"]["decision"] or (hit["changes"]["reason_code"] and not hit["changes"]["decision"])
            ),
            "judges_flips_all_llm_used": _judges_flips_all_llm(hits),
            "judges_metric": None if n_hits == 0 else round(judges_stable_hits / n_hits, 10),
            "judges_stable_hits": judges_stable_hits,
            "missing_hits": len(missing_ids),
            "n_hits": n_hits,
            "n_runs": len(runs),
            "strict_change_hit_ids": strict_ids,
            "strict_change_hits": len(strict_ids),
        },
        "ui": {
            "decision_legend": {
                "DIFFERENT_ENTITY": "clear",
                "MISSING": "missing",
                "REVIEW": "review",
                "SAME_ENTITY": "match",
            },
            "filters": _filters(hits, sensitive_ids),
            "flip_types": list(FLIP_TYPES),
            "run_strip": {"n_runs": len(runs), "run_labels": [run.label for run in runs]},
        },
    }


def stamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dump_report(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_report(report), encoding="utf-8")


def report_from_files(
    output_paths: list[Path] | None,
    trace_paths: list[Path] | None,
    llm_off_output: Path | None,
    generated_at: str,
) -> dict:
    outputs = list(output_paths or [])
    traces = list(trace_paths or [])
    if outputs and traces and len(outputs) != len(traces):
        raise ReproError(
            f"got {len(outputs)} output files and {len(traces)} trace files; pass the same number of each"
        )
    count = len(outputs or traces)
    if count < 2:
        raise ReproError(f"need at least 2 runs, got {count}")
    label_source = outputs or traces
    labels = labels_for(label_source, count)
    runs = []
    for index in range(count):
        output_path = outputs[index] if outputs else None
        trace_path = traces[index] if traces else None
        runs.append(load_run_files(output_path, trace_path, labels[index]))
    llm_off = None
    if llm_off_output is not None:
        llm_off = load_run_files(llm_off_output, None, "llm-off")
    return build_report(
        runs,
        llm_off,
        generated_at,
        {"outputs": bool(outputs), "traces": bool(traces), "llm_off_output": llm_off_output is not None},
    )


def default_system_run() -> Path:
    return Path(__file__).resolve().parents[2] / "system" / "run"


def _command(system_run: Path, data: str, output: Path) -> list[str]:
    if os.access(system_run, os.X_OK):
        return [str(system_run), data, str(output)]
    return [sys.executable, str(system_run), data, str(output)]


def _invoke(system_run: Path, data: str, output: Path, env: dict) -> None:
    completed = subprocess.run(
        _command(system_run, data, output),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ReproError(f"system/run exited {completed.returncode} for {output.name}: {detail}")


def run_and_report(
    data: str,
    n_runs: int,
    work_dir: Path,
    system_run: Path,
    capture_traces: bool,
    llm_off: bool,
    generated_at: str,
) -> dict:
    if n_runs < 2:
        raise ReproError(f"need at least 2 runs, got {n_runs}")
    if not system_run.is_file():
        raise ReproError(f"system/run not found at {system_run}")
    work_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    trace_paths: list[Path] = []
    for index in range(n_runs):
        run_dir = work_dir / f"run-{index + 1:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        output_path = run_dir / "output.jsonl"
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        if capture_traces:
            trace_path = run_dir / "trace.jsonl"
            env["TRACE_PATH"] = str(trace_path.resolve())
            trace_paths.append(trace_path)
        else:
            env.pop("TRACE_PATH", None)
        _invoke(system_run, data, output_path, env)
        output_paths.append(output_path)
    llm_off_path = None
    if llm_off:
        off_dir = work_dir / "llm-off"
        off_dir.mkdir(parents=True, exist_ok=True)
        llm_off_path = off_dir / "output.jsonl"
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        env["USE_LLM_NOTES"] = "0"
        env["SANCTIONS_LLM"] = "0"
        env.pop("TRACE_PATH", None)
        _invoke(system_run, data, llm_off_path, env)
    return report_from_files(
        output_paths,
        trace_paths if capture_traces else None,
        llm_off_path,
        generated_at,
    )
