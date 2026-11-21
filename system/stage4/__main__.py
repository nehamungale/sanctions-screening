"""``python -m stage4 <data folder> <output file>`` using the Stage 1–3 cache."""

from __future__ import annotations

import os
import sys

from shared.time_budget import arm_run_deadline
from stage4.build import run_stage4


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m stage4 <data folder> <output file>", file=sys.stderr)
        return 2
    arm_run_deadline()
    cache_dir = os.environ.get("SANCTIONS_CACHE", "working")
    summary = run_stage4(args[0], cache_dir, args[1])
    print(
        f"stage 4: {summary['hits']} hits; "
        + ", ".join(f"{key} {summary['decisions'][key]}" for key in sorted(summary["decisions"]))
        + f"; {summary['elapsed_seconds']}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
