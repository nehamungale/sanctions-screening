"""Synthetic reproducibility cases. No participant data."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from tools.repro.cli import main
from tools.repro.example import EXAMPLE_STAMP, build_example_report
from tools.repro.report import (
    assemble_run,
    build_report,
    dump_report,
    report_from_files,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PATH = ROOT / "tools" / "repro" / "repro.example.json"
STAMP = "2026-01-01T00:00:00+00:00"


def output(hit_id, decision="REVIEW", code="INSUFFICIENT_DATA", evidence=None, customer="CUS-000001", alert=None, reason="UNIQUE_REASON_SENTINEL"):
    return {
        "alert_id": alert or "A-" + hit_id.split("-", 1)[1],
        "customer_record_id": customer,
        "decision": decision,
        "evidence": ["KYC-000001"] if evidence is None else evidence,
        "hit_id": hit_id,
        "reason": reason,
        "reason_code": code,
    }


def trace_for(row, steps=None, llm_used=False, fragility="solid", facts=None, comparison=None, llm_calls=None, extra=None):
    record = {
        "alert_id": row["alert_id"],
        "badges": {"fragility": fragility, "llm_used": llm_used},
        "hit_id": row["hit_id"],
        "llm_calls": llm_calls or [],
        "steps": steps or [],
        "trace_schema": 1,
        "verdict": {
            "customer_record_id": row["customer_record_id"],
            "decision": row["decision"],
            "evidence": list(row["evidence"]),
            "reason": row["reason"],
            "reason_code": row["reason_code"],
        },
    }
    if facts is not None:
        record["identity"] = {"facts": facts}
    if comparison is not None:
        record["comparison"] = comparison
    if extra:
        record.update(extra)
    return record


def header(git_sha="a" * 40, prompts=None):
    return {
        "git_sha": git_sha,
        "hashes": {
            "input": "input-hash",
            "name_variants": "variants-hash",
            "policy": "policy-hash",
            "prompts": {"extract": "e1", "read": "e2"} if prompts is None else prompts,
        },
        "model": "openai/gpt-4o-mini",
        "provider": "ExampleProvider",
        "python_version": "3.12.3",
        "record_type": "run_header",
        "rules_version": "r1.0",
        "timestamp": "2020-01-01T00:00:00Z",
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def report_from_rows(run_rows, headers=None, stamp=STAMP, traces=None, llm_off=None):
    runs = []
    for index, rows in enumerate(run_rows):
        by_id = {row["hit_id"]: row for row in rows}
        trace_map = {}
        if traces is not None:
            trace_map = {row["hit_id"]: row for row in traces[index]}
        run_header = None if headers is None else headers[index]
        runs.append(assemble_run(f"run-{index + 1:02d}", run_header, by_id, trace_map))
    off = None
    if llm_off is not None:
        off = assemble_run("llm-off", None, {row["hit_id"]: row for row in llm_off}, {})
    return build_report(
        runs,
        off,
        stamp,
        {
            "llm_off_output": llm_off is not None,
            "outputs": True,
            "traces": traces is not None,
        },
    )


def policy_steps(dob="fired", location="not_fired"):
    return [
        {"quote": "QUOTE_SENTINEL_SHOULD_NOT_LEAK", "result": dob, "rule": "DOB_MISMATCH", "why": "dob rule"},
        {"result": "not_fired", "rule": "ENTITY_TYPE_MISMATCH", "why": "same type"},
        {"result": location, "rule": "LOCATION_MISMATCH", "why": "location rule"},
        {"result": "not_fired", "rule": "DECEASED", "why": "no death date"},
        {"result": "not_fired", "rule": "TEMPORAL_IMPOSSIBILITY", "why": " age ok "},
    ]


class ReportTests(unittest.TestCase):
    def test_five_identical_runs_metric_one(self):
        rows = [
            output("H-00000A", "DIFFERENT_ENTITY", "DOB_MISMATCH"),
            output("H-000001", "SAME_ENTITY", "NAME_DOB_MATCH"),
            output("H-000002", "REVIEW", "INSUFFICIENT_DATA"),
        ]
        report = report_from_rows([rows, rows, rows, rows, rows])
        self.assertEqual(report["summary"]["n_runs"], 5)
        self.assertEqual(report["summary"]["n_hits"], 3)
        self.assertEqual(report["summary"]["judges_metric"], 1.0)
        self.assertEqual(report["summary"]["judges_stable_hits"], 3)
        self.assertEqual(report["summary"]["decision_flip_hits"], 0)
        self.assertEqual(report["summary"]["code_only_flip_hits"], 0)
        self.assertEqual(report["summary"]["strict_change_hits"], 0)
        self.assertEqual(report["summary"]["missing_hits"], 0)
        self.assertEqual([hit["flip_type"] for hit in report["hits"]], ["none", "none", "none"])
        self.assertTrue(all(hit["stable"] for hit in report["hits"]))
        self.assertEqual([hit["hit_id"] for hit in report["hits"]], ["H-000001", "H-000002", "H-00000A"])
        self.assertEqual(len(report["heatmap"]["decisions"]), 3)
        self.assertEqual(len(report["heatmap"]["decisions"][0]), 5)
        self.assertEqual(
            report["summary"]["decision_counts_per_run"],
            [{"DIFFERENT_ENTITY": 1, "REVIEW": 1, "SAME_ENTITY": 1}] * 5,
        )
        self.assertIsNone(report["config_check"]["runs"])
        self.assertFalse(report["config_check"]["available"])
        self.assertTrue(all(value is None for value in report["config_check"]["all_identical"].values()))
        self.assertIsNone(report["llm_sensitivity"])
        blob = dump_report(report)
        self.assertNotIn("UNIQUE_REASON_SENTINEL", blob)
        self.assertNotIn("timestamp", blob)
        self.assertEqual(report["meta"]["generated_at"], STAMP)
        self.assertEqual(blob, dump_report(json.loads(blob)))

    def test_decision_flip(self):
        stable = output("H-000001", "REVIEW", "INSUFFICIENT_DATA")
        left = output("H-000002", "DIFFERENT_ENTITY", "DOB_MISMATCH")
        right = output("H-000002", "REVIEW", "INSUFFICIENT_DATA")
        report = report_from_rows([[stable, left], [stable, right]])
        flips = {hit["hit_id"]: hit for hit in report["hits"]}
        self.assertEqual(flips["H-000002"]["flip_type"], "decision")
        self.assertEqual(flips["H-000002"]["per_run"], [
            ["DIFFERENT_ENTITY", "DOB_MISMATCH"],
            ["REVIEW", "INSUFFICIENT_DATA"],
        ])
        self.assertFalse(flips["H-000002"]["judges_stable"])
        self.assertEqual(flips["H-000002"]["modal_decision"], "REVIEW")
        self.assertEqual(report["summary"]["decision_flip_hits"], 1)
        self.assertEqual(report["summary"]["code_only_flip_hits"], 0)
        self.assertEqual(report["summary"]["judges_metric"], 0.5)
        self.assertEqual(report["ui"]["filters"]["flipped_only"], ["H-000002"])
        self.assertEqual(report["ui"]["filters"]["decision_flip"], ["H-000002"])

    def test_code_only_flip(self):
        left = output("H-000010", "REVIEW", "INSUFFICIENT_DATA")
        right = output("H-000010", "REVIEW", "AMBIGUOUS_CUSTOMER_RECORD")
        report = report_from_rows([[left], [right], [left]])
        hit = report["hits"][0]
        self.assertEqual(hit["flip_type"], "code")
        self.assertTrue(hit["changes"]["reason_code"])
        self.assertFalse(hit["changes"]["decision"])
        self.assertEqual(report["summary"]["code_only_flip_hits"], 1)
        self.assertEqual(report["summary"]["decision_flip_hits"], 0)
        self.assertEqual(report["summary"]["strict_change_hits"], 0)
        self.assertEqual(report["summary"]["judges_metric"], 0.0)
        self.assertEqual(hit["modal_reason_code"], "INSUFFICIENT_DATA")

    def test_evidence_and_customer_only_changes_keep_judges_metric(self):
        evidence_a = output("H-000001", "DIFFERENT_ENTITY", "LOCATION_MISMATCH", ["KYC-000001"])
        evidence_b = output("H-000001", "DIFFERENT_ENTITY", "LOCATION_MISMATCH", ["KYC-000002", "KYC-000001"])
        customer_a = output("H-000002", "SAME_ENTITY", "NAME_DOB_MATCH", customer="CUS-000001")
        customer_b = output("H-000002", "SAME_ENTITY", "NAME_DOB_MATCH", customer="CUS-000002")
        report = report_from_rows(
            [[evidence_a, customer_a], [evidence_a, customer_a], [evidence_b, customer_b]]
        )
        by_id = {hit["hit_id"]: hit for hit in report["hits"]}
        self.assertEqual(report["summary"]["judges_metric"], 1.0)
        self.assertEqual(report["summary"]["decision_flip_hits"], 0)
        self.assertEqual(report["summary"]["code_only_flip_hits"], 0)
        self.assertEqual(report["summary"]["strict_change_hits"], 2)
        self.assertEqual(report["summary"]["strict_change_hit_ids"], ["H-000001", "H-000002"])
        self.assertEqual(by_id["H-000001"]["flip_type"], "evidence")
        self.assertTrue(by_id["H-000001"]["judges_stable"])
        self.assertEqual(by_id["H-000001"]["evidence_per_run"][2], ["KYC-000001", "KYC-000002"])
        self.assertEqual(by_id["H-000002"]["flip_type"], "evidence")
        self.assertTrue(by_id["H-000002"]["changes"]["customer_record_id"])
        self.assertIsNone(by_id["H-000001"]["first_divergent_step"])

    def test_hit_missing_in_one_run(self):
        keep = output("H-000001", "REVIEW", "INSUFFICIENT_DATA")
        gone = output("H-000002", "DIFFERENT_ENTITY", "DECEASED")
        report = report_from_rows([[keep, gone], [keep]])
        by_id = {hit["hit_id"]: hit for hit in report["hits"]}
        self.assertEqual(by_id["H-000002"]["flip_type"], "other")
        self.assertEqual(by_id["H-000002"]["missing_from_runs"], [1])
        self.assertIsNone(by_id["H-000002"]["per_run"][1])
        self.assertFalse(by_id["H-000002"]["judges_stable"])
        self.assertTrue(by_id["H-000001"]["stable"])
        self.assertEqual(report["summary"]["missing_hits"], 1)
        self.assertEqual(report["summary"]["hits_missing_from_some_runs"], ["H-000002"])
        self.assertEqual(report["summary"]["decision_flip_hits"], 0)
        self.assertEqual(report["summary"]["strict_change_hits"], 0)
        self.assertEqual(report["summary"]["judges_metric"], 0.5)
        self.assertEqual(report["summary"]["decision_counts_per_run"][0]["DIFFERENT_ENTITY"], 1)
        self.assertEqual(report["summary"]["decision_counts_per_run"][1]["DIFFERENT_ENTITY"], 0)
        self.assertIsNone(report["heatmap"]["decisions"][1][1])
        self.assertIn("H-000002", report["ui"]["filters"]["flipped_only"])

    def test_config_check_flags_different_git_sha(self):
        row = output("H-000001", "REVIEW", "INSUFFICIENT_DATA")
        traced = trace_for(row)
        headers = [header("a" * 40) for _ in range(5)]
        headers[2] = header("b" * 40, prompts={"read": "e2", "extract": "e1"})
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            paths = []
            for index, run_header in enumerate(headers):
                path = folder / f"trace-{index}.jsonl"
                write_jsonl(path, [run_header, traced])
                paths.append(path)
            report = report_from_files(None, paths, None, STAMP)
        self.assertTrue(report["config_check"]["available"])
        flags = report["config_check"]["all_identical"]
        self.assertFalse(flags["git_sha"])
        self.assertTrue(flags["rules_version"])
        self.assertTrue(flags["policy_hash"])
        self.assertTrue(flags["name_variants_hash"])
        self.assertTrue(flags["prompt_hashes"])
        self.assertTrue(flags["input_hash"])
        self.assertTrue(flags["model"])
        self.assertTrue(flags["provider"])
        self.assertTrue(flags["python_version"])
        self.assertEqual(report["config_check"]["runs"][2]["git_sha"], "b" * 40)
        self.assertNotIn("timestamp", json.dumps(report["config_check"]))
        self.assertNotIn("run_id", json.dumps(report))
        self.assertEqual(report["summary"]["judges_metric"], 1.0)

    def test_trace_divergence_at_known_step(self):
        row = output("H-000001", "DIFFERENT_ENTITY", "DOB_MISMATCH")
        left = trace_for(row, policy_steps("fired", "not_fired"))
        right = trace_for(row, policy_steps("not_fired", "fired"))
        # Input order is scrambled; stable order still puts DOB_MISMATCH at index 3.
        report = report_from_rows([[row], [row]], traces=[[left], [right]])
        hit = report["hits"][0]
        self.assertEqual(hit["flip_type"], "other")
        self.assertTrue(hit["judges_stable"])
        self.assertTrue(hit["changes"]["steps"])
        self.assertFalse(hit["changes"]["evidence"])
        self.assertEqual(report["summary"]["judges_metric"], 1.0)
        self.assertEqual(report["summary"]["strict_change_hits"], 1)
        step = hit["first_divergent_step"]
        self.assertEqual(step["rule"], "DOB_MISMATCH")
        self.assertEqual(step["order_index"], 3)
        self.assertEqual(step["occurrence"], 0)
        self.assertEqual(step["values_per_run"][0]["result"], "fired")
        self.assertEqual(step["values_per_run"][1]["result"], "not_fired")
        self.assertNotIn("quote", step["values_per_run"][0])
        blob = dump_report(report)
        self.assertNotIn("QUOTE_SENTINEL_SHOULD_NOT_LEAK", blob)

    def test_reordered_steps_and_quote_text_are_stable(self):
        row = output("H-000001", "DIFFERENT_ENTITY", "DOB_MISMATCH")
        steps_a = [
            {"result": "not_fired", "rule": "ZULU", "why": "later"},
            {"result": "fired", "rule": "DOB_MISMATCH", "why": "dob rule"},
            {"result": "not_fired", "rule": "ALPHA", "why": "earlier"},
        ]
        steps_b = [
            {"result": "not_fired", "rule": "ALPHA", "why": " earlier "},
            {"quote": "other span", "result": "fired", "rule": "DOB_MISMATCH", "why": "dob rule"},
            {"result": "not_fired", "rule": "ZULU", "why": "later"},
        ]
        facts = {"dob": {"quote": "QUOTE_SENTINEL_SHOULD_NOT_LEAK", "source_id": "KYC-000001", "value": "cafe\u0301"}}
        facts_folded = {"dob": {"quote": "different words", "source_id": "KYC-000001", "value": "caf\u00e9"}}
        left = trace_for(row, steps_a, facts=facts, llm_calls=[{"quote": "QUOTE_SENTINEL_SHOULD_NOT_LEAK", "response_id": "1"}])
        right = trace_for(row, steps_b, facts=facts_folded, llm_calls=[{"quote": "else", "response_id": "2"}])
        report = report_from_rows([[row], [row]], traces=[[left], [right]])
        hit = report["hits"][0]
        self.assertTrue(hit["stable"])
        self.assertEqual(hit["flip_type"], "none")
        self.assertEqual(report["summary"]["strict_change_hits"], 0)
        self.assertIsNone(hit["first_divergent_step"])
        self.assertNotIn("QUOTE_SENTINEL_SHOULD_NOT_LEAK", dump_report(report))

    def test_canonical_fact_change_is_strict(self):
        row = output("H-000001", "REVIEW", "INSUFFICIENT_DATA")
        left = trace_for(
            row,
            facts={"dob": {"source_id": "KYC-000001", "value": "year-a"}},
            comparison=[{"customer": "year-a", "dim": "dob", "hit": "year-b", "src": ["H-000001#dobs", "KYC-000001"]}],
        )
        right = trace_for(
            row,
            facts={"dob": {"source_id": "KYC-000001", "value": "year-b"}},
            comparison=[{"customer": "year-a", "dim": "dob", "hit": "year-b", "src": ["KYC-000001", "H-000001#dobs"]}],
        )
        report = report_from_rows([[row], [row]], traces=[[left], [right]])
        hit = report["hits"][0]
        self.assertEqual(report["summary"]["judges_metric"], 1.0)
        self.assertEqual(report["summary"]["strict_change_hits"], 1)
        self.assertEqual(hit["flip_type"], "other")
        self.assertEqual(hit["first_divergent_fact"]["attribute"], "identity.dob")
        self.assertEqual(hit["first_divergent_fact"]["values_per_run"][0]["value"], "year-a")
        self.assertEqual(hit["first_divergent_fact"]["values_per_run"][1]["value"], "year-b")

    def test_llm_sensitivity_against_modal(self):
        same = output("H-000001", "SAME_ENTITY", "NAME_DOB_MATCH")
        review = output("H-000001", "REVIEW", "INSUFFICIENT_DATA")
        steady = output("H-000002", "DIFFERENT_ENTITY", "DOB_MISMATCH")
        off_only = output("H-000003", "REVIEW", "INSUFFICIENT_DATA")
        report = report_from_rows(
            [[same, steady], [same, steady], [same, steady], [review, steady]],
            llm_off=[review, steady, off_only],
        )
        sensitivity = report["llm_sensitivity"]
        self.assertEqual(sensitivity["n_sensitive"], 2)
        self.assertEqual(sensitivity["hit_ids"], ["H-000001", "H-000003"])
        first = sensitivity["hits"][0]
        self.assertEqual(first["llm_on_modal_decision"], "SAME_ENTITY")
        self.assertEqual(first["llm_on_modal_reason_code"], "NAME_DOB_MATCH")
        self.assertEqual(first["llm_off_decision"], "REVIEW")
        self.assertIsNone(sensitivity["hits"][1]["llm_on_modal_decision"])
        self.assertEqual(report["ui"]["filters"]["llm_sensitive"], ["H-000001", "H-000003"])

    def test_flips_split_by_llm_used(self):
        decision_row = output("H-000001", "SAME_ENTITY", "NAME_DOB_MATCH")
        decision_other = output("H-000001", "REVIEW", "INSUFFICIENT_DATA")
        code_row = output("H-000002", "REVIEW", "INSUFFICIENT_DATA")
        code_other = output("H-000002", "REVIEW", "AMBIGUOUS_CUSTOMER_RECORD")
        evidence_row = output("H-000003", "DIFFERENT_ENTITY", "DOB_MISMATCH", ["KYC-000001"])
        evidence_other = output("H-000003", "DIFFERENT_ENTITY", "DOB_MISMATCH", ["KYC-000002"])
        traces = [
            [
                trace_for(decision_row, llm_used=True),
                trace_for(code_row, llm_used=False),
                trace_for(evidence_row, llm_used=None),
            ],
            [
                trace_for(decision_other, llm_used=True),
                trace_for(code_other, llm_used=False),
                trace_for(evidence_other, llm_used=None),
            ],
        ]
        # Badge value None is stored as JSON null and comes back as None.
        traces[0][2]["badges"]["llm_used"] = None
        traces[1][2]["badges"]["llm_used"] = None
        report = report_from_rows(
            [[decision_row, code_row, evidence_row], [decision_other, code_other, evidence_other]],
            traces=traces,
        )
        buckets = report["summary"]["flips_by_llm_used"]
        self.assertEqual(buckets["llm_used"]["decision"], 1)
        self.assertEqual(buckets["not_llm_used"]["code"], 1)
        self.assertEqual(buckets["unknown"]["evidence"], 1)
        self.assertFalse(report["summary"]["judges_flips_all_llm_used"])

    def test_output_trace_mismatch_is_other(self):
        row = output("H-000001", "DIFFERENT_ENTITY", "DOB_MISMATCH")
        drifted = trace_for(output("H-000001", "REVIEW", "INSUFFICIENT_DATA"))
        agreed = trace_for(row)
        report = report_from_rows([[row], [row]], traces=[[agreed], [drifted]])
        hit = report["hits"][0]
        self.assertEqual(hit["per_run"][1][0], "DIFFERENT_ENTITY")
        self.assertEqual(hit["flip_type"], "other")
        self.assertTrue(hit["judges_stable"])
        self.assertEqual(hit["output_trace_mismatch_runs"], [1])

    def test_modal_decision_tie_breaks_toward_review(self):
        report = report_from_rows(
            [
                [output("H-000001", "DIFFERENT_ENTITY", "DOB_MISMATCH")],
                [output("H-000001", "REVIEW", "INSUFFICIENT_DATA")],
            ]
        )
        self.assertEqual(report["hits"][0]["modal_decision"], "REVIEW")

    def test_cli_writes_sorted_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            left = folder / "left.jsonl"
            right = folder / "right.jsonl"
            out = folder / "repro.json"
            write_jsonl(left, [output("H-000002", "REVIEW", "INSUFFICIENT_DATA"), output("H-000001", "REVIEW", "INSUFFICIENT_DATA")])
            write_jsonl(right, [output("H-000001", "REVIEW", "INSUFFICIENT_DATA"), output("H-000002", "SAME_ENTITY", "NAME_DOB_MATCH")])
            code = main(["--outputs", str(left), str(right), "--out", str(out), "--generated-at", STAMP])
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            report = json.loads(text)
            self.assertEqual([hit["hit_id"] for hit in report["hits"]], ["H-000001", "H-000002"])
            self.assertEqual(report["hits"][1]["flip_type"], "decision")
            self.assertEqual(text, dump_report(report))
            self.assertTrue(text.endswith("\n"))

    def test_cli_rejects_a_single_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            one = folder / "one.jsonl"
            write_jsonl(one, [output("H-000001")])
            code = main(["--outputs", str(one), "--out", str(folder / "repro.json")])
            self.assertEqual(code, 1)

    def test_runner_sets_trace_path_and_llm_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            log_path = folder / "invocations.jsonl"
            stub = folder / "run"
            stub.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, os, sys",
                        "data, output = sys.argv[1], sys.argv[2]",
                        "row = {",
                        '    "TRACE_PATH": os.environ.get("TRACE_PATH"),',
                        '    "USE_LLM_NOTES": os.environ.get("USE_LLM_NOTES"),',
                        '    "SANCTIONS_LLM": os.environ.get("SANCTIONS_LLM"),',
                        '    "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),',
                        '    "output": output,',
                        "}",
                        f'with open({str(log_path)!r}, "a", encoding="utf-8") as handle:',
                        "    handle.write(json.dumps(row) + chr(10))",
                        "hit = {",
                        '    "alert_id": "A-000001",',
                        '    "customer_record_id": None,',
                        '    "decision": "REVIEW",',
                        '    "evidence": [],',
                        '    "hit_id": "H-000001",',
                        '    "reason": "stub",',
                        '    "reason_code": "INSUFFICIENT_DATA",',
                        "}",
                        'with open(output, "w", encoding="utf-8") as handle:',
                        "    handle.write(json.dumps(hit) + chr(10))",
                        'trace_path = os.environ.get("TRACE_PATH")',
                        "if trace_path:",
                        '    header = {"record_type": "run_header", "git_sha": "abc", "rules_version": "r1.0", "model": "none", "provider": "none"}',
                        '    traced = {"hit_id": "H-000001", "alert_id": "A-000001", "verdict": hit, "badges": {"llm_used": False, "fragility": "solid"}, "steps": []}',
                        '    with open(trace_path, "w", encoding="utf-8") as handle:',
                        "        handle.write(json.dumps(header) + chr(10))",
                        "        handle.write(json.dumps(traced) + chr(10))",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            previous_notes = os.environ.get("USE_LLM_NOTES")
            previous_trace = os.environ.get("TRACE_PATH")
            os.environ["USE_LLM_NOTES"] = "1"
            os.environ["TRACE_PATH"] = str(folder / "parent-trace.jsonl")
            try:
                code = main(
                    [
                        "--run",
                        "--data",
                        str(folder / "data"),
                        "--n",
                        "2",
                        "--work-dir",
                        str(folder / "work"),
                        "--system-run",
                        str(stub),
                        "--capture-traces",
                        "--llm-off",
                        "--out",
                        str(folder / "repro.json"),
                        "--generated-at",
                        STAMP,
                    ]
                )
            finally:
                if previous_notes is None:
                    os.environ.pop("USE_LLM_NOTES", None)
                else:
                    os.environ["USE_LLM_NOTES"] = previous_notes
                if previous_trace is None:
                    os.environ.pop("TRACE_PATH", None)
                else:
                    os.environ["TRACE_PATH"] = previous_trace
            self.assertEqual(code, 0, msg=(folder / "work").exists())
            invocations = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(invocations), 3)
            trace_paths = [row["TRACE_PATH"] for row in invocations[:2]]
            self.assertTrue(all(trace_paths))
            self.assertNotEqual(trace_paths[0], trace_paths[1])
            self.assertTrue(all(row["PYTHONHASHSEED"] == "0" for row in invocations))
            self.assertTrue(all(row["USE_LLM_NOTES"] == "1" for row in invocations[:2]))
            self.assertEqual(invocations[2]["USE_LLM_NOTES"], "0")
            self.assertEqual(invocations[2]["SANCTIONS_LLM"], "0")
            self.assertIsNone(invocations[2]["TRACE_PATH"])
            report = json.loads((folder / "repro.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["judges_metric"], 1.0)
            self.assertTrue(report["config_check"]["all_identical"]["git_sha"])
            self.assertEqual(report["llm_sensitivity"]["n_sensitive"], 0)
            self.assertEqual(report["meta"]["run_labels"], ["run-01", "run-02"])

    def test_runner_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            stub = folder / "run"
            stub.write_text("#!/bin/sh\necho boom >&2\nexit 3\n", encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            code = main(
                [
                    "--run",
                    "--data",
                    str(folder),
                    "--n",
                    "2",
                    "--work-dir",
                    str(folder / "work"),
                    "--system-run",
                    str(stub),
                    "--out",
                    str(folder / "repro.json"),
                ]
            )
            self.assertEqual(code, 1)

    def test_example_file_matches_generator_and_has_no_identity_values(self):
        report = build_example_report()
        on_disk = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(report, on_disk)
        self.assertEqual(EXAMPLE_PATH.read_text(encoding="utf-8"), dump_report(report))
        by_id = {hit["hit_id"]: hit for hit in report["hits"]}
        self.assertEqual(by_id["H-000001"]["flip_type"], "none")
        self.assertEqual(by_id["H-000002"]["flip_type"], "decision")
        self.assertEqual(by_id["H-000003"]["flip_type"], "code")
        self.assertEqual(by_id["H-000004"]["flip_type"], "evidence")
        self.assertEqual(by_id["H-000005"]["flip_type"], "other")
        self.assertEqual(by_id["H-000005"]["missing_from_runs"], [3])
        self.assertEqual(by_id["H-000006"]["first_divergent_step"]["rule"], "DOB_MISMATCH")
        self.assertEqual(by_id["H-000006"]["first_divergent_step"]["order_index"], 3)
        self.assertEqual(report["summary"]["judges_metric"], 0.5)
        self.assertEqual(report["summary"]["judges_stable_hits"], 3)
        self.assertEqual(report["summary"]["decision_flip_hits"], 1)
        self.assertEqual(report["summary"]["code_only_flip_hits"], 1)
        self.assertEqual(report["summary"]["strict_change_hits"], 2)
        self.assertEqual(report["summary"]["missing_hits"], 1)
        self.assertFalse(report["config_check"]["all_identical"]["git_sha"])
        self.assertTrue(report["config_check"]["all_identical"]["rules_version"])
        self.assertEqual(report["llm_sensitivity"]["hit_ids"], ["H-000002"])
        self.assertEqual(report["ui"]["filters"]["thin_clearances"], ["H-000004"])
        self.assertEqual(report["ui"]["filters"]["thin_or_borderline_and_llm"], ["H-000002"])
        self.assertEqual(len(by_id["H-000001"]["per_run"]), 5)
        blob = dump_report({"hits": report["hits"], "heatmap": report["heatmap"]})
        self.assertNotIn("UNIQUE", blob)
        self.assertNotRegex(blob, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(report["meta"]["generated_at"], EXAMPLE_STAMP)
        for hit in report["hits"]:
            self.assertNotIn("generated_at", hit)
            self.assertNotIn("timestamp", json.dumps(hit))


if __name__ == "__main__":
    unittest.main()
