"""The optional veto can only remove a clearance."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage4.model import Decision
from stage4.veto import apply_veto


def _item(decision, code, hit_id="H-0000AA", fragility="thin"):
    row = Decision(decision=decision, reason_code=code, fragility=fragility, evidence=["KYC-0000A1"])
    return {
        "hit_id": hit_id,
        "decision": row,
        "texts": {"NOTE-0000B1": "The customer lived in Canada before screening."},
    }


class VetoTests(unittest.TestCase):
    def test_off_does_not_call(self):
        calls = {"n": 0}

        def transport(_texts):
            calls["n"] += 1
            return {"found": True, "kind": "customer_country", "source_id": "NOTE-0000B1", "quote": "Canada"}

        # No transport and the switch is off: the helper returns immediately
        # only when transport is None. Passing a transport is the test double,
        # so this case checks a SAME decision is left alone even if called.
        item = _item("SAME_ENTITY", "NAME_DOB_MATCH")
        apply_veto([item], transport=transport, budget=5)
        self.assertEqual(item["decision"].decision, "SAME_ENTITY")
        self.assertEqual(calls["n"], 0)

    def test_three_agreeing_quotes_downgrade_a_clear(self):
        item = _item("DIFFERENT_ENTITY", "LOCATION_MISMATCH")

        def transport(_texts):
            return {
                "found": True,
                "kind": "customer_country",
                "source_id": "NOTE-0000B1",
                "quote": "lived in Canada",
            }

        apply_veto([item], transport=transport, budget=5)
        self.assertEqual(item["decision"].decision, "REVIEW")
        self.assertEqual(item["decision"].reason_code, "INSUFFICIENT_DATA")
        self.assertEqual(item["veto"], "vetoed")

    def test_disagreement_or_a_bad_quote_leaves_the_clear(self):
        item = _item("DIFFERENT_ENTITY", "DOB_MISMATCH")
        replies = [
            {"found": True, "kind": "hit_dob", "source_id": "NOTE-0000B1", "quote": "lived in Canada"},
            {"found": False, "kind": "hit_dob", "source_id": "NOTE-0000B1", "quote": "lived in Canada"},
            {"found": True, "kind": "hit_dob", "source_id": "NOTE-0000B1", "quote": "lived in Canada"},
        ]

        def transport(_texts):
            return replies.pop(0)

        apply_veto([item], transport=transport, budget=5)
        self.assertEqual(item["decision"].decision, "DIFFERENT_ENTITY")

        item = _item("DIFFERENT_ENTITY", "DOB_MISMATCH", hit_id="H-0000B1")

        def bad(_texts):
            return {"found": True, "kind": "customer_country", "source_id": "NOTE-0000B1", "quote": "not in the note"}

        apply_veto([item], transport=bad, budget=5)
        self.assertEqual(item["decision"].decision, "DIFFERENT_ENTITY")

    def test_exhausted_budget_makes_no_change(self):
        item = _item("DIFFERENT_ENTITY", "LOCATION_MISMATCH")

        def transport(_texts):
            raise AssertionError("budget is empty")

        apply_veto([item], transport=transport, budget=0)
        self.assertEqual(item["decision"].decision, "DIFFERENT_ENTITY")
        self.assertEqual(item["veto"], "skipped_budget")


if __name__ == "__main__":
    unittest.main()
