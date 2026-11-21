"""Reproducibility against the local dev folder. Skips when that folder is absent.

The dev files are participant data and are not fixtures in this repository.
"""

import filecmp
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.build import run_stage1
from stage1.countries import countries_in_note, norm_country, unmapped_country_leaves
from stage1.load import DataStore

DEV = os.environ.get("SANCTIONS_DEV", "/cursor/stores/bot/hackathon/dev")
ARTEFACTS = (
    "person_golden.jsonl",
    "record_view.jsonl",
    "index_record_id.json",
    "index_account_id.json",
    "index_account_record_id.json",
    "index_login_handle.json",
    "index_login_record_id.json",
    "index_email_record_id.json",
    "index_name_part_record_id.json",
    "index_email.json",
    "index_name.json",
)


@unittest.skipUnless(os.path.isdir(DEV), "dev data is not on this machine")
class DevReproTests(unittest.TestCase):
    def test_two_runs_match_and_cluster_counts(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            first = run_stage1(DEV, left, use_llm=False)
            second = run_stage1(DEV, right, use_llm=False)
            for name in ARTEFACTS:
                self.assertTrue(
                    filecmp.cmp(os.path.join(left, name), os.path.join(right, name), shallow=False),
                    name,
                )
        self.assertEqual(first["records"], 72265)
        self.assertEqual(first["persons"], 72142)
        self.assertEqual(first["phone_dob_edges"], 116)
        self.assertEqual(first["doc_edges"], 7)
        self.assertEqual(first["doc_edges_new_components"], 7)
        self.assertEqual(first["multi_record_persons"], 123)
        self.assertEqual(second["persons"], first["persons"])
        notes = first["notes"]
        self.assertEqual(notes["kyc"], 22575)
        self.assertEqual(notes["noise"], 6253)
        self.assertEqual(notes["residence"], 3067)
        self.assertEqual(notes["ignored"], 0)
        self.assertEqual(notes["kyc_dob"], 22575)
        self.assertEqual(notes["kyc_doc_country"], 22575)
        self.assertEqual(notes["kyc_check_date"], 22575)
        self.assertEqual(notes["kyc_name"], 22575)
        self.assertEqual(notes["kyc_document_type"], 22574)
        self.assertEqual(notes["kyc_provider"], 22573)
        # The spec's 17 flagged notes were counted before the uppercase-token fix.
        # The three notes with a second run ("PASSED") now read: PASSED is a
        # stop word. One note keeps the note_annotation flag.
        self.assertEqual(notes["flagged"], 1)
        self.assertEqual(notes["flag_counts"], {"note_annotation": 1})
        self.assertLess(first["elapsed_seconds"], 120)

    def test_structured_countries_map(self):
        store = DataStore(DEV)
        unmapped = []
        seen_notes = 0
        seen_search = 0

        def take(value, where):
            for leaf in unmapped_country_leaves(value):
                unmapped.append(f"{where}:{leaf}")

        for row in store.read_jsonl("customers.jsonl"):
            take(row.get("nationality"), "customers.nationality")
            take(row.get("residence_country"), "customers.residence_country")
        for row in store.read_jsonl("kyc_checks.jsonl"):
            take(row.get("document_country"), "kyc_checks.document_country")
        for row in store.read_jsonl("hits.jsonl"):
            for field in ("nationality", "citizenship", "countries", "place_of_birth", "addresses"):
                take(row.get(field), f"hits.{field}")
        for row in store.read_jsonl("notes.jsonl"):
            countries_in_note(row.get("text") or "")
            seen_notes += 1
        for row in store.read_jsonl("search_results.jsonl"):
            countries_in_note(row.get("title") or "")
            countries_in_note(row.get("snippet") or "")
            seen_search += 1
        self.assertGreater(seen_notes, 0)
        self.assertGreater(seen_search, 0)
        self.assertEqual(unmapped, [])
        self.assertIsNone(norm_country("International")[0])
        self.assertEqual(norm_country("International")[1], [])
        self.assertIsNone(norm_country("Europe")[0])
        self.assertEqual(norm_country("Palestina")[0], "Palestine")
        self.assertEqual(norm_country("Macao Special Administrative Region of China")[0], "Macao")


if __name__ == "__main__":
    unittest.main()
