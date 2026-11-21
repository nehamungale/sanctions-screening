"""Tier-2 birth years from search results.

Used only for an individual with no tier-1 date. A result counts when the
snippet contains the listing phrase and, after the subject's own name words
are removed, a country tied to the hit.
"""

from __future__ import annotations

import re

from stage1.normalise_text import norm_text

_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_AGE = re.compile(r"(?<![\d,])\b(\d{1,3})\b")


def search_key(name: object) -> str:
    """Sorted name words: folded, dots and apostrophes removed, initials dropped."""
    text = norm_text(re.sub(r"\([^)]*\)", "", "" if name is None else str(name)))
    text = text.replace(".", "").replace("'", "")
    words = [word for word in re.findall(r"[a-z0-9]+", text) if len(word) > 1]
    return " ".join(sorted(words))


def _strip_name_words(snippet: str, name_words: set[str]) -> str:
    # Same join as the measurement script. Extra spaces do not affect a
    # single-word country, which is what the dev accepts rely on.
    return " ".join(piece for piece in re.split(r"(\W+)", snippet) if norm_text(piece) not in name_words)


def _country_matches(stripped: str, country: str) -> bool:
    if re.search(rf"\b{re.escape(country)}\b", stripped):
        return True
    folded = norm_text(stripped)
    return re.search(rf"\b{re.escape(norm_text(country))}\b", folded) is not None


def evaluate_search(
    name: object,
    phrase: str,
    countries: list[str],
    results: list[dict],
) -> dict:
    key = search_key(name)
    name_words = set(key.split())
    considered = sorted(result["result_id"] for result in results)
    accepted: list[dict] = []
    rejected = {"phrase": 0, "country": 0, "year_age": 0}
    ordered = sorted(results, key=lambda row: row["result_id"])
    country_order = sorted(set(countries), key=lambda value: (-len(value), value))
    for result in ordered:
        snippet = result.get("snippet") or ""
        if phrase not in snippet:
            rejected["phrase"] += 1
            continue
        stripped = _strip_name_words(snippet, name_words)
        matched = next((country for country in country_order if _country_matches(stripped, country)), None)
        if matched is None:
            rejected["country"] += 1
            continue
        years = _YEAR.findall(snippet)
        ages = [int(token) for token in _AGE.findall(snippet) if 1 <= int(token) <= 120]
        if len(years) != 1 or len(ages) != 1:
            rejected["year_age"] += 1
            continue
        year = int(years[0])
        age = ages[0]
        accepted.append({
            "result_id": result["result_id"],
            "source_id": result["result_id"],
            "years": sorted({year - age - 1, year - age}),
            "month": None,
            "day": None,
            "precision": "year",
            "country": matched,
            "phrase": phrase,
            "method": "regex",
            "may_solely_support_different_entity": True,
            "quote": snippet,
        })
    return {
        "key": key,
        "consulted": True,
        "considered": considered,
        "accepted": accepted,
        "rejected": rejected,
    }


def not_consulted(name: object) -> dict:
    return {
        "key": search_key(name),
        "consulted": False,
        "considered": [],
        "accepted": [],
        "rejected": {"phrase": 0, "country": 0, "year_age": 0},
    }
