"""Golden-record edge cases. Every customer row is synthetic."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.build import build_from_tables

VARIANTS = {
    "groups": [
        ["yusuf", "joseph", "joe"],
        ["joseph", "joe", "jose"],
    ],
    "company_legal_forms": ["gmbh", "inc", "ltd", "na"],
}


def customer(record_id, **overrides):
    row = {
        "record_id": record_id,
        "entity_type": "Individual",
        "full_name": "Alice Smith",
        "preferred_name": None,
        "login_name": None,
        "dob": "1990-01-02",
        "nationality": "Nigerian",
        "residence_country": "GB",
        "city": "Oslo",
        "address": "1 High Street, Oslo",
        "email": f"{record_id.lower()}@example.com",
        "phone": "+44 7700 900123",
        "registration_number": None,
    }
    row.update(overrides)
    return row


def tables(customers, accounts=None, onboarding=None, checks=None, notes=None):
    return {
        "customers": customers,
        "accounts": accounts or [],
        "onboarding": onboarding or [],
        "kyc_checks": checks or [],
        "notes": notes or [],
        "name_variants": VARIANTS,
    }


def people_of(payload):
    built, indexes, stats = build_from_tables(payload)
    return {person["person_id"]: person for person in built}, indexes, stats


class ClusterTests(unittest.TestCase):
    def test_phone_dob_merges_different_formats_and_family_does_not(self):
        payload = tables([
            customer("CUS-000010", full_name="Costa Marcos", dob="September 12, 1985", phone="+44 799097796", email="a@example.com"),
            customer("CUS-000020", full_name="Costa Marcos", dob="1985-09-12", phone="+44799097796", email="b@example.com", residence_country="BR", nationality="Brazil"),
            customer("CUS-000030", full_name="Costa Sister", dob="1999-01-01", phone="+44 799097796", email="c@example.com"),
        ])
        people, _indexes, stats = people_of(payload)
        self.assertEqual(stats["phone_dob_edges"], 1)
        self.assertEqual(stats["persons"], 2)
        merged = people["P-CUS-000010"]
        self.assertEqual(merged["record_ids"], ["CUS-000010", "CUS-000020"])
        self.assertEqual(merged["cluster_edges"][0]["rule"], "PHONE_DOB")
        self.assertEqual(merged["cluster_edges"][0]["dob"], "1985-09-12")
        self.assertIn("P-CUS-000030", people)
        self.assertEqual(people["P-CUS-000030"]["cluster_edges"], [])

    def test_partial_dob_does_not_merge(self):
        payload = tables([
            customer("CUS-000010", dob="1990", phone="+1 415 5550100"),
            customer("CUS-000020", dob="1990-05-01", phone="+14155550100", email="b@example.com"),
        ])
        _people, _indexes, stats = people_of(payload)
        self.assertEqual(stats["persons"], 2)
        self.assertEqual(stats["phone_dob_edges"], 0)

    def test_doc_number_merges_null_dob_and_rejected_does_not(self):
        customers = [
            customer("CUS-000010", dob=None, phone="+1 202 5550101", email="a@example.com"),
            customer("CUS-000020", dob="1980-04-04", phone="+1 202 5550199", email="b@example.com"),
            customer("CUS-000030", dob="1970-01-01", phone="+1 202 5550188", email="c@example.com"),
            customer("CUS-000040", dob="1971-01-01", phone="+1 202 5550177", email="d@example.com"),
        ]
        onboarding = [
            {"customer_id": "CUS-000010", "kyc_applicant_id": "APP-1", "account_id": "ACC-1"},
            {"customer_id": "CUS-000020", "kyc_applicant_id": "APP-2", "account_id": "ACC-2"},
            {"customer_id": "CUS-000030", "kyc_applicant_id": "APP-3", "account_id": "ACC-3"},
            {"customer_id": "CUS-000040", "kyc_applicant_id": "APP-4", "account_id": "ACC-4"},
        ]
        checks = [
            _check("KYC-1000", "APP-1", "approved", "1988-01-01", "N470-106 19", "2020-01-01"),
            _check("KYC-2000", "APP-2", "approved", "1988-01-01", "n47010619", "2021-01-01", country="Canada"),
            _check("KYC-3000", "APP-3", "rejected", "1970-01-01", "XX-1", "2022-01-01"),
            _check("KYC-4000", "APP-4", "expired", "1971-01-01", "XX-1", "2023-01-01"),
        ]
        people, _indexes, stats = people_of(tables(customers, onboarding=onboarding, checks=checks))
        self.assertEqual(stats["doc_edges"], 1)
        self.assertEqual(stats["doc_edges_new_components"], 1)
        self.assertEqual(stats["persons"], 3)
        merged = people["P-CUS-000010"]
        self.assertEqual(merged["record_ids"], ["CUS-000010", "CUS-000020"])
        self.assertEqual(merged["cluster_edges"][0]["rule"], "DOC_NO")
        self.assertEqual(merged["cluster_edges"][0]["document_number"], "N47010619")
        self.assertEqual(people["P-CUS-000030"]["record_ids"], ["CUS-000030"])
        self.assertEqual(people["P-CUS-000040"]["record_ids"], ["CUS-000040"])

    def test_joint_account_does_not_merge(self):
        customers = [
            customer("CUS-000010", full_name="Luca Morillo", dob="1980-01-01", phone="+34 600111111", email="luca@example.com"),
            customer("CUS-000020", full_name="Elvira Morillo", dob="1940-01-01", phone="+34 600222222", email="elvira@example.com"),
        ]
        accounts = [
            {"account_id": "ACC-JOINT", "customer_id": "CUS-000010", "login_handle": "luca", "phone": "+34 600111111"},
            {"account_id": "ACC-JOINT", "customer_id": "CUS-000020", "login_handle": "elvira", "phone": "+34 600222222"},
            {"account_id": "ACC-ONLY", "customer_id": "CUS-000010", "login_handle": "luca2", "phone": "+34 600111111"},
        ]
        people, indexes, stats = people_of(tables(customers, accounts=accounts))
        self.assertEqual(stats["persons"], 2)
        self.assertEqual(indexes["account_id"]["ACC-JOINT"], ["P-CUS-000010", "P-CUS-000020"])
        self.assertEqual(indexes["account_id"]["ACC-ONLY"], ["P-CUS-000010"])
        self.assertEqual(indexes["login_handle"]["luca"], ["P-CUS-000010"])
        self.assertEqual(indexes["email"]["luca@example.com"], ["P-CUS-000010"])
        self.assertEqual(indexes["record_id"]["CUS-000020"], "P-CUS-000020")


class FactTests(unittest.TestCase):
    def test_verified_beats_declared_and_newer_rejected_is_ignored(self):
        customers = [
            customer("CUS-000010", full_name="Jacob Johnson", dob="1963-12-02", phone="+1 415 5550001", email="a@example.com", city="Oslo", nationality="American", residence_country="US"),
            customer("CUS-000020", full_name="Jacob Johnson", dob="02/12/1963", phone="+14155550001", email="b@example.com", nationality="US", residence_country="SG"),
        ]
        onboarding = [
            {"customer_id": "CUS-000010", "kyc_applicant_id": "APP-1", "account_id": "ACC-1"},
            {"customer_id": "CUS-000020", "kyc_applicant_id": "APP-2", "account_id": "ACC-2"},
        ]
        checks = [
            _check("KYC-OLD", "APP-1", "approved", "1968-02-17", "DOC1", "2019-01-01", name="SARAH JOHNSON", country="United States"),
            _check("KYC-NEW", "APP-1", "expired", "1999-09-09", "DOC9", "2024-01-01", name="OTHER PERSON", country="France"),
        ]
        people, _indexes, _stats = people_of(tables(customers, onboarding=onboarding, checks=checks))
        person = people["P-CUS-000010"]
        self.assertEqual(person["legal_name"]["value"], "SARAH JOHNSON")
        self.assertTrue(person["legal_name"]["verified"])
        self.assertEqual(person["legal_name"]["source_id"], "KYC-OLD")
        self.assertEqual(person["dob"]["value"], "1968-02-17")
        self.assertTrue(person["dob"]["verified"])
        self.assertEqual(person["declared_dobs"][0]["value"], "1963-12-02")
        self.assertEqual(person["ignored_checks"], [{"check_id": "KYC-NEW", "reason": "not approved", "result": "expired"}])
        self.assertNotIn("UNVERIFIED", person["flags"])
        country_values = {(item["value"], item["kind"]) for item in person["countries"]}
        self.assertIn(("United States", "nationality"), country_values)
        self.assertIn(("Singapore", "residence"), country_values)
        self.assertIn(("United States", "doc_country"), country_values)
        self.assertNotIn("Oslo", {item["value"] for item in person["countries"]})
        self.assertIsNone(person["incorporation_date"])

    def test_no_verification_and_kyc_note_and_residence(self):
        bare = customer("CUS-000010", full_name="No Check Person", dob="1981-03-03", email="bare@example.com", nationality="Spain", residence_country="ES")
        noted = customer("CUS-000020", full_name="Note Person", dob="1970-01-01", email="note@example.com", phone="+49 1510000002", nationality="Germany", residence_country="DE")
        text = (
            "Sumsub completed identity verification for NOTE PERSON, born December 1, 1975, "
            "using a passport issued in Italy on 2024-05-05."
        )
        residence = "The client declared 2014 to 2021 as the period they were working and dwelling in Ghana."
        notes = [
            {"note_id": "NOTE-A", "requester_email": "note@example.com", "created_at": "2024-05-05", "channel": "kyc", "text": text},
            {"note_id": "NOTE-B", "requester_email": "note@example.com", "created_at": "2024-06-01", "channel": "phone", "text": residence},
            {"note_id": "NOTE-C", "requester_email": "bare@example.com", "created_at": "2024-06-02", "channel": "app", "text": "Customer reported a lost card. Card frozen and a replacement ordered to the address on file."},
        ]
        people, indexes, _stats = people_of(tables([bare, noted], notes=notes))
        unverified = people["P-CUS-000010"]
        self.assertIn("UNVERIFIED", unverified["flags"])
        self.assertFalse(unverified["legal_name"]["verified"])
        self.assertEqual(unverified["legal_name"]["value"], "No Check Person")
        self.assertEqual(unverified["dob"]["source_id"], "CUS-000010")
        self.assertEqual(unverified["note_ids_residence"], [])

        verified = people["P-CUS-000020"]
        self.assertEqual(verified["legal_name"]["value"], "NOTE PERSON")
        self.assertEqual(verified["legal_name"]["source_kind"], "kyc_note")
        self.assertEqual(verified["dob"]["value"], "1975-12-01")
        self.assertTrue(verified["dob"]["verified"])
        self.assertIn("NOTE-A", verified["note_ids_verification"])
        self.assertEqual(verified["note_ids_residence"], ["NOTE-B"])
        residence_rows = [item for item in verified["countries"] if item["kind"] == "residence_note"]
        self.assertEqual(residence_rows, [{
            "kind": "residence_note",
            "source_id": "NOTE-B",
            "value": "Ghana",
            "years": [2014, 2021],
        }])
        self.assertIn("P-CUS-000020", indexes["name"]["by_part"]["note"])
        self.assertNotIn("oslo", indexes["name"]["by_part"])

    def test_two_approved_events_keep_both_countries_and_latest_wins(self):
        customers = [
            customer("CUS-000010", dob=None, phone="+1 2025550101", email="a@example.com", full_name="Same Person", nationality="Canada", residence_country="CA"),
            customer("CUS-000020", dob="1980-01-01", phone="+44 7700900999", email="b@example.com", full_name="Same Person", nationality="United States", residence_country="US"),
        ]
        onboarding = [
            {"customer_id": "CUS-000010", "kyc_applicant_id": "APP-1", "account_id": "ACC-1"},
            {"customer_id": "CUS-000020", "kyc_applicant_id": "APP-2", "account_id": "ACC-2"},
        ]
        checks = [
            _check("KYC-EARLY", "APP-1", "approved", "1980-01-01", "X74734409", "2020-01-01", name="SAME PERSON", country="Canada"),
            _check("KYC-LATE", "APP-2", "approved", "1982-02-02", "X74734409", "2023-01-01", name="OTHER HUMAN", country="United States"),
        ]
        people, _indexes, _stats = people_of(tables(customers, onboarding=onboarding, checks=checks))
        person = people["P-CUS-000010"]
        self.assertEqual(person["legal_name"]["source_id"], "KYC-LATE")
        self.assertEqual(person["dob"]["value"], "1982-02-02")
        self.assertIn("MULTI_VERIFICATION_CONFLICT", person["flags"])
        doc_countries = [item["value"] for item in person["countries"] if item["kind"] == "doc_country"]
        self.assertEqual(doc_countries, ["Canada", "United States"])

    def test_tie_breaks_kyc_over_note_then_source_id(self):
        row = customer("CUS-000010", email="a@example.com")
        onboarding = [{"customer_id": "CUS-000010", "kyc_applicant_id": "APP-1", "account_id": "ACC-1"}]
        checks = [
            _check("KYC-B", "APP-1", "approved", "1990-01-02", "D1", "2020-01-01", name="FROM CHECK B"),
            _check("KYC-A", "APP-1", "approved", "1991-01-01", "D2", "2020-01-01", name="FROM CHECK A"),
        ]
        text = "Onfido confirmed passport for FROM NOTE, born 1992-02-02, in Spain on 2020-01-01."
        notes = [{"note_id": "NOTE-A", "requester_email": "a@example.com", "created_at": "2020-01-01", "channel": "kyc", "text": text}]
        people, _indexes, _stats = people_of(tables([row], onboarding=onboarding, checks=checks, notes=notes))
        person = people["P-CUS-000010"]
        self.assertEqual(person["legal_name"]["source_id"], "KYC-A")
        self.assertEqual(person["legal_name"]["value"], "FROM CHECK A")

    def test_placeholder_short_name_and_unmapped(self):
        row = customer(
            "CUS-000010",
            full_name="PAWEŁ N/A N/A",
            nationality="Atlantis",
            residence_country="ES",
            dob="yesterday",
        )
        people, _indexes, _stats = people_of(tables([row]))
        person = people["P-CUS-000010"]
        self.assertEqual(person["legal_name"]["parts"], ["pawel"])
        self.assertIn("NAME_TOO_SHORT", person["flags"])
        self.assertIn("PLACEHOLDER_NAME", person["flags"])
        self.assertIn("UNPARSED_DATE", person["flags"])
        self.assertIn("UNMAPPED_COUNTRY", person["flags"])
        self.assertIn("UNVERIFIED", person["flags"])
        mapped = {(item["value"], item["kind"]) for item in person["countries"]}
        self.assertIn(("atlantis", "nationality"), mapped)
        self.assertIn(("Spain", "residence"), mapped)
        self.assertNotIn("Oslo", {item["value"] for item in person["countries"]})

    def test_company_incorporation_dates(self):
        full = customer(
            "CUS-000010",
            entity_type="Company",
            full_name="TD Bank, N.A. GmbH",
            dob="08/02/1985",
            nationality=None,
            residence_country="NL",
            registration_number="REG-1",
            email="co@example.com",
        )
        partial = customer(
            "CUS-000020",
            entity_type="Company",
            full_name="Partial Mills Ltd",
            dob="February 1968",
            phone="+31 201111111",
            email="part@example.com",
            residence_country="Netherlands",
            nationality=None,
        )
        onboarding = [
            {"customer_id": "CUS-000010", "kyc_applicant_id": "APP-1", "account_id": "ACC-1"},
            {"customer_id": "CUS-000020", "kyc_applicant_id": "APP-2", "account_id": "ACC-2"},
        ]
        checks = [
            _check("KYC-CO", "APP-1", "approved", "1985-02-08", None, "2022-02-02", name="TD BANK", country="Netherlands", document_type="registry extract"),
            _check("KYC-PART", "APP-2", "approved", "2013-02", None, "2022-03-03", name="PARTIAL MILLS", country="Netherlands", document_type="registry extract"),
        ]
        people, _indexes, _stats = people_of(tables([full, partial], onboarding=onboarding, checks=checks))
        company = people["P-CUS-000010"]
        self.assertEqual(company["legal_name"]["parts"], ["td", "bank"])
        self.assertEqual(company["incorporation_date"]["value"], "1985-02-08")
        self.assertEqual(company["incorporation_date"]["precision"], "day")
        self.assertTrue(company["incorporation_date"]["verified"])
        self.assertEqual(company["dob"]["value"], "1985-02-08")
        self.assertEqual(company["registration_numbers"], ["REG-1"])
        partial_person = people["P-CUS-000020"]
        self.assertEqual(partial_person["incorporation_date"]["value"], "2013-02")
        self.assertEqual(partial_person["incorporation_date"]["precision"], "month")
        self.assertEqual(partial_person["declared_dobs"][0]["value"], "1968-02")

    def test_type_conflict(self):
        customers = [
            customer("CUS-000010", entity_type="Individual", dob="1985-09-12", phone="+44 799097796"),
            customer("CUS-000020", entity_type="Company", full_name="Acme Ltd", dob="1985-09-12", phone="+44799097796", email="b@example.com"),
        ]
        people, _indexes, _stats = people_of(tables(customers))
        person = people["P-CUS-000010"]
        self.assertIsNone(person["entity_type"]["value"])
        self.assertIn("TYPE_CONFLICT", person["flags"])

    def test_byte_identical_on_synthetic(self):
        payload = tables([
            customer("CUS-000002", full_name="Zed Alpha"),
            customer("CUS-000001", full_name="Amy Beta", email="amy@example.com", phone="+1 2025550199"),
        ])
        first, indexes_a, _stats = build_from_tables(payload)
        second, indexes_b, _stats = build_from_tables(payload)
        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=False),
            json.dumps(second, sort_keys=True, ensure_ascii=False),
        )
        self.assertEqual(indexes_a, indexes_b)
        self.assertEqual([person["person_id"] for person in first], ["P-CUS-000001", "P-CUS-000002"])


class RunTests(unittest.TestCase):
    def test_executable_writes_cache_not_predictions(self):
        with tempfile.TemporaryDirectory() as folder:
            data = os.path.join(folder, "data")
            cache = os.path.join(folder, "cache")
            os.makedirs(data)
            _write_jsonl(os.path.join(data, "customers.jsonl"), [customer("CUS-000010")])
            _write_jsonl(os.path.join(data, "accounts.jsonl"), [
                {"account_id": "ACC-1", "customer_id": "CUS-000010", "login_handle": "alice", "phone": "+44 7700 900123"},
            ])
            _write_jsonl(os.path.join(data, "onboarding.jsonl"), [])
            _write_jsonl(os.path.join(data, "kyc_checks.jsonl"), [])
            _write_jsonl(os.path.join(data, "notes.jsonl"), [])
            with open(os.path.join(data, "name_variants.json"), "w", encoding="utf-8") as handle:
                json.dump(VARIANTS, handle)
            output = os.path.join(folder, "summary.json")
            env = dict(os.environ)
            env["SANCTIONS_CACHE"] = cache
            env["USE_LLM_NOTES"] = "0"
            completed = subprocess.run(
                [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run"), data, output],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(os.path.isfile(os.path.join(cache, "person_golden.jsonl")))
            self.assertTrue(os.path.isfile(os.path.join(cache, "index_record_id.json")))
            self.assertFalse(os.path.exists(os.path.join(folder, "output", "dev.jsonl")))
            with open(output, encoding="utf-8") as handle:
                summary = json.loads(handle.read())
            self.assertEqual(summary["stage"], 1)
            self.assertEqual(summary["records"], 1)
            self.assertEqual(summary["persons"], 1)


def _check(check_id, applicant, result, dob, document, checked_at, name="ALICE SMITH", country="Nigeria", document_type="passport"):
    return {
        "check_id": check_id,
        "applicant_id": applicant,
        "provider": "Persona",
        "verified_name": name,
        "verified_dob": dob,
        "document_type": document_type,
        "document_number": document,
        "document_country": country,
        "result": result,
        "checked_at": checked_at,
    }


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


if __name__ == "__main__":
    unittest.main()
