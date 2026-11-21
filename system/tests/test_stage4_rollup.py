"""Alert roll-up and the rule that a model-read fact cannot clear a hit."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.normalise import NameTools
from stage4.ambiguity import decide_hit
from stage4.dates import agrees, contradicts
from stage4.rollup import roll_up

VARIANTS = {"groups": [], "company_legal_forms": ["ltd", "inc"]}


def _alert(alert_id, hit_ids):
    return {"alert_id": alert_id, "hit_ids": list(hit_ids)}


def _row(decision, code="DOB_MISMATCH", fragility="solid", missing=""):
    return {
        "decision": decision,
        "reason_code": code,
        "fragility": fragility,
        "missing": missing,
        "not_decided": False,
        "errored": False,
    }


class RollupTests(unittest.TestCase):
    def test_all_different_is_cleared(self):
        alerts = [_alert("A-0000A1", ["H-0000B1", "H-0000A1"])]
        decisions = {
            "H-0000A1": _row("DIFFERENT_ENTITY", "DOB_MISMATCH"),
            "H-0000B1": _row("DIFFERENT_ENTITY", "LOCATION_MISMATCH", fragility="thin"),
        }
        summary = roll_up(alerts, decisions)[0]
        self.assertEqual(summary["alert_status"], "CLEARED")
        self.assertEqual(summary["blocking_hit_ids"], [])
        self.assertEqual(summary["undecided_hit_ids"], [])
        self.assertEqual([hit["hit_id"] for hit in summary["hits"]], ["H-0000A1", "H-0000B1"])

    def test_same_and_review_is_escalated_and_lists_both(self):
        alerts = [_alert("A-0000A1", ["H-0000B1", "H-0000A1"])]
        decisions = {
            "H-0000A1": _row("REVIEW", "INSUFFICIENT_DATA", missing="the hit gives no date of birth"),
            "H-0000B1": _row("SAME_ENTITY", "NAME_DOB_MATCH"),
        }
        summary = roll_up(alerts, decisions)[0]
        self.assertEqual(summary["alert_status"], "ESCALATED")
        self.assertEqual(summary["blocking_hit_ids"], ["H-0000A1", "H-0000B1"])
        self.assertEqual({hit["decision"] for hit in summary["hits"]}, {"SAME_ENTITY", "REVIEW"})

    def test_one_review_blocks_the_clear(self):
        alerts = [_alert("A-0000A1", ["H-0000A1", "H-0000B1"])]
        decisions = {
            "H-0000A1": _row("DIFFERENT_ENTITY"),
            "H-0000B1": _row("REVIEW", "INSUFFICIENT_DATA", missing="the hit gives no date of birth"),
        }
        summary = roll_up(alerts, decisions)[0]
        self.assertEqual(summary["alert_status"], "NEEDS_REVIEW")
        self.assertEqual(summary["blocking_hit_ids"], ["H-0000B1"])
        self.assertEqual(summary["undecided_hit_ids"], [])

    def test_missing_hit_is_not_decided_and_never_clears(self):
        alerts = [_alert("A-0000A1", ["H-0000A1", "H-0000C1"])]
        decisions = {"H-0000A1": _row("DIFFERENT_ENTITY")}
        summary = roll_up(alerts, decisions)[0]
        self.assertEqual(summary["alert_status"], "NEEDS_REVIEW")
        self.assertEqual(summary["undecided_hit_ids"], ["H-0000C1"])
        missing = summary["hits"][1]
        self.assertEqual(missing["reason_code"], "HIT_NOT_DECIDED")
        self.assertIsNone(missing["decision"])
        self.assertNotEqual(summary["alert_status"], "CLEARED")

    def test_errored_hit_is_not_decided(self):
        alerts = [_alert("A-0000A1", ["H-0000A1"])]
        decisions = {"H-0000A1": {**_row("REVIEW", "INSUFFICIENT_DATA"), "errored": True, "not_decided": True}}
        summary = roll_up(alerts, decisions)[0]
        self.assertEqual(summary["hits"][0]["reason_code"], "HIT_NOT_DECIDED")
        self.assertEqual(summary["alert_status"], "NEEDS_REVIEW")

    def test_same_entity_outranks_an_undecided_hit(self):
        alerts = [_alert("A-0000A1", ["H-0000A1", "H-0000B1"])]
        decisions = {"H-0000A1": _row("SAME_ENTITY", "NAME_DOB_MATCH")}
        summary = roll_up(alerts, decisions)[0]
        self.assertEqual(summary["alert_status"], "ESCALATED")
        self.assertIn("H-0000B1", summary["undecided_hit_ids"])

    def test_empty_alert_is_not_cleared(self):
        summary = roll_up([_alert("A-0000A1", [])], {})[0]
        self.assertEqual(summary["alert_status"], "NEEDS_REVIEW")

    def test_rollup_is_identical_across_reruns(self):
        alerts = [_alert("A-0000B1", ["H-0000B1"]), _alert("A-0000A1", ["H-0000C1", "H-0000A1"])]
        decisions = {
            "H-0000C1": _row("DIFFERENT_ENTITY", "DECEASED"),
            "H-0000A1": _row("REVIEW", "INSUFFICIENT_DATA"),
            "H-0000B1": _row("SAME_ENTITY", "NAME_LOCATION_MATCH"),
        }
        import json
        first = json.dumps(roll_up(alerts, decisions), sort_keys=True)
        second = json.dumps(roll_up(alerts, decisions), sort_keys=True)
        self.assertEqual(first, second)


def _person(method="regex", may_clear=True, dob="1990-04-02"):
    return {
        "person_id": "P-CUS-999991",
        "record_ids": ["CUS-999991"],
        "customer_record_ids": ["CUS-999991"],
        "entity_type": {"value": "Individual", "source_id": "CUS-999991"},
        "legal_name": {
            "value": "Jane Example",
            "parts": ["jane", "example"],
            "real_part_count": 2,
            "verified": True,
            "method": "regex",
            "source_id": "KYC-0000A1",
            "source_kind": "kyc_check",
            "blocks_name_clear": False,
            "may_solely_support_different_entity": True,
        },
        "names_all": [{
            "value": "Jane Example",
            "parts": ["jane", "example"],
            "blocks_name_clear": False,
            "kind": "legal_name",
            "source_id": "KYC-0000A1",
        }],
        "dob": {
            "value": dob,
            "precision": "day",
            "verified": True,
            "method": method,
            "source_id": "KYC-0000A1",
            "may_solely_support_different_entity": may_clear,
        },
        "declared_dobs": [{
            "value": dob, "precision": "day", "comparable": True, "source_id": "CUS-999991",
        }],
        "incorporation_date": None,
        "countries": [{"value": "Ireland", "kind": "residence", "source_id": "CUS-999991"}],
        "flags": [],
        "contracts": {
            "block_dob_age_name_clear": False,
            "block_location_mismatch": False,
            "block_name_clear": False,
            "block_name_mismatch_verified": False,
        },
        "cluster_edges": [],
        "ignored_checks": [],
    }


def _hit():
    return {
        "hit_id": "H-0000AA",
        "alert_id": "A-0000A1",
        "entity_type": "Individual",
        "names": [{
            "value": "Example, Jane",
            "kind": "primary",
            "parts": ["example", "jane"],
            "script": "latin",
            "source_field": "name",
        }],
        "countries": [{"value": "Canada", "unmapped": False, "field": "countries"}],
        "dob_candidates": [{
            "years": [1961], "month": 7, "day": 15, "precision": "day",
            "source": "dobs", "source_id": "H-0000AA#dobs", "method": "regex",
            "may_solely_support_different_entity": True, "rule_strength": "strong",
        }],
        "incorporation_dates": [],
        "deceased": {"life_status": "Alive", "date": None, "precision": None, "method": "field"},
        "earliest_dated_report": None,
        "flags": [],
        "search_results": {"accepted": []},
    }


def _resolution():
    return {
        "alert_id": "A-0000A1",
        "resolution_status": "resolved_single",
        "resolution_quality": "clean_link",
        "resolution_clean": True,
        "resolution_method": "link_account",
        "customer_record_id": "CUS-999991",
        "candidates": [{
            "person_id": "P-CUS-999991",
            "record_ids": ["CUS-999991"],
            "matched_records": ["CUS-999991"],
            "fragility_flags": [],
        }],
        "flags": [],
        "fragility_flags": [],
        "screened": {"entity_type": "Individual"},
    }


def _alert_row():
    return {
        "alert_id": "A-0000A1",
        "screened_at": "2026-02-01",
        "customer": {"entity_type": "Individual", "name": "Jane Example", "dob": "1990-04-02"},
        "hit_ids": ["H-0000AA"],
    }


class LlmCannotClearTests(unittest.TestCase):
    def test_llm_dob_cannot_clear_even_if_upstream_allows_it(self):
        person = _person(method="llm", may_clear=True)
        hit = _hit()
        # Same country and an agreeing name, so the only contradiction is the model-read date.
        hit["countries"] = [{"value": "Ireland", "unmapped": False, "field": "countries"}]
        decision = decide_hit(
            hit, _alert_row(), _resolution(),
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertNotEqual(decision.decision, "DIFFERENT_ENTITY")
        self.assertEqual(decision.decision, "REVIEW")
        self.assertIn("LLM_FACT", decision.blocked.get("DOB_MISMATCH", []))

    def test_the_same_dob_read_by_a_rule_can_clear(self):
        person = _person(method="regex", may_clear=True)
        decision = decide_hit(
            _hit(), _alert_row(), _resolution(),
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "DIFFERENT_ENTITY")
        self.assertEqual(decision.reason_code, "DOB_MISMATCH")
        self.assertNotIn("LLM_FACT", decision.blocked.get("DOB_MISMATCH", []))

    def test_llm_name_may_support_same_entity(self):
        person = _person()
        person["legal_name"]["method"] = "llm"
        person["legal_name"]["may_solely_support_different_entity"] = False
        person["dob"]["value"] = "1961-07-15"
        person["declared_dobs"][0]["value"] = "1961-07-15"
        hit = _hit()
        hit["countries"] = [{"value": "Ireland", "unmapped": False, "field": "countries"}]
        decision = decide_hit(
            hit, _alert_row(), _resolution(),
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "SAME_ENTITY")
        self.assertIn(decision.reason_code, {"NAME_DOB_MATCH", "NAME_DOB_LOCATION_MATCH"})

    def test_joint_account_tiebreak_does_not_block(self):
        blocked = _resolution()
        blocked["resolution_clean"] = False
        blocked["candidates"][0]["fragility_flags"] = ["joint_account_tiebreak"]
        blocked["fragility_flags"] = ["joint_account_tiebreak"]
        decision = decide_hit(
            _hit(), _alert_row(), blocked,
            {"P-CUS-999991": _person()}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "DIFFERENT_ENTITY")
        self.assertNotIn("joint_account_tiebreak", decision.blocked.get("DOB_MISMATCH", []))

        person = _person()
        person["dob"]["value"] = "1961-07-15"
        person["declared_dobs"][0]["value"] = "1961-07-15"
        hit = _hit()
        hit["countries"] = [{"value": "Ireland", "unmapped": False, "field": "countries"}]
        match = decide_hit(
            hit, _alert_row(), blocked,
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertEqual(match.decision, "SAME_ENTITY")

    def test_non_latin_alias_blocks_a_name_clear_only_when_it_outnumbers_latin_names(self):
        person = _person()
        hit = _hit()
        # One Latin name and two non-Latin aliases: blocked.
        hit["names"] = [
            {"value": "Oliver Fictional", "kind": "primary", "parts": ["oliver", "fictional"], "script": "latin"},
            {"value": "示例", "kind": "alias", "parts": [], "script": "non_latin"},
            {"value": "Пример", "kind": "alias", "parts": [], "script": "non_latin"},
        ]
        hit["flags"] = ["NON_LATIN_ALIAS"]
        hit["dob_candidates"] = []
        hit["countries"] = [{"value": "Ireland", "unmapped": False, "field": "countries"}]
        decision = decide_hit(
            hit, _alert_row(), _resolution(),
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "REVIEW")
        self.assertIn("NON_LATIN_ALIAS", decision.blocked.get("NAME_MISMATCH_VERIFIED", []))
        # Two Latin names and one non-Latin alias: the Latin forms decide.
        hit["names"] = [
            {"value": "Oliver Fictional", "kind": "primary", "parts": ["oliver", "fictional"], "script": "latin"},
            {"value": "Oliver Example", "kind": "alias", "parts": ["oliver", "example"], "script": "latin"},
            {"value": "示例", "kind": "alias", "parts": [], "script": "non_latin"},
        ]
        cleared = decide_hit(
            hit, _alert_row(), _resolution(),
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertEqual(cleared.decision, "DIFFERENT_ENTITY")
        self.assertEqual(cleared.reason_code, "NAME_MISMATCH_VERIFIED")

    def test_missing_field_blocks_only_the_clear_that_needs_it(self):
        # The record had no date of birth: a location clear goes through, a DOB clear does not.
        resolution = _resolution()
        resolution["resolution_clean"] = False
        resolution["candidates"][0]["fragility_flags"] = ["candidate_kept_on_missing_field"]
        resolution["candidates"][0]["filters"] = {"skipped_missing": [{"filter": "dob", "side": "record"}]}
        resolution["fragility_flags"] = ["candidate_kept_on_missing_field"]
        hit = _hit()
        hit["dob_candidates"] = []
        decision = decide_hit(
            hit, _alert_row(), resolution,
            {"P-CUS-999991": _person()}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "DIFFERENT_ENTITY")
        self.assertEqual(decision.reason_code, "LOCATION_MISMATCH")
        dob_case = decide_hit(
            _hit(), _alert_row(), resolution,
            {"P-CUS-999991": _person()}, NameTools(VARIANTS),
        )
        self.assertIn("candidate_kept_on_missing_field", dob_case.blocked.get("DOB_MISMATCH", []))
        # An alert that simply did not state a field blocks nothing.
        resolution["candidates"][0]["filters"] = {"skipped_missing": [{"filter": "dob", "side": "alert"}]}
        clear = decide_hit(
            _hit(), _alert_row(), resolution,
            {"P-CUS-999991": _person()}, NameTools(VARIANTS),
        )
        self.assertEqual(clear.decision, "DIFFERENT_ENTITY")

    def test_partial_screened_dob_blocks_date_clears_but_not_location(self):
        resolution = _resolution()
        resolution["resolution_clean"] = False
        resolution["candidates"][0]["fragility_flags"] = ["dob_partial_only"]
        resolution["fragility_flags"] = ["dob_partial_only"]
        hit = _hit()
        hit["dob_candidates"] = []
        decision = decide_hit(
            hit, _alert_row(), resolution,
            {"P-CUS-999991": _person()}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "DIFFERENT_ENTITY")
        self.assertEqual(decision.reason_code, "LOCATION_MISMATCH")
        dob_case = decide_hit(
            _hit(), _alert_row(), resolution,
            {"P-CUS-999991": _person()}, NameTools(VARIANTS),
        )
        self.assertIn("dob_partial_only", dob_case.blocked.get("DOB_MISMATCH", []))

    def test_unverified_flag_blocks_a_name_clear_when_the_legal_name_is_verified(self):
        person = _person()
        person["flags"] = ["UNVERIFIED"]
        self.assertTrue(person["legal_name"]["verified"])
        hit = _hit()
        hit["names"] = [{
            "value": "Oliver Fictional", "kind": "primary",
            "parts": ["oliver", "fictional"], "script": "latin",
        }]
        hit["dob_candidates"] = []
        hit["countries"] = [{"value": "Ireland", "unmapped": False, "field": "countries"}]
        decision = decide_hit(
            hit, _alert_row(), _resolution(),
            {"P-CUS-999991": person}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "REVIEW")
        self.assertIn("BLOCK_NAME_MISMATCH_VERIFIED", decision.blocked.get("NAME_MISMATCH_VERIFIED", []))

    def test_one_year_apart_is_neither_agreement_nor_contradiction(self):
        customer = {"y": 1980, "m": 5, "d": 1}
        self.assertFalse(contradicts(customer, {"years": [1981], "month": None, "day": None}))
        self.assertFalse(agrees(customer, {"years": [1981], "month": None, "day": None}))
        self.assertTrue(contradicts(customer, {"years": [1982], "month": None, "day": None}))
        self.assertTrue(agrees(customer, {"years": [1980], "month": None, "day": None}))


if __name__ == "__main__":
    unittest.main()
