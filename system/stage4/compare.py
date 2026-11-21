"""Compare one hit with one resolved person. Six dimensions, no decision yet."""

from __future__ import annotations

import re

from stage1.normalise import NameTools

from stage4.dates import (
    age_on,
    agrees,
    as_date,
    contradicts,
    deceased_before_screening,
    earliest_day,
    parse_parts,
    under_sixteen,
)
from stage4.model import AGREE, CONTRADICT, UNKNOWN, Comparison, Dim

_TYPES = {"Individual", "Company"}
_BORN_CUE = re.compile(r"born|date of birth", re.IGNORECASE)


def person_type(person: dict) -> str | None:
    value = (person.get("entity_type") or {}).get("value")
    return value if value in _TYPES else None


def type_contradicts(left: object, right: object) -> bool:
    return left in _TYPES and right in _TYPES and left != right


def compare(hit: dict, alert: dict, person: dict, tools: NameTools) -> Comparison:
    cmp = Comparison(person_type=person_type(person))
    cmp.entity_type = _type_dim(hit, alert, person)
    cmp.dob = _dob_dim(hit, person, cmp)
    cmp.time = _time_dim(hit, person, cmp)
    cmp.death = _death_dim(hit, alert)
    cmp.name = _name_dim(hit, person, tools, cmp)
    cmp.location = _location_dim(hit, person, cmp)
    _issue_flags(hit, person, cmp)
    return cmp


def _type_dim(hit: dict, alert: dict, person: dict) -> Dim:
    customer = person_type(person)
    listed = hit.get("entity_type")
    screened = (alert.get("customer") or {}).get("entity_type")
    source = (person.get("entity_type") or {}).get("source_id")
    status = UNKNOWN
    if type_contradicts(customer, listed):
        status = CONTRADICT
    elif customer and listed and customer == listed:
        status = AGREE
    dim = Dim(
        status=status,
        customer=customer,
        hit=listed,
        sources=[source] if source and status == CONTRADICT else [],
        detail={"screened": screened},
    )
    method = (person.get("entity_type") or {}).get("method")
    if method == "llm":
        dim.llm_used = True
    return dim


def _customer_dates(person: dict) -> tuple[dict | None, list[dict], bool]:
    """Verified date (or None), declared dates, and whether every declared date parsed."""
    raw = person.get("dob") or {}
    verified = None
    # An LLM-read verified date still counts as a contradiction, so it can
    # push the hit to review. The gate stops it from clearing the hit.
    if raw.get("verified") and raw.get("value"):
        verified = parse_parts(raw.get("value"))
        if verified is not None:
            verified["source_id"] = raw.get("source_id")
            verified["method"] = raw.get("method") or "regex"
    declared = []
    all_comparable = True
    for entry in person.get("declared_dobs") or []:
        if not entry.get("comparable") or not entry.get("value"):
            all_comparable = False
            continue
        parts = parse_parts(entry.get("value"))
        if parts is None:
            all_comparable = False
            continue
        parts["source_id"] = entry.get("source_id")
        parts["method"] = "record"
        declared.append(parts)
    if not (person.get("declared_dobs") or []):
        all_comparable = False
    return verified, declared, all_comparable and len(declared) == len(person.get("declared_dobs") or [])


def _company_dates(person: dict) -> dict | None:
    raw = person.get("incorporation_date") or {}
    if not raw or not raw.get("value"):
        return None
    parts = parse_parts(raw.get("value"))
    if parts is None:
        return None
    parts["source_id"] = raw.get("source_id")
    parts["method"] = raw.get("method") or "record"
    parts["verified"] = bool(raw.get("verified"))
    return parts


def _candidates(hit: dict, company: bool) -> list[dict]:
    key = "incorporation_dates" if company else "dob_candidates"
    rows = []
    for candidate in hit.get(key) or []:
        years = [int(year) for year in (candidate.get("years") or []) if year is not None]
        if not years:
            continue
        rows.append(candidate)
    return rows


