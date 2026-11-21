"""Profile-note birth sentences and dated reports.

Birth text is read from the first paragraph only. An age at a date becomes two
candidate years, computed here. Dated reports keep the strict SOP line and
allow extra whitespace after the semicolon.
"""

from __future__ import annotations

import re
from datetime import date

from stage1.normalise import parse_date

_MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)
_FULL = rf"(?:\d{{1,2}} (?:{_MONTHS}) \d{{4}}|(?:{_MONTHS}) \d{{1,2}}, \d{{4}}|\d{{4}}-\d\d-\d\d)"
_MONTH_YEAR = rf"(?:{_MONTHS}) \d{{4}}"
_BORN = re.compile(rf"\bborn (?:on |in )?({_FULL}|{_MONTH_YEAR}|\d{{4}})\b")
_REF = re.compile(rf"({_FULL}|{_MONTH_YEAR})")
_AGE_AS_OF = re.compile(rf"\bAge: (\d{{1,3}})\b")
_AS_OF = re.compile(rf"\bas of ({_FULL})")
# "reached" alone is not a cue. Two dev paragraphs use it for something other than age.
_CUE = re.compile(r"\b(aged?|years? old|year-old|age of|at age)\b", re.IGNORECASE)
_AGE_PATTERNS = (
    re.compile(r"\baged? (\d{1,3})\b"),
    re.compile(r"\b(\d{1,3})[- ]years?[- ]old\b"),
    re.compile(r"\bage of (\d{1,3})\b"),
    re.compile(r"\bat age (\d{1,3})\b"),
    re.compile(r"\bwas (\d{1,3})\b(?!,? \d{4})"),
    re.compile(r"\breached (?:the age of )?(\d{1,3})\b"),
    re.compile(r"\bturned (\d{1,3})\b"),
    re.compile(r"\bAge: (\d{1,3})\b"),
    re.compile(r", (\d{1,3}),"),
    re.compile(r"\b(\d{1,3}) years of age\b"),
)
# Whitespace after ";" is tolerated. One dev line has two spaces there.
_REPORT = re.compile(rf"^According to [^;\n]+;\s+({_MONTHS}) (\d{{1,2}}), (\d{{4}}):")
_MONTH_INDEX = {name: index for index, name in enumerate(_MONTHS.split("|"), start=1)}


def first_paragraph(text: object) -> str:
    return ("" if text is None else str(text)).strip().split("\n\n", 1)[0]


def _span(text: str, start: int, end: int) -> str:
    return text[start:end]


def _candidate(
    *,
    years: list[int],
    month: int | None,
    day: int | None,
    precision: str,
    source_id: str,
    rule: str,
    quote: str,
    method: str = "regex",
) -> dict:
    return {
        "years": list(years),
        "month": month,
        "day": day,
        "precision": precision,
        "source": "profile_note",
        "source_id": source_id,
        "method": method,
        "rule": rule,
        "quote": quote,
        "may_solely_support_different_entity": method != "llm",
    }


def _from_parsed(parsed: dict, source_id: str, rule: str, quote: str) -> dict:
    return _candidate(
        years=[parsed["y"]],
        month=parsed["m"],
        day=parsed["d"],
        precision=parsed["precision"],
        source_id=source_id,
        rule=rule,
        quote=quote,
    )


def _age_years(year: int, age: int) -> list[int]:
    return sorted({year - age - 1, year - age})


def _ages(text: str) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    for pattern in _AGE_PATTERNS:
        for match in pattern.finditer(text):
            age = int(match.group(1))
            if 1 <= age <= 120:
                found.append((age, match.start(), match.end()))
    return found


def parse_note_dob(text: object, source_id: str) -> dict:
    """Birth candidates from the first paragraph.

    ``unresolved`` is true when a birth cue is present and the rules cannot
    settle on one statement. Search results must not fill that gap.
    """
    paragraph = first_paragraph(text)
    empty = {"candidates": [], "unresolved": False, "statements": 0}
    if not paragraph:
        return empty
    born = list(_BORN.finditer(paragraph))
    if born:
        values = {match.group(1) for match in born}
        if len(values) == 1:
            raw = born[0].group(1)
            parsed, flags = parse_date(raw, mode="hit")
            if parsed and not flags:
                quote = _span(paragraph, born[0].start(), born[0].end())
                candidate = _from_parsed(parsed, source_id, "born", quote)
                return {"candidates": [candidate], "unresolved": False, "statements": 1}
        return {"candidates": [], "unresolved": True, "statements": 0}
    age_header = _AGE_AS_OF.search(paragraph)
    as_of = _AS_OF.search(paragraph)
    if age_header and as_of:
        age = int(age_header.group(1))
        parsed, flags = parse_date(as_of.group(1), mode="hit")
        if parsed and not flags and 1 <= age <= 120:
            start = min(age_header.start(), as_of.start())
            end = max(age_header.end(), as_of.end())
            candidate = _candidate(
                years=_age_years(parsed["y"], age),
                month=None,
                day=None,
                precision="year",
                source_id=source_id,
                rule="record_as_of",
                quote=_span(paragraph, start, end),
            )
            return {"candidates": [candidate], "unresolved": False, "statements": 1}
        return {"candidates": [], "unresolved": True, "statements": 0}
    ages = _ages(paragraph)
    refs = list(_REF.finditer(paragraph))
    distinct_ages = sorted({age for age, _start, _end in ages})
    distinct_refs = sorted({match.group(1) for match in refs})
    if distinct_ages or _CUE.search(paragraph):
        if len(distinct_ages) == 1 and len(distinct_refs) == 1:
            parsed, flags = parse_date(distinct_refs[0], mode="hit")
            if parsed and not flags:
                age = distinct_ages[0]
                age_span = next(item for item in ages if item[0] == age)
                start = min(age_span[1], refs[0].start())
                end = max(age_span[2], refs[0].end())
                candidate = _candidate(
                    years=_age_years(parsed["y"], age),
                    month=None,
                    day=None,
                    precision="year",
                    source_id=source_id,
                    rule="age_at_date",
                    quote=_span(paragraph, start, end),
                )
                return {"candidates": [candidate], "unresolved": False, "statements": 1}
        return {"candidates": [], "unresolved": True, "statements": 0}
    return empty


def parse_dated_reports(text: object, hit_id: str) -> tuple[list[dict], dict | None]:
    """SOP lines ``According to …; Month DD, YYYY:``. Earliest date, then earliest line."""
    source_id = f"{hit_id}#profile_notes"
    reports: list[dict] = []
    for index, line in enumerate(("" if text is None else str(text)).splitlines()):
        match = _REPORT.match(line)
        if not match:
            continue
        month = _MONTH_INDEX[match.group(1)]
        day = int(match.group(2))
        year = int(match.group(3))
        try:
            date(year, month, day)
        except ValueError:
            continue
        reports.append({
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "precision": "day",
            "line_index": index,
            "source_id": source_id,
            "source_text_prefix": match.group(0),
            "method": "regex",
        })
    reports.sort(key=lambda row: (row["line_index"], row["date"]))
    earliest = min(reports, key=lambda row: (row["date"], row["line_index"])) if reports else None
    return reports, earliest
