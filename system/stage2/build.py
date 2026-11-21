"""Assemble one hit golden profile per hit.

Tier 1 is the ``dobs`` field and a birth sentence in the first paragraph of
the profile notes, both kept. Tier 2 is search results, and only when tier 1
is empty. Companies take an incorporation date from ``dobs`` only. Death comes
from ``life_status`` and ``deceased_date`` only.
"""

from __future__ import annotations

import json
import os
import time

from stage1.load import DataStore
from stage1.normalise import NameTools, parse_date

from stage2.countries import hit_countries
from stage2.listing import listing
from stage2.llm import NoteFallback, llm_enabled
from stage2.names import hit_names
from stage2.notes import first_paragraph, parse_dated_reports, parse_note_dob
from stage2.practice import agreement
from stage2.search import evaluate_search, not_consulted, search_key

def _dob_from_field(raw: str, hit_id: str, field: str) -> tuple[dict | None, list[str]]:
    parsed, flags = parse_date(raw, mode="hit")
    if not parsed or flags:
        return None, flags or ["UNPARSED_DATE"]
    return {
        "years": [parsed["y"]],
        "month": parsed["m"],
        "day": parsed["d"],
        "precision": parsed["precision"],
        "source": "dobs",
        "source_id": f"{hit_id}#{field}",
        "method": "regex",
        "rule": "dobs",
        "quote": str(raw),
        "may_solely_support_different_entity": True,
    }, []


def _search_candidate(accepted: dict) -> dict:
    return {
        "years": list(accepted["years"]),
        "month": None,
        "day": None,
        "precision": "year",
        "source": "search_result",
        "source_id": accepted["result_id"],
        "method": "regex",
        "rule": "search_result",
        "quote": accepted.get("quote") or "",
        "may_solely_support_different_entity": True,
        "country": accepted.get("country"),
        "phrase": accepted.get("phrase"),
    }


def build_hit(hit: dict, tools: NameTools, by_query: dict[str, list[dict]], fallback: NoteFallback) -> dict:
    hit_id = hit["hit_id"]
    entity_type = hit.get("entity_type")
    names, name_flags = hit_names(hit, tools)
    listed = listing(hit)
    countries, country_flags = hit_countries(hit)
    flags = list(name_flags) + list(country_flags)
    reports, earliest = parse_dated_reports(hit.get("profile_notes"), hit_id)
    deceased, death_flags = _deceased(hit)
    flags.extend(death_flags)

    field_dates: list[dict] = []
    for raw in hit.get("dobs") or []:
        candidate, date_flags = _dob_from_field(str(raw), hit_id, "dobs")
        flags.extend(date_flags)
        if candidate:
            field_dates.append(candidate)

    note_candidates: list[dict] = []
    block_search = False
    if entity_type == "Individual":
        note = parse_note_dob(hit.get("profile_notes"), f"{hit_id}#profile_notes")
        note_candidates.extend(note["candidates"])
        if note["unresolved"]:
            resolved = fallback.resolve(hit_id, str(hit.get("name") or ""), first_paragraph(hit.get("profile_notes")))
            flags.extend(resolved["flags"])
            if resolved["candidate"]:
                note_candidates.append(resolved["candidate"])
            elif "NOTE_DOB_UNRESOLVED" in resolved["flags"] or "NOTE_DOB_UNRESOLVED" in flags:
                block_search = True
                if "NOTE_DOB_UNRESOLVED" not in flags:
                    flags.append("NOTE_DOB_UNRESOLVED")

    tier1 = field_dates + note_candidates
    if entity_type == "Company":
        search = not_consulted(hit.get("name"))
        dob_candidates: list[dict] = []
        incorporation = field_dates
        dob_tier = None
        if not incorporation:
            flags.append("NO_DOB")
    else:
        incorporation = []
        if tier1 or block_search:
            search = not_consulted(hit.get("name"))
            dob_candidates = tier1
            dob_tier = "tier1" if tier1 else None
        else:
            search = evaluate_search(
                hit.get("name"),
                listed["phrase"],
                [entry["value"] for entry in countries],
                by_query.get(search_key(hit.get("name")), []),
            )
            dob_candidates = [_search_candidate(item) for item in search["accepted"]]
            dob_tier = "tier2" if dob_candidates else None
        if not dob_candidates:
            flags.append("NO_DOB")
        year_sets = {tuple(item["years"]) for item in search["accepted"]}
        if len(search["accepted"]) >= 2 and len(year_sets) >= 2:
            flags.append("MULTI_SR_CONFLICT")

    return {
        "hit_id": hit_id,
        "alert_id": hit.get("alert_id"),
        "entity_type": entity_type,
        "match_score": hit.get("match_score"),
        "names": names,
        "listing": listed,
        "countries": countries,
        "dob_candidates": dob_candidates,
        "dob_tier": dob_tier,
        "incorporation_dates": incorporation,
        "deceased": deceased,
        "dated_reports": reports,
        "earliest_dated_report": earliest,
        "search_results": {
            "key": search["key"],
            "consulted": search["consulted"],
            "considered": search["considered"],
            "accepted": [_accepted_public(item) for item in search["accepted"]],
            "rejected": search["rejected"],
        },
        "flags": sorted(set(flags)),
    }


