"""Optional note fallback. Off unless ``USE_LLM_NOTES=1``.

The model may fill slots the regex left empty. It never overrides a regex
value. Returned strings must appear literally in the note, and dates must
parse with ``parse_date``. The key is read from ``OPENROUTER_API_KEY`` and is
never hardcoded.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request

from stage1.countries import countries_in_note
from stage1.normalise import parse_date

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_CACHE: dict[str, dict | None] = {}

_SCHEMA_HINT = {
    "name": None,
    "dob": None,
    "doc_country": None,
    "is_successful_verification": True,
    "residence": [],
    "evidence_span": "",
}


def llm_enabled() -> bool:
    return os.environ.get("USE_LLM_NOTES", "0") == "1"


def fill_null_slots(text: str, parsed: dict, transport=None, enabled: bool | None = None) -> dict:
    """Fill null fields on a parser result. ``transport(text) -> dict | None``."""
    if not parsed.get("flags"):
        return parsed
    if enabled is None:
        enabled = llm_enabled()
    if transport is None:
        if not enabled:
            return parsed
        transport = openrouter_transport
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest in _CACHE and transport is openrouter_transport:
        suggestion = _CACHE[digest]
    else:
        try:
            suggestion = transport(text)
        except Exception:
            parsed.setdefault("flags", []).append("llm_error")
            return parsed
        if transport is openrouter_transport:
            _CACHE[digest] = suggestion
    if not suggestion:
        return parsed
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
        parsed["source_method"] = "llm"
    return parsed


def openrouter_transport(text: str) -> dict | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    payload = {
        "model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract identity slots from a bank note. Reply with JSON only. "
                    "Use null for anything not literally present. Do not infer."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"schema": _SCHEMA_HINT, "note": text}, ensure_ascii=False),
            },
        ],
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)
