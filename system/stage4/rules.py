"""Decide one hit against one person. Contradictions, then the gate, then confirmation."""

from __future__ import annotations

from stage4.gate import GateContext, gate, gate_words
from stage4.model import AGREE, CONTRADICT, PRIORITY, UNKNOWN, Comparison, Decision

_CODE_DIM = {
    "ENTITY_TYPE_MISMATCH": "type",
    "DECEASED": "death",
    "TEMPORAL_IMPOSSIBILITY": "time",
    "DOB_MISMATCH": "dob",
    "NAME_MISMATCH_VERIFIED": "name",
    "LOCATION_MISMATCH": "location",
}


def decide_for_person(
    hit: dict,
    alert: dict,
    person: dict,
    resolution: dict,
    cmp: Comparison,
    candidate: dict | None = None,
    disabled: frozenset[str] | None = None,
) -> Decision:
    ctx = GateContext(
        hit=hit,
        person=person,
        resolution=resolution,
        candidate=candidate,
        cmp=cmp,
        alert=alert,
    )
    fired = [code for code in PRIORITY if cmp.contradiction(code)]
    location_exception = False
    if "LOCATION_MISMATCH" in fired and cmp.name.status == AGREE and cmp.dob.status == AGREE:
        fired.remove("LOCATION_MISMATCH")
        location_exception = True

    blocked: dict[str, list[str]] = {}
    passed: list[str] = []
    for code in fired:
        result = gate(code, ctx, disabled)
        if result.ok:
            passed.append(code)
        else:
            blocked[code] = result.reasons

    # Belt: an LLM-read dimension never stays in the passed list, whatever the table says.
    kept = []
    for code in passed:
        if cmp.dim(code).llm_used:
            blocked[code] = sorted(set(blocked.get(code, []) + ["LLM_FACT"]))
        else:
            kept.append(code)
    passed = kept

    person_id = person.get("person_id")
    matched = list((candidate or {}).get("matched_records") or [])
    if passed:
        decision = Decision(
            decision="DIFFERENT_ENTITY",
            reason_code=passed[0],
            passed=passed,
            fired=fired,
            blocked=blocked,
            cmp=cmp,
            kind="clear",
            person_id=person_id,
            matched_records=matched,
        )
        decision.fragility = _fragility(cmp, passed[0])
        decision.llm_used = False
        return decision

    if fired:
        primary = fired[0]
        reasons = blocked.get(primary) or []
        gaps = _screened_gaps(candidate)
        note = _gate_note(reasons, gaps, alert)
        decision = Decision(
            decision="REVIEW",
            reason_code="INSUFFICIENT_DATA",
            passed=[],
            fired=fired,
            blocked=blocked,
            cmp=cmp,
            kind="review_gate",
            gate_note=note,
            missing=note,
            screened_gaps=gaps,
            person_id=person_id,
            matched_records=matched,
        )
        decision.llm_used = any(cmp.dim(code).llm_used for code in fired)
        decision.fragility = "borderline" if decision.llm_used else "thin"
        return decision

    if location_exception:
        return _review(cmp, person_id, matched, missing="name and date of birth agree but no country is shared", kind="review_exception")

    if cmp.person_type == "Individual":
        if cmp.name.status == AGREE and cmp.dob.status == AGREE and cmp.location.status != CONTRADICT:
            code = "NAME_DOB_LOCATION_MATCH" if cmp.location.status == AGREE else "NAME_DOB_MATCH"
            return _same(code, cmp, person_id, matched)
    elif cmp.name.status == AGREE and cmp.location.status == AGREE and cmp.dob.status != CONTRADICT:
        return _same("NAME_LOCATION_MATCH", cmp, person_id, matched)

    return _review(cmp, person_id, matched, missing=_missing(cmp), kind="review_insufficient")


