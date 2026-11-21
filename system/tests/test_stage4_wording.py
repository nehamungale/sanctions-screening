"""Reason text and trace labels. Synthetic ids only."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.normalise import NameTools
from stage4.ambiguity import decide_hit
from stage4.compare import compare
from stage4.model import Decision
from stage4.trace import hit_trace

VARIANTS = {"groups": [], "company_legal_forms": ["ltd"]}


def _sentences(text: str) -> list[str]:
    return [part for part in text.replace("!", ".").replace("?", ".").split(".") if part.strip()]


def _person(**overrides):
    legal = {
        "value": "Jane Example",
        "parts": ["jane", "example"],
        "real_part_count": 2,
        "verified": True,
        "method": "regex",
        "source_id": "KYC-SYN101",
        "source_kind": "kyc_check",
        "blocks_name_clear": False,
        "may_solely_support_different_entity": True,
    }
    legal.update(overrides.pop("legal", {}))
    dob = {
        "value": "1990-04-02",
        "precision": "day",
        "verified": True,
        "method": "regex",
        "source_id": "KYC-SYN101",
        "may_solely_support_different_entity": True,
    }
    dob.update(overrides.pop("dob", {}))
    person = {
        "person_id": "P-CUS-SYN001",
        "record_ids": ["CUS-SYN001"],
        "customer_record_ids": ["CUS-SYN001"],
        "entity_type": {"value": "Individual", "source_id": "CUS-SYN001"},
        "legal_name": legal,
        "names_all": [{
            "value": legal["value"], "parts": legal["parts"], "blocks_name_clear": False,
            "kind": "legal_name", "source_id": legal["source_id"],
        }],
        "dob": dob,
        "declared_dobs": [{
            "value": dob.get("value"), "precision": "day", "comparable": bool(dob.get("value")),
            "source_id": "CUS-SYN001",
        }],
        "incorporation_date": None,
        "countries": [{"value": "Ireland", "kind": "residence", "source_id": "CUS-SYN001"}],
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
    person.update(overrides)
    return person


def _hit(hit_id="H-SYN001", **overrides):
    hit = {
        "hit_id": hit_id,
        "alert_id": "A-SYN001",
        "entity_type": "Individual",
        "names": [{
            "value": "Example, Oliver", "kind": "primary",
            "parts": ["example", "oliver"], "script": "latin",
        }],
        "countries": [{"value": "Canada", "unmapped": False, "field": "countries"}],
        "dob_candidates": [{
            "years": [1961], "month": 7, "day": 15, "precision": "day",
            "source": "dobs", "method": "regex", "may_solely_support_different_entity": True,
            "rule_strength": "strong",
        }],
        "incorporation_dates": [],
        "deceased": {"life_status": "Alive", "date": None, "precision": None, "method": "field"},
        "earliest_dated_report": None,
        "flags": [],
    }
    hit.update(overrides)
    return hit


def _resolution(**overrides):
    row = {
        "alert_id": "A-SYN001",
        "resolution_status": "resolved_single",
        "resolution_quality": "clean_link",
        "resolution_clean": True,
        "resolution_method": "link_account",
        "customer_record_id": "CUS-SYN001",
        "candidates": [{
            "person_id": "P-CUS-SYN001",
            "record_ids": ["CUS-SYN001"],
            "matched_records": ["CUS-SYN001"],
            "fragility_flags": [],
            "filters": {"skipped_missing": []},
        }],
        "flags": [],
        "fragility_flags": [],
    }
    row.update(overrides)
    return row


def _alert():
    return {
        "alert_id": "A-SYN001",
        "screened_at": "2026-02-01",
        "customer": {"entity_type": "Individual", "name": "Jane Example", "dob": "1990-04-02"},
        "hit_ids": ["H-SYN001"],
    }


class ReasonTests(unittest.TestCase):
    def test_location_reasons_name_this_hit_and_the_cited_records(self):
        tools = NameTools(VARIANTS)
        person = _person()
        first = decide_hit(_hit("H-SYN001"), _alert(), _resolution(), {"P-CUS-SYN001": person}, tools)
        second_hit = _hit("H-SYN002")
        second_alert = _alert()
        second_alert["hit_ids"] = ["H-SYN002"]
        second = decide_hit(second_hit, second_alert, _resolution(), {"P-CUS-SYN001": person}, tools)
        for decision, hit_id in ((first, "H-SYN001"), (second, "H-SYN002")):
            self.assertEqual(decision.decision, "DIFFERENT_ENTITY")
            self.assertIn(hit_id, decision.reason)
            self.assertIn("Jane Example", decision.reason)
            self.assertIn("Oliver", decision.reason)
            self.assertTrue(any(item in decision.reason for item in decision.evidence) or "CUS-SYN001" in decision.reason)
            count = len(_sentences(decision.reason))
            self.assertGreaterEqual(count, 2)
            self.assertLessEqual(count, 4)
        self.assertNotEqual(first.reason, second.reason)
        self.assertEqual(first.reason_code, second.reason_code)
        self.assertEqual(first.evidence, second.evidence)
        self.assertEqual(first.record, second.record)

    def test_missing_screened_field_is_named(self):
        resolution = _resolution()
        resolution["resolution_clean"] = False
        resolution["candidates"][0]["fragility_flags"] = ["candidate_kept_on_missing_field"]
        resolution["candidates"][0]["filters"] = {"skipped_missing": [{"filter": "country", "side": "record"}]}
        resolution["fragility_flags"] = ["candidate_kept_on_missing_field"]
        decision = decide_hit(
            _hit(), _alert(), resolution, {"P-CUS-SYN001": _person()}, NameTools(VARIANTS),
        )
        self.assertEqual(decision.decision, "REVIEW")
        self.assertIn("country on the record", decision.reason)
        self.assertIn("H-SYN001", decision.reason)
        self.assertGreaterEqual(len(_sentences(decision.reason)), 2)
        self.assertLessEqual(len(_sentences(decision.reason)), 4)


class TraceShapeTests(unittest.TestCase):
    def _trace(self, person, hit=None):
        hit = hit or _hit()
        alert = _alert()
        cmp = compare(hit, alert, person, NameTools(VARIANTS))
        decision = Decision(
            decision="REVIEW", reason_code="INSUFFICIENT_DATA", cmp=cmp,
            person_id=person["person_id"], missing="no customer record fits the alert",
        )
        return hit_trace(hit, alert, {}, decision, person=person), cmp

    def test_unverified_name_without_a_kyc_check_is_not_verified(self):
        person = _person(flags=["UNVERIFIED"], legal={
            "verified": False, "source_kind": "record", "source_id": "CUS-SYN105", "value": "Jane Example",
        })
        trace, _cmp = self._trace(person, _hit("H-SYN105"))
        self.assertFalse(trace["identity"]["facts"]["name"]["verified"])

    def test_kyc_check_name_is_verified(self):
        trace, _cmp = self._trace(_person())
        self.assertTrue(trace["identity"]["facts"]["name"]["verified"])
        self.assertEqual(trace["identity"]["facts"]["name"]["source_id"], "KYC-SYN101")

    def test_dob_without_a_source_is_not_verified(self):
        person = _person(dob={
            "value": "1990-04-02", "verified": True, "source_id": None, "method": "record",
            "precision": "day", "may_solely_support_different_entity": False,
        })
        trace, _cmp = self._trace(person, _hit("H-SYN102"))
        dob = trace["identity"]["facts"]["dob"]
        self.assertFalse(dob["verified"])
        self.assertIsNone(dob["source_id"])

    def test_death_row_separates_the_screening_date(self):
        person = _person()
        hit = _hit()
        hit["deceased"] = {"life_status": "Deceased", "date": "2018-06", "precision": "month", "method": "field"}
        trace, _cmp = self._trace(person, hit)
        death = next(row for row in trace["comparison"] if row["dim"] == "death")
        self.assertIsNone(death["customer"])
        self.assertEqual(death["hit"], "2018-06")
        self.assertEqual(death["screening_date"], "2026-02-01")
        self.assertIn("Screening date", death["note"])

    def test_dob_hit_is_a_date_and_the_sentence_is_a_note(self):
        trace, _cmp = self._trace(_person())
        dob = next(row for row in trace["comparison"] if row["dim"] == "dob")
        self.assertEqual(dob["hit"], "1961-07-15")
        self.assertNotIn("listed date", dob["hit"])
        self.assertIn("1961-07-15", dob["note"])

    def test_tipping_point_is_a_sentence_and_hides_errors(self):
        person = _person()
        hit = _hit()
        alert = _alert()
        cmp = compare(hit, alert, person, NameTools(VARIANTS))
        review = Decision(
            decision="REVIEW", reason_code="INSUFFICIENT_DATA", cmp=cmp,
            missing="no customer record fits the alert",
        )
        text = hit_trace(hit, alert, {}, review, person=person)["tipping_point"]
        self.assertTrue(text.endswith("."))
        self.assertNotIn("Supplying", text)
        self.assertIn("no customer record fits the alert", text)
        failed = Decision(
            decision="REVIEW", reason_code="INSUFFICIENT_DATA", cmp=cmp,
            missing="ValueError", errored=True,
        )
        failed_text = hit_trace(hit, alert, {}, failed, person=person)["tipping_point"]
        self.assertEqual(failed_text, "The hit could not be decided.")
        self.assertNotIn("ValueError", failed_text)


if __name__ == "__main__":
    unittest.main()
