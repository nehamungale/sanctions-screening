"""Unseen data must not stop the run. Fixtures are synthetic."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline
from shared.io import canonical_entity_type, clean_row, load_table, read_jsonl
from tests.test_stage4_output import _write


class ReaderTests(unittest.TestCase):
    def test_entity_type_synonyms(self):
        self.assertEqual(canonical_entity_type("individual"), "Individual")
        self.assertEqual(canonical_entity_type(" Natural_Person "), "Individual")
        self.assertEqual(canonical_entity_type("Organisation"), "Company")
        self.assertEqual(canonical_entity_type("Company"), "Company")
        self.assertEqual(canonical_entity_type("Vessel"), "Vessel")
        self.assertIsNone(canonical_entity_type(None))

    def test_hit_list_fields_become_lists(self):
        row = clean_row("hits.jsonl", {"hit_id": "H-000001", "dobs": "1970", "aliases": None, "countries": ["Ireland"]})
        self.assertEqual(row["dobs"], ["1970"])
        self.assertEqual(row["aliases"], [])
        self.assertEqual(row["countries"], ["Ireland"])

    def test_alert_without_customer_object(self):
        row = clean_row("alerts.jsonl", {"alert_id": "A-000001", "customer": None, "hit_ids": "H-000001"})
        self.assertEqual(row["customer"], {})
        self.assertEqual(row["hit_ids"], ["H-000001"])

    def test_optional_missing_and_bad_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_table(folder, "search_results.jsonl"), [])
            with self.assertRaises(FileNotFoundError):
                load_table(folder, "hits.jsonl")
            path = os.path.join(folder, "notes.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"note_id": "NOTE-1"}\nnot json\n[1, 2]\n\n')
            self.assertEqual(read_jsonl(path), [{"note_id": "NOTE-1"}])


class FallbackTests(unittest.TestCase):
    def _data(self, folder):
        data = os.path.join(folder, "data")
        os.makedirs(data)
        _write(data)
        return data

    def test_missing_optional_files_still_decide(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self._data(folder)
            for name in ("search_results.jsonl", "notes.jsonl", "name_variants.json"):
                os.remove(os.path.join(data, name))
            out = os.path.join(folder, "out.jsonl")
            with mock.patch.dict(os.environ, {"SANCTIONS_CACHE": os.path.join(folder, "cache"), "SANCTIONS_LLM": "0"}):
                self.assertEqual(pipeline.main([data, out]), 0)
            rows = [json.loads(line) for line in open(out, encoding="utf-8")]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["decision"], "DIFFERENT_ENTITY")

    def test_a_crashing_stage_still_writes_review_for_every_hit(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self._data(folder)
            out = os.path.join(folder, "out.jsonl")
            with mock.patch.dict(os.environ, {"SANCTIONS_CACHE": os.path.join(folder, "cache"), "SANCTIONS_LLM": "0"}), \
                    mock.patch.object(pipeline, "run_stage3", side_effect=RuntimeError("boom")), \
                    mock.patch("sys.stderr"):
                self.assertEqual(pipeline.main([data, out]), 0)
            rows = [json.loads(line) for line in open(out, encoding="utf-8")]
            self.assertEqual([row["decision"] for row in rows], ["REVIEW"])
            self.assertEqual(rows[0]["reason_code"], "INSUFFICIENT_DATA")
            self.assertEqual(rows[0]["evidence"], ["A-0000A1"])


if __name__ == "__main__":
    unittest.main()
