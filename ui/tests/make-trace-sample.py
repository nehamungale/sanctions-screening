#!/usr/bin/env python3
"""Append the Stage 4 alert summaries to fixtures/trace.sample.jsonl, as the real pipeline does,
and write fixtures/trace-crosscheck.sample.jsonl: the same trace with one summary deliberately wrong.

The hit lines in the fixture are hand-written synthetic records in the stage4 trace shape
(system/stage4/trace.py). The summary lines are computed with the repo's own roll-up
(system/stage4/rollup.py) from those hit lines and fixtures/alerts.sample.jsonl. In the crosscheck
copy (?sample=crosscheck) one is broken so the UI's cross-check has a disagreement to show:

  A-SYN009  the pipeline would say NEEDS_REVIEW (H-SYN014 not decided); the crosscheck copy says
            CLEARED. The UI must still show Needs review: summaries never make an alert Cleared.

    python3 tests/make-trace-sample.py [path/to/repo checkout]   (read-only; no bytecode written)
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
UI = Path(__file__).resolve().parent.parent
REPO = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REPRO_REPO", "/workspace/review_repo"))
sys.path.insert(0, str(REPO / "system"))
from stage4.rollup import roll_up  # noqa: E402

trace = UI / "fixtures/trace.sample.jsonl"
rows = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
hits = [row for row in rows if "alert_status" not in row]
alerts = [json.loads(line) for line in (UI / "fixtures/alerts.sample.jsonl").read_text().splitlines() if line.strip()]
decisions = {
    h["hit_id"]: {
        "decision": h["verdict"]["decision"],
        "reason_code": h["verdict"]["reason_code"],
        "fragility": h["badges"]["fragility"],
        "missing": None if h["verdict"]["decision"] != "REVIEW" else (h["steps"][-1].get("why") or None),
        "not_decided": h["not_decided"],
        "errored": h["not_decided"] and h["hit_id"] == "H-SYN014",
    }
    for h in hits
}
summaries = roll_up(alerts, decisions)
dump = lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
trace.write_text("".join(dump(r) + "\n" for r in hits + summaries))
broken = json.loads(json.dumps(summaries))
for s in broken:
    if s["alert_id"] == "A-SYN009":
        s["alert_status"] = "CLEARED"
        s["blocking_hit_ids"] = []
(UI / "fixtures/trace-crosscheck.sample.jsonl").write_text("".join(dump(r) + "\n" for r in hits + broken))
print(f"wrote {len(hits)} hit lines and {len(summaries)} alert summaries (+ the crosscheck copy)")
