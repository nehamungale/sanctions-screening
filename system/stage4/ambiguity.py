"""Choose the customer, then one decision per hit."""

from __future__ import annotations

from stage1.normalise import NameTools

from stage4.compare import compare, type_contradicts
from stage4.evidence import collect, customer_record_for_output
from stage4.model import PRIORITY, Decision
from stage4.reasons import render
from stage4.rules import decide_for_person


def decide_hit(
    hit: dict,
    alert: dict | None,
    resolution: dict | None,
    persons: dict[str, dict],
    tools: NameTools,
    disabled: frozenset[str] | None = None,
) -> Decision:
    alert = alert or {"alert_id": hit.get("alert_id"), "customer": {}, "hit_ids": [hit.get("hit_id")]}
    if resolution is None or hit.get("_missing_profile"):
        return _undecided(hit, alert, "not_decided")
    status = resolution.get("resolution_status")
    if status == "not_found":
        return _not_found(hit, alert, resolution)
    candidates = sorted(resolution.get("candidates") or [], key=lambda row: row.get("person_id") or "")
    if not candidates:
        return _undecided(hit, alert, "not_decided")
    if status == "resolved_single":
        candidate = candidates[0]
        person = persons.get(candidate.get("person_id"))
        if person is None:
            return _undecided(hit, alert, "not_decided")
        cmp = compare(hit, alert, person, tools)
        decision = decide_for_person(hit, alert, person, resolution, cmp, candidate, disabled)
        record = customer_record_for_output(resolution.get("customer_record_id"))
        decision.finish(record)
        decision.evidence = collect(decision, hit, person, alert)
        decision.reason = render(decision, hit, person, alert)
        decision.alternatives = [_alternative(candidate, decision)]
        return decision

    per: list[Decision] = []
    for candidate in candidates:
        person = persons.get(candidate.get("person_id"))
        if person is None:
            return _undecided(hit, alert, "not_decided")
        cmp = compare(hit, alert, person, tools)
        per.append(decide_for_person(hit, alert, person, resolution, cmp, candidate, disabled))
    decisions = {item.decision for item in per}
    if len(decisions) == 1:
        return _combine(per, candidates, hit, alert, persons)
    return _split(per, candidates, hit, alert)


def _not_found(hit: dict, alert: dict, resolution: dict) -> Decision:
    screened = ((alert.get("customer") or {}).get("entity_type"))
    if type_contradicts(screened, hit.get("entity_type")):
        decision = Decision(
            decision="DIFFERENT_ENTITY",
            reason_code="ENTITY_TYPE_MISMATCH",
            kind="not_found_clear",
            passed=["ENTITY_TYPE_MISMATCH"],
            record=None,
            fragility="solid",
        )
    else:
        decision = Decision(
            decision="REVIEW",
            reason_code="INSUFFICIENT_DATA",
            kind="not_found_review",
            record=None,
            missing="no customer record fits the alert",
            fragility="thin",
        )
    decision.evidence = collect(decision, hit, {}, alert)
    decision.reason = render(decision, hit, {}, alert)
    return decision


def _undecided(hit: dict, alert: dict, kind: str) -> Decision:
    decision = Decision(
        decision="REVIEW",
        reason_code="INSUFFICIENT_DATA",
        kind=kind,
        not_decided=True,
        missing="the hit was not decided",
        fragility="thin",
    )
    decision.evidence = collect(decision, hit, {}, alert)
    decision.reason = render(decision, hit, {}, alert)
    return decision


