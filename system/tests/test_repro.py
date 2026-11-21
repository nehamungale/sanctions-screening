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
from stage1.countries import norm_country
from stage1.load import DataStore

DEV = os.environ.get("SANCTIONS_DEV", "/cursor/stores/bot/hackathon/dev")
ARTEFACTS = (
    "person_golden.jsonl",
    "index_record_id.json",
    "index_account_id.json",
    "index_login_handle.json",
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
        self.assertEqual(notes["kyc_name"], 22572)
        self.assertEqual(notes["kyc_document_type"], 22574)
        self.assertEqual(notes["kyc_provider"], 22573)
        # The spec's 17 flagged notes were counted before the uppercase-token fix.
        # After that fix, three notes still have a second run ("PASSED") and one
        # keeps the note_annotation flag. Slots the regex filled are still used.
        self.assertEqual(notes["flagged"], 4)
        self.assertEqual(notes["flag_counts"], {"name_ambiguous": 3, "note_annotation": 1})
        self.assertLess(first["elapsed_seconds"], 120)

    def test_structured_countries_map(self):
        store = DataStore(DEV)
        values = set()
        for row in store.read_jsonl("customers.jsonl"):
            values.add(row.get("nationality"))
            values.add(row.get("residence_country"))
        for row in store.read_jsonl("kyc_checks.jsonl"):
            values.add(row.get("document_country"))
        unmapped = []
        for value in sorted(values, key=lambda item: (item is None, str(item))):
            if value is None or str(value).strip() == "":
                continue
            _canonical, flags = norm_country(value)
            if "UNMAPPED_COUNTRY" in flags:
                unmapped.append(value)
        self.assertEqual(unmapped, [])


if __name__ == "__main__":
    unittest.main()