def _dob_dim(hit: dict, person: dict, cmp: Comparison) -> Dim:
    company = cmp.person_type == "Company"
    candidates = _candidates(hit, company)
    if company:
        verified = _company_dates(person)
        declared: list[dict] = []
        every = verified is not None
        agree_pool = [verified] if verified else []
    else:
        verified, declared, every = _customer_dates(person)
        agree_pool = [verified] if verified else list(declared)
    dim = Dim(customer=(verified or (declared[0] if declared else None) or {}).get("value") if (verified or declared) else None)
    dim.hit = _hit_date_phrase(candidates)
    dim.detail = {
        "candidates": candidates,
        "verified": verified,
        "declared": declared,
        "every_declared": every,
        "company": company,
    }
    if verified and verified.get("method") == "llm":
        dim.llm_used = True
    if any(item.get("method") == "llm" for item in candidates):
        dim.llm_used = True
    if not candidates or not agree_pool:
        dim.status = UNKNOWN
        return dim
    if any(agrees(pool, candidate) for pool in agree_pool for candidate in candidates):
        dim.status = AGREE
        dim.sources = _agree_sources(agree_pool, candidates)
        if verified and any(agrees(item, candidate) for item in declared for candidate in candidates):
            if not any(agrees(verified, candidate) for candidate in candidates):
                cmp.issues.append("DECLARED_DOB_AGREES")
        return dim
    if verified is not None and all(contradicts(verified, candidate) for candidate in candidates):
        dim.status = CONTRADICT
        dim.sources = [verified["source_id"]] if verified.get("source_id") else []
        dim.sources.extend(_search_sources(candidates))
        if any(agrees(item, candidate) for item in declared for candidate in candidates):
            cmp.issues.append("DECLARED_DOB_AGREES")
        if verified.get("method") == "llm" or verified.get("may_not_clear"):
            dim.llm_used = True
        raw = person.get("dob") or {}
        if raw.get("verified") and raw.get("may_solely_support_different_entity") is False:
            dim.detail["may_not_clear"] = True
        return dim
    if verified is None and every and declared and all(
        all(contradicts(item, candidate) for candidate in candidates) for item in declared
    ):
        dim.status = CONTRADICT
        dim.sources = sorted({item["source_id"] for item in declared if item.get("source_id")})
        dim.sources.extend(_search_sources(candidates))
        return dim
    dim.status = UNKNOWN
    return dim


def _agree_sources(pool: list[dict], candidates: list[dict]) -> list[str]:
    sources = []
    for item in pool:
        if item and item.get("source_id") and any(agrees(item, candidate) for candidate in candidates):
            sources.append(item["source_id"])
    sources.extend(_search_sources([
        candidate for candidate in candidates
        if any(agrees(item, candidate) for item in pool if item)
    ]))
    return _unique(sources)


def _search_sources(candidates: list[dict]) -> list[str]:
    """Search-result ids only. Listed dates and profile notes are not cited."""
    found = []
    for candidate in candidates:
        if candidate.get("source") == "search_result" and candidate.get("source_id"):
            found.append(candidate["source_id"])
    return found


def _hit_date_phrase(candidates: list[dict]) -> str | None:
    if not candidates:
        return None
    return "; ".join(_one_phrase(candidate) for candidate in candidates)


def _one_phrase(candidate: dict) -> str:
    years = list(candidate.get("years") or [])
    month = candidate.get("month")
    day = candidate.get("day")
    if len(years) == 1 and month and day:
        shown = f"{years[0]:04d}-{int(month):02d}-{int(day):02d}"
    elif len(years) == 1 and month:
        shown = f"{years[0]:04d}-{int(month):02d}"
    elif len(years) == 1:
        shown = f"{years[0]:04d}"
    elif len(years) == 2:
        shown = f"{years[0]} or {years[1]}"
    elif len(years) > 2:
        shown = f"{years[0]}-{years[-1]}"
    else:
        shown = ""
    source = candidate.get("source")
    if source == "profile_note":
        if len(years) >= 2:
            return f"the hit's profile notes put its birth year at {shown}"
        return f"the hit's profile notes put its birth at {shown}"
    if source == "search_result":
        return f"the hit's search results put its birth year at {shown}"
    return f"the hit's listed date of birth is {shown}"


def _time_dim(hit: dict, person: dict, cmp: Comparison) -> Dim:
    report = hit.get("earliest_dated_report") or None
    dim = Dim(hit=(report or {}).get("date") if report else None)
    on = as_date(report.get("date")) if report and report.get("date") else None
    if on is None:
        return dim
    detail = cmp.dob.detail
    verified = detail.get("verified")
    declared = detail.get("declared") or []
    fired = False
    source = None
    max_age = None
    if cmp.person_type == "Company":
        if verified is not None:
            earliest = f"{verified['y']:04d}-{verified['m'] or 1:02d}-{verified['d'] or 1:02d}"
            fired = earliest > report["date"]
            source = verified.get("source_id")
            dim.customer = verified.get("value")
    elif verified is not None:
        fired = under_sixteen(verified, on)
        source = verified.get("source_id")
        dim.customer = verified.get("value")
        max_age = age_on(earliest_day(verified), on)
    elif detail.get("every_declared") and declared:
        fired = all(under_sixteen(item, on) for item in declared)
        source = declared[0].get("source_id")
        dim.customer = declared[0].get("value")
        max_age = min(age_on(earliest_day(item), on) for item in declared)
    if fired:
        dim.status = CONTRADICT
        if source:
            dim.sources = [source]
        if verified and verified.get("method") == "llm":
            dim.llm_used = True
    dim.detail = {"max_age": max_age, "report": report.get("date") if report else None}
    return dim


