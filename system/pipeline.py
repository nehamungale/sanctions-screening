"""Run Stages 1 to 4. The output file is one JSON line per hit."""

from __future__ import annotations

import json
import os
import sys
import traceback

from shared.io import load_table
from shared.llm_client import OpenRouterClient
from shared.time_budget import SHARED_TIME_CAP_SECONDS, arm_run_deadline, deadline_fired
from stage1.build import run_stage1
from stage1.cli import ARTEFACTS as STAGE1_ARTEFACTS
from stage1.llm import llm_enabled as notes_llm_enabled
from stage2.build import run_stage2
from stage2.llm import llm_enabled as hits_llm_enabled
from stage3.cli import run_stage3
from stage4.build import run_stage4
from stage4.output import dumps_jsonl, line_from


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: system/run <data folder> <output file>", file=sys.stderr)
        return 2
    data_folder, output_file = args
    cache_dir = os.environ.get("SANCTIONS_CACHE", "working")
    # One client, one clock, and one run budget for every stage that calls out.
    # The shared cap is 1,200s (20 minutes). The run deadline at 25 minutes
    # is the last stop before the brief's 30 minutes.
    arm_run_deadline()
    try:
        client = OpenRouterClient() if notes_llm_enabled() or hits_llm_enabled() else None
        stage1 = run_stage1(data_folder, cache_dir, client=client)
        stage2 = run_stage2(data_folder, cache_dir, client=client)
        stage3 = run_stage3(
            data_folder,
            os.path.join(cache_dir, "alert_resolution.jsonl"),
            cache_dir,
        )
        stage4 = run_stage4(data_folder, cache_dir, output_file, client=client)
    except Exception as error:  # noqa: BLE001 - any failure must still leave a valid output file
        traceback.print_exc()
        written = write_fallback(data_folder, output_file)
        if written is None:
            print(f"ERROR: {type(error).__name__}: {error}. No output written.", file=sys.stderr)
            return 2
        print(
            f"ERROR: {type(error).__name__}: {error}. Wrote {written} REVIEW lines to {output_file} "
            "so that no hit is cleared without a decision.",
            file=sys.stderr,
        )
        return 0
    try:
        _report(stage1, stage2, stage3, stage4, cache_dir, output_file)
    except Exception:  # noqa: BLE001 - the output file is already complete
        traceback.print_exc()
    return 0


def write_fallback(data_folder: str, output_file: str) -> int | None:
    """One REVIEW line per hit, used only when a stage failed. ``None`` if hits cannot be read."""
    try:
        hits = load_table(data_folder, "hits.jsonl")
    except Exception:  # noqa: BLE001
        return None
    lines = []
    seen = set()
    for hit in hits:
        hit_id = hit.get("hit_id")
        if not hit_id or hit_id in seen:
            continue
        seen.add(hit_id)
        lines.append(line_from(
            hit_id,
            hit.get("alert_id"),
            "REVIEW",
            "INSUFFICIENT_DATA",
            None,
            "The system could not finish processing this alert, so no comparison was made. "
            "The hit is left for review.",
            [hit["alert_id"]] if hit.get("alert_id") else [],
        ))
    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(dumps_jsonl(lines))
    return len(lines)


def _report(stage1: dict, stage2: dict, stage3: dict, stage4: dict, cache_dir: str, output_file: str) -> None:
    """Write ``run_summary.json`` to the cache and print the run's counts."""
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
        "deadline_fired": deadline_fired(),
        "decisions": stage4["decisions"],
        "practice_score": stage4.get("practice"),
        "review_rate": stage4["review_rate"],
        "rules_version": stage4["rules_version"],
        "shared_time_cap_seconds": SHARED_TIME_CAP_SECONDS,
        "stage": 4,
        "stage4_seconds": stage4["elapsed_seconds"],
        "stages": [1, 2, 3, 4],
        "veto": stage4["llm_veto"],
    }
    os.makedirs(cache_dir, exist_ok=True)
    summary_path = os.path.join(cache_dir, "run_summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
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
    decisions = stage4["decisions"]
    print(
        f"stage 4: {stage4['hits']} hits; "
        + ", ".join(f"{key} {decisions[key]}" for key in sorted(decisions))
        + f"; review rate {stage4['review_rate']}; {stage4['elapsed_seconds']}s"
    )
    scored = stage4.get("practice")
    if scored:
        print(
            f"stage 4 practice: {scored['right']}/{scored['labels']} decisions; "
            f"reason codes {scored['reason_codes_on_right']}/{scored['right'] or 0} on right; "
            f"unsafe {scored['unsafe']}; score {scored['decision_score']}"
        )
    print(f"artefacts: {cache_dir}")
    print(f"output: {output_file}")
    print(f"summary: {summary_path}")
    print(
        f"notes flagged {notes['flagged']}/{notes['notes']}"
    )


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
