"""Stage 2 parsers and profile assembly. Fixtures are invented, not dev rows."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.llm_client import OpenRouterClient
from stage1.countries import norm_country
from stage1.normalise import NameTools
from stage2.build import build_profiles
from stage2.llm import NoteFallback, candidate_from_model, llm_enabled
from stage2.notes import parse_dated_reports, parse_note_dob
from stage2.search import evaluate_search, search_key

VARIANTS = {"groups": [["robert", "bob"]], "company_legal_forms": ["ltd", "inc", "sa", "gmbh"]}
PHRASE = "a politically exposed person"


def hit(**overrides):
    base = {
        "hit_id": "H-SYN0AA",
        "alert_id": "A-0000AA",
        "match_score": 95,
        "entity_type": "Individual",
        "name": "Quinn, Ada",
        "first_name": "Ada",
        "middle_name": None,
        "last_name": "Quinn",
        "best_matching_name": None,
        "aliases": [],
        "dobs": [],
        "place_of_birth": None,
        "life_status": "Alive",
        "deceased_date": None,
        "nationality": [],
        "citizenship": [],
        "countries": ["Ireland"],
        "addresses": [],
        "categories": ["PEP"],
        "primary_category": "PEP",
        "profile_notes": None,
    }
    base.update(overrides)
    return base


def profiles(rows, results=None, enabled=False, transport=None, cache_dir=None):
    built, fallback = build_profiles(
        rows,
        results or [],
        VARIANTS,
        cache_dir=cache_dir,
        enabled=enabled,
        transport=transport,
    )
    return built, fallback


class NameTests(unittest.TestCase):
    def test_surname_given_has_the_same_parts(self):
        tools = NameTools(VARIANTS)
        left = tools.split("Quinn, Ada", "Individual")[0]
        right = tools.split("Ada Quinn", "Individual")[0]
        self.assertEqual(sorted(left), sorted(right))
        self.assertEqual(left, ["quinn", "ada"])

    def test_alias_tags_and_nickname_and_single_part(self):
        rows, _fallback = profiles([hit(
            aliases=["Ada Quinn (AKA)", "Addie (Nickname)", "Cher (AKA)", "AQ (Acronym)"],
        )])
        aliases = [entry for entry in rows[0]["names"] if entry["kind"] == "alias"]
        self.assertEqual([entry["tag"] for entry in aliases], ["AKA", "Nickname", "AKA", "Acronym"])
        self.assertEqual(aliases[1]["parts"], ["addie"])
        self.assertEqual(aliases[2]["parts"], ["cher"])
        self.assertEqual(aliases[0]["source_id"], "H-SYN0AA#aliases")
        self.assertEqual(aliases[0]["source_field"], "aliases[0]")

    def test_non_latin_alias_is_kept_without_parts(self):
        rows, _fallback = profiles([hit(aliases=["علي (None, Arabic)", "Ada (AKA)"])])
        non_latin = rows[0]["names"][1]
        self.assertEqual(non_latin["script"], "non_latin")
        self.assertEqual(non_latin["parts"], [])
        self.assertEqual(non_latin["tag"], "None, Arabic")
        self.assertIn("NON_LATIN_ALIAS", rows[0]["flags"])
        self.assertEqual(rows[0]["names"][2]["parts"], ["ada"])

    def test_company_legal_form_dropped(self):
        rows, _fallback = profiles([hit(
            entity_type="Company",
            name="Northwind Trading Ltd",
            first_name=None,
            last_name=None,
            categories=["Registration"],
            primary_category=None,
        )])
        self.assertEqual(rows[0]["names"][0]["parts"], ["northwind", "trading"])
        self.assertEqual(rows[0]["listing"]["phrase"], "named on a watchlist")
        self.assertEqual(rows[0]["listing"]["from"], "categories")

    def test_structured_name_dropped_when_parts_match(self):
        rows, _fallback = profiles([hit(name="Ada Quinn")])
        kinds = [entry["kind"] for entry in rows[0]["names"]]
        self.assertNotIn("structured", kinds)
        kept, _fallback = profiles([hit(name="Quinn, Ada Mae", middle_name="Belle")])
        structured = [entry for entry in kept[0]["names"] if entry["kind"] == "structured"]
        self.assertEqual(len(structured), 1)
        self.assertEqual(structured[0]["parts"], ["ada", "belle", "quinn"])
        self.assertEqual(structured[0]["source_id"], "H-SYN0AA#name")
        self.assertNotIn("#structured", structured[0]["source_id"])


class DateTests(unittest.TestCase):
    def test_mixed_precision_and_ambiguous_slash(self):
        rows, _fallback = profiles([hit(dobs=["1990", "1991-02", "1992-03-04", "03/04/1980"])])
        candidates = rows[0]["dob_candidates"]
        self.assertEqual([item["precision"] for item in candidates], ["year", "month", "day"])
        self.assertEqual(candidates[2]["day"], 4)
        self.assertEqual(candidates[0]["source_id"], "H-SYN0AA#dobs")
        self.assertIn("DOBS_UNPARSED", rows[0]["flags"])
        self.assertFalse(rows[0]["search_results"]["consulted"])
        self.assertEqual(rows[0]["dob_tier"], "tier1")
        self.assertFalse(rows[0]["search_results"]["consulted"])

    def test_dobs_and_note_are_both_kept(self):
        rows, _fallback = profiles([hit(
            dobs=["1950"],
            profile_notes="Ada Quinn was born in 1952.\n\nLater text.",
        )])
        sources = [item["source"] for item in rows[0]["dob_candidates"]]
        self.assertEqual(sources, ["dobs", "profile_note"])
        self.assertEqual(rows[0]["dob_candidates"][1]["years"], [1952])
        self.assertEqual(rows[0]["dob_tier"], "tier1")

    def test_born_full_date_and_year(self):
        full = parse_note_dob("She was born on 17 July 1939 in the city.", "H-SYN0AA#profile_notes")
        self.assertEqual(full["candidates"][0]["precision"], "day")
        self.assertEqual(full["candidates"][0]["years"], [1939])
        self.assertEqual(full["candidates"][0]["month"], 7)
        self.assertEqual(full["candidates"][0]["day"], 17)
        year = parse_note_dob("born in 1952.", "H-SYN0AA#profile_notes")
        self.assertEqual(year["candidates"][0]["precision"], "year")
        self.assertEqual(year["candidates"][0]["years"], [1952])

    def test_age_shapes_compute_two_years(self):
        samples = {
            "Ada was aged 45 in March 2019 when sentenced.": [1973, 1974],
            "On June 2010 a 30-year-old Ada was named.": [1979, 1980],
            "She reached the age of 38 in November 2000.": [1961, 1962],
            "Ada was 37 years of age by November 1981.": [1943, 1944],
            "In March 1999, at which time she was 23.": [1975, 1976],
            "Age: 40\nas of May 15, 2010 the record was current.": [1969, 1970],
        }
        for text, years in samples.items():
            parsed = parse_note_dob(text, "H-SYN0AA#profile_notes")
            self.assertEqual(parsed["candidates"][0]["years"], years, text)
            self.assertEqual(parsed["candidates"][0]["precision"], "year")
            self.assertIsNone(parsed["candidates"][0]["month"])
            weak = parsed["candidates"][0]["rule_strength"] == "weak"
            self.assertEqual(parsed["candidates"][0]["may_solely_support_different_entity"], not weak)

    def test_later_paragraph_is_ignored(self):
        parsed = parse_note_dob("Nothing about a date here.\n\nShe was born in 1952.", "H-SYN0AA#profile_notes")
        self.assertEqual(parsed["candidates"], [])
        self.assertFalse(parsed["unresolved"])
        spaced = parse_note_dob("Nothing about a date here.\n \nShe was born in 1952.", "H-SYN0AA#profile_notes")
        self.assertEqual(spaced["candidates"], [])
        windows = parse_note_dob("Nothing about a date here.\r\n\r\nShe was born in 1952.", "H-SYN0AA#profile_notes")
        self.assertEqual(windows["candidates"], [])

    def test_birth_cues_are_case_insensitive_and_block_when_unparsed(self):
        born = parse_note_dob("Born on 12 March 1970 in the city.", "H-SYN0AA#profile_notes")
        self.assertEqual(born["candidates"][0]["years"], [1970])
        self.assertEqual(born["candidates"][0]["precision"], "day")
        self.assertEqual(born["candidates"][0]["day"], 12)
        city = parse_note_dob("She was born in Paris in 1970.", "H-SYN0AA#profile_notes")
        self.assertEqual(city["candidates"][0]["years"], [1970])
        self.assertEqual(city["candidates"][0]["precision"], "year")
        ordinal = parse_note_dob("born on 5th March 1970.", "H-SYN0AA#profile_notes")
        self.assertEqual((ordinal["candidates"][0]["day"], ordinal["candidates"][0]["month"]), (5, 3))
        ambiguous = parse_note_dob("Date of birth: 12/03/1970.", "H-SYN0AA#profile_notes")
        self.assertTrue(ambiguous["unresolved"])
        self.assertEqual(ambiguous["candidates"], [])
        clear = parse_note_dob("Date of birth: 15/03/1970.", "H-SYN0AA#profile_notes")
        self.assertEqual(clear["candidates"][0]["years"], [1970])
        self.assertEqual(clear["candidates"][0]["day"], 15)
        rows, _fallback = profiles([hit(profile_notes="Place of birth: Madrid, and nothing more.")], [
            {"result_id": "SR-000040", "query": "ada quinn", "snippet": "Ada Quinn is a politically exposed person aged 40 in 2010 in Ireland.", "title": "", "source": "web"},
        ])
        self.assertIn("NOTE_DOB_UNRESOLVED", rows[0]["flags"])
        self.assertFalse(rows[0]["search_results"]["consulted"])
        self.assertEqual(rows[0]["dob_candidates"], [])

    def test_relative_ages_are_skipped_and_weak_patterns_are_tagged(self):
        kept = parse_note_dob("His son, 12, lives abroad. Ada was aged 45 in March 2019.", "H-1")
        self.assertEqual(kept["candidates"][0]["years"], [1973, 1974])
        self.assertEqual(kept["candidates"][0]["rule_strength"], "strong")
        wife = parse_note_dob("His wife was 40 in March 2010.", "H-1")
        self.assertEqual(wife["candidates"], [])
        self.assertFalse(wife["unresolved"])
        weak = parse_note_dob("In March 1999, at which time she was 23.", "H-1")
        self.assertEqual(weak["candidates"][0]["years"], [1975, 1976])
        self.assertEqual(weak["candidates"][0]["rule_strength"], "weak")
        self.assertFalse(weak["candidates"][0]["may_solely_support_different_entity"])

    def test_loose_dobs_forms_and_unparsed_blocks_search(self):
        from stage2.build import parse_hit_dob
        self.assertEqual(parse_hit_dob("c. 1970")[0]["years"], [1970])
        self.assertEqual(parse_hit_dob("Mar 1970")[0]["precision"], "month")
        self.assertEqual(parse_hit_dob("12 Mar 1970")[0]["day"], 12)
        self.assertEqual(parse_hit_dob("1970-1972")[0]["years"], [1970, 1971, 1972])
        self.assertEqual(parse_hit_dob("1970-00-00")[0]["precision"], "year")
        rows, _fallback = profiles([hit(dobs=["not-a-date"])], [
            {"result_id": "SR-000041", "query": "ada quinn", "snippet": "Ada Quinn is a politically exposed person aged 40 in 2010 in Ireland.", "title": "", "source": "web"},
        ])
        self.assertIn("DOBS_UNPARSED", rows[0]["flags"])
        self.assertFalse(rows[0]["search_results"]["consulted"])
        self.assertEqual(rows[0]["dob_candidates"], [])

    def test_two_ages_or_two_dates_are_unresolved(self):
        two_ages = parse_note_dob("aged 30 in March 1990 and aged 40 in June 2000.", "H-1")
        self.assertTrue(two_ages["unresolved"])
        self.assertEqual(two_ages["candidates"], [])
        two_dates = parse_note_dob("She was aged 30 in March 1990 after a hearing in June 1991.", "H-1")
        self.assertTrue(two_dates["unresolved"])

    def test_counts_and_money_are_not_ages(self):
        parsed = parse_note_dob("The group of 12 companies paid 5000 in 2019.", "H-1")
        self.assertEqual(parsed["candidates"], [])
        self.assertFalse(parsed["unresolved"])
        reached = parse_note_dob("He reached the summit in June 2019.", "H-1")
        self.assertEqual(reached["candidates"], [])
        self.assertFalse(reached["unresolved"])

    def test_prison_record_keeps_the_as_of_date(self):
        parsed = parse_note_dob(
            "Age: 55 as of December 13, 2017. The earlier hearing was June 23, 2017.",
            "H-1",
        )
        self.assertEqual(parsed["candidates"][0]["rule"], "record_as_of")
        self.assertEqual(parsed["candidates"][0]["years"], [1961, 1962])


class SearchTests(unittest.TestCase):
    def test_phrase_and_country_and_name_word_guard(self):
        spain = "Ada Quinn is a politically exposed person aged 40 in 2010 in Spain."
        jordan = "Jordan Quinn, a politically exposed person, aged 40 in 2010 in Jordan."
        wrong = "Ada Quinn is a politician aged 40 in 2010 in Spain."
        results = [
            {"result_id": "SR-000002", "query": "ada quinn", "snippet": wrong, "title": "", "source": "web"},
            {"result_id": "SR-000001", "query": "ada quinn", "snippet": spain, "title": "", "source": "web"},
        ]
        outcome = evaluate_search("Quinn, Ada", PHRASE, ["Spain"], results)
        self.assertEqual([item["result_id"] for item in outcome["accepted"]], ["SR-000001"])
        self.assertEqual(outcome["accepted"][0]["years"], [1969, 1970])
        self.assertEqual(outcome["rejected"]["phrase"], 1)
        guarded = evaluate_search("Jordan Quinn", PHRASE, ["Jordan"], [
            {"result_id": "SR-000003", "query": search_key("Jordan Quinn"), "snippet": jordan, "title": "", "source": "web"},
        ])
        self.assertEqual(guarded["accepted"], [])
        self.assertEqual(guarded["rejected"]["country"], 1)

    def test_company_dobs_are_incorporation_dates_only(self):
        rows, _fallback = profiles([hit(
            entity_type="Company",
            name="Northwind Trading Ltd",
            dobs=["2010-05-01"],
            profile_notes="The firm was born in 1999.\n\nAccording to Desk; May 2, 2014: a filing.",
        )])
        self.assertEqual(rows[0]["dob_candidates"], [])
        self.assertEqual(rows[0]["incorporation_dates"][0]["years"], [2010])
        self.assertEqual(rows[0]["incorporation_dates"][0]["precision"], "day")
        self.assertEqual(rows[0]["incorporation_dates"][0]["source"], "dobs")
        self.assertEqual(rows[0]["earliest_dated_report"]["date"], "2014-05-02")
        self.assertFalse(rows[0]["search_results"]["consulted"])

    def test_tier1_skips_search_and_company_skips_search(self):
        snippet = "Ada Quinn is a politically exposed person aged 40 in 2010 in Ireland."
        results = [{"result_id": "SR-000010", "query": "ada quinn", "snippet": snippet, "title": "", "source": "web"}]
        rows, _fallback = profiles([hit(dobs=["1980-01-02"])], results)
        self.assertFalse(rows[0]["search_results"]["consulted"])
        self.assertEqual(rows[0]["dob_candidates"][0]["source"], "dobs")
        company, _fallback = profiles([
            hit(hit_id="H-SYN0BB", entity_type="Company", name="Northwind Trading Ltd", dobs=[], countries=["Spain"]),
        ], [{
            "result_id": "SR-000011",
            "query": search_key("Northwind Trading Ltd"),
            "snippet": "Northwind Trading Ltd is named on a watchlist in Spain aged 10 in 2010.",
            "title": "",
            "source": "web",
        }])
        self.assertFalse(company[0]["search_results"]["consulted"])
        self.assertEqual(company[0]["dob_candidates"], [])
        self.assertEqual(company[0]["incorporation_dates"], [])
        self.assertIn("NO_DOB", company[0]["flags"])

    def test_several_results_are_kept_and_conflict_flagged(self):
        def snippet(country, year, age):
            return f"Ada Quinn is a politically exposed person aged {age} in {year} in {country}."
        results = [
            {"result_id": "SR-0000B2", "query": "ada quinn", "snippet": snippet("Ireland", 2010, 40), "title": "", "source": "web"},
            {"result_id": "SR-0000B1", "query": "ada quinn", "snippet": snippet("Ireland", 2000, 40), "title": "", "source": "web"},
        ]
        rows, _fallback = profiles([hit()], results)
        self.assertEqual(rows[0]["dob_tier"], "tier2")
        self.assertEqual([item["source_id"] for item in rows[0]["dob_candidates"]], ["SR-0000B1", "SR-0000B2"])
        self.assertIn("MULTI_SR_CONFLICT", rows[0]["flags"])

    def test_unresolved_note_does_not_consult_search(self):
        snippet = "Ada Quinn is a politically exposed person aged 40 in 2010 in Ireland."
        rows, fallback = profiles([hit(profile_notes="aged 30 in March 1990 and aged 40 in June 2000.")], [
            {"result_id": "SR-000020", "query": "ada quinn", "snippet": snippet, "title": "", "source": "web"},
        ], enabled=False)
        self.assertIn("NOTE_DOB_UNRESOLVED", rows[0]["flags"])
        self.assertFalse(rows[0]["search_results"]["consulted"])
        self.assertEqual(rows[0]["dob_candidates"], [])
        self.assertEqual(fallback.calls, 0)
        self.assertIn("NO_DOB", rows[0]["flags"])


class ReportAndCountryTests(unittest.TestCase):
    def test_dated_reports_and_near_misses(self):
        notes = "\n".join([
            "According to Example News; April 19, 2019: a hearing.",
            "According to Example News;  April 19, 2018: two spaces.",
            "According to Example News: April 19, 2017: colon.",
            "According to Example News; April 2016: month and year.",
            "According to Example News; 2015: year only.",
            "According to Example News; April 19, 2014; trailing semicolon",
            "Según el informe; April 19, 2013: not English.",
            "According to Example News; as of April 19, 2012: as of.",
        ])
        reports, earliest = parse_dated_reports(notes, "H-SYN0AA")
        self.assertEqual([item["date"] for item in reports], ["2019-04-19", "2018-04-19"])
        self.assertEqual(earliest["date"], "2018-04-19")
        self.assertEqual(earliest["line_index"], 1)
        self.assertEqual(earliest["source_id"], "H-SYN0AA#profile_notes")
        self.assertEqual(earliest["precision"], "day")

    def test_earliest_of_several(self):
        notes = "According to A; November 2, 2020: later.\nAccording to B; January 8, 2015: earlier."
        _reports, earliest = parse_dated_reports(notes, "H-SYN0AA")
        self.assertEqual(earliest["date"], "2015-01-08")

    def test_death_fields_only(self):
        dated, _fallback = profiles([hit(life_status="Deceased", deceased_date="2021-08-02", profile_notes="He died in 1999.")])
        self.assertEqual(dated[0]["deceased"]["date"], "2021-08-02")
        self.assertEqual(dated[0]["deceased"]["precision"], "day")
        self.assertNotIn("DECEASED_NO_DATE", dated[0]["flags"])
        undated, _fallback = profiles([hit(hit_id="H-SYN0CC", life_status="Deceased", deceased_date=None)])
        self.assertIsNone(undated[0]["deceased"]["date"])
        self.assertIn("DECEASED_NO_DATE", undated[0]["flags"])
        self.assertEqual(undated[0]["dob_candidates"], [])

    def test_countries_tags_regions_and_shared_table(self):
        self.assertEqual(norm_country("Macao SAR")[0], "Macao")
        rows, _fallback = profiles([hit(
            nationality=["Sassari, Sassari, Italy"],
            addresses=["1 Example Street, Dublin, Ireland [Business]", "Europe"],
            countries=["International", "Northern Mariana Islands"],
            place_of_birth="Somewhere, Atlantis",
            citizenship=["Macao SAR"],
        )])
        values = [(entry["field"], entry["value"]) for entry in rows[0]["countries"]]
        self.assertEqual(values, [
            ("countries", "Northern Mariana Islands"),
            ("nationality", "Italy"),
            ("citizenship", "Macao"),
            ("addresses", "Ireland"),
            ("place_of_birth", "Atlantis"),
        ])
        self.assertIn("UNMAPPED_COUNTRY", rows[0]["flags"])
        self.assertTrue(rows[0]["countries"][-1]["unmapped"])
        self.assertNotIn("NO_COUNTRY", rows[0]["flags"])
        empty, _fallback = profiles([hit(hit_id="H-SYN0DD", countries=[], nationality=[], citizenship=[])])
        self.assertIn("NO_COUNTRY", empty[0]["flags"])


class LlmTests(unittest.TestCase):
    def test_quote_reparse_and_disagreement_and_off_switch(self):
        paragraph = "She was born in 1970. Later she was aged 30 in March 2019."
        missing = candidate_from_model(paragraph, {
            "statement": "born",
            "born_date": "1970",
            "age": None,
            "reference_date": None,
            "quote": "born in 1800",
        }, "H-SYN0AA#profile_notes")
        self.assertIsNone(missing)
        derived = candidate_from_model(paragraph, {
            "statement": "age_at_date",
            "born_date": None,
            "age": 30,
            "reference_date": "March 2019",
            "quote": "aged 30 in March 2019",
        }, "H-SYN0AA#profile_notes")
        self.assertEqual(derived["years"], [1988, 1989])
        self.assertEqual(derived["method"], "llm")
        self.assertFalse(derived["may_solely_support_different_entity"])

        state = {"n": 0}

        def disagree(_paragraph):
            state["n"] += 1
            if state["n"] == 1:
                return {
                    "statement": "born", "born_date": "1970", "age": None,
                    "reference_date": None, "quote": "born in 1970",
                }
            return {
                "statement": "age_at_date", "born_date": None, "age": 30,
                "reference_date": "March 2019", "quote": "aged 30 in March 2019",
            }

        with tempfile.TemporaryDirectory() as cache:
            rows, fallback = profiles(
                [hit(profile_notes="She was born in 1970 and also born in 1971. Later she was aged 30 in March 2019.")],
                enabled=True,
                transport=disagree,
                cache_dir=cache,
            )
        self.assertIn("LLM_UNKNOWN", rows[0]["flags"])
        self.assertEqual(rows[0]["dob_candidates"], [])
        self.assertGreaterEqual(fallback.calls, 2)
        previous = os.environ.get("USE_LLM_HITS")
        forced = os.environ.get("SANCTIONS_LLM")
        try:
            os.environ["USE_LLM_HITS"] = "1"
            os.environ["SANCTIONS_LLM"] = "0"
            self.assertFalse(llm_enabled())
            os.environ["SANCTIONS_LLM"] = "1"
            self.assertTrue(llm_enabled())
        finally:
            if previous is None:
                os.environ.pop("USE_LLM_HITS", None)
            else:
                os.environ["USE_LLM_HITS"] = previous
            if forced is None:
                os.environ.pop("SANCTIONS_LLM", None)
            else:
                os.environ["SANCTIONS_LLM"] = forced

    def test_llm_success_uses_code_for_years_and_skips_search(self):
        def transport(_paragraph):
            return {
                "statement": "age_at_date",
                "born_date": None,
                "age": 45,
                "reference_date": "March 2019",
                "quote": "aged 45 in March 2019",
            }

        notes = "She was aged 45 in March 2019 and also aged 40 in June 2010."
        snippet = "Ada Quinn is a politically exposed person aged 40 in 2010 in Ireland."
        rows, _fallback = profiles(
            [hit(profile_notes=notes)],
            [{"result_id": "SR-000030", "query": "ada quinn", "snippet": snippet, "title": "", "source": "web"}],
            enabled=True,
            transport=transport,
        )
        candidate = rows[0]["dob_candidates"][0]
        self.assertEqual(candidate["years"], [1973, 1974])
        self.assertEqual(candidate["method"], "llm")
        self.assertFalse(candidate["may_solely_support_different_entity"])
        self.assertEqual(rows[0]["dob_tier"], "tier1")
        self.assertFalse(rows[0]["search_results"]["consulted"])
        self.assertNotIn("LLM_UNKNOWN", rows[0]["flags"])

    def test_cache_skips_the_second_call_and_paid_model_does_not_call_out(self):
        calls = {"n": 0}

        def transport(_paragraph):
            calls["n"] += 1
            return {"statement": "none", "born_date": None, "age": None, "reference_date": None, "quote": "no birth"}

        paragraph = "A note with no birth fact and the words no birth."
        with tempfile.TemporaryDirectory() as cache:
            fallback = NoteFallback(cache, True, transport=transport)
            first = fallback.resolve("H-SYN0AA", "Ada Quinn", paragraph)
            fallback.save()
            second = NoteFallback(cache, True, transport=transport)
            again = second.resolve("H-SYN0AA", "Ada Quinn", paragraph)
        self.assertEqual(calls["n"], 3)
        self.assertIsNone(first["candidate"])
        self.assertIn("NOTE_DOB_UNRESOLVED", first["flags"])
        self.assertFalse(again["called"])
        self.assertIn("NOTE_DOB_UNRESOLVED", again["flags"])

        def empty_quote(_paragraph):
            return {"statement": "none", "born_date": None, "age": None, "reference_date": None, "quote": ""}

        with tempfile.TemporaryDirectory() as cache:
            blank = NoteFallback(cache, True, transport=empty_quote)
            refused = blank.resolve("H-SYN0AA", "Ada Quinn", "A paragraph with a birth cue and no date.")
        self.assertIsNone(refused["candidate"])
        self.assertIn("NOTE_DOB_UNRESOLVED", refused["flags"])

        def explode(_request, timeout=0):
            raise AssertionError("paid model must not call the network")

        client = OpenRouterClient(model="openai/gpt-4o", api_key="not-used", urlopen=explode)
        with tempfile.TemporaryDirectory() as cache:
            paid = NoteFallback(cache, True, client=client)
            result = paid.resolve("H-SYN0AA", "Ada Quinn", "aged 30 in March 1990 and aged 40 in June 2000.")
        self.assertIn("LLM_UNKNOWN", result["flags"])
        self.assertEqual(client.calls, 0)

    def test_profiles_are_byte_identical(self):
        rows = [
            hit(hit_id="H-SYN0BB", name="Zed Example"),
            hit(profile_notes="born on 2 May 1980.\n\nAccording to Desk; May 2, 2020: report."),
        ]
        first, _fallback = profiles(rows)
        second, _fallback = profiles(list(reversed(rows)))
        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=False),
            json.dumps(second, sort_keys=True, ensure_ascii=False),
        )
        self.assertEqual([row["hit_id"] for row in first], ["H-SYN0AA", "H-SYN0BB"])


if __name__ == "__main__":
    unittest.main()
