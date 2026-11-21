"""Command-line entry for Stage 1."""

from __future__ import annotations

import json
import os
import sys

from stage1.build import run_stage1

ARTEFACTS = (
    "person_golden.jsonl",
    "index_record_id.json",
    "index_account_id.json",
    "index_login_handle.json",
    "index_email.json",
    "index_name.json",
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: system/run <data folder> <output file>", file=sys.stderr)
        return 2
    data_folder, output_file = args
    cache_dir = os.environ.get("SANCTIONS_CACHE", "working")
    try:
        stats = run_stage1(data_folder, cache_dir)
    except FileNotFoundError as error:
        print(f"missing input: {error}", file=sys.stderr)
        return 2
    elapsed = stats.get("elapsed_seconds")
    summary = {
        "artefacts": list(ARTEFACTS),
        "cache_dir": cache_dir,
        "doc_edges": stats["doc_edges"],
        "doc_edges_new_components": stats["doc_edges_new_components"],
        "multi_record_persons": stats["multi_record_persons"],
        "notes": stats["notes"],
        "persons": stats["persons"],
        "phone_dob_edges": stats["phone_dob_edges"],
        "records": stats["records"],
        "stage": 1,
    }
    parent = os.path.dirname(output_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    notes = stats["notes"]
    print(
        f"stage 1: {stats['records']} records -> {stats['persons']} persons; "
        f"phone+dob edges {stats['phone_dob_edges']}; doc edges {stats['doc_edges']} "
        f"({stats['doc_edges_new_components']} new); "
        f"notes flagged {notes['flagged']}/{notes['notes']}; "
        f"kyc name {notes['kyc_name']}/{notes['kyc']} dob {notes['kyc_dob']}/{notes['kyc']} "
        f"country {notes['kyc_doc_country']}/{notes['kyc']}; "
        f"residence {notes['residence']}; noise {notes['noise']}; "
        f"{elapsed}s"
    )
    print(f"artefacts: {cache_dir}")
    print(f"summary: {output_file}")
    return 0
