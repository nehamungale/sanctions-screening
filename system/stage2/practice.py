"""Compare hit profiles with practice labels. Reads no names into the repo."""

from __future__ import annotations

import re

_PAIR_OR = re.compile(r"hit's (\d{4}) or (\d{4})")
_PAIR_COMMA = re.compile(r"hit's (\d{4}), (\d{4})")
_PAIR_AT = re.compile(r"\bat (\d{4}) or (\d{4})")
_HIT_ISO = re.compile(r"hit's (\d{4}-\d{2}(?:-\d{2})?)")
_HIT_DOB = re.compile(r"hit's date of birth (?:is|of) (\d{4}-\d{2}-\d{2})")
_REPORT = re.compile(r"\bon (\d{4}-\d{2}-\d{2})")


def _covers_years(candidates: list[dict], years: set[int]) -> bool:
    """One age-at-date candidate holds both years."""
    return any(years <= set(candidate.get("years") or []) for candidate in candidates)


def _covers_year_list(candidates: list[dict], years: set[int]) -> bool:
    """A comma list is several single-year dates, so the union may cover it."""
    found = set()
    for candidate in candidates:
        found.update(candidate.get("years") or [])
    return years <= found


def _covers_iso(candidates: list[dict], iso: str) -> bool:
    parts = [int(part) for part in iso.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else None
    day = parts[2] if len(parts) > 2 else None
    for candidate in candidates:
        if year not in (candidate.get("years") or []):
            continue
        if month is not None and candidate.get("month") != month:
            continue
        if day is not None and candidate.get("day") != day:
            continue
        return True
    return False


def label_agrees(profile: dict, label: dict) -> bool:
    """True when cited search results and stated hit dates are in the profile."""
    reason = label.get("reference_reason") or ""
    evidence = [item for item in (label.get("evidence") or []) if isinstance(item, str)]
    cited = sorted(item for item in evidence if item.startswith("SR-"))
    accepted = sorted(item["result_id"] for item in (profile.get("search_results") or {}).get("accepted") or [])
    if cited != accepted:
        return False
    candidates = list(profile.get("dob_candidates") or []) + list(profile.get("incorporation_dates") or [])
    for match in _PAIR_OR.finditer(reason):
        if not _covers_years(candidates, {int(match.group(1)), int(match.group(2))}):
            return False
    for match in _PAIR_COMMA.finditer(reason):
        if not _covers_year_list(candidates, {int(match.group(1)), int(match.group(2))}):
            return False
    for match in _PAIR_AT.finditer(reason):
        if not _covers_years(candidates, {int(match.group(1)), int(match.group(2))}):
            return False
    for match in list(_HIT_ISO.finditer(reason)) + list(_HIT_DOB.finditer(reason)):
        if not _covers_iso(candidates, match.group(1)):
            return False
    earliest = (profile.get("earliest_dated_report") or {}).get("date")
    for match in _REPORT.finditer(reason):
        if earliest != match.group(1):
            return False
    return True


def agreement(profiles: list[dict], labels: list[dict]) -> dict:
    by_id = {row["hit_id"]: row for row in profiles}
    individual = []
    company = []
    for label in labels:
        profile = by_id.get(label["hit_id"])
        if profile is None:
            continue
        ok = label_agrees(profile, label)
        bucket = individual if profile.get("entity_type") == "Individual" else company
        bucket.append(ok)
    return {
        "individual": len(individual),
        "individual_agree": sum(1 for ok in individual if ok),
        "company": len(company),
        "company_agree": sum(1 for ok in company if ok),
    }
