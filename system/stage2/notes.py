"""Profile-note birth sentences and dated reports.

Birth text is read from the first paragraph only. An age at a date becomes two
candidate years, computed here. Dated reports keep the strict SOP line and
allow extra whitespace after the semicolon.

``rule_strength`` is ``strong`` or ``weak``. Weak patterns are ``was N``,
``, N,``, and ``reached``. Stage 4 must not clear a hit on a weak candidate
alone: it can support a strong fact, and it must not be the only ground for
``DIFFERENT_ENTITY``. Strong candidates may.
"""

from __future__ import annotations

import re
from datetime import date

from stage1.normalise import parse_date

_MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)
_ABBR = (
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_MON = rf"(?:{_MONTHS}|{_ABBR})"
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_DATE = (
    rf"(?:{_DAY}\s+(?:of\s+)?{_MON}\s+\d{{4}}"
    rf"|{_MON}\s+{_DAY},?\s+\d{{4}}"
    rf"|{_MON}\s+\d{{4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|\d{{1,2}}/\d{{1,2}}/\d{{4}}"
    rf"|\d{{4}})"
)
_FULL = rf"(?:\d{{1,2}} (?:{_MONTHS}) \d{{4}}|(?:{_MONTHS}) \d{{1,2}}, \d{{4}}|\d{{4}}-\d\d-\d\d)"
_MONTH_YEAR = rf"(?:{_MONTHS}) \d{{4}}"
_REF = re.compile(rf"({_FULL}|{_MONTH_YEAR}|{_DAY}\s+(?:of\s+)?{_MON}\s+\d{{4}}|{_MON}\s+\d{{4}})", re.IGNORECASE)
_AGE_AS_OF = re.compile(r"\bAge:\s*(\d{1,3})\b", re.IGNORECASE)
_AS_OF = re.compile(rf"\bas of ({_FULL}|{_DAY}\s+{_MON}\s+\d{{4}})", re.IGNORECASE)
# Birth words are cues even when no age number is present. Case is ignored.
_CUE = re.compile(
    r"\b(?:aged?|years?[ -]old|year-old|age of|at age|born|birth|dob)\b|\bb\.",
    re.IGNORECASE,
)
_BIRTH_WORD = re.compile(r"\b(?:born|birth|dob)\b|\bb\.", re.IGNORECASE)
_INTRO = re.compile(
    rf"\bborn\s+in\s+(?:(?!(?:{_DATE})\b)[A-Za-z][\w'.-]*)(?:\s+[A-Za-z][\w'.-]*){{0,4}}\s+in\s+(\d{{4}})\b"
    rf"|\bborn\s+on\s+({_DATE})\b"
    rf"|\bborn\s+in\s+({_DATE})\b"
    rf"|\b(?:date\s+of\s+birth|birth\s+date|dob)\s*[:\-]?\s*({_DATE})\b"
    rf"|\bb\.\s*({_DATE})\b",
    re.IGNORECASE,
)
# 'was N', ', N,', and 'reached' are weak: they often describe someone else or a non-age.
_AGE_PATTERNS = (
    (re.compile(r"\baged?\s+(\d{1,3})\b", re.IGNORECASE), "strong"),
    (re.compile(r"\b(\d{1,3})[- ]years?[- ]old\b", re.IGNORECASE), "strong"),
    (re.compile(r"\bage of\s+(\d{1,3})\b", re.IGNORECASE), "strong"),
    (re.compile(r"\bat age\s+(\d{1,3})\b", re.IGNORECASE), "strong"),
    (re.compile(r"\bturned\s+(\d{1,3})\b", re.IGNORECASE), "strong"),
    (re.compile(r"\bAge:\s*(\d{1,3})\b", re.IGNORECASE), "strong"),
    (re.compile(r"\b(\d{1,3})\s+years of age\b", re.IGNORECASE), "strong"),
    (re.compile(r"\bwas\s+(\d{1,3})\b(?!,?\s*\d{4})", re.IGNORECASE), "weak"),
    (re.compile(r"\breached\s+(?:the age of\s+)?(\d{1,3})\b", re.IGNORECASE), "weak"),
    (re.compile(r", (\d{1,3}),"), "weak"),
)
_RELATIVE_BEFORE = re.compile(
    r"\b(?:son|sons|daughter|daughters|wife|wives|husband|husbands|child|children|"
    r"brother|brothers|sister|sisters|father|mother|nephew|niece|"
    r"grandson|grandsons|granddaughter|granddaughters|"
    r"spouse|partner|uncle|aunt|grandfather|grandmother|"
    r"sibling|siblings|parent|parents|"
    r"stepson|stepdaughter|stepfather|stepmother|"
    r"grandchild|grandchildren|widow|widower|cousin|cousins)\b[\s,:'\-]*$",
    re.IGNORECASE,
)
_ABBR_TO_FULL = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "sept": "September", "oct": "October",
    "nov": "November", "dec": "December",
}
_PARA_BREAK = re.compile(r"(?:\r?\n[ \t]*){2,}")
# Whitespace after ";" is tolerated. One dev line has two spaces there.
_REPORT = re.compile(rf"^According to [^;\n]+;\s+({_MONTHS}) (\d{{1,2}}), (\d{{4}}):")
_MONTH_INDEX = {name: index for index, name in enumerate(_MONTHS.split("|"), start=1)}


