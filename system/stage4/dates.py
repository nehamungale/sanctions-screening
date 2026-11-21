"""Date agreement, contradiction, age and death. Policy P6 and P7.

``dates_compatible`` in Stage 1 is the agreement test (same year, and the
same month or day when both dates give one). It is not the opposite of a
contradiction: dates one year apart are neither.
"""

from __future__ import annotations

import calendar
from datetime import date


def parse_parts(value: object) -> dict | None:
    """``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` to ``{y, m, d, precision, value}``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    bits = text.split("-")
    if not bits[0].isdigit():
        return None
    year = int(bits[0])
    month = int(bits[1]) if len(bits) > 1 and bits[1].isdigit() else None
    day = int(bits[2]) if len(bits) > 2 and bits[2].isdigit() else None
    if month is not None and not 1 <= month <= 12:
        return None
    if day is not None and month is None:
        return None
    if day is not None:
        try:
            date(year, month, day)
        except ValueError:
            return None
        precision = "day"
        shown = f"{year:04d}-{month:02d}-{day:02d}"
    elif month is not None:
        precision = "month"
        shown = f"{year:04d}-{month:02d}"
    else:
        precision = "year"
        shown = f"{year:04d}"
    return {"y": year, "m": month, "d": day, "precision": precision, "value": shown}


def agrees(customer: dict, candidate: dict) -> bool:
    """P7. A year agrees with a full date in that year."""
    years = list(candidate.get("years") or [])
    if customer.get("y") not in years:
        return False
    month = candidate.get("month")
    day = candidate.get("day")
    if customer.get("m") is not None and month is not None and customer["m"] != month:
        return False
    if customer.get("d") is not None and day is not None and customer["d"] != day:
        return False
    return True


def contradicts(customer: dict, candidate: dict) -> bool:
    """P6 date of birth. More than one year outside, or the same year with a different month or day."""
    years = [int(year) for year in (candidate.get("years") or [])]
    if not years:
        return False
    if min(abs(int(customer["y"]) - year) for year in years) > 1:
        return True
    if len(years) == 1 and int(customer["y"]) == years[0]:
        month = candidate.get("month")
        day = candidate.get("day")
        if customer.get("m") is not None and month is not None:
            if customer["m"] != month:
                return True
            if customer.get("d") is not None and day is not None and customer["d"] != day:
                return True
    return False


def as_date(value: object) -> date | None:
    text = "" if value is None else str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        except ValueError:
            return None
    parts = parse_parts(text[:10] if len(text) >= 10 else text)
    if parts is None or parts["m"] is None or parts["d"] is None:
        return None
    return date(parts["y"], parts["m"], parts["d"])


def last_possible_day(value: object, precision: str | None) -> date | None:
    """Year → 31 Dec, month → last day of that month, day → that day."""
    parts = parse_parts(value)
    if parts is None:
        return None
    prec = precision or parts["precision"]
    if prec == "year" or parts["m"] is None:
        return date(parts["y"], 12, 31)
    if prec == "month" or parts["d"] is None:
        last = calendar.monthrange(parts["y"], parts["m"])[1]
        return date(parts["y"], parts["m"], last)
    return date(parts["y"], parts["m"], parts["d"])


def earliest_day(parts: dict) -> date:
    """Earliest calendar day a partial date can be. Used so a contradiction holds for every reading."""
    return date(int(parts["y"]), int(parts["m"] or 1), int(parts["d"] or 1))


def age_on(birth: date, on: date) -> int:
    years = on.year - birth.year
    if (on.month, on.day) < (birth.month, birth.day):
        years -= 1
    return years


def under_sixteen(parts: dict, on: date) -> bool:
    """True only when even the oldest reading of ``parts`` is under 16 on ``on``."""
    return age_on(earliest_day(parts), on) < 16


def screened_date(alert: dict) -> date | None:
    return as_date(alert.get("screened_at"))


def deceased_before_screening(hit: dict, alert: dict) -> tuple[bool, date | None, date | None]:
    """Dated death strictly before the screening date. No date never clears."""
    deceased = hit.get("deceased") or {}
    if not deceased.get("date"):
        return False, None, screened_date(alert)
    latest = last_possible_day(deceased.get("date"), deceased.get("precision"))
    screened = screened_date(alert)
    if latest is None or screened is None:
        return False, latest, screened
    return latest < screened, latest, screened