def _accepted_public(item: dict) -> dict:
    return {
        "result_id": item["result_id"],
        "source_id": item["source_id"],
        "years": item["years"],
        "month": item["month"],
        "day": item["day"],
        "precision": item["precision"],
        "country": item["country"],
        "phrase": item["phrase"],
        "method": item["method"],
        "may_solely_support_different_entity": item["may_solely_support_different_entity"],
    }


def _deceased(hit: dict) -> tuple[dict, list[str]]:
    raw = hit.get("deceased_date")
    flags: list[str] = []
    parsed = None
    if raw:
        parsed, date_flags = parse_date(raw, mode="hit")
        if date_flags or not parsed:
            flags.extend(date_flags or ["UNPARSED_DATE"])
            parsed = None
    life = hit.get("life_status")
    if life == "Deceased" and parsed is None:
        flags.append("DECEASED_NO_DATE")
    return {
        "life_status": life,
        "date": parsed["value"] if parsed else None,
        "precision": parsed["precision"] if parsed else None,
        "source_id": f"{hit['hit_id']}#deceased_date",
        "method": "field",
    }, flags


def build_profiles(
    hits: list[dict],
    search_results: list[dict],
    name_variants: dict | None,
    *,
    cache_dir: str | None = None,
    enabled: bool | None = None,
    client=None,
    transport=None,
) -> tuple[list[dict], NoteFallback]:
    tools = NameTools(name_variants)
    by_query: dict[str, list[dict]] = {}
    for result in search_results:
        by_query.setdefault(result["query"], []).append(result)
    for rows in by_query.values():
        rows.sort(key=lambda row: row["result_id"])
    if enabled is None:
        enabled = llm_enabled()
    fallback = NoteFallback(cache_dir, enabled, client=client, transport=transport)
    profiles = [build_hit(hit, tools, by_query, fallback) for hit in sorted(hits, key=lambda row: row["hit_id"])]
    fallback.save()
    return profiles, fallback


def summarise(profiles: list[dict]) -> dict:
    buckets = {"dobs_only": 0, "dobs_and_note": 0, "note_only": 0, "search_result": 0, "unknown": 0}
    note_statements = 0
    deceased = 0
    deceased_undated = 0
    report_lines = 0
    report_hits = 0
    individuals = 0
    for profile in profiles:
        report_lines += len(profile["dated_reports"])
        if profile["dated_reports"]:
            report_hits += 1
        if profile["deceased"]["life_status"] == "Deceased":
            deceased += 1
            if not profile["deceased"]["date"]:
                deceased_undated += 1
        if profile["entity_type"] != "Individual":
            continue
        individuals += 1
        sources = {candidate["source"] for candidate in profile["dob_candidates"]}
        note_statements += sum(1 for candidate in profile["dob_candidates"] if candidate["source"] == "profile_note")
        has_dobs = "dobs" in sources
        has_note = "profile_note" in sources
        has_search = "search_result" in sources
        if has_dobs and has_note:
            buckets["dobs_and_note"] += 1
        elif has_dobs:
            buckets["dobs_only"] += 1
        elif has_note:
            buckets["note_only"] += 1
        elif has_search:
            buckets["search_result"] += 1
        else:
            buckets["unknown"] += 1
    return {
        "hits": len(profiles),
        "individuals": individuals,
        "companies": len(profiles) - individuals,
        "dob_buckets": buckets,
        "note_birth_statements": note_statements,
        "deceased": deceased,
        "deceased_undated": deceased_undated,
        "dated_report_lines": report_lines,
        "dated_report_hits": report_hits,
    }


def run_stage2(data_folder: str, cache_dir: str, enabled: bool | None = None) -> dict:
    """Read the data folder and write ``hit_golden.jsonl`` under ``cache_dir``."""
    started = time.perf_counter()
    store = DataStore(data_folder)
    hits = store.read_jsonl("hits.jsonl")
    search_results = store.read_jsonl("search_results.jsonl")
    variants = store.read_json("name_variants.json")
    profiles, fallback = build_profiles(
        hits, search_results, variants, cache_dir=cache_dir, enabled=enabled
    )
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "hit_golden.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for profile in profiles:
            handle.write(json.dumps(profile, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            handle.write("\n")
    stats = summarise(profiles)
    labels_path = os.path.join(data_folder, "practice_labels.jsonl")
    if os.path.isfile(labels_path):
        labels = store.read_jsonl("practice_labels.jsonl")
        stats["practice"] = agreement(profiles, labels)
    stats["llm_enabled"] = fallback.enabled
    stats["llm_calls"] = fallback.calls
    stats["llm_hits"] = fallback.hits_called
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    stats["cache_dir"] = cache_dir
    stats["output"] = path
    return stats