def first_paragraph(text: object) -> str:
    """Text up to the first blank line. A blank line may hold spaces or ``\\r``."""
    raw = "" if text is None else str(text).strip()
    if not raw:
        return ""
    return _PARA_BREAK.split(raw, maxsplit=1)[0]


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
    rule_strength: str = "strong",
) -> dict:
    weak = rule_strength == "weak"
    return {
        "years": list(years),
        "month": month,
        "day": day,
        "precision": precision,
        "source": "profile_note",
        "source_id": source_id,
        "method": method,
        "rule": rule,
        "rule_strength": rule_strength,
        "quote": quote,
        "may_solely_support_different_entity": method != "llm" and not weak,
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


def _relative_before(text: str, start: int) -> bool:
    window = text[max(0, start - 48):start]
    return _RELATIVE_BEFORE.search(window) is not None


def _parse_surface_date(raw: str):
    """Parse one date fragment from a note. Hit slash dates stay ambiguous."""
    text = raw.strip().rstrip(".,;")
    text = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\bof\b", " ", text, flags=re.IGNORECASE)

    def _month(match: re.Match) -> str:
        return _ABBR_TO_FULL.get(match.group(0).lower(), match.group(0))

    text = re.sub(rf"\b(?:{_ABBR})\b", _month, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash:
        first, second, year = (int(slash.group(1)), int(slash.group(2)), slash.group(3))
        text = f"{first:02d}/{second:02d}/{year}"
    return parse_date(text, mode="hit")


def _ages(text: str) -> list[tuple[int, int, int, str]]:
    found: list[tuple[int, int, int, str]] = []
    for pattern, strength in _AGE_PATTERNS:
        for match in pattern.finditer(text):
            if _relative_before(text, match.start()):
                continue
            age = int(match.group(1))
            if 1 <= age <= 120:
                found.append((age, match.start(), match.end(), strength))
    return found


def _strength(ages: list[tuple[int, int, int, str]], age: int) -> str:
    if any(item[0] == age and item[3] == "strong" for item in ages):
        return "strong"
    return "weak"


def parse_note_dob(text: object, source_id: str) -> dict:
    """Birth candidates from the first paragraph.

    ``unresolved`` is true when a birth cue is present and the rules cannot
    settle on one statement. Search results must not fill that gap.
    """
    paragraph = first_paragraph(text)
    empty = {"candidates": [], "unresolved": False, "statements": 0}
    if not paragraph:
        return empty
    unresolved = {"candidates": [], "unresolved": True, "statements": 0}
    intros = list(_INTRO.finditer(paragraph))
    if intros:
        parsed_ok = []
        for match in intros:
            raw = next(group for group in match.groups() if group)
            parsed, flags = _parse_surface_date(raw)
            if not parsed or flags:
                return unresolved
            parsed_ok.append((parsed, match))
        values = {item[0]["value"] for item in parsed_ok}
        if len(values) == 1:
            parsed, match = parsed_ok[0]
            quote = _span(paragraph, match.start(), match.end())
            candidate = _from_parsed(parsed, source_id, "born", quote)
            return {"candidates": [candidate], "unresolved": False, "statements": 1}
        return unresolved
    age_header = _AGE_AS_OF.search(paragraph)
    as_of = _AS_OF.search(paragraph)
    if age_header and as_of and not _relative_before(paragraph, age_header.start()):
        age = int(age_header.group(1))
        parsed, flags = _parse_surface_date(as_of.group(1))
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
                rule_strength="strong",
            )
            return {"candidates": [candidate], "unresolved": False, "statements": 1}
        return unresolved
    ages = _ages(paragraph)
    refs = list(_REF.finditer(paragraph))
    distinct_ages = sorted({age for age, _start, _end, _strength in ages})
    distinct_refs = []
    for match in refs:
        token = match.group(1)
        parsed, flags = _parse_surface_date(token)
        if parsed and not flags:
            distinct_refs.append((token, parsed, match.start(), match.end()))
    unique_refs = sorted({item[0] for item in distinct_refs})
    subject_cue = bool(ages) or _BIRTH_WORD.search(paragraph) or (
        _CUE.search(paragraph) and not _only_relative_cue(paragraph)
    )
    if distinct_ages or subject_cue:
        if len(distinct_ages) == 1 and len(unique_refs) == 1:
            _token, parsed, ref_start, ref_end = distinct_refs[0]
            age = distinct_ages[0]
            age_span = next(item for item in ages if item[0] == age)
            start = min(age_span[1], ref_start)
            end = max(age_span[2], ref_end)
            candidate = _candidate(
                years=_age_years(parsed["y"], age),
                month=None,
                day=None,
                precision="year",
                source_id=source_id,
                rule="age_at_date",
                quote=_span(paragraph, start, end),
                rule_strength=_strength(ages, age),
            )
            return {"candidates": [candidate], "unresolved": False, "statements": 1}
        if subject_cue or distinct_ages:
            return unresolved
    return empty


def _only_relative_cue(paragraph: str) -> bool:
    """True when every age phrase sits after a relative word and no birth word remains."""
    if _BIRTH_WORD.search(paragraph):
        return False
    for pattern, _strength in _AGE_PATTERNS:
        for match in pattern.finditer(paragraph):
            if not _relative_before(paragraph, match.start()):
                return False
    return True


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