def _combine(per: list[Decision], candidates: list[dict], hit: dict, alert: dict, persons: dict) -> Decision:
    shared = per[0].decision
    record_ids = _matched(candidates)
    evidence = list(record_ids)
    for item in per:
        evidence.extend(item.evidence or collect(item, hit, persons.get(item.person_id) or {}, alert))
    if shared == "DIFFERENT_ENTITY":
        code = _shared_clear_code(per)
        decision = Decision(
            decision="DIFFERENT_ENTITY",
            reason_code=code,
            passed=[code],
            cmp=per[0].cmp,
            kind="clear",
            record="AMBIGUOUS",
            fragility=per[0].fragility,
            fired=per[0].fired,
        )
    elif shared == "SAME_ENTITY":
        codes = {item.reason_code for item in per}
        if len(codes) == 1:
            code = per[0].reason_code
        elif (per[0].cmp.person_type if per[0].cmp else "") == "Company":
            code = "NAME_LOCATION_MATCH"
        else:
            code = "NAME_DOB_MATCH"
        decision = Decision(
            decision="SAME_ENTITY",
            reason_code=code,
            passed=[code],
            cmp=per[0].cmp,
            kind="confirm",
            record="AMBIGUOUS",
            fragility=per[0].fragility,
        )
    else:
        missing = per[0].missing or "the records do not settle the hit"
        ids = ", ".join(record_ids)
        decision = Decision(
            decision="REVIEW",
            reason_code="INSUFFICIENT_DATA",
            kind="ambiguous_review",
            record="AMBIGUOUS",
            cmp=per[0].cmp,
            missing=missing,
            gate_note=(
                f"{len(candidates)} different customers fit this alert ({ids}). "
                f"For each of them {missing}"
            ),
            fragility="thin",
        )
    decision.evidence = collect(decision, hit, persons.get(per[0].person_id) or {}, alert, extra=_unique(evidence))
    if decision.kind == "ambiguous_review":
        decision.reason = render(decision, hit, {}, alert)
    else:
        # Describe the first candidate's facts; the evidence lists every candidate.
        person = persons.get(per[0].person_id) or {}
        decision.reason = render(decision, hit, person, alert)
        if decision.decision == "DIFFERENT_ENTITY":
            decision.reason = _ensure_two(decision.reason, "The same contradiction holds for every customer that fits this alert.")
    decision.matched_records = record_ids
    decision.alternatives = [_alternative(candidate, item) for candidate, item in zip(candidates, per)]
    return decision


def _split(per: list[Decision], candidates: list[dict], hit: dict, alert: dict) -> Decision:
    record_ids = _matched(candidates)
    ids = ", ".join(record_ids)
    phrases = []
    evidence = list(record_ids)
    for item, candidate in zip(per, candidates):
        label = _words(item.decision)
        holder = ", ".join(candidate.get("matched_records") or [])
        phrases.append(f"{label} for {holder}")
        evidence.extend(collect(item, hit, {}, alert))
    note = (
        f"{len(candidates)} different customers fit this alert ({ids}). "
        f"The hit would be {' but '.join(phrases)}, so it is left for review"
    )
    decision = Decision(
        decision="REVIEW",
        reason_code="AMBIGUOUS_CUSTOMER_RECORD",
        kind="ambiguous_split",
        record="AMBIGUOUS",
        gate_note=note,
        missing="the customers do not agree",
        fragility="thin",
        cmp=per[0].cmp,
    )
    decision.evidence = collect(decision, hit, {}, alert, extra=_unique(evidence))
    decision.reason = render(decision, hit, {}, alert)
    decision.alternatives = [_alternative(candidate, item) for candidate, item in zip(candidates, per)]
    return decision


def _shared_clear_code(per: list[Decision]) -> str:
    sets = [set(item.passed) for item in per]
    shared = set.intersection(*sets) if sets else set()
    for code in PRIORITY:
        if code in shared:
            return code
    primaries = [item.reason_code for item in per]
    for code in PRIORITY:
        if code in primaries:
            return code
    return per[0].reason_code


def _matched(candidates: list[dict]) -> list[str]:
    found = []
    for candidate in candidates:
        for record_id in candidate.get("matched_records") or []:
            if record_id not in found:
                found.append(record_id)
    return sorted(found)


def _unique(values: list) -> list[str]:
    found = []
    for value in values:
        if value and value not in found:
            found.append(value)
    return sorted(found)


def _alternative(candidate: dict, decision: Decision) -> dict:
    record = (candidate.get("matched_records") or [None])[0]
    return {
        "customer_record_id": record,
        "person_id": candidate.get("person_id"),
        "decision": decision.decision,
        "reason_code": decision.reason_code,
    }


def _words(decision: str) -> str:
    if decision == "SAME_ENTITY":
        return "the same person"
    if decision == "DIFFERENT_ENTITY":
        return "a different person"
    return "left for review"


def _ensure_two(text: str, extra: str) -> str:
    if text.count(".") >= 2:
        return text
    return text.rstrip() + " " + extra
