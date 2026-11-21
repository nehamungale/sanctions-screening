"""Deterministic normalisers: names, dates, phones, emails, document numbers."""

from __future__ import annotations

import re
from datetime import date

from shared.names import agree_parts
from stage1.normalise_text import norm_text

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_MISSING_DATES = {"", "n/a", "na", "null", "none", "unknown", "-", "--"}
_PLACEHOLDERS = {"na", "test", "unknown", "xxx", "none"}
_NA_RE = re.compile(r"\bn\s*[./]\s*a\b")

_ISO_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_ISO_MONTH = re.compile(r"(\d{4})-(\d{2})")
_DMY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_D_MONTH_Y = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_MONTH_D_Y = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")
_MONTH_Y = re.compile(r"([A-Za-z]+)\s+(\d{4})")
_YEAR = re.compile(r"(\d{4})")


def parse_date(value: object, mode: str = "customer") -> tuple[dict | None, list[str]]:
    """Parse one date string.

    ``mode='customer'`` treats ``DD/MM/YYYY`` as day-first. ``mode='hit'`` leaves a
    slash date UNKNOWN when both numeric parts are 12 or under, because hit
    dates are written however the provider wrote them. An unambiguous slash
    date (one part above 12) is still parsed. Returns ``(parsed, flags)``.
    A missing value is ``(None, [])``. An ambiguous hit slash date is
    ``(None, ["UNKNOWN_DATE"])``. Anything else unrecognised is
    ``(None, ["UNPARSED_DATE"])``.
    """
    if mode not in ("customer", "hit"):
        raise ValueError(f"unknown date mode {mode!r}")
    if value is None:
        return None, []
    raw = str(value).strip()
    if raw.lower() in _MISSING_DATES:
        return None, []
    parsed, ambiguous = _parse_date_raw(raw, mode)
    if ambiguous:
        return None, ["UNKNOWN_DATE"]
    if parsed is None:
        return None, ["UNPARSED_DATE"]
    parsed["raw"] = raw
    return parsed, []


def _parse_date_raw(raw: str, mode: str = "customer") -> tuple[dict | None, bool]:
    match = _ISO_DAY.fullmatch(raw)
    if match:
        return _full(int(match.group(1)), int(match.group(2)), int(match.group(3))), False
    match = _ISO_MONTH.fullmatch(raw)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if _year_ok(year) and 1 <= month <= 12:
            return _pack(year, month, None, "month"), False
        return None, False
    match = _DMY.fullmatch(raw)
    if match:
        first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if mode == "hit" and first <= 12 and second <= 12:
            return None, True
        if first > 12 and second > 12:
            return None, False
        if mode == "customer" or first > 12:
            return _full(year, second, first), False
        return _full(year, first, second), False
    match = _D_MONTH_Y.fullmatch(raw)
    if match:
        month = MONTHS.get(match.group(2).lower())
        if month:
            return _full(int(match.group(3)), month, int(match.group(1))), False
        return None, False
    match = _MONTH_D_Y.fullmatch(raw)
    if match:
        month = MONTHS.get(match.group(1).lower())
        if month:
            return _full(int(match.group(3)), month, int(match.group(2))), False
        return None, False
    match = _MONTH_Y.fullmatch(raw)
    if match:
        month = MONTHS.get(match.group(1).lower())
        year = int(match.group(2))
        if month and _year_ok(year):
            return _pack(year, month, None, "month"), False
        return None, False
    match = _YEAR.fullmatch(raw)
    if match:
        year = int(match.group(1))
        if _year_ok(year):
            return _pack(year, None, None, "year"), False
        return None, False
    return None, False


def _year_ok(year: int) -> bool:
    return 1000 <= year <= 2999


def _full(year: int, month: int, day: int) -> dict | None:
    if not _year_ok(year) or not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return _pack(year, month, day, "day")


def _pack(year: int, month: int | None, day: int | None, precision: str) -> dict:
    if precision == "day":
        value = f"{year:04d}-{month:02d}-{day:02d}"
    elif precision == "month":
        value = f"{year:04d}-{month:02d}"
    else:
        value = f"{year:04d}"
    return {"y": year, "m": month, "d": day, "precision": precision, "value": value}


