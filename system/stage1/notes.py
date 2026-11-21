"""Deterministic KYC and residence note parser.

Port of the organiser prototype's ``extract_kyc_v2`` rules: uppercase-token
names (Unicode-aware), the date that is not ``created_at``, and one lexicon
country after ``(Note: ...)`` is removed. Six fixed noise sentences are ignored.
"""

from __future__ import annotations

import re

from stage1.countries import countries_in_note
from stage1.llm import fill_null_slots
from stage1.normalise import parse_date

MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)
FULL_DATE_RE = re.compile(
    rf"\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|\d{{2}}/\d{{2}}/\d{{4}}"
    rf"|\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}"
    rf"|(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}",
    re.IGNORECASE,
)
YEAR_DOB_RE = re.compile(
    r"(?:born(?:\s+in)?|DOB|date\s+of\s+birth(?:\s+of)?|birth\s+date(?:\s+of)?)"
    r"\D{0,20}?\b(\d{4})\b(?![-/\d])",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
NEGATION_RE = re.compile(r"\b(?:not|never|plan|visit)\b", re.IGNORECASE)
DOC_RE = re.compile(
    r"\b(registry extract|driving licen[cs]e|driver'?s licen[cs]e|"
    r"national ID|passport|identification document|ID card)\b",
    re.IGNORECASE,
)
PAREN_RE = re.compile(r"\([^)]*\)")

PROVIDERS = (
    "Companies registry lookup",
    "Sumsub",
    "Onfido",
    "Veriff",
    "Persona",
)
STOP_TOKENS = {"ID", "DOB", "KYC"}
NOISE = {
    "Customer asked about savings interest rates and was sent the current tariff.",
    "Customer called to ask how long an international transfer takes. Gave the usual timelines.",
    "Customer reported a lost card. Card frozen and a replacement ordered to the address on file.",
    "Customer updated their mobile number after changing provider. Verified through the app.",
    "Customer asked why a card payment was declined at a supermarket. Explained the daily limit and how to raise it.",
    "Customer requested a statement for a rental application. Sent the last three months.",
}
_KNOWN_CHANNELS = {"kyc", "phone", "email", "app"}


def parse_note(note: dict, use_llm: bool | None = None, transport=None) -> dict:
    """Turn one note into ``noise``, ``verification``, ``residence``, or ``ignored``."""
    text = note.get("text") or ""
    channel = (note.get("channel") or "").strip().lower()
    if channel == "kyc":
        parsed = extract_kyc(text, note.get("created_at"))
        parsed = fill_null_slots(text, parsed, transport=transport, enabled=use_llm)
        event = {
            "source_id": note.get("note_id"),
            "kind": "kyc_note",
            "date": _canonical_day(note.get("created_at")),
            "name": parsed.get("name"),
            "dob": parsed.get("dob"),
            "dob_precision": parsed.get("dob_precision"),
            "doc_country": parsed.get("doc_country"),
            "document_type": parsed.get("document_type"),
            "provider": parsed.get("provider"),
        }
        if parsed.get("llm_fields"):
            event["llm_fields"] = list(parsed["llm_fields"])
        return {"kind": "verification", "event": event, "flags": list(parsed.get("flags") or [])}
    if text in NOISE:
        return {"kind": "noise", "event": None, "flags": []}
    flags: list[str] = []
    if channel not in _KNOWN_CHANNELS:
        flags.append("unknown_channel")
    residence, residence_flags = extract_residence(text)
    flags.extend(residence_flags)
    if residence is None or flags:
        return {"kind": "ignored", "event": None, "flags": flags}
    residence["note_id"] = note.get("note_id")
    return {"kind": "residence", "event": residence, "flags": []}


def extract_kyc(text: str, created_at: object) -> dict:
    out: dict = {
        "provider": _provider(text),
        "document_type": _document_type(text),
        "check_date": None,
        "dob": None,
        "dob_precision": None,
        "name": None,
        "doc_country": None,
        "flags": [],
        "source_method": "regex",
    }
    created = _canonical_day(created_at)
    full_dates = []
    for match in FULL_DATE_RE.finditer(text or ""):
        parsed, _flags = parse_date(match.group(0))
        if parsed and parsed["precision"] == "day":
            full_dates.append(parsed["value"])
    if created and created in full_dates:
        out["check_date"] = created
    else:
        out["flags"].append("check_date_missing")
    others = sorted({value for value in full_dates if value != created})
    if len(others) == 1:
        out["dob"] = others[0]
        out["dob_precision"] = "day"
    elif not others:
        years = YEAR_DOB_RE.findall(text or "")
        unique_years = sorted(set(years))
        if len(unique_years) == 1:
            out["dob"] = unique_years[0]
            out["dob_precision"] = "year"
        elif created and full_dates.count(created) > 1:
            out["dob"] = created
            out["dob_precision"] = "day"
    if out["dob"] is None:
        out["flags"].append("dob_unresolved")
    name = _extract_name(text or "")
    if name is None:
        out["flags"].append("name_ambiguous")
    else:
        out["name"] = name
    countries = countries_in_note(text or "")
    if len(countries) == 1:
        out["doc_country"] = countries[0]
    else:
        out["flags"].append("country_ambiguous")
    if "(Note:" in (text or ""):
        out["flags"].append("note_annotation")
    return out


def extract_residence(text: str) -> tuple[dict | None, list[str]]:
    flags: list[str] = []
    if NEGATION_RE.search(text or ""):
        flags.append("negation")
    countries = countries_in_note(text or "")
    years = [int(year) for year in YEAR_RE.findall(text or "")]
    if len(countries) != 1:
        flags.append("country_count")
    if len(years) != 2:
        flags.append("year_count")
    if flags:
        return None, flags
    start, end = years[0], years[1]
    if start > end:
        start, end = end, start
    return {"country": countries[0], "year_from": start, "year_to": end}, []


def _provider(text: str) -> str | None:
    folded = text.lower()
    found = [provider for provider in PROVIDERS if provider.lower() in folded]
    if len(found) == 1:
        return found[0]
    return None


def _document_type(text: str) -> str | None:
    specific = []
    unknown = []
    for match in DOC_RE.finditer(text or ""):
        canon = _canon_doc(match.group(1))
        if canon == "unknown_id":
            unknown.append(canon)
        else:
            specific.append(canon)
    if specific:
        return specific[0]
    if unknown:
        return unknown[0]
    return None


def _canon_doc(surface: str) -> str:
    token = surface.lower()
    if "licen" in token:
        return "driving licence"
    if token == "national id":
        return "national ID"
    if token == "passport":
        return "passport"
    if token == "registry extract":
        return "registry extract"
    return "unknown_id"


def _extract_name(text: str) -> str | None:
    blanked = FULL_DATE_RE.sub(" ", text)
    blanked = PAREN_RE.sub(" ", blanked)
    runs: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if any(_is_upper_word(token) for token in current):
            runs.append(" ".join(current))
        current.clear()

    for raw in blanked.split():
        token = raw.strip(".,;:!?\"“”()[]{}")
        token = re.sub(r"['’]s$", "", token)
        if not token:
            continue
        if token.upper() in STOP_TOKENS:
            flush()
            continue
        if _is_name_token(token):
            current.append(token)
        else:
            flush()
    flush()
    # A sentence-initial "A" is uppercase but not a name. Keep a run only when it
    # contains at least two uppercase letters (PAWEŁ still qualifies; "A" does not).
    kept = [run for run in dict.fromkeys(runs) if _uppercase_letters(run) >= 2]
    if len(kept) == 1:
        return kept[0]
    return None


def _uppercase_letters(token: str) -> int:
    return sum(1 for ch in token if ch.isalpha() and ch == ch.upper())


def _is_upper_word(token: str) -> bool:
    if not any(ch.isalpha() for ch in token):
        return False
    return token == token.upper()


def _is_placeholder_token(token: str) -> bool:
    if token.upper() in {"N/A", "N.A.", "N.A", "NA"}:
        return True
    return token.isdigit()


def _is_name_token(token: str) -> bool:
    return _is_upper_word(token) or _is_placeholder_token(token)


def _canonical_day(value: object) -> str | None:
    parsed, _flags = parse_date(value)
    if parsed and parsed["precision"] == "day":
        return parsed["value"]
    if value is None:
        return None
    text = str(value).strip()
    return text or None
