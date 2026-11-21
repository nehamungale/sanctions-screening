"""Command-line entry for Stage 3.

``python -m stage3 <data folder> <alert_resolution.jsonl>``

Reads ``alerts.jsonl`` and ``name_variants.json`` from the data folder and the
Stage 1 record-level cache from ``SANCTIONS_CACHE`` or ``working/``.
``system/run`` calls ``run_stage3`` after Stages 1 and 2. This stage does not
decide hits.
"""

from __future__ import annotations

import json
import os
import sys
import time

from shared.io import load_table, load_variants, read_jsonl
from stage3.resolve import dumps_jsonl, label_matches, resolve_alerts, summarise
from stage3.stage1_adapter import load_catalog


def run_stage3(data_folder: str, output_file: str, cache_dir: str | None = None) -> dict:
    """Resolve every alert and write one JSON line per alert. Returns the summary."""
    cache = cache_dir or os.environ.get("SANCTIONS_CACHE", "working")
    started = time.perf_counter()
    customers_path = os.path.join(data_folder, "customers.jsonl")
    catalog = load_catalog(
        cache,
        load_variants(data_folder),
        customers_path if os.path.isfile(customers_path) else None,
    )
    alerts = load_table(data_folder, "alerts.jsonl")
    rows = resolve_alerts(alerts, catalog)
    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(dumps_jsonl(rows))
    summary = summarise(rows)
    practice = _practice(rows, data_folder)
    if practice is not None:
        summary["practice"] = practice
    summary["cache_dir"] = cache
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    summary["output"] = output_file
    return summary


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m stage3 <data folder> <alert_resolution.jsonl>", file=sys.stderr)
        return 2
    data_folder, output_file = args
    try:
        summary = run_stage3(data_folder, output_file)
    except FileNotFoundError as error:
        print(f"missing input: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _practice(rows: list[dict], data_folder: str) -> dict | None:
    """Score ``practice_labels.jsonl`` when the data folder has one."""
    path = os.path.join(data_folder, "practice_labels.jsonl")
    if not os.path.isfile(path):
        return None
    labels = read_jsonl(path)
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
