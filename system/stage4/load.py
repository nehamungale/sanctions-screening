"""Load Stage 4 inputs. ``person_golden.jsonl`` is streamed, not held in full."""

from __future__ import annotations

import json
import os


def read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_stage4(data_folder: str, cache_dir: str) -> dict:
    alerts = read_jsonl(os.path.join(data_folder, "alerts.jsonl"))
    hits = read_jsonl(os.path.join(data_folder, "hits.jsonl"))
    resolutions = read_jsonl(os.path.join(cache_dir, "alert_resolution.jsonl"))
    profiles = read_jsonl(os.path.join(cache_dir, "hit_golden.jsonl"))
    with open(os.path.join(data_folder, "name_variants.json"), encoding="utf-8") as handle:
        variants = json.load(handle)
    needed = set()
    for row in resolutions:
        for candidate in row.get("candidates") or []:
            if candidate.get("person_id"):
                needed.add(candidate["person_id"])
    persons: dict[str, dict] = {}
    golden = os.path.join(cache_dir, "person_golden.jsonl")
    with open(golden, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            person_id = row.get("person_id")
            if person_id in needed:
                persons[person_id] = row
                if len(persons) == len(needed):
                    break
    return {
        "alerts": alerts,
        "alerts_by_id": {row["alert_id"]: row for row in alerts},
        "hits": hits,
        "resolutions": {row["alert_id"]: row for row in resolutions},
        "profiles": {row["hit_id"]: row for row in profiles},
        "persons": persons,
        "variants": variants,
        "known_ids": _known_ids(data_folder, alerts, hits),
    }


def _known_ids(data_folder: str, alerts: list[dict], hits: list[dict]) -> set[str]:
    found = {row["alert_id"] for row in alerts}
    found.update(row["hit_id"] for row in hits)
    specs = (
        ("customers.jsonl", "record_id"),
        ("accounts.jsonl", "account_id"),
        ("onboarding.jsonl", "kyc_applicant_id"),
        ("kyc_checks.jsonl", "check_id"),
        ("notes.jsonl", "note_id"),
        ("search_results.jsonl", "result_id"),
    )
    for name, key in specs:
        path = os.path.join(data_folder, name)
        if not os.path.isfile(path):
            continue
        for row in read_jsonl(path):
            if row.get(key):
                found.add(row[key])
    return found
