"""Run Stage 1, then Stage 2, then Stage 3. Decisions are not produced here."""

from __future__ import annotations

import json
import os
import sys

from stage1.build import run_stage1
from stage1.cli import ARTEFACTS as STAGE1_ARTEFACTS
from stage2.build import run_stage2
from stage3.cli import run_stage3


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: system/run <data folder> <output file>", file=sys.stderr)
        return 2
    data_folder, output_file = args
    cache_dir = os.environ.get("SANCTIONS_CACHE", "working")
    try:
        stage1 = run_stage1(data_folder, cache_dir)
        stage2 = run_stage2(data_folder, cache_dir)
        stage3 = run_stage3(
            data_folder,
            os.path.join(cache_dir, "alert_resolution.jsonl"),
            cache_dir,
        )
    except FileNotFoundError as error:
        print(f"missing input: {error}", file=sys.stderr)
        return 2
    summary = {
        "alert_resolution": _alert_resolution(stage3),
        "artefacts": list(STAGE1_ARTEFACTS) + ["hit_golden.jsonl", "alert_resolution.jsonl"],
        "cache_dir": cache_dir,
        "companies": stage2["companies"],
        "dated_report_hits": stage2["dated_report_hits"],
        "dated_report_lines": stage2["dated_report_lines"],
        "deceased": stage2["deceased"],
        "deceased_undated": stage2["deceased_undated"],
        "dob_buckets": stage2["dob_buckets"],
        "doc_edges": stage1["doc_edges"],
        "doc_edges_new_components": stage1["doc_edges_new_components"],
        "hits": stage2["hits"],
        "individuals": stage2["individuals"],
        "llm_calls": stage2["llm_calls"],
        "llm_enabled": stage2["llm_enabled"],
        "multi_record_persons": stage1["multi_record_persons"],
        "note_birth_statements": stage2["note_birth_statements"],
        "notes": stage1["notes"],
        "persons": stage1["persons"],
        "phone_dob_edges": stage1["phone_dob_edges"],
        "practice": stage2.get("practice"),
        "records": stage1["records"],
        "stage": 3,
        "stages": [1, 2, 3],
    }
    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    notes = stage1["notes"]
    buckets = stage2["dob_buckets"]
    print(
        f"stage 1: {stage1['records']} records -> {stage1['persons']} persons; "
        f"{stage1['elapsed_seconds']}s"
    )
    print(
        f"stage 2: {stage2['hits']} hits; individuals {stage2['individuals']}; "
        f"dobs only {buckets['dobs_only']}; dobs+note {buckets['dobs_and_note']}; "
        f"note only {buckets['note_only']}; search {buckets['search_result']}; "
        f"unknown {buckets['unknown']}; "
        f"note statements {stage2['note_birth_statements']}; "
        f"deceased {stage2['deceased']} undated {stage2['deceased_undated']}; "
        f"reports {stage2['dated_report_lines']} lines / {stage2['dated_report_hits']} hits; "
        f"llm calls {stage2['llm_calls']}; {stage2['elapsed_seconds']}s"
    )
    practice = stage2.get("practice")
    if practice:
        print(
            f"practice: individuals {practice['individual_agree']}/{practice['individual']}; "
            f"companies {practice['company_agree']}/{practice['company']}"
        )
    resolution = summary["alert_resolution"]
    status = resolution["status"]
    print(
        f"stage 3: {resolution['alerts']} alerts; "
        + ", ".join(f"{key} {status[key]}" for key in sorted(status))
        +         f"; joint {resolution['joint_resolved']}/{resolution['joint_alerts']}; "
        + f"clean {resolution['resolution_clean']}; "
        + f"{stage3['elapsed_seconds']}s"
    )
    alert_practice = resolution.get("practice")
    if alert_practice:
        print(
            f"stage 3 practice: {alert_practice['matched']}/{alert_practice['labels']}"
        )
    print(f"artefacts: {cache_dir}")
    print(f"summary: {output_file}")
    print(
        f"notes flagged {notes['flagged']}/{notes['notes']}"
    )
    return 0


def _alert_resolution(stage3: dict) -> dict:
    """Stable Stage 3 counts. Elapsed time stays on stdout, not in this object."""
    kept = {
        "alerts": stage3["alerts"],
        "flags": stage3["flags"],
        "fragility_flags": stage3["fragility_flags"],
        "joint_alerts": stage3["joint_alerts"],
        "joint_resolved": stage3["joint_resolved"],
        "linked_alerts": stage3["linked_alerts"],
        "method": stage3["method"],
        "resolution_clean": stage3["resolution_clean"],
        "resolution_method": stage3["resolution_method"],
        "resolution_quality": stage3["resolution_quality"],
        "resolution_status": stage3["resolution_status"],
        "status": stage3["status"],
        "unlinked_alerts": stage3["unlinked_alerts"],
        "unlinked_status": stage3["unlinked_status"],
    }
    if "practice" in stage3:
        kept["practice"] = stage3["practice"]
    return kept
