"""Optional note fallback. Off unless ``USE_LLM_NOTES=1``.

Production calls go through ``shared.llm_client``. Three unanimous calls are
required; any failure leaves the slot empty (UNKNOWN, never a clear). A test
may pass ``transport(text) -> dict`` to inject one suggestion. Injected values
still have to appear verbatim in the note and never override a regex slot.
The key is read from ``OPENROUTER_API_KEY`` and is never hardcoded. There is
no response cache.
"""

from __future__ import annotations

import os

from shared.llm_client import OpenRouterClient
from stage1.countries import countries_in_note
from stage1.normalise import parse_date

NOTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "dob", "doc_country"],
    "properties": {
        "name": {"type": ["string", "null"]},
        "dob": {"type": ["string", "null"]},
        "doc_country": {"type": ["string", "null"]},
    },
}


def llm_enabled() -> bool:
    """On only when ``USE_LLM_NOTES=1``. ``SANCTIONS_LLM=0`` forces every stage off."""
    if os.environ.get("SANCTIONS_LLM") == "0":
        return False
    return os.environ.get("USE_LLM_NOTES", "0") == "1"


def fill_null_slots(text: str, parsed: dict, transport=None, enabled: bool | None = None, client=None) -> dict:
    """Fill null fields on a parser result. Regex values are left untouched."""
    if not parsed.get("flags"):
        return parsed
    if os.environ.get("SANCTIONS_LLM") == "0":
        return parsed
    if enabled is None:
        enabled = llm_enabled()
    if transport is None:
        if not enabled:
            return parsed
        if client is None:
            client = OpenRouterClient()
        extraction = client.extract(text, NOTE_SCHEMA, schema_name="note_slots")
        if extraction.status != "ok" or not extraction.value:
            parsed.setdefault("flags", []).append("llm_unknown")
            return parsed
        return _apply_suggestion(text, parsed, extraction.value, method="llm")
    try:
        suggestion = transport(text)
    except Exception:
        parsed.setdefault("flags", []).append("llm_error")
        return parsed
    if not suggestion:
        return parsed
    return _apply_suggestion(text, parsed, suggestion, method="llm")


def _apply_suggestion(text: str, parsed: dict, suggestion: dict, method: str) -> dict:
    filled: list[str] = []
    if not parsed.get("name") and suggestion.get("name"):
        name = str(suggestion["name"])
        if name and name in text:
            parsed["name"] = name
            filled.append("name")
        else:
            parsed["flags"].append("llm_rejected")
    if not parsed.get("dob") and suggestion.get("dob"):
        raw = str(suggestion["dob"])
        dob, _flags = parse_date(raw)
        if dob and raw in text:
            parsed["dob"] = dob["value"]
            parsed["dob_precision"] = dob["precision"]
            filled.append("dob")
        else:
            parsed["flags"].append("llm_rejected")
    if not parsed.get("doc_country") and suggestion.get("doc_country"):
        country = str(suggestion["doc_country"])
        if country and country in text and countries_in_note(country):
            parsed["doc_country"] = countries_in_note(country)[0]
            filled.append("doc_country")
        else:
            parsed["flags"].append("llm_rejected")
    if filled:
        parsed["llm_fields"] = filled
        parsed["source_method"] = method
        parsed["method"] = method
        parsed["may_solely_support_different_entity"] = False
    return parsed
