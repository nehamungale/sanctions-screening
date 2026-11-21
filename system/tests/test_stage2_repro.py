"""Stage 2 against the local dev folder. Skips when that folder is absent.

The dev files are participant data and are not fixtures in this repository.
"""

import filecmp
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage2.build import run_stage2

DEV = os.environ.get("SANCTIONS_DEV", "/cursor/stores/bot/hackathon/dev")


@unittest.skipUnless(os.path.isdir(DEV), "dev data is not on this machine")
class Stage2DevTests(unittest.TestCase):
    def test_counts_agreement_and_byte_identity(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            first = run_stage2(DEV, left, enabled=False)
            second = run_stage2(DEV, right, enabled=False)
            self.assertTrue(
                filecmp.cmp(
                    os.path.join(left, "hit_golden.jsonl"),
                    os.path.join(right, "hit_golden.jsonl"),
                    shallow=False,
                )
            )
        buckets = first["dob_buckets"]
        self.assertEqual(first["individuals"], 702)
        self.assertEqual(buckets["dobs_only"], 146)
        self.assertEqual(buckets["dobs_and_note"], 6)
        self.assertEqual(buckets["note_only"], 50)
        self.assertEqual(buckets["search_result"], 55)
        self.assertEqual(buckets["unknown"], 445)
        self.assertEqual(first["note_birth_statements"], 56)
        self.assertEqual(first["deceased"], 6)
        self.assertEqual(first["deceased_undated"], 2)
        # Strict single-space lines are 639/214. Whitespace after ";" keeps one more.
        self.assertEqual(first["dated_report_lines"], 640)
        self.assertEqual(first["dated_report_hits"], 215)
        self.assertEqual(first["llm_calls"], 0)
        self.assertFalse(first["llm_enabled"])
        self.assertEqual(second["note_birth_statements"], first["note_birth_statements"])
        self.assertLess(first["elapsed_seconds"], 30)


if __name__ == "__main__":
    unittest.main()
