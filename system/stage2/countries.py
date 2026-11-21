"""Countries tied to a hit, via the Stage 1 country table.

Each value contributes its last comma-separated part, after address tags such
as ``[Business]`` are removed. ``norm_country`` drops International and Europe
and maps Macao, Kosovo, and Palestine. Unknown leaves stay as written.
"""

from __future__ import annotations

import re

from stage1.countries import norm_country

_TAG = re.compile(r"\[[^\]]*\]")
_FIELDS = ("countries", "nationality", "citizenship", "addresses", "place_of_birth")


def _leaf(raw: str) -> str:
    text = _TAG.sub(" ", raw)
    bits = [bit.strip(" .;") for bit in text.split(",") if bit.strip(" .;")]
    return bits[-1] if bits else ""


def hit_countries(hit: dict) -> tuple[list[dict], list[str]]:
    hit_id = hit["hit_id"]
    entries: list[dict] = []
    flags: list[str] = []
    for field in _FIELDS:
        value = hit.get(field)
        items = value if isinstance(value, list) else ([value] if isinstance(value, str) else [])
        for raw in items:
            if not raw:
                continue
            leaf = _leaf(str(raw))
            if not leaf:
                continue
            canonical, country_flags = norm_country(leaf)
            if canonical is None and not country_flags:
                continue
            unmapped = bool(country_flags)
            if unmapped:
                flags.append("UNMAPPED_COUNTRY")
            entries.append({
                "value": leaf if unmapped else canonical,
                "field": field,
                "raw": str(raw),
                "source_id": f"{hit_id}#{field}",
                "precision": None,
                "method": "field",
                "unmapped": unmapped,
            })
    if not entries:
        flags.append("NO_COUNTRY")
    return entries, flags
