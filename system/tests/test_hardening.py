"""Stage 1 hardening contracts. Fixtures are synthetic."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.contracts import (
    customer_record_id_for_output,
    dob_mismatch_allowed,
    hit_field_evidence,
    location_mismatch_allowed,
    name_mismatch_verified_allowed,
)
from stage1.build import build_from_tables
from stage1.normalise import NameTools, parse_date

VARIANTS = {
    "groups": [
        ["yusuf", "joseph", "joe"],
        ["joseph", "joe", "jose"],
    ],
    "company_legal_forms": ["gmbh", "ltd", "na", "inc"],
}


def _greedy_agree(tools, left, right):
    """The old longest-first matcher, kept here so the regression is visible."""
    parts_left = tools.parts(left, "Individual")
    parts_right = tools.parts(right, "Individual")

    def candidates(parts):
        found = [(part, (index,)) for index, part in enumerate(parts)]
        for index in range(len(parts) - 1):
            found.append((parts[index] + parts[index + 1], (index, index + 1)))
        return found

    possible = []
    for text_left, cover_left in candidates(parts_left):
        for text_right, cover_right in candidates(parts_right):
            if tools.parts_match(text_left, text_right):
                possible.append((text_left, text_right, cover_left, cover_right))
    possible.sort(key=lambda item: (-max(len(item[0]), len(item[1])), item[0], item[1]))
    used_left, used_right, matched = set(), set(), []
    for text_left, text_right, cover_left, cover_right in possible:
        if any(index in used_left for index in cover_left) or any(index in used_right for index in cover_right):
            continue
        used_left.update(cover_left)
        used_right.update(cover_right)
        matched.append((text_left, text_right))
    shorter = parts_left if len(parts_left) <= len(parts_right) else parts_right
    shorter_used = used_left if shorter is parts_left else used_right
    covered = bool(shorter) and len(shorter_used) == len(shorter)
    return len(matched) >= 2 or covered


class NameMatcherTests(unittest.TestCase):
    def test_exhaustive_finds_pairing_greedy_misses(self):
        tools = NameTools({"groups": [], "company_legal_forms": []})
        left, right = "Aaaabbb Ccc Ddd", "Aaaabbbccc Aaaabbb Ccc Zzzzz"
        self.assertFalse(_greedy_agree(tools, left, right))
        agreed = tools.names_agree(left, right)
        self.assertTrue(agreed["agree"])
        self.assertEqual(agreed["matched_pairs"], ["aaaabbb=aaaabbb", "ccc=ccc"])
        self.assertTrue(agreed["exhaustive"])

    def test_join_across_variant_groups_on_both_sides(self):
        tools = NameTools(VARIANTS)
        agreed = tools.names_agree("Yusuf Smith", "Josephsmith")
        self.assertTrue(agreed["agree"])
        agreed = tools.names_agree("Abdul Basit", "Abdulbasit")
        self.assertTrue(agreed["agree"])

    def test_equal_length_agreement_is_symmetric(self):
        tools = NameTools(VARIANTS)
        pairs = [
            ("Aaaabbb Ccc Ddd", "Aaaabbbccc Aaaabbb Ccc Zzzzz"),
            ("Yusuf Smith", "Josephsmith"),
            ("Abdul Basit", "Abdulbasit"),
            ("Abdulsalam Zed", "Abdul Salam"),
            ("Abdul Basit Rahman", "AbdulBasit Rahman"),
            ("AbdulBasit", "Abdul Basit"),
            ("Mark", "Markus"),
            ("Joseph", "Yusuf"),
            ("Yusuf", "Jose"),
            ("Raskovic", "Raković"),
            ("Starling", "Sterling"),
            ("Carl E. Andersen", "Andersen, Carl"),
            ("John Smith", "John"),
            ("Sarah Johnson", "James Jacob Johnson"),
            ("", "Ada Lovelace"),
            ("J.R. Example", "Example Junior"),
        ]
        bare = NameTools({"groups": [], "company_legal_forms": []})
        for left, right in pairs:
            forward = tools.names_agree(left, right)["agree"]
            backward = tools.names_agree(right, left)["agree"]
            self.assertEqual(forward, backward, (left, right))
            self.assertEqual(bare.names_agree(left, right)["agree"], bare.names_agree(right, left)["agree"], (left, right))
        self.assertTrue(tools.names_agree("Abdulsalam Zed", "Abdul Salam")["agree"])
        self.assertTrue(tools.names_agree("Abdul Salam", "Abdulsalam Zed")["agree"])

    def test_dotted_initials_and_placeholder_only(self):
        tools = NameTools(VARIANTS)
        self.assertEqual(tools.parts("J.R. Example", "Individual"), ["jr", "example"])
        self.assertEqual(tools.parts("J.R.", "Individual"), ["jr"])
        person = _only(build_from_tables(_tables([
            _customer("CUS-SYN010", full_name="J.R."),
            _customer("CUS-SYN020", full_name="N/A N/A", email="na@example.com", phone="+1 2025550102"),
        ])))
        short = person["P-CUS-SYN010"]
        self.assertEqual(short["legal_name"]["parts"], ["jr"])
        self.assertTrue(short["legal_name"]["blocks_name_clear"])
        self.assertIn("NAME_TOO_SHORT", short["flags"])
        self.assertIn("BLOCK_NAME_CLEAR", short["flags"])
        self.assertFalse(name_mismatch_verified_allowed(short))
        placeholder = person["P-CUS-SYN020"]
        self.assertEqual(placeholder["legal_name"]["parts"], [])
        self.assertIn("PLACEHOLDER_NAME", placeholder["flags"])
        self.assertIn("BLOCK_NAME_CLEAR", placeholder["flags"])
        self.assertFalse(name_mismatch_verified_allowed(placeholder))
        usable = next(row for row in short["names_all"] if row["kind"] == "legal_name")
        self.assertTrue(usable["blocks_name_clear"])
        self.assertEqual(usable["real_part_count"], 1)


class ContractTests(unittest.TestCase):
    def test_negative_kyc_note_is_not_a_verification(self):
        text = (
            "Sumsub rejected identity verification for ALICE SMITH, born January 2, 1990, "
            "using a national ID issued in Nigeria on 2024-05-01. The check was declined."
        )
        people, _indexes, _stats = build_from_tables(_tables(
            [_customer("CUS-SYN010")],
            notes=[{
                "note_id": "NOTE-NEG1",
                "requester_email": "cus-syn010@example.com",
                "channel": "kyc",
                "created_at": "2024-05-01",
                "text": text,
            }],
        ))
        person = people[0]
        self.assertEqual(person["note_ids_verification"], [])
        self.assertNotIn("NOTE-NEG1", [event.get("source_id") for event in person["verification_events"]])
        self.assertIn("BLOCK_DOB_AGE_NAME_CLEAR", person["flags"])
        self.assertIn("NOTE_FLAGGED:NOTE-NEG1", person["flags"])
        self.assertFalse(name_mismatch_verified_allowed(person))
        self.assertFalse(dob_mismatch_allowed(person, "1980-01-01"))
    def test_unverified_name_cannot_clear_on_name_mismatch(self):
        people = _only(build_from_tables(_tables([
            _customer("CUS-SYN010", full_name="Alice Smith"),
        ])))
        person = people["P-CUS-SYN010"]
        self.assertFalse(person["legal_name"]["verified"])
        self.assertEqual(person["legal_name"]["method"], "record")
        self.assertFalse(person["legal_name"]["may_solely_support_different_entity"])
        self.assertIn("BLOCK_NAME_MISMATCH_VERIFIED", person["flags"])
        self.assertTrue(person["contracts"]["block_name_mismatch_verified"])
        self.assertFalse(name_mismatch_verified_allowed(person))

    def test_unparsed_note_blocks_location_and_verification_clears(self):
        notes = [{
            "note_id": "NOTE-SYN001",
            "requester_email": "cus-syn010@example.com",
            "created_at": "2024-01-01",
            "channel": "phone",
            "text": "The client lived in Spain and Ghana between 2010 and 2012.",
        }, {
            "note_id": "NOTE-SYN002",
            "requester_email": "cus-syn010@example.com",
            "created_at": "2024-02-02",
            "channel": "kyc",
            "text": "Passport mentioned for someone on 2024-02-02 but the wording is not a clean verification.",
        }]
        people = _only(build_from_tables(_tables([
            _customer("CUS-SYN010", full_name="Alice Smith", residence_country="ES", nationality="Spain"),
        ], notes=notes)))
        person = people["P-CUS-SYN010"]
        values = {item["value"] for item in person["countries"]}
        self.assertIn("Spain", values)
        self.assertIn("Ghana", values)
        self.assertIn("BLOCK_LOCATION_MISMATCH", person["flags"])
        self.assertIn("BLOCK_DOB_AGE_NAME_CLEAR", person["flags"])
        self.assertTrue(any(flag.startswith("NOTE_FLAGGED:") for flag in person["flags"]))
        self.assertFalse(location_mismatch_allowed(person))
        self.assertFalse(dob_mismatch_allowed(person, "1970-01-01"))

    def test_declared_dobs_keep_every_record_and_block_partial_contradiction(self):
        people = _only(build_from_tables(_tables(
            [
                _customer("CUS-SYN010", dob=None, phone="+1 2025550101"),
                _customer("CUS-SYN020", dob="1980-03-04", phone="+44 7700900999", email="b@example.com"),
                _customer("CUS-SYN030", dob="1970-01-01", phone="+33 612345678", email="c@example.com"),
            ],
            onboarding=[
                {"customer_id": "CUS-SYN010", "kyc_applicant_id": "APP-1", "account_id": "ACC-1"},
                {"customer_id": "CUS-SYN020", "kyc_applicant_id": "APP-2", "account_id": "ACC-2"},
            ],
            checks=[
                _check("KYC-SYN101", "APP-1", "DOC-1"),
                _check("KYC-SYN102", "APP-2", "DOC-1"),
            ],
        )))
        merged = people["P-CUS-SYN010"]
        by_id = {row["source_id"]: row for row in merged["declared_dobs"]}
        self.assertFalse(by_id["CUS-SYN010"]["comparable"])
        self.assertEqual(by_id["CUS-SYN020"]["value"], "1980-03-04")
        self.assertIn("CUS-SYN010", by_id["CUS-SYN010"]["source_id"])
        self.assertFalse(dob_mismatch_allowed(merged, "1970-05-05"))
        both_contradict = {
            "flags": [],
            "declared_dobs": [
                {"value": "1970-01-01", "precision": "day", "source_id": "CUS-SYN030", "comparable": True},
                {"value": "1971-01-01", "precision": "day", "source_id": "CUS-SYN031", "comparable": True},
            ],
        }
        self.assertTrue(dob_mismatch_allowed(both_contradict, "1980-03-04"))
        one_agrees = {
            "flags": [],
            "declared_dobs": [
                {"value": "1980-03-04", "precision": "day", "source_id": "CUS-SYN020", "comparable": True},
                {"value": "1970-01-01", "precision": "day", "source_id": "CUS-SYN030", "comparable": True},
            ],
        }
        self.assertFalse(dob_mismatch_allowed(one_agrees, "1980-03-04"))

    def test_hit_slash_dates_are_unknown_when_ambiguous(self):
        parsed, flags = parse_date("03/04/1980", mode="hit")
        self.assertIsNone(parsed)
        self.assertEqual(flags, ["UNKNOWN_DATE"])
        customer, customer_flags = parse_date("04 March 1980", mode="customer")
        self.assertEqual(customer["value"], "1980-03-04")
        self.assertEqual(customer_flags, [])
        person = {
            "flags": [],
            "declared_dobs": [
                {"value": "1980-03-04", "precision": "day", "source_id": "CUS-SYN010", "comparable": True},
            ],
        }
        self.assertFalse(dob_mismatch_allowed(person, "03/04/1980"))
        day, day_flags = parse_date("15/04/1980", mode="hit")
        self.assertEqual(day_flags, [])
        self.assertEqual(day["value"], "1980-04-15")

    def test_output_ids_are_cus_not_person_ids(self):
        people = _only(build_from_tables(_tables([
            _customer("CUS-SYN010", full_name="Alice Smith"),
            _customer("CUS-SYN020", full_name="Alice Smith", dob="1990-01-02", phone="+44 7700 900123", email="b@example.com"),
        ])))
        person = people["P-CUS-SYN010"]
        self.assertTrue(person["person_id"].startswith("P-"))
        self.assertEqual(person["customer_record_ids"], ["CUS-SYN010", "CUS-SYN020"])
        self.assertTrue(person["contracts"]["emit_customer_record_id_not_person_id"])
        # Production output checks stay ^CUS-[0-9]{6}$ and ^H-[0-9A-F]{6}#field$.
        # CUS-SYN* / H-SYN* fixtures are rejected. The stand-in below is only
        # the shape those helpers accept, not a dev-dataset id.
        conforming_a = "CUS-" + "900010"
        conforming_b = "CUS-" + "900020"
        chosen = customer_record_id_for_output(
            {"customer_record_ids": [conforming_a, conforming_b]}
        )
        self.assertEqual(chosen, conforming_a)
        self.assertFalse(chosen.startswith("P-"))
        with self.assertRaises(ValueError):
            customer_record_id_for_output(person)
        hit = "H-" + "ABCDEF"
        self.assertEqual(hit_field_evidence(hit, "dob"), hit + "#dob")
        with self.assertRaises(ValueError):
            hit_field_evidence("H-SYN2CD", "dob")
        for fact in (person["legal_name"], person["dob"], person["entity_type"]):
            self.assertIn("source_id", fact)


def _tables(customers, accounts=None, onboarding=None, checks=None, notes=None):
    return {
        "customers": customers,
        "accounts": accounts or [],
        "onboarding": onboarding or [],
        "kyc_checks": checks or [],
        "notes": notes or [],
        "name_variants": VARIANTS,
    }


def _customer(record_id, **overrides):
    row = {
        "record_id": record_id,
        "entity_type": "Individual",
        "full_name": "Alice Smith",
        "preferred_name": None,
        "login_name": None,
        "dob": "1990-01-02",
        "nationality": "Nigeria",
        "residence_country": "GB",
        "city": "Oslo",
        "address": "1 Road",
        "email": f"{record_id.lower()}@example.com",
        "phone": "+44 7700 900123",
        "registration_number": None,
    }
    row.update(overrides)
    return row


def _check(check_id, applicant, document):
    return {
        "check_id": check_id,
        "applicant_id": applicant,
        "provider": "Persona",
        "verified_name": "ALICE SMITH",
        "verified_dob": "1990-01-02",
        "document_type": "passport",
        "document_number": document,
        "document_country": "Nigeria",
        "result": "approved",
        "checked_at": "2020-01-01",
    }


def _only(built):
    people, _indexes, _stats = built
    return {person["person_id"]: person for person in people}


if __name__ == "__main__":
    unittest.main()
