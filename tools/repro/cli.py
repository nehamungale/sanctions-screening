"""Command line for the reproducibility report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.repro.report import ReproError, default_system_run, report_from_files, run_and_report, stamp_now, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.repro",
        description=(
            "Compare N screening runs (N >= 2, normally 5) and write repro.json. "
            "Pass output JSONL files, trace JSONL files, or both. "
            "Or rerun system/run and then build the report."
        ),
    )
    parser.add_argument("--outputs", nargs="+", metavar="FILE", help="one JSONL output per run, in run order")
    parser.add_argument("--traces", nargs="+", metavar="FILE", help="one JSONL trace per run, in the same order")
    parser.add_argument("--llm-off-output", metavar="FILE", help="extra output from a run with the LLM switched off")
    parser.add_argument("--out", required=True, help="where to write repro.json")
    parser.add_argument("--generated-at", help="timestamp for meta.generated_at (default: UTC now)")
    parser.add_argument("--run", action="store_true", help="call system/run N times, then build the report")
    parser.add_argument("--data", help="data folder passed to system/run")
    parser.add_argument("--n", type=int, default=5, help="how many times to run (default 5)")
    parser.add_argument("--work-dir", help="directory for per-run output and trace files")
    parser.add_argument("--system-run", help="path to system/run (default: <repo>/system/run)")
    parser.add_argument(
        "--capture-traces",
        action="store_true",
        help="with --run, set TRACE_PATH to a per-run trace file",
    )
    parser.add_argument(
        "--llm-off",
        action="store_true",
        help="with --run, add one system/run with USE_LLM_NOTES=0 and SANCTIONS_LLM=0",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    generated_at = args.generated_at or stamp_now()
    try:
        if args.run:
            if args.outputs or args.traces or args.llm_off_output:
                raise ReproError("with --run, do not also pass --outputs, --traces, or --llm-off-output")
            if not args.data or not args.work_dir:
                raise ReproError("--run requires --data and --work-dir")
            report = run_and_report(
                args.data,
                args.n,
                Path(args.work_dir),
                Path(args.system_run) if args.system_run else default_system_run(),
                args.capture_traces,
                args.llm_off,
                generated_at,
            )
        else:
            if args.capture_traces or args.llm_off:
                raise ReproError("--capture-traces and --llm-off are only used with --run")
            if not args.data and not args.outputs and not args.traces:
                raise ReproError("pass --outputs and/or --traces (at least 2 runs), or use --run")
            if args.data or args.work_dir or args.system_run:
                raise ReproError("--data, --work-dir, and --system-run are only used with --run")
            report = report_from_files(
                [Path(path) for path in args.outputs] if args.outputs else None,
                [Path(path) for path in args.traces] if args.traces else None,
                Path(args.llm_off_output) if args.llm_off_output else None,
                generated_at,
            )
        write_report(report, Path(args.out))
    except ReproError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    summary = report["summary"]
    metric = summary["judges_metric"]
    metric_text = "n/a" if metric is None else f"{metric:.4f}"
    print(
        f"repro: {summary['n_runs']} runs, {summary['n_hits']} hits, "
        f"judges_metric {metric_text}, "
        f"decision flips {summary['decision_flip_hits']}, "
        f"code flips {summary['code_only_flip_hits']}, "
        f"strict {summary['strict_change_hits']}, "
        f"missing {summary['missing_hits']}"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
