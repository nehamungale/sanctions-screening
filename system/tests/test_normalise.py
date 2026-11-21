"""Unit tests for normalisers. Fixtures are hand-written, not dataset rows."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.countries import countries_in_note, norm_country
from stage1.normalise import NameTools, dates_compatible, dates_identical_full, levenshtein, norm_docno, norm_email, norm_phone, parse_date
from stage1.normalise_text import norm_text

VARIANTS = {
    "groups": [
        ["yusuf", "yousef", "joseph", "joe"],
        ["joseph", "joe", "jose", "giuseppe"],
        ["robert", "rob", "bob", "roberto"],
        ["muhammad", "mohammed", "mohamed"],
    ],
    "company_legal_forms": ["ab", "ag", "gmbh", "inc", "llc", "ltd", "na", "sa", "se"],
}


class TextTests(unittest.TestCase):
    def test_transliteration(self):
        self.assertEqual(norm_text("PAWEŁ"), "pawel")
        self.assertEqual(norm_text("Müller-Kägi"), "muller-kagi")
        self.assertEqual(norm_text("Jørgensen"), "jorgensen")
        self.assertEqual(norm_text("Straße"), "strasse")
        self.assertEqual(norm_text("ÆØÅ"), "aeoa")
        self.assertEqual(norm_text("Þór"), "thor")

    def test_accents_drop(self):
        self.assertEqual(norm_text("Raković"), "rakovic")
        self.assertEqual(norm_text("GOZNÁLEZ"), "goznalez")
        self.assertEqual(norm_text("González"), "gonzalez")


class DateTests(unittest.TestCase):
    def test_formats(self):
        day, flags = parse_date("1979-12-02")
        self.assertEqual(flags, [])
        self.assertEqual(day["value"], "1979-12-02")
        self.assertEqual(day["precision"], "day")
        self.assertEqual(parse_date("19/05/2004")[0]["value"], "2004-05-19")
        self.assertEqual(parse_date("05/06/2004")[0]["value"], "2004-06-05")
        self.assertEqual(parse_date("27 June 1967")[0]["value"], "1967-06-27")
        self.assertEqual(parse_date("February 19, 2002")[0]["value"], "2002-02-19")
        year, _flags = parse_date("1990")
        self.assertEqual((year["precision"], year["value"], year["m"], year["d"]), ("year", "1990", None, None))
        month, _flags = parse_date("2013-02")
        self.assertEqual((month["precision"], month["value"], month["d"]), ("month", "2013-02", None))
        named, _flags = parse_date("February 1968")
        self.assertEqual(named["value"], "1968-02")
        self.assertEqual(named["precision"], "month")

    def test_day_first_and_invalid(self):
        self.assertIsNone(parse_date(None)[0])
        self.assertEqual(parse_date(None)[1], [])
        self.assertEqual(parse_date("n/a")[1], [])
        parsed, flags = parse_date("not-a-date")
        self.assertIsNone(parsed)
        self.assertEqual(flags, ["UNPARSED_DATE"])
        self.assertEqual(parse_date("31/02/2000")[1], ["UNPARSED_DATE"])
        self.assertEqual(parse_date("32/01/2000")[1], ["UNPARSED_DATE"])

    def test_compatibility(self):
        full, _flags = parse_date("1990-06-01")
        year, _flags = parse_date("1990")
        other, _flags = parse_date("1991-06-01")
        self.assertTrue(dates_compatible(full, year))
        self.assertFalse(dates_compatible(full, other))
        self.assertFalse(dates_identical_full(full, year))
        self.assertTrue(dates_identical_full(full, parse_date("01/06/1990")[0]))
        month, _flags = parse_date("2013-02")
        inside, _flags = parse_date("2013-02-08")
        self.assertTrue(dates_compatible(month, inside))


class CountryTests(unittest.TestCase):
    def test_codes_names_demonyms(self):
        codes = {
            "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BD": "Bangladesh",
            "BR": "Brazil", "CA": "Canada", "CI": "Côte d'Ivoire", "DE": "Germany",
            "DK": "Denmark", "ES": "Spain", "FI": "Finland", "FR": "France",
            "GB": "United Kingdom", "GH": "Ghana", "ID": "Indonesia", "IE": "Ireland",
            "IN": "India", "IT": "Italy", "KE": "Kenya", "MX": "Mexico", "NG": "Nigeria",
            "NL": "Netherlands", "NO": "Norway", "PE": "Peru", "PK": "Pakistan",
            "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Serbia",
            "SE": "Sweden", "SG": "Singapore", "US": "United States", "ZA": "South Africa",
        }
        for code, name in codes.items():
            self.assertEqual(norm_country(code)[0], name, code)
            self.assertEqual(norm_country(name)[1], [])
        self.assertEqual(norm_country("Nigerian")[0], "Nigeria")
        self.assertEqual(norm_country("British")[0], "United Kingdom")
        self.assertEqual(norm_country("the United States")[0], "United States")
        self.assertEqual(norm_country("the United Kingdom")[0], "United Kingdom")
        self.assertEqual(norm_country("USA")[0], "United States")
        self.assertEqual(norm_country("UK")[0], "United Kingdom")
        self.assertEqual(norm_country("Cote D'Ivoire")[0], "Côte d'Ivoire")
        self.assertEqual(norm_country("Côte d'Ivoire")[0], "Côte d'Ivoire")
        self.assertEqual(norm_country("Northern Mariana Islands")[0], "Northern Mariana Islands")
        self.assertEqual(norm_country("Deutschland")[0], "Germany")
        self.assertEqual(norm_country("Côte d Ivoire")[0], "Côte d'Ivoire")
        self.assertEqual(norm_country("the UK")[0], "United Kingdom")
        self.assertEqual(countries_in_note("She lived in the UK and later in Deutschland."), ["United Kingdom", "Germany"])
        self.assertEqual(countries_in_note("Posted to Côte d Ivoire."), ["Côte d'Ivoire"])
        self.assertNotEqual(norm_country("MP")[0], "United States")

    def test_macao_kosovo_palestine(self):
        macao = (
            "MO",
            "Macao",
            "Macau",
            "Macao SAR",
            "Macau SAR",
            "Macao SAR of China",
            "Macau SAR of China",
            "Macao Special Administrative Region of China",
            "Macau Special Administrative Region of China",
        )
        for spelling in macao:
            self.assertEqual(norm_country(spelling)[0], "Macao", spelling)
            self.assertEqual(norm_country(spelling)[1], [], spelling)
        for spelling in ("XK", "Kosovo"):
            self.assertEqual(norm_country(spelling)[0], "Kosovo", spelling)
            self.assertEqual(norm_country(spelling)[1], [], spelling)
        for spelling in ("PS", "Palestine", "Palestina", "State of Palestine", "Palestinian Territories"):
            self.assertEqual(norm_country(spelling)[0], "Palestine", spelling)
            self.assertEqual(norm_country(spelling)[1], [], spelling)

    def test_unmapped(self):
        value, flags = norm_country("Atlantis")
        self.assertEqual(value, "atlantis")
        self.assertEqual(flags, ["UNMAPPED_COUNTRY"])
        self.assertEqual(norm_country(None), (None, []))
        self.assertEqual(norm_country("  "), (None, []))


class PhoneTests(unittest.TestCase):
    def test_phone_email_doc(self):
        self.assertEqual(norm_phone("+44 799097796"), "+44799097796")
        self.assertEqual(norm_phone("0044 799"), "0044799")
        self.assertIsNone(norm_phone(None))
        self.assertIsNone(norm_phone("no digits"))
        self.assertEqual(norm_email("  Ada.Lovelace@Example.com "), "ada.lovelace@example.com")
        self.assertEqual(norm_docno("n470-106 19"), "N47010619")
        self.assertIsNone(norm_docno("  "))
        self.assertIsNone(norm_docno(None))


class NameTests(unittest.TestCase):
    def setUp(self):
        self.names = NameTools(VARIANTS)

    def test_parts_and_placeholders(self):
        self.assertEqual(self.names.parts("EMEKA EMEKA NWOSU", "Individual"), ["emeka", "nwosu"])
        self.assertEqual(self.names.parts("Carl E. Andersen", "Individual"), ["carl", "andersen"])
        parts, placeholder = self.names.split("PAWEŁ N/A N/A", "Individual")
        self.assertEqual(parts, ["pawel"])
        self.assertTrue(placeholder)
        parts, placeholder = self.names.split("SANI 0000 0000", "Individual")
        self.assertEqual(parts, ["sani"])
        self.assertTrue(placeholder)
        parts, placeholder = self.names.split("NA ANNI", "Individual")
        self.assertEqual(parts, ["anni"])
        self.assertTrue(placeholder)
        self.assertEqual(self.names.parts("TD Bank, N.A. GmbH", "Company"), ["td", "bank"])
        self.assertEqual(
            self.names.parts("Metropolitan Transportation Authority, Inc. (MTA)", "Company"),
            ["metropolitan", "transportation", "authority"],
        )
        self.assertFalse(self.names.split("TD Bank, N.A. GmbH", "Company")[1])

    def test_variants_and_distance(self):
        self.assertEqual(levenshtein("ab", "ba"), 2)
        self.assertTrue(self.names.parts_match("joseph", "yusuf"))
        self.assertTrue(self.names.parts_match("joseph", "jose"))
        self.assertFalse(self.names.parts_match("yusuf", "jose"))
        self.assertFalse(self.names.parts_match("mark", "markus"))
        self.assertTrue(self.names.parts_match("starling", "sterling"))
        self.assertTrue(self.names.parts_match("raskovic", "rakovic"))
        self.assertTrue(self.names.parts_match("cirstian", "cristian"))
        self.assertTrue(self.names.parts_match("goznalez", "gonzalez"))
        self.assertFalse(self.names.parts_match("abcd", "abdc"))
        self.assertFalse(self.names.parts_match("ab", "abc"))

    def test_names_agree(self):
        agree = self.names.names_agree("Abdul Basit Rahman", "AbdulBasit Rahman")
        self.assertTrue(agree["agree"])
        agree = self.names.names_agree("AbdulBasit", "Abdul Basit")
        self.assertTrue(agree["agree"])
        self.assertEqual(agree["reason"], "shorter covered")
        self.assertFalse(self.names.names_agree("Mark", "Markus")["agree"])
        self.assertTrue(self.names.names_agree("Joseph", "Yusuf")["agree"])
        self.assertFalse(self.names.names_agree("Yusuf", "Jose")["agree"])
        self.assertTrue(self.names.names_agree("Raskovic", "Raković")["agree"])
        self.assertTrue(self.names.names_agree("Starling", "Sterling")["agree"])
        self.assertTrue(self.names.names_agree("Carl E. Andersen", "Andersen, Carl")["agree"])
        self.assertTrue(self.names.names_agree("John Smith", "John")["agree"])
        self.assertFalse(self.names.names_agree("Sarah Johnson", "James Jacob Johnson")["agree"])
        self.assertFalse(self.names.names_agree("", "Ada Lovelace")["agree"])


if __name__ == "__main__":
    unittest.main()