def _screened_gaps(candidate: dict | None) -> list[str]:
    """Which screened filter was skipped, for the reason text only."""
    found: list[str] = []
    filters = (candidate or {}).get("filters") or {}
    for item in filters.get("skipped_missing") or []:
        if isinstance(item, dict) and item.get("filter"):
            side = item.get("side") or "record"
            label = f"{item['filter']} on the {side}"
        elif isinstance(item, str) and item:
            label = item
        else:
            continue
        if label not in found:
            found.append(label)
    return found


def _gate_note(reasons: list[str], gaps: list[str], alert: dict) -> str:
    extras: list[str] = []
    if "candidate_kept_on_missing_field" in reasons:
        named = ", ".join(gaps) if gaps else "a field that was not named"
        extras.append(f"the customer was kept despite a missing screened field ({named})")
    if "dob_partial_only" in reasons:
        dob = ((alert.get("customer") or {}).get("dob")) or "unknown"
        extras.append(f"the screened date of birth {dob} matched the customer only in part")
    if extras:
        return "; ".join(extras)
    return gate_words(reasons)


def _same(code: str, cmp: Comparison, person_id: str | None, matched: list) -> Decision:
    used = cmp.name.llm_used or cmp.dob.llm_used or cmp.location.llm_used
    return Decision(
        decision="SAME_ENTITY",
        reason_code=code,
        passed=[code],
        cmp=cmp,
        kind="confirm",
        person_id=person_id,
        matched_records=matched,
        llm_used=used,
        fragility=_fragility(cmp, code),
    )


def _review(cmp: Comparison, person_id: str | None, matched: list, missing: str, kind: str) -> Decision:
    return Decision(
        decision="REVIEW",
        reason_code="INSUFFICIENT_DATA",
        cmp=cmp,
        kind=kind,
        missing=missing,
        person_id=person_id,
        matched_records=matched,
        llm_used=bool(cmp and (cmp.name.llm_used or cmp.dob.llm_used)),
        fragility="thin",
    )


def _missing(cmp: Comparison) -> str:
    if cmp.name.detail.get("short") or "NAME_TOO_SHORT" in cmp.issues:
        return "the customer's name has too few real parts to compare"
    if cmp.dob.status == UNKNOWN and not (cmp.dob.detail.get("candidates") or []):
        return "the hit gives no date of birth"
    if cmp.dob.status == UNKNOWN and cmp.dob.detail.get("verified"):
        return "the customer's date of birth is within a year of the hit's"
    if cmp.name.status != AGREE:
        return "the names do not agree closely enough to confirm"
    if cmp.location.status == UNKNOWN:
        return "there is no country to compare"
    return "the records do not settle the comparison"


def _fragility(cmp: Comparison, code: str) -> str:
    if code == "DOB_MISMATCH" and _dob_edge(cmp):
        return "borderline"
    if code == "NAME_MISMATCH_VERIFIED" and cmp.name.detail.get("fuzzy"):
        return "borderline"
    sources = list(cmp.dim(code).sources) if code in cmp_codes() else []
    if code in ("NAME_DOB_MATCH", "NAME_DOB_LOCATION_MATCH", "NAME_LOCATION_MATCH"):
        sources = list(cmp.dob.sources) + list(cmp.location.sources) + list(cmp.name.sources)
    if len(set(sources)) <= 1:
        return "thin"
    return "solid"


def cmp_codes() -> set[str]:
    return set(_CODE_DIM)


def _dob_edge(cmp: Comparison) -> bool:
    verified = cmp.dob.detail.get("verified")
    if not verified:
        return False
    for candidate in cmp.dob.detail.get("candidates") or []:
        years = [int(year) for year in (candidate.get("years") or [])]
        if not years:
            continue
        gap = min(abs(int(verified["y"]) - year) for year in years)
        if gap == 2:
            return True
        if len(years) == 1 and years[0] == int(verified["y"]) and candidate.get("month") not in (None, verified.get("m")):
            return True
    return False