def dates_compatible(left: dict | None, right: dict | None) -> bool:
    """Equal in every part both dates give. A year agrees with a full date in that year."""
    if not left or not right:
        return False
    if left["y"] != right["y"]:
        return False
    if left["m"] is not None and right["m"] is not None and left["m"] != right["m"]:
        return False
    if left["d"] is not None and right["d"] is not None and left["d"] != right["d"]:
        return False
    return True


def dates_identical_full(left: dict | None, right: dict | None) -> bool:
    """Both day precision and equal. This is the clustering comparison."""
    return bool(
        left
        and right
        and left["precision"] == "day"
        and right["precision"] == "day"
        and left["value"] == right["value"]
    )


def norm_phone(value: object) -> str | None:
    """Keep a leading ``+`` and digits only."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    leading = "+" if text.startswith("+") else ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    return leading + digits


def norm_email(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def norm_docno(value: object) -> str | None:
    """Uppercase, strip spaces and hyphens. Empty becomes None."""
    if value is None:
        return None
    text = re.sub(r"[\s-]+", "", str(value).upper())
    return text or None


def levenshtein(left: str, right: str) -> int:
    """Insert, delete, or substitute costs 1, so a transposition costs 2."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, ch_left in enumerate(left, 1):
        current = [i]
        for j, ch_right in enumerate(right, 1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            substitute = previous[j - 1] + (ch_left != ch_right)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


class NameTools:
    """Name-part rules from the identity SOP, driven by ``name_variants.json``."""

    def __init__(self, name_variants: dict | None):
        payload = name_variants or {}
        self.legal_forms = frozenset(norm_text(item) for item in payload.get("company_legal_forms", []))
        self.variants: dict[str, set[str]] = {}
        for group in payload.get("groups", []):
            members = {norm_text(part) for part in group if norm_text(part)}
            for part in members:
                self.variants[part] = self.variants.get(part, set()) | members

    def parts(self, name: object, entity_type: str | None) -> list[str]:
        return self.split(name, entity_type)[0]

    def split(self, name: object, entity_type: str | None) -> tuple[list[str], bool]:
        """Return ``(ordered distinct parts, placeholder_dropped)``."""
        if name is None:
            return [], False
        text = str(name).translate(str.maketrans({"’": "'", "‘": "'", "`": "'", "ʼ": "'"}))
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"\[[^\]]*\]", " ", text)
        text = norm_text(text)
        company = entity_type == "Company"
        had_placeholder = (not company) and bool(_NA_RE.search(text))
        text = text.replace(".", "").replace("'", "").replace("`", "")
        text = re.sub(r"[^0-9a-z]+", " ", text)
        legal = self.legal_forms if company else frozenset()
        parts: list[str] = []
        seen: set[str] = set()
        for token in text.split():
            if len(token) == 1:
                continue
            placeholder = token in _PLACEHOLDERS or token.isdigit()
            if token in legal:
                continue
            if placeholder:
                had_placeholder = True
                continue
            if token not in seen:
                seen.add(token)
                parts.append(token)
        return parts, had_placeholder

    def parts_match(self, left: str, right: str) -> bool:
        if left == right:
            return True
        if right in self.variants.get(left, ()) or left in self.variants.get(right, ()):
            return True
        shortest = min(len(left), len(right))
        if shortest < 4:
            return False
        limit = 1 if shortest <= 6 else 2
        if abs(len(left) - len(right)) > limit:
            return False
        return levenshtein(left, right) <= limit

    def names_agree(
        self,
        left: object,
        right: object,
        entity_left: str | None = "Individual",
        entity_right: str | None = "Individual",
    ) -> dict:
        """SOP name agreement. Shared by the customer and hit tracks.

        Pairing is exhaustive (see ``shared.names.agree_parts``), not greedy.
        """
        parts_left = left if isinstance(left, list) else self.parts(left, entity_left)
        parts_right = right if isinstance(right, list) else self.parts(right, entity_right)
        return agree_parts(parts_left, parts_right, self.parts_match)
