"""Synthetic grading cases. No participant data: every record below is invented."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.eval.cli import grade, main
from tools.eval.data import DataIndex
from tools.eval.parse import load_labels

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "output.schema.json"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


ALERTS = [
    {"alert_id": "A-AAA001", "screened_at": "2026-11-06",
     "customer": {"name": "Zorvan Quillet", "entity_type": "Individual", "dob": "1970-01-02", "country": "Freedonia", "city": None},
     "account_ref": "ACC-AAA001", "login_handle": None, "email": None, "hit_ids": ["H-AAA001", "H-AAA002"]},
    {"alert_id": "A-AAA002", "screened_at": "2026-11-06",
     "customer": {"name": "Mirela Ostvik", "entity_type": "Individual", "dob": None, "country": None, "city": None},
     "account_ref": None, "login_handle": "mostvik", "email": None, "hit_ids": ["H-AAA003"]},
    {"alert_id": "A-AAA003", "screened_at": "2026-11-06",
     "customer": {"name": "Tobiah Wrenfield", "entity_type": "Individual", "dob": "1980-05-05", "country": "Sylvania", "city": None},
     "account_ref": "ACC-AAA003", "login_handle": None, "email": None, "hit_ids": ["H-AAA004"]},
]

HITS = [
    {"hit_id": "H-AAA001", "alert_id": "A-AAA001", "entity_type": "Individual", "name": "Quillet, Zorvan",
     "aliases": [], "dobs": ["1970"], "countries": ["Freedonia"], "nationality": [], "citizenship": [], "addresses": []},
    {"hit_id": "H-AAA002", "alert_id": "A-AAA001", "entity_type": "Individual", "name": "Quillet, Zorvan",
     "aliases": [], "dobs": ["1955"], "countries": ["Ruritania"], "nationality": [], "citizenship": [], "addresses": []},
    {"hit_id": "H-AAA003", "alert_id": "A-AAA002", "entity_type": "Individual", "name": "Ostvik, Mirela",
     "aliases": [], "dobs": [], "countries": [], "nationality": [], "citizenship": [], "addresses": []},
    {"hit_id": "H-AAA004", "alert_id": "A-AAA003", "entity_type": "Individual", "name": "Wrenfield, Tobiah",
     "aliases": [], "dobs": ["1940"], "countries": ["Sylvania"], "nationality": [], "citizenship": [], "addresses": []},
]

CUSTOMERS = [
    {"record_id": "CUS-900001", "entity_type": "Individual", "full_name": "Zorvan Quillet", "dob": "02/01/1970",
     "nationality": "Freedonia", "residence_country": "FD", "city": "Fredville", "email": "zq@example.invalid"},
    {"record_id": "CUS-900002", "entity_type": "Individual", "full_name": "Mirela Ostvik", "dob": None,
     "nationality": None, "residence_country": None, "city": None, "email": None},
    {"record_id": "CUS-900003", "entity_type": "Individual", "full_name": "Mirela Ostvik", "dob": None,
     "nationality": None, "residence_country": None, "city": None, "email": None},
    {"record_id": "CUS-900004", "entity_type": "Individual", "full_name": "Tobiah Wrenfield", "dob": "05/05/1980",
     "nationality": "Sylvania", "residence_country": "SY", "city": None, "email": "tw@example.invalid"},
]

ACCOUNTS = [
    {"account_id": "ACC-AAA001", "customer_id": "CUS-900001", "login_handle": "zquillet"},
    {"account_id": "ACC-AAA003", "customer_id": "CUS-900004", "login_handle": "twren"},
]
ONBOARDING = [{"account_id": "ACC-AAA001", "customer_id": "CUS-900001", "kyc_applicant_id": "APP-AAA001"}]
KYC = [{"check_id": "KYC-AAA001", "applicant_id": "APP-AAA001", "verified_name": "Zorvan Quillet",
        "verified_dob": "1970-01-02", "document_country": "Freedonia", "document_number": "X1", "result": "approved"}]
NOTES = [{"note_id": "NOTE-AAA001", "requester_email": "tw@example.invalid", "text": "Tobiah Wrenfield born 1980-05-05."}]
SEARCH = [{"result_id": "SR-AAA001", "query": "zorvan quillet", "title": "Zorvan Quillet", "snippet": "A report."}]

LABELS = [
    {"hit_id": "H-AAA001", "alert_id": "A-AAA001", "decision": "SAME_ENTITY",
     "reason_codes": ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], "customer_record_ids": ["CUS-900001"],
     "evidence": ["CUS-900001", "KYC-AAA001"],
     "reference_reason": "Zorvan Quillet's date of birth 1970-01-02 (KYC-AAA001) agrees with the hit's 1970 and both are linked to Freedonia.",
     "path": ["account_ref ACC-AAA001 -> accounts -> CUS-900001", "kyc -> KYC-AAA001"]},
    {"hit_id": "H-AAA002", "alert_id": "A-AAA001", "decision": "DIFFERENT_ENTITY",
     "reason_codes": ["DOB_MISMATCH", "LOCATION_MISMATCH"], "customer_record_ids": ["CUS-900001"],
     "evidence": ["CUS-900001"],
     "reference_reason": "The customer's date of birth 1970-01-02 contradicts the hit's 1955, and Freedonia differs from Ruritania.",
     "path": ["account_ref ACC-AAA001 -> accounts -> CUS-900001"]},
    {"hit_id": "H-AAA003", "alert_id": "A-AAA002", "decision": "REVIEW",
     "reason_codes": ["AMBIGUOUS_CUSTOMER_RECORD"], "customer_record_ids": ["AMBIGUOUS"],
     "evidence": ["CUS-900002", "CUS-900003"],
     "reference_reason": "Two different people named Mirela Ostvik (CUS-900002, CUS-900003) fit the alert.",
     "path": ["login_handle mostvik -> different people fit"]},
    {"hit_id": "H-AAA004", "alert_id": "A-AAA003", "decision": "DIFFERENT_ENTITY",
     "reason_codes": ["DOB_MISMATCH"], "customer_record_ids": ["CUS-900004"],
     "evidence": ["CUS-900004", "NOTE-AAA001"],
     "reference_reason": "Tobiah Wrenfield's date of birth 1980-05-05 (NOTE-AAA001) contradicts the hit's 1940.",
     "path": ["account_ref ACC-AAA003 -> accounts -> CUS-900004", "customer email -> notes -> NOTE-AAA001"]},
]

# All-REVIEW baseline: SAME->REVIEW 2 + DIFFERENT->REVIEW 3 + REVIEW 0 + DIFFERENT->REVIEW 3 = 8
ALL_REVIEW_COST = 8


def make_data(root: Path) -> Path:
    data = root / "dev"
    data.mkdir()
    _write_jsonl(data / "alerts.jsonl", ALERTS)
    _write_jsonl(data / "hits.jsonl", HITS)
    _write_jsonl(data / "customers.jsonl", CUSTOMERS)
    _write_jsonl(data / "accounts.jsonl", ACCOUNTS)
    _write_jsonl(data / "onboarding.jsonl", ONBOARDING)
    _write_jsonl(data / "kyc_checks.jsonl", KYC)
    _write_jsonl(data / "notes.jsonl", NOTES)
    _write_jsonl(data / "search_results.jsonl", SEARCH)
    _write_jsonl(data / "practice_labels.jsonl", LABELS)
    (data / "name_variants.json").write_text(json.dumps({
        "description": "synthetic", "groups": [["zorvan", "zorven"]], "company_legal_forms": ["ltd", "gmbh"],
    }), encoding="utf-8")
    return data


def perfect_rows() -> list[dict]:
    """Rows in the official output.schema.json shape (``reason``, not ``explanation``)."""
    rows = []
    for lab in LABELS:
        rows.append({
            "hit_id": lab["hit_id"],
            "alert_id": lab["alert_id"],
            "decision": lab["decision"],
            "reason_code": lab["reason_codes"][0],
            "customer_record_id": lab["customer_record_ids"][0],
            "reason": lab["reference_reason"],
            "evidence": list(lab["evidence"]),
        })
    return rows


def by_hit(rows: list[dict]) -> dict[str, dict]:
    return {r["hit_id"]: r for r in rows}


class EvalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = make_data(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_run(self, name: str, rows: list[dict]) -> Path:
        path = self.root / name
        _write_jsonl(path, rows)
        return path

    def run_grade(self, *runs: list[dict]) -> dict:
        paths = [self.write_run(f"run{i + 1}.jsonl", rows) for i, rows in enumerate(runs)]
        return grade(paths, data_dir=self.data)


class TestSchema(unittest.TestCase):
    def test_fixture_rows_use_the_official_output_fields(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        for row in perfect_rows():
            self.assertEqual(set(schema["required"]), set(row))
            self.assertIn(row["reason_code"], schema["properties"]["reason_code"]["enum"])


class TestLabels(EvalTestCase):
    def test_jsonl_labels_lists_ambiguous_and_path(self) -> None:
        labels = load_labels(self.data / "practice_labels.jsonl")
        self.assertEqual(4, len(labels))
        self.assertEqual(["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"], labels[0]["reason_codes"])
        self.assertEqual(["CUS-900001"], labels[0]["customer_record_ids"])
        self.assertEqual(["AMBIGUOUS"], labels[2]["customer_record_ids"])
        self.assertIn("KYC-AAA001", labels[0]["path"])
        self.assertIn("account_ref", labels[0]["path"])

    def test_data_index_reads_jsonl_folder(self) -> None:
        idx = DataIndex(self.data)
        for rid in ("H-AAA001", "A-AAA001", "CUS-900001", "ACC-AAA001", "APP-AAA001", "KYC-AAA001", "NOTE-AAA001", "SR-AAA001"):
            self.assertTrue(idx.id_exists(rid), rid)
        self.assertFalse(idx.id_exists("CUS-000000"))
        self.assertEqual("A-AAA001", idx.hit_to_alert["H-AAA002"])
        self.assertEqual("Zorvan Quillet", idx.alerts["A-AAA001"]["customer_name"])
        self.assertIn("ltd", idx.legal_forms)
        self.assertEqual(idx.variant_of["zorvan"], idx.variant_of["zorven"])


class TestAccuracy(EvalTestCase):
    def test_perfect_output(self) -> None:
        acc = self.run_grade(perfect_rows())["accuracy"]
        self.assertEqual(1.0, acc["decision_accuracy"])
        self.assertEqual(1.0, acc["reason_code_accepted_rate"])
        self.assertEqual(0, acc["decision_cost"])
        self.assertEqual(ALL_REVIEW_COST, acc["cost_all_review"])
        self.assertEqual(1.0, acc["decision_score"])
        self.assertEqual(1.0, acc["evidence_recall_macro"])
        self.assertEqual(1.0, acc["evidence_precision_macro"])
        self.assertEqual(0, acc["n_false_clears"])

    def test_false_clear_costs_60_and_is_listed(self) -> None:
        rows = perfect_rows()
        rows[0].update(decision="DIFFERENT_ENTITY", reason_code="LOCATION_MISMATCH")
        acc = self.run_grade(rows)["accuracy"]
        self.assertEqual(60, acc["decision_cost"])
        self.assertEqual(0.0, acc["decision_score"])
        self.assertEqual(1, acc["n_false_clears"])
        self.assertIn("H-AAA001", json.dumps(acc["false_clears"]))

    def test_review_overuse_cost(self) -> None:
        rows = perfect_rows()
        rows[1].update(decision="REVIEW", reason_code="INSUFFICIENT_DATA")
        acc = self.run_grade(rows)["accuracy"]
        self.assertEqual(3, acc["decision_cost"])
        self.assertAlmostEqual(round(1 - 3 / ALL_REVIEW_COST, 4), acc["decision_score"])
        self.assertEqual(1, acc["n_review_overuse"])
        self.assertEqual(0, acc["n_false_clears"])

    def test_any_listed_reason_code_is_accepted(self) -> None:
        rows = perfect_rows()
        rows[1]["reason_code"] = "LOCATION_MISMATCH"
        rows[3]["reason_code"] = "LOCATION_MISMATCH"
        acc = self.run_grade(rows)["accuracy"]
        self.assertEqual(1.0, acc["decision_accuracy"])
        self.assertEqual(0.75, acc["reason_code_accepted_rate"])

    def test_missing_labelled_hit_scored_as_review(self) -> None:
        rows = [r for r in perfect_rows() if r["hit_id"] != "H-AAA002"]
        acc = self.run_grade(rows)["accuracy"]
        self.assertEqual(1, acc["n_missing"])
        self.assertEqual(3, acc["decision_cost"])
        self.assertEqual(0, acc["n_false_clears"])

    def test_extra_evidence_lowers_precision_not_recall(self) -> None:
        rows = perfect_rows()
        rows[3]["evidence"] = rows[3]["evidence"] + ["SR-AAA001"]
        acc = self.run_grade(rows)["accuracy"]
        self.assertEqual(1.0, acc["evidence_recall_macro"])
        self.assertLess(acc["evidence_precision_macro"], 1.0)
        self.assertEqual(1, acc["n_extra_evidence_hits"])


class TestExplainability(EvalTestCase):
    def test_perfect_output_has_no_issues(self) -> None:
        explain = self.run_grade(perfect_rows())["explain"]
        self.assertEqual(0, explain["n_hits_with_issues"])

    def test_made_up_citation_is_flagged(self) -> None:
        rows = perfect_rows()
        rows[0]["evidence"] = rows[0]["evidence"] + ["NOTE-FFFFFF"]
        explain = self.run_grade(rows)["explain"]
        self.assertEqual([{"hit_id": "H-AAA001", "unsupported_ids": ["NOTE-FFFFFF"]}], explain["unsupported_citations"])

    def test_generic_reason_without_hit_facts_is_flagged(self) -> None:
        rows = perfect_rows()
        rows[1]["reason"] = "The records were reviewed and a decision was made."
        rows[1]["evidence"] = []
        rows[1]["customer_record_id"] = None
        explain = self.run_grade(rows)["explain"]
        self.assertEqual(["H-AAA002"], [m["hit_id"] for m in explain["missing_hit_facts"]])

    def test_boilerplate_reused_on_three_hits_is_flagged(self) -> None:
        rows = perfect_rows()
        for row in rows[:3]:
            row["reason"] = "Zorvan Quillet was compared with the hit."
        explain = self.run_grade(rows)["explain"]
        self.assertEqual(1, explain["boilerplate_group_count"])

    def test_reason_code_must_belong_to_decision(self) -> None:
        rows = perfect_rows()
        rows[0]["reason_code"] = "DOB_MISMATCH"
        explain = self.run_grade(rows)["explain"]
        self.assertEqual(["H-AAA001"], [r["hit_id"] for r in explain["invalid_or_mismatched_reason_codes"]])


class TestReproducibility(EvalTestCase):
    def test_five_identical_runs(self) -> None:
        repro = self.run_grade(*[perfect_rows() for _ in range(5)])["repro"]
        self.assertEqual(5, repro["n_runs"])
        self.assertEqual(1.0, repro["official_repro_rate"])
        self.assertEqual(0, repro["n_hits_differing"])

    def test_decision_or_code_change_breaks_official_repro(self) -> None:
        runs = [perfect_rows() for _ in range(5)]
        runs[2][1].update(decision="REVIEW", reason_code="INSUFFICIENT_DATA")
        runs[4][3]["reason_code"] = "LOCATION_MISMATCH"  # same decision, other code
        repro = self.run_grade(*runs)["repro"]
        self.assertEqual(0.5, repro["official_repro_rate"])
        self.assertEqual({"H-AAA002", "H-AAA004"}, {d["hit_id"] for d in repro["differing_hits"]})

    def test_citation_change_is_listed_but_keeps_official_repro(self) -> None:
        runs = [perfect_rows() for _ in range(5)]
        runs[1][0]["evidence"] = ["CUS-900001"]
        repro = self.run_grade(*runs)["repro"]
        self.assertEqual(1.0, repro["official_repro_rate"])
        self.assertEqual(["H-AAA001"], [d["hit_id"] for d in repro["differing_hits"]])


class TestCli(EvalTestCase):
    def test_cli_prints_scoreboard_and_writes_only_when_asked(self) -> None:
        run = self.write_run("out.jsonl", perfect_rows())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(0, main(["--data", str(self.data), "--outputs", str(run)]))
        self.assertIn("decision_score=1.0", buf.getvalue())
        self.assertEqual({"dev", "out.jsonl"}, {p.name for p in self.root.iterdir()})

        report, metrics = self.root / "r" / "report.md", self.root / "r" / "metrics.json"
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--data", str(self.data), "--outputs", str(run), "--report", str(report), "--metrics", str(metrics)])
        self.assertTrue(report.read_text(encoding="utf-8").startswith("#"))
        self.assertEqual(1.0, json.loads(metrics.read_text(encoding="utf-8"))["accuracy"]["decision_score"])


if __name__ == "__main__":
    unittest.main()