def _death_dim(hit: dict, alert: dict) -> Dim:
    fired, _latest, screened = deceased_before_screening(hit, alert)
    deceased = hit.get("deceased") or {}
    dim = Dim(
        status=CONTRADICT if fired else UNKNOWN,
        customer=screened.isoformat() if screened else None,
        hit=deceased.get("date"),
        detail={"precision": deceased.get("precision"), "life_status": deceased.get("life_status")},
    )
    if deceased.get("method") == "llm":
        dim.llm_used = True
    if fired:
        alert_id = alert.get("alert_id")
        if alert_id:
            dim.sources = [alert_id]
    return dim


def _name_dim(hit: dict, person: dict, tools: NameTools, cmp: Comparison) -> Dim:
    legal = person.get("legal_name") or {}
    dim = Dim(customer=legal.get("value"))
    comparable = [entry for entry in (hit.get("names") or []) if entry.get("parts")]
    primary = next((entry for entry in (hit.get("names") or []) if entry.get("kind") == "primary"), None)
    dim.hit = (primary or {}).get("value")
    individual = cmp.person_type == "Individual"
    short = bool(legal.get("blocks_name_clear")) or (
        individual and int(legal.get("real_part_count") or 0) < 2 and bool(legal.get("verified"))
    )
    if individual and (short or "NAME_TOO_SHORT" in set(person.get("flags") or []) or "BLOCK_NAME_CLEAR" in set(person.get("flags") or [])):
        # A verified short name blocks both sides. An unverified short legal
        # name can still agree through a longer non-blocking form.
        if legal.get("verified") or not _agreement_forms(person):
            dim.status = UNKNOWN
            dim.detail = {"clear_status": UNKNOWN, "short": True}
            cmp.issues.append("NAME_TOO_SHORT")
            return dim
    if legal.get("method") == "llm":
        dim.llm_used = True
    left_sets = _customer_name_sets(person)
    if not left_sets or not comparable:
        dim.status = UNKNOWN
        dim.detail = {"clear_status": UNKNOWN}
        return dim
    any_agree = False
    non_exhaustive = False
    matched_value = None
    matched_pairs: list = []
    fuzzy = False
    for parts in left_sets:
        for entry in comparable:
            # Agreement does not depend on argument order (shared.names.agree_parts).
            result = tools.names_agree(list(parts), list(entry["parts"]))
            if not result.get("exhaustive", True):
                non_exhaustive = True
            if result.get("agree"):
                any_agree = True
                matched_value = entry.get("value")
                matched_pairs = list(result.get("matched_pairs") or [])
                for pair in matched_pairs:
                    left, _, right = str(pair).partition("=")
                    if left != right:
                        fuzzy = True
    verified = bool(legal.get("verified")) and legal.get("method") != "llm"
    clear_status = UNKNOWN
    if verified and not any_agree and not non_exhaustive and comparable:
        clear_status = CONTRADICT
        if legal.get("source_id"):
            dim.sources = [legal["source_id"]]
    if any_agree:
        dim.status = AGREE
    elif clear_status == CONTRADICT:
        dim.status = CONTRADICT
    else:
        dim.status = UNKNOWN
    if non_exhaustive:
        cmp.issues.append("NON_EXHAUSTIVE_NAME")
        if clear_status == CONTRADICT:
            clear_status = UNKNOWN
            dim.status = UNKNOWN
            dim.sources = []
    dim.detail = {
        "clear_status": clear_status,
        "both_agree": any_agree,
        "matched_hit_name": matched_value,
        "matched_pairs": matched_pairs,
        "fuzzy": fuzzy,
        "source_id": legal.get("source_id"),
    }
    if dim.status == AGREE and legal.get("source_id"):
        dim.sources = [legal["source_id"]]
    return dim


