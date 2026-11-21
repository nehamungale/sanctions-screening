"""Output order and a byte-identical rerun on a synthetic folder."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage4.output import dumps_jsonl, line_from

VARIANTS = {"groups": [["robert", "bob"]], "company_legal_forms": ["ltd", "inc"]}


class OutputOrderTests(unittest.TestCase):
    def test_lines_sort_by_hit_and_keep_key_order(self):
        rows = [
            line_from("H-0000B1", "A-0000A1", "REVIEW", "INSUFFICIENT_DATA", None, "One. Two.", []),
            line_from("H-0000A1", "A-0000A1", "DIFFERENT_ENTITY", "DOB_MISMATCH", "CUS-999991", "One. Two.", ["KYC-0000A1"]),
        ]
        text = dumps_jsonl(rows)
        lines = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([row["hit_id"] for row in lines], ["H-0000A1", "H-0000B1"])
        self.assertEqual(list(lines[0]), [
            "hit_id", "alert_id", "decision", "reason_code", "customer_record_id", "reason", "evidence",
        ])
        self.assertEqual(text, dumps_jsonl(list(reversed(rows))))


class RerunTests(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            data = os.path.join(folder, "data")
            os.makedirs(data)
            _write(data)
            first = os.path.join(folder, "first.jsonl")
            second = os.path.join(folder, "second.jsonl")
            env = dict(os.environ)
            env["SANCTIONS_LLM"] = "0"
            env["USE_LLM_NOTES"] = "0"
            env["USE_LLM_HITS"] = "0"
            env.pop("OPENROUTER_API_KEY", None)
            run = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run")
            env["SANCTIONS_CACHE"] = os.path.join(folder, "cache-a")
            left = subprocess.run([run, data, first], check=False, capture_output=True, text=True, env=env)
            env["SANCTIONS_CACHE"] = os.path.join(folder, "cache-b")
            right = subprocess.run([run, data, second], check=False, capture_output=True, text=True, env=env)
            self.assertEqual(left.returncode, 0, left.stderr)
            self.assertEqual(right.returncode, 0, right.stderr)
            with open(first, "rb") as handle:
                raw_first = handle.read()
            with open(second, "rb") as handle:
                raw_second = handle.read()
            self.assertEqual(raw_first, raw_second)
            self.assertTrue(raw_first.endswith(b"\n"))
            row = json.loads(raw_first.decode("utf-8").splitlines()[0])
            self.assertIn(row["decision"], {"DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"})
            sentences = [part for part in row["reason"].replace("!", ".").replace("?", ".").split(".") if part.strip()]
            self.assertGreaterEqual(len(sentences), 2)
            self.assertLessEqual(len(sentences), 4)


def _write(data):
    def dump(name, rows):
        with open(os.path.join(data, name), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row))
                handle.write("\n")

    dump("customers.jsonl", [{
        "record_id": "CUS-999991",
        "entity_type": "Individual",
        "full_name": "Jane Example",
        "preferred_name": None,
        "login_name": None,
        "dob": "1990-04-02",
        "nationality": "Ireland",
        "residence_country": "Ireland",
        "city": "Dublin",
        "address": "1 Example Street",
        "email": "jane@example.com",
        "phone": "+353 1 0000000",
        "registration_number": None,
    }])
    dump("accounts.jsonl", [{
        "account_id": "ACC-000001",
        "customer_id": "CUS-999991",
        "login_handle": "jane",
        "phone": "+353 1 0000000",
    }])
    dump("onboarding.jsonl", [{
        "account_id": "ACC-000001",
        "customer_id": "CUS-999991",
        "kyc_applicant_id": "APP-000001",
        "onboarded_at": "2020-01-01",
    }])
    dump("kyc_checks.jsonl", [{
        "check_id": "KYC-0000A1",
        "applicant_id": "APP-000001",
        "provider": "Example",
        "verified_name": "JANE EXAMPLE",
        "verified_dob": "1990-04-02",
        "document_type": "passport",
        "document_number": "EX123",
        "document_country": "Ireland",
        "result": "approved",
        "checked_at": "2024-01-01",
    }])
    dump("notes.jsonl", [])
    dump("hits.jsonl", [{
        "hit_id": "H-0000AA",
        "alert_id": "A-0000A1",
        "match_score": 90,
        "entity_type": "Individual",
        "name": "Example, Oliver",
        "aliases": [],
        "dobs": ["1961-07-15"],
        "nationality": [],
        "citizenship": [],
        "countries": ["Canada"],
        "addresses": [],
        "categories": ["PEP"],
        "primary_category": "PEP",
        "profile_notes": None,
        "life_status": "Alive",
        "deceased_date": None,
    }])
    dump("search_results.jsonl", [])
    dump("alerts.jsonl", [{
        "alert_id": "A-0000A1",
        "screened_at": "2026-02-01",
        "customer": {
            "name": "Jane Example",
            "entity_type": "Individual",
            "dob": "1990-04-02",
            "country": "Ireland",
            "city": "Dublin",
        },
        "account_ref": "ACC-000001",
        "login_handle": None,
        "email": None,
        "hit_ids": ["H-0000AA"],
    }])
    with open(os.path.join(data, "name_variants.json"), "w", encoding="utf-8") as handle:
        json.dump(VARIANTS, handle)


if __name__ == "__main__":
    unittest.main()
