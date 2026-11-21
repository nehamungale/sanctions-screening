"""Stage diagnostics in tools/eval. Synthetic data only."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.eval.stages import label_agrees, label_matches, stage_diagnostics


class HitProfileTests(unittest.TestCase):
    def test_label_years_and_search_ids(self):
        profile = {
            "entity_type": "Individual",
            "dob_candidates": [{
                "years": [1976, 1977], "month": None, "day": None, "source": "search_result",
            }],
            "incorporation_dates": [],
            "search_results": {"accepted": [{"result_id": "SR-000001"}]},
            "earliest_dated_report": {"date": "2020-01-08"},
        }
        self.assertTrue(label_agrees(profile, {
            "reference_reason": "agrees with the hit's 1976 or 1977.",
            "evidence": ["SR-000001"],
        }))
        self.assertFalse(label_agrees(profile, {
            "reference_reason": "agrees with the hit's 1976 or 1977.",
            "evidence": ["SR-000099"],
        }))
        listed = {
            "entity_type": "Individual",
            "dob_candidates": [
                {"years": [1994], "month": None, "day": None},
                {"years": [1995], "month": None, "day": None},
            ],
            "incorporation_dates": [],
            "search_results": {"accepted": []},
            "earliest_dated_report": None,
        }
        self.assertTrue(label_agrees(listed, {
            "reference_reason": "agrees with the hit's 1994, 1995.",
            "evidence": [],
        }))
        self.assertTrue(label_agrees(profile, {
            "reference_reason": "The hit's dated report on 2020-01-08.",
            "evidence": ["SR-000001"],
        }))


class AlertResolutionTests(unittest.TestCase):
    def test_label_matcher(self):
        resolved = {
            "alert_id": "A-1",
            "status": "RESOLVED",
            "customer_record_id": "CUS-SYN010",
            "chosen_person_ids": ["P-CUS-SYN010"],
            "candidates": [{
                "person_id": "P-CUS-SYN010",
                "record_ids": ["CUS-SYN010", "CUS-SYN020"],
                "matched_records": ["CUS-SYN020"],
                "why": {},
            }],
        }
        good, reason = label_matches(resolved, ["CUS-SYN020", "CUS-SYN010"])
        self.assertTrue(good, reason)
        bad, reason = label_matches(resolved, ["CUS-SYN010"])
        self.assertFalse(bad)
        self.assertIn("records", reason)
        ambiguous = {
            "status": "AMBIGUOUS",
            "customer_record_id": "AMBIGUOUS",
            "chosen_person_ids": ["P-1", "P-2"],
            "candidates": [{"person_id": "P-1"}, {"person_id": "P-2"}],
        }
        good, reason = label_matches(ambiguous, ["AMBIGUOUS"])
        self.assertTrue(good, reason)
        person_id = dict(resolved)
        person_id["customer_record_id"] = "P-CUS-SYN010"
        bad, _reason = label_matches(person_id, ["CUS-SYN010", "CUS-SYN020"])
        self.assertFalse(bad)

    def test_stage_diagnostics_reads_the_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            (cache / "alert_resolution.jsonl").write_text(json.dumps({
                "alert_id": "A-1", "status": "RESOLVED", "customer_record_id": "CUS-SYN010",
                "chosen_person_ids": ["P-CUS-SYN010"],
                "candidates": [{"person_id": "P-CUS-SYN010", "record_ids": ["CUS-SYN010"]}],
            }) + "\n", encoding="utf-8")
            (cache / "hit_golden.jsonl").write_text(json.dumps({
                "hit_id": "H-1", "entity_type": "Individual", "dob_candidates": [],
                "incorporation_dates": [], "search_results": {"accepted": []},
            }) + "\n", encoding="utf-8")
            labels = cache / "labels.jsonl"
            labels.write_text(json.dumps({
                "hit_id": "H-1", "alert_id": "A-1", "customer_record_ids": "CUS-SYN010",
                "reference_reason": "No dates.", "evidence": [],
            }) + "\n", encoding="utf-8")
            result = stage_diagnostics(cache, labels)
        self.assertEqual(result["stage3_alert_resolution"]["matched"], 1)
        self.assertEqual(result["stage2_hit_profiles"]["individual_agree"], 1)


if __name__ == "__main__":
    unittest.main()
