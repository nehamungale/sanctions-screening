"""Deciding record ids only. Hit field tokens are never cited."""

from __future__ import annotations

import re

from stage4.model import AGREE, Decision

_CUS = re.compile(r"^CUS-[0-9]{6}$")
_HIT_FIELD = re.compile(r"^H-[0-9A-F]{6}#")


def collect(decision: Decision, hit: dict, person: dict, alert: dict, extra: list[str] | None = None) -> list[str]:
    ids: list[str] = []
    cmp = decision.cmp
    if decision.kind in {"not_found_clear", "not_found_review", "not_decided"}:
        ids.append(alert.get("alert_id"))
    elif decision.kind in {"ambiguous_split", "ambiguous_review"}:
        ids.extend(extra or [])
    elif cmp is not None and decision.decision == "DIFFERENT_ENTITY":
        for code in decision.passed:
            ids.extend(cmp.dim(code).sources)
    elif cmp is not None and decision.kind == "review_gate" and decision.fired:
        ids.extend(cmp.dim(decision.fired[0]).sources)
    elif cmp is not None and decision.decision == "SAME_ENTITY":
        ids.extend(_same_ids(decision.reason_code, cmp))
    elif cmp is not None:
        if cmp.dob.status == AGREE:
            ids.extend(_customer_sources(cmp.dob.sources))
        if cmp.location.status == AGREE:
            ids.extend(cmp.location.sources)
        if cmp.name.status == AGREE and decision.reason_code != "INSUFFICIENT_DATA":
            ids.extend(_customer_sources(cmp.name.sources))
    if extra and decision.kind not in {"ambiguous_split", "ambiguous_review"}:
        ids.extend(extra)
    return _clean(ids)


def _same_ids(code: str, cmp) -> list[str]:
    ids: list[str] = []
    if code in {"NAME_DOB_MATCH", "NAME_DOB_LOCATION_MATCH"}:
        ids.extend(_customer_sources(cmp.dob.sources))
    if code in {"NAME_DOB_LOCATION_MATCH", "NAME_LOCATION_MATCH"}:
        ids.extend(cmp.location.sources)
    return ids


def _customer_sources(sources: list) -> list[str]:
    """Search-result ids stay. Hit field tokens do not."""
    kept = []
    for source in sources:
        if not source or _HIT_FIELD.match(str(source)):
            continue
        kept.append(str(source))
    return kept


def _clean(ids: list) -> list[str]:
    found = []
    for item in ids:
        if not item or not isinstance(item, str):
            continue
        if _HIT_FIELD.match(item):
            continue
        if item not in found:
            found.append(item)
    return sorted(found)


def customer_record_for_output(value: object) -> str | None:
    if value in (None, "", "AMBIGUOUS"):
        return None if value in (None, "") else "AMBIGUOUS"
    if isinstance(value, str) and (_CUS.fullmatch(value) or value == "AMBIGUOUS"):
        return value
    return None
