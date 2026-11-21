#!/usr/bin/env python3
"""Regenerate fixtures/repro.sample.json and fixtures/repro-flipped.sample.json.

Builds five synthetic runs (outputs + traces) from fixtures/trace.sample.jsonl in a temp
folder and runs the repo's own report tool on them, so the fixtures match
tools/repro/repro.schema.json exactly. Read-only on the repo (no bytecode written).

    python3 tests/make-repro-samples.py [path/to/sanctions-screening clone]
"""
import copy, json, os, subprocess, sys, tempfile
from pathlib import Path

UI = Path(__file__).resolve().parent.parent
REPO = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REPRO_REPO", "/workspace/review_repo"))
BASE = [json.loads(l) for l in (UI / "fixtures/trace.sample.jsonl").read_text().splitlines() if l.strip()]
HEADER = {
    "run_id": None, "git_sha": "0000000000000000000000000000000000000001", "rules_version": "r1.0",
    "hashes": {"policy": "policy-hash-1", "name_variants": "variants-hash-1",
               "prompts": {"read_note": "prompt-hash-1"}, "input": "input-hash-1"},
    "model": "example/model-a", "provider": "example-provider", "python_version": "3.12.3",
}

# Official output fields (output.schema.json); anything else in verdict stays out.
OUTPUT_FIELDS = ["decision", "reason_code", "reason", "evidence", "customer_record_id"]

def set_verdict(rec, decision, code):
    rec["verdict"]["decision"], rec["verdict"]["reason_code"] = decision, code

def runs(flipped: bool):
    out = []
    for i in range(5):
        recs = {r["hit_id"]: copy.deepcopy(r) for r in BASE}
        # Unstable but no clear involved: an LLM-touched REVIEW hit reads as SAME_ENTITY in run 5.
        if i == 4:
            set_verdict(recs["H-SYN006"], "SAME_ENTITY", "NAME_DOB_MATCH")
        # Evidence-only change: same verdict and code, one extra evidence id in run 3.
        if i == 2:
            recs["H-SYN004"]["verdict"]["evidence"].append("H-SYN004#sources")
        # Variant: a clear (LOCATION_MISMATCH) turns into REVIEW in run 3.
        if flipped and i == 2:
            set_verdict(recs["H-SYN008"], "REVIEW", "INSUFFICIENT_DATA")
        out.append(list(recs.values()))
    return out

def build(flipped: bool, target: Path):
    with tempfile.TemporaryDirectory() as d:
        outputs, traces = [], []
        for i, recs in enumerate(runs(flipped)):
            o, t = Path(d) / f"run{i+1}.jsonl", Path(d) / f"trace{i+1}.jsonl"
            o.write_text("".join(json.dumps({"hit_id": r["hit_id"], "alert_id": r["alert_id"], **{k: r["verdict"].get(k) for k in OUTPUT_FIELDS}}) + "\n" for r in recs))
            t.write_text(json.dumps({**HEADER, "run_id": f"run-{i+1}"}) + "\n" + "".join(json.dumps(r) + "\n" for r in recs))
            outputs.append(str(o)); traces.append(str(t))
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, "-m", "tools.repro", "--outputs", *outputs, "--traces", *traces,
                        "--generated-at", "2026-11-21T00:00:00Z", "--out", str(target)], cwd=REPO, env=env, check=True)
    print("wrote", target)

build(False, UI / "fixtures/repro.sample.json")
build(True, UI / "fixtures/repro-flipped.sample.json")
