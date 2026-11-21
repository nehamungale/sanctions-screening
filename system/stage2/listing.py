"""Listing phrase from the primary category, else the first category."""

from __future__ import annotations

_PHRASES = {
    "Sanctions": "a sanctioned individual",
    "PEP": "a politically exposed person",
    "Enforcement": "the subject of enforcement action",
    "Adverse Media": "named in adverse media",
    "SOE": "a state-owned enterprise official",
}
_OTHER = "named on a watchlist"


def listing(hit: dict) -> dict:
    primary = hit.get("primary_category")
    categories = hit.get("categories") or []
    if primary:
        category = primary
        origin = "primary_category"
    elif categories:
        category = categories[0]
        origin = "categories"
    else:
        category = None
        origin = "categories"
    return {
        "category": category,
        "phrase": _PHRASES.get(category, _OTHER),
        "from": origin,
        "source_id": f"{hit['hit_id']}#{origin}",
        "precision": None,
    }
