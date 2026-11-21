"""Grade screening output files against the practice labels.

Usage (from the repo root):
  python -m tools.eval --data dev --outputs output/dev.jsonl
  python -m tools.eval --data dev --outputs run1.jsonl run2.jsonl run3.jsonl run4.jsonl run5.jsonl \\
      --report eval-report.md --metrics eval-metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .constants import DEFAULT_DATA_DIR, LABELS_FILENAME, NAME_VARIANTS_FILENAME
from .data import DataIndex
from .metrics import (
    grade_accuracy,
    grade_error_analysis,
    grade_explainability,
    grade_reproducibility,
    per_run_score_summary,
    primary_row_map,
    _row_by_hit,
)
from .parse import load_labels, load_output_files
from .report import label_inventory, render_report


def grade(
    output_paths: list[Path],
    labels_path: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    policy_path: Path | None = None,
    boilerplate_min: int = 3,
) -> dict:
    """``data_dir`` is the data folder (dev/*.jsonl, or workbook CSVs)."""
    if not output_paths:
        raise ValueError("At least one output file is required.")
    data_dir = Path(data_dir)
    if labels_path is None:
        labels_path = data_dir / LABELS_FILENAME
    if policy_path is None:
        policy_path = data_dir / NAME_VARIANTS_FILENAME
    labels = load_labels(labels_path)
    data = DataIndex(data_dir, policy_path)
    runs = load_output_files(output_paths)
    repro = grade_reproducibility(runs)
    run_accuracies = [grade_accuracy(labels, _row_by_hit(rows)) for _, rows in runs]
    repro.update(per_run_score_summary([name for name, _ in runs], run_accuracies))
    predicted = primary_row_map(runs)
    explain = grade_explainability(runs[0][1], data, boilerplate_min=boilerplate_min)
    accuracy = run_accuracies[0]
    analysis = grade_error_analysis(labels, accuracy, data)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M") + " Europe/London"
    report_md = render_report(runs, labels, repro, explain, accuracy, analysis, generated_at)
    metrics = {
        "generated_at": generated_at,
        "outputs": [str(p) for p in output_paths],
        "labels_path": str(labels_path),
        "data_dir": str(data_dir),
        "label_inventory": label_inventory(labels, analysis),
        "reproducibility": dict(repro),
        "explainability": {k: v for k, v in explain.items() if k != "per_hit"},
        "explainability_per_hit": explain["per_hit"],
        "accuracy": {k: v for k, v in accuracy.items() if k != "per_hit"},
        "accuracy_per_hit": accuracy["per_hit"],
        "error_analysis": {
            "by_evidence_path": analysis["by_evidence_path"],
            "by_edge_tag": analysis["by_edge_tag"],
            "by_gold_decision": analysis["by_gold_decision"],
            "path_category_counts": analysis["path_category_counts"],
            "edge_tag_counts": analysis["edge_tag_counts"],
            "label_path_categories": analysis["label_path_categories"],
            "label_edge_tags": analysis["label_edge_tags"],
        },
    }
    return {
        "metrics": metrics,
        "report_md": report_md,
        "repro": repro,
        "explain": explain,
        "accuracy": accuracy,
    }


def write_outputs(result: dict, report_path: Path | None, metrics_path: Path | None) -> None:
    """Reports hold identity facts from the data folder: keep them out of git."""
    if report_path:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(result["report_md"], encoding="utf-8")
    if metrics_path:
        metrics_path = Path(metrics_path)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(
            json.dumps(result["metrics"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Grade sanctions name-screening system outputs against the 50 practice labels.",
    )
    p.add_argument(
        "--outputs", nargs="+", type=Path, default=None,
        help="One or more output files (CSV, JSON or JSONL). N≥5 enables the reproducibility score.",
    )
    p.add_argument(
        "--outputs-dir", type=Path, default=None,
        help="Directory of output files (sorted by name). Combined with --outputs if both are given.",
    )
    p.add_argument(
        "--data", "--sheets", dest="data", type=Path, default=DEFAULT_DATA_DIR,
        help="Data folder (dev/ with *.jsonl). Default: dev",
    )
    p.add_argument(
        "--labels", type=Path, default=None,
        help=f"Practice labels (JSONL, JSON or CSV). Default: <data>/{LABELS_FILENAME}",
    )
    p.add_argument(
        "--policy", type=Path, default=None,
        help=f"Name variants JSON (or Policy.txt). Default: <data>/{NAME_VARIANTS_FILENAME}",
    )
    p.add_argument("--report", type=Path, default=None, help="Write a Markdown report here (optional).")
    p.add_argument("--metrics", type=Path, default=None, help="Write metrics JSON here (optional).")
    p.add_argument(
        "--boilerplate-min", type=int, default=3,
        help="Flag an explanation as boilerplate if this many hits share the same wording.",
    )
    return p


def collect_output_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    if args.outputs:
        paths.extend(args.outputs)
    if args.outputs_dir:
        directory = Path(args.outputs_dir)
        if not directory.is_dir():
            raise FileNotFoundError(f"Outputs directory not found: {directory}")
        found = sorted(
            p for p in directory.iterdir()
            if p.is_file()
            and p.suffix.lower() in {".json", ".jsonl", ".ndjson", ".csv"}
            and not p.name.startswith(".")
        )
        if not found:
            raise FileNotFoundError(f"No JSON/JSONL/CSV files in {directory}")
        paths.extend(found)
    if not paths:
        raise SystemExit("Provide --outputs and/or --outputs-dir.")
    return paths


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = collect_output_paths(args)
    result = grade(
        output_paths=paths,
        labels_path=args.labels,
        data_dir=args.data,
        policy_path=args.policy,
        boilerplate_min=args.boilerplate_min,
    )
    write_outputs(result, args.report, args.metrics)
    acc = result["accuracy"]
    repro = result["repro"]
    explain = result["explain"]
    if args.report:
        print(f"Wrote {args.report}")
    if args.metrics:
        print(f"Wrote {args.metrics}")
    print(
        f"decision_score={acc['decision_score']}  "
        f"cost={acc['decision_cost']}  "
        f"cost_all_review={acc['cost_all_review']}  "
        f"decision_accuracy={acc['decision_accuracy']}  "
        f"reason_accepted={acc['reason_code_accepted_rate']}  "
        f"evidence_recall_macro={acc['evidence_recall_macro']}  "
        f"evidence_precision_macro={acc['evidence_precision_macro']}  "
        f"false_clears={acc['n_false_clears']}  "
        f"review_overuse={acc['n_review_overuse']}"
    )
    print(
        f"repro_runs={repro['n_runs']}  "
        f"official_repro_rate={repro.get('official_repro_rate')}  "
        f"differing_hits={repro['n_hits_differing']}  "
        f"explainability_issues={explain['n_hits_with_issues']}/{explain['n_rows']}"
    )
    return 0
