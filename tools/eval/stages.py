"""Stage diagnostics: check the pipeline's intermediate files against the practice labels.

The official score only sees the final output. These two checks look one step
earlier, so a wrong decision can be traced to the stage that caused it:

* Stage 2 (``hit_golden.jsonl``): does the hit profile hold the dates and
  search results the label's reference reason relies on?
* Stage 3 (``alert_resolution.jsonl``): does the alert resolve to exactly the
  labelled customer records (or to ``AMBIGUOUS``)?

They read the cache folder ``system/run`` writes (``working/`` or
``$SANCTIONS_CACHE``). ``system/run`` itself never reads the labels.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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


def hit_profile_agreement(profiles: list[dict], labels: list[dict]) -> dict:
    """Stage 2: per entity type, how many labelled hits have the label's dates and search results."""
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


def label_matches(row: dict, expected_record_ids: list[str]) -> tuple[bool, str]:
    """Whether one practice label's customer resolution matches this alert.

    ``["AMBIGUOUS"]`` matches status AMBIGUOUS. Any other list must be exactly
    the resolved person's record ids, and ``customer_record_id`` one of them.
    """
    expected = list(expected_record_ids)
    if expected == ["AMBIGUOUS"]:
        if row["status"] != "AMBIGUOUS" or row["customer_record_id"] != "AMBIGUOUS":
            return False, f"expected AMBIGUOUS, got {row['status']} {row['customer_record_id']!r}"
        if not row["candidates"] or not row["chosen_person_ids"]:
            return False, "ambiguous alert dropped its candidates"
        return True, ""
    if row["status"] != "RESOLVED":
        return False, f"status {row['status']}"
    record_id = row["customer_record_id"]
    if not isinstance(record_id, str) or record_id.startswith("P-"):
        return False, f"customer_record_id {record_id!r}"
    chosen = row["chosen_person_ids"]
    if len(chosen) != 1:
        return False, f"chosen {chosen}"
    candidate = next((item for item in row["candidates"] if item["person_id"] == chosen[0]), None)
    if candidate is None:
        return False, "missing candidate"
    if set(candidate["record_ids"]) != set(expected):
        return False, f"records {candidate['record_ids']} != {sorted(expected)}"
    if record_id not in set(expected):
        return False, f"customer_record_id {record_id} not in {sorted(expected)}"
    return True, ""


def alert_resolution_agreement(rows: list[dict], labels: list[dict]) -> dict:
    """Stage 3: labelled alerts that resolve to the labelled customer records."""
    by_alert = {row["alert_id"]: row for row in rows}
    matched = 0
    misses = []
    for label in labels:
        row = by_alert.get(label.get("alert_id"))
        if row is None:
            good, reason = False, "alert not resolved"
        else:
            good, reason = label_matches(row, label.get("customer_record_ids") or [])
        if good:
            matched += 1
            continue
        misses.append({
            "alert_id": label.get("alert_id"),
            "customer_record_id": None if row is None else row.get("customer_record_id"),
            "hit_id": label.get("hit_id"),
            "method": None if row is None else row.get("method"),
            "reason": reason,
            "status": None if row is None else row.get("status"),
        })
    misses.sort(key=lambda item: (str(item.get("hit_id") or ""), str(item.get("alert_id") or "")))
    return {"labels": len(labels), "matched": matched, "misses": misses}


def stage_diagnostics(cache_dir: Path, labels_path: Path) -> dict:
    """Both checks, for whichever cache files exist."""
    labels = _read_jsonl(labels_path)
    for label in labels:
        records = label.get("customer_record_ids")
        if isinstance(records, str):
            label["customer_record_ids"] = [part.strip() for part in records.split(";") if part.strip()]
    result: dict = {}
    profiles = Path(cache_dir) / "hit_golden.jsonl"
    if profiles.is_file():
        result["stage2_hit_profiles"] = hit_profile_agreement(_read_jsonl(profiles), labels)
    resolutions = Path(cache_dir) / "alert_resolution.jsonl"
    if resolutions.is_file():
        result["stage3_alert_resolution"] = alert_resolution_agreement(_read_jsonl(resolutions), labels)
    return result
