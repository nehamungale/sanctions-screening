"""Note parser tests. Sentences are synthetic or taken from the spec's examples."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.llm import fill_null_slots
from stage1.notes import NOISE, extract_kyc, parse_note

NOISE_SENTENCE = "Customer reported a lost card. Card frozen and a replacement ordered to the address on file."


class KycTests(unittest.TestCase):
    def test_standard_note(self):
        text = (
            "Sumsub completed identity verification for NILS MARTIN, born December 13, 1977, "
            "using a national ID issued in Germany on 2023-02-19."
        )
        parsed = extract_kyc(text, "2023-02-19")
        self.assertEqual(parsed["name"], "NILS MARTIN")
        self.assertEqual(parsed["dob"], "1977-12-13")
        self.assertEqual(parsed["dob_precision"], "day")
        self.assertEqual(parsed["doc_country"], "Germany")
        self.assertEqual(parsed["document_type"], "national ID")
        self.assertEqual(parsed["provider"], "Sumsub")
        self.assertEqual(parsed["check_date"], "2023-02-19")
        self.assertEqual(parsed["flags"], [])

    def test_day_first_and_demonym(self):
        text = (
            "AMAKA AFOLABI's identity was confirmed via Veriff on 2024-04-26 "
            "using a Nigerian national ID. DOB recorded as 10/08/1988."
        )
        parsed = extract_kyc(text, "2024-04-26")
        self.assertEqual(parsed["name"], "AMAKA AFOLABI")
        self.assertEqual(parsed["dob"], "1988-08-10")
        self.assertEqual(parsed["doc_country"], "Nigeria")
        self.assertEqual(parsed["provider"], "Veriff")
        self.assertEqual(parsed["flags"], [])

    def test_year_only(self):
        text = (
            "Identity check successfully performed via Onfido on 2024-10-03 for ASAD ULLAH KHAN, "
            "born 1966, using a United Kingdom driving licence."
        )
        parsed = extract_kyc(text, "2024-10-03")
        self.assertEqual(parsed["name"], "ASAD ULLAH KHAN")
        self.assertEqual(parsed["dob"], "1966")
        self.assertEqual(parsed["dob_precision"], "year")
        self.assertEqual(parsed["doc_country"], "United Kingdom")
        self.assertEqual(parsed["document_type"], "driving licence")
        self.assertEqual(parsed["flags"], [])

    def test_unicode_and_placeholders(self):
        text = (
            "Sumsub verified the identity of PAWEŁ N/A N/A on 2025-02-20, utilizing a driving "
            "licence from Spain showing 20 September 1962 as the birth date."
        )
        parsed = extract_kyc(text, "2025-02-20")
        self.assertEqual(parsed["name"], "PAWEŁ N/A N/A")
        self.assertEqual(parsed["dob"], "1962-09-20")
        self.assertEqual(parsed["doc_country"], "Spain")
        self.assertNotIn("name_ambiguous", parsed["flags"])

    def test_leading_placeholder(self):
        text = (
            "Verification for N/A GILBERT, born May 21, 1995, was approved by Sumsub on "
            "2023-02-24 using a national ID from United States."
        )
        parsed = extract_kyc(text, "2023-02-24")
        self.assertEqual(parsed["name"], "N/A GILBERT")
        self.assertEqual(parsed["dob"], "1995-05-21")
        self.assertEqual(parsed["flags"], [])

    def test_distractors(self):
        text = (
            "On 2025-06-18, Onfido cleared LIAM HALL, born 1997-01-15, following the verification "
            "of an Italy-issued driving licence (Note: United Kingdom)."
        )
        parsed = extract_kyc(text, "2025-06-18")
        self.assertEqual(parsed["name"], "LIAM HALL")
        self.assertEqual(parsed["doc_country"], "Italy")
        self.assertIn("note_annotation", parsed["flags"])
        self.assertNotIn("country_ambiguous", parsed["flags"])

        competitor = (
            "NICOLE JAMES JACKSON had her passport verified by Sumsub's competitor, Veriff, "
            "on 2025-07-27. The document from United States lists her DOB as 04/12/1976."
        )
        parsed = extract_kyc(competitor, "2025-07-27")
        self.assertIsNone(parsed["provider"])
        self.assertEqual(parsed["name"], "NICOLE JAMES JACKSON")
        self.assertEqual(parsed["dob"], "1976-12-04")
        self.assertEqual(parsed["doc_country"], "United States")

    def test_sentence_initial_letter_is_not_a_second_name(self):
        text = (
            "A Spain passport was checked for ADA LOVELACE, born June 1, 1990, "
            "using Onfido on 2024-01-02."
        )
        parsed = extract_kyc(text, "2024-01-02")
        self.assertEqual(parsed["name"], "ADA LOVELACE")
        self.assertEqual(parsed["dob"], "1990-06-01")
        self.assertEqual(parsed["flags"], [])

    def test_status_word_passed_is_a_second_run(self):
        text = (
            "Verification PASSED for ADA LOVELACE, born June 1, 1990. "
            "Passport from Spain was checked by Veriff on 2024-01-02."
        )
        parsed = extract_kyc(text, "2024-01-02")
        self.assertIsNone(parsed["name"])
        self.assertIn("name_ambiguous", parsed["flags"])
        self.assertEqual(parsed["dob"], "1990-06-01")
        self.assertEqual(parsed["doc_country"], "Spain")

    def test_kyc_token_and_id_card(self):
        text = (
            "KYC review completed for KELECHI ADEBAYO MUSA on 2024-03-13 via Sumsub. "
            "Passport from Nigeria verified, confirming DOB December 10, 1973."
        )
        parsed = extract_kyc(text, "2024-03-13")
        self.assertEqual(parsed["name"], "KELECHI ADEBAYO MUSA")
        self.assertEqual(parsed["dob"], "1973-12-10")
        self.assertNotIn("name_ambiguous", parsed["flags"])

        card = "On 2023-04-15, Onfido successfully validated PABLO CONTI, born 24/04/1959, using an ID card from France."
        parsed = extract_kyc(card, "2023-04-15")
        self.assertEqual(parsed["document_type"], "unknown_id")
        self.assertEqual(parsed["doc_country"], "France")
        self.assertEqual(parsed["name"], "PABLO CONTI")


class ResidenceTests(unittest.TestCase):
    def test_residence_and_noise(self):
        text = "Employment and residency in Bangladesh were reported by the individual for 2015 to 2019."
        parsed = parse_note({"note_id": "NOTE-1", "channel": "phone", "created_at": "2020-01-01", "text": text})
        self.assertEqual(parsed["kind"], "residence")
        self.assertEqual(parsed["event"]["country"], "Bangladesh")
        self.assertEqual(parsed["event"]["year_from"], 2015)
        self.assertEqual(parsed["event"]["year_to"], 2019)
        self.assertEqual(parsed["flags"], [])

        noise = parse_note({"note_id": "NOTE-2", "channel": "app", "created_at": "2020-01-01", "text": NOISE_SENTENCE})
        self.assertEqual(noise["kind"], "noise")
        self.assertEqual(len(NOISE), 6)

    def test_negation_is_not_evidence(self):
        text = "The client did not live in Ghana from 2015 to 2019."
        parsed = parse_note({"note_id": "NOTE-3", "channel": "phone", "created_at": "2020-01-01", "text": text})
        self.assertEqual(parsed["kind"], "ignored")
        self.assertIn("negation", parsed["flags"])

    def test_unknown_channel_flagged(self):
        text = "Lived in Ghana between 2011 and 2014."
        parsed = parse_note({"note_id": "NOTE-4", "channel": "fax", "created_at": "2020-01-01", "text": text})
        self.assertIn("unknown_channel", parsed["flags"])
        self.assertNotEqual(parsed["kind"], "residence")


class LlmTests(unittest.TestCase):
    def test_off_by_default_and_nulls_only(self):
        calls = []

        def transport(text):
            calls.append(text)
            return {"name": "SHOULD NOT APPLY", "dob": "1990-01-01", "doc_country": "France"}

        parsed = extract_kyc(
            "Sumsub completed identity verification for NILS MARTIN, born December 13, 1977, "
            "using a national ID issued in Germany on 2023-02-19.",
            "2023-02-19",
        )
        filled = fill_null_slots("note", parsed, transport=transport, enabled=False)
        self.assertEqual(calls, [])
        self.assertEqual(filled["name"], "NILS MARTIN")

        empty = {
            "name": None,
            "dob": None,
            "dob_precision": None,
            "doc_country": None,
            "flags": ["dob_unresolved", "name_ambiguous", "country_ambiguous"],
        }
        text = "Manual review for ADA LOVELACE born 1990-01-01 in Spain."
        filled = fill_null_slots(text, empty, transport=transport, enabled=True)
        self.assertEqual(filled["name"], None)
        self.assertEqual(filled["doc_country"], None)
        self.assertIn("llm_rejected", filled["flags"])
        self.assertEqual(filled["dob"], "1990-01-01")
        self.assertEqual(filled["llm_fields"], ["dob"])

        protected = {"name": "NILS MARTIN", "dob": "1977-12-13", "dob_precision": "day", "doc_country": "Germany", "flags": ["note_annotation"]}
        filled = fill_null_slots(text, protected, transport=transport, enabled=True)
        self.assertEqual(filled["name"], "NILS MARTIN")
        self.assertEqual(filled["dob"], "1977-12-13")
        self.assertNotIn("llm_fields", filled)


if __name__ == "__main__":
    unittest.main()