def _agreement_forms(person: dict) -> list[list[str]]:
    forms = []
    for entry in person.get("names_all") or []:
        if entry.get("blocks_name_clear"):
            continue
        if entry.get("parts"):
            forms.append(list(entry["parts"]))
    return forms


def _customer_name_sets(person: dict) -> list[list[str]]:
    legal = person.get("legal_name") or {}
    if legal.get("verified") and legal.get("method") != "llm" and legal.get("parts"):
        return [list(legal["parts"])]
    return _agreement_forms(person)


def _location_dim(hit: dict, person: dict, cmp: Comparison) -> Dim:
    grouped: dict[str, list[str]] = {}
    kinds: dict[str, set[str]] = {}
    for entry in person.get("countries") or []:
        value = entry.get("value")
        source = entry.get("source_id")
        if not value or not source:
            continue
        grouped.setdefault(value, [])
        if source not in grouped[value]:
            grouped[value].append(source)
        kinds.setdefault(value, set()).add(entry.get("kind") or "")
    hit_values = []
    unmapped = False
    for entry in hit.get("countries") or []:
        if entry.get("unmapped"):
            unmapped = True
            continue
        if entry.get("value") and entry["value"] not in hit_values:
            hit_values.append(entry["value"])
    customer_values = sorted(grouped)
    listed = sorted(hit_values)
    shared = sorted(set(customer_values) & set(listed))
    if shared:
        status = AGREE
    elif customer_values and listed:
        status = CONTRADICT
    else:
        status = UNKNOWN
    if status == CONTRADICT:
        sources = [source for value in customer_values for source in grouped[value]]
    elif status == AGREE:
        sources = [source for value in shared for source in grouped[value]]
    else:
        sources = []
    note_only = False
    if status == CONTRADICT:
        for value in customer_values:
            only = kinds.get(value) or set()
            if only and only <= {"residence_note", "note_country"}:
                note_only = True
    dim = Dim(
        status=status,
        customer=customer_values,
        hit=listed,
        sources=_unique(sources),
        detail={"shared": shared, "note_only": note_only, "unmapped_hit": unmapped, "by_value": grouped},
    )
    return dim


def _issue_flags(hit: dict, person: dict, cmp: Comparison) -> None:
    flags = set(person.get("flags") or [])
    hit_flags = set(hit.get("flags") or [])
    if "NON_LATIN_ALIAS" in hit_flags:
        cmp.issues.append("NON_LATIN_ALIAS")
    if "UNMAPPED_COUNTRY" in hit_flags or cmp.location.detail.get("unmapped_hit"):
        cmp.issues.append("HIT_UNMAPPED_COUNTRY")
    if "NOTE_DOB_UNRESOLVED" in hit_flags:
        cmp.issues.append("NOTE_DOB_UNRESOLVED")
    if hit_flags & {"UNPARSED_DATE", "UNKNOWN_DATE", "DOBS_UNPARSED"}:
        cmp.issues.append("HIT_UNPARSED_DATE")
    if "LLM_UNKNOWN" in hit_flags or "LLM_SKIPPED_BUDGET" in hit_flags:
        cmp.issues.append("LLM_DOB_UNKNOWN")
    if "MULTI_SR_CONFLICT" in hit_flags:
        cmp.issues.append("MULTI_SR_CONFLICT")
    if any(item.get("rule_strength") == "weak" for item in (hit.get("dob_candidates") or [])):
        cmp.issues.append("WEAK_DOB_RULE")
    text = hit.get("_profile_text") or ""
    paragraph = text.strip().split("\n\n", 1)[0] if text else ""
    if paragraph and _BORN_CUE.search(paragraph):
        if any(item.get("source") == "search_result" for item in (hit.get("dob_candidates") or [])):
            cmp.issues.append("BORN_CUE_SEARCH_DOB")
    if cmp.dob.detail.get("may_not_clear"):
        cmp.issues.append("DOB_MAY_NOT_CLEAR")
    legal = person.get("legal_name") or {}
    if legal.get("method") == "llm" or (
        legal.get("verified") and legal.get("may_solely_support_different_entity") is False
    ):
        cmp.issues.append("NAME_MAY_NOT_CLEAR")
        cmp.name.llm_used = cmp.name.llm_used or legal.get("method") == "llm"
    if "NON_EXHAUSTIVE_NAME" in cmp.issues and cmp.dob.status == AGREE:
        cmp.issues.append("NON_EXHAUSTIVE_BLOCKS_LOCATION")


def _unique(values: list) -> list[str]:
    found = []
    for value in values:
        if value and value not in found:
            found.append(value)
    return sorted(found)
