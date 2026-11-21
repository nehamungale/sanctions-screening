"""Optional profile-note birth fallback. Off unless explicitly enabled.

``USE_LLM_HITS=1`` turns it on. ``SANCTIONS_LLM=0`` forces it off, so a
whole-system LLM-off run cannot leave this stage on. Calls go through
``shared.llm_client``: free model only, pinned provider, temperature 0,
strict JSON, quote check, three agreeing calls. Years are computed here.
A fact that came from the model is ``method='llm'`` and
``may_solely_support_different_entity`` is false.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from shared.llm_client import DEFAULT_MODEL, DEFAULT_PROVIDER_ORDER, OpenRouterClient
from stage1.normalise import parse_date

PROMPT_VERSION = "hit-note-dob-v1"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statement", "born_date", "age", "reference_date", "quote"],
    "properties": {
        "statement": {"type": "string", "enum": ["born", "age_at_date", "none"]},
        "born_date": {"type": ["string", "null"]},
        "age": {"type": ["integer", "null"]},
        "reference_date": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"]},
    },
}
_STATEMENTS = {"born", "age_at_date", "none"}


def llm_enabled() -> bool:
    if os.environ.get("SANCTIONS_LLM") == "0":
        return False
    return os.environ.get("USE_LLM_HITS", "0") == "1"


def _age_years(year: int, age: int) -> list[int]:
    return sorted({year - age - 1, year - age})


def candidate_from_model(paragraph: str, value: dict, source_id: str) -> dict | None:
    """Build a candidate from a model object. Years come from ``parse_date``."""
    if not isinstance(value, dict):
        return None
    statement = value.get("statement")
    quote = value.get("quote") or ""
    if statement not in _STATEMENTS:
        return None
    if statement == "none":
        return None
    if not quote or quote not in paragraph:
        return None
    if statement == "born":
        born = value.get("born_date")
        if not isinstance(born, str) or born not in quote:
            return None
        parsed, flags = parse_date(born, mode="hit")
        if not parsed or flags:
            return None
        return {
            "years": [parsed["y"]],
            "month": parsed["m"],
            "day": parsed["d"],
            "precision": parsed["precision"],
            "source": "profile_note",
            "source_id": source_id,
            "method": "llm",
            "rule": "born",
            "quote": quote,
            "may_solely_support_different_entity": False,
        }
    age = value.get("age")
    reference = value.get("reference_date")
    if isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= 120:
        return None
    if not isinstance(reference, str) or reference not in quote:
        return None
    if re.search(rf"\b{age}\b", quote) is None:
        return None
    parsed, flags = parse_date(reference, mode="hit")
    if not parsed or flags:
        return None
    return {
        "years": _age_years(parsed["y"], age),
        "month": None,
        "day": None,
        "precision": "year",
        "source": "profile_note",
        "source_id": source_id,
        "method": "llm",
        "rule": "age_at_date",
        "quote": quote,
        "may_solely_support_different_entity": False,
    }


class NoteFallback:
    """Three agreeing calls, or UNKNOWN. Disabled instances never call out."""

    def __init__(self, cache_dir: str | None, enabled: bool, client=None, transport=None):
        self.enabled = enabled
        self.client = client
        self.transport = transport
        self.cache_path = os.path.join(cache_dir, "llm_hit_cache.json") if cache_dir else None
        self.cache: dict[str, dict] = {}
        self.calls = 0
        self.hits_called = 0
        if self.enabled and self.cache_path and os.path.isfile(self.cache_path):
            with open(self.cache_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self.cache = loaded

    def resolve(self, hit_id: str, name: str, paragraph: str) -> dict:
        """Return ``candidate``, ``flags``, and whether the network was required."""
        source_id = f"{hit_id}#profile_notes"
        if not self.enabled:
            return {"candidate": None, "flags": ["NOTE_DOB_UNRESOLVED"], "called": False}
        key = self._key(paragraph)
        if key in self.cache:
            stored = self.cache[key]
            candidate = candidate_from_model(paragraph, stored.get("value") or {}, source_id) if stored.get("ok") else None
            flags = [] if candidate or stored.get("none") else ["NOTE_DOB_UNRESOLVED", "LLM_UNKNOWN"]
            if stored.get("budget"):
                flags = ["NOTE_DOB_UNRESOLVED", "LLM_SKIPPED_BUDGET"]
            return {"candidate": candidate, "flags": flags, "called": False}
        value, detail = self._call(name, paragraph)
        self.hits_called += 1
        candidate = candidate_from_model(paragraph, value, source_id) if value else None
        none = bool(value and value.get("statement") == "none" and (value.get("quote") or "") in paragraph)
        budget = detail == "time_or_budget_cap"
        self.cache[key] = {"ok": candidate is not None, "none": none and candidate is None, "budget": budget, "value": value}
        if candidate:
            flags = []
        elif budget:
            flags = ["NOTE_DOB_UNRESOLVED", "LLM_SKIPPED_BUDGET"]
        elif none:
            flags = []
        else:
            flags = ["NOTE_DOB_UNRESOLVED", "LLM_UNKNOWN"]
        return {"candidate": candidate, "flags": flags, "called": True}

    def save(self) -> None:
        if not self.enabled or not self.cache_path or not self.cache:
            return
        parent = os.path.dirname(self.cache_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(self.cache, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")

    def _key(self, paragraph: str) -> str:
        model = getattr(self.client, "model", None) or DEFAULT_MODEL
        provider = getattr(self.client, "provider_order", None) or DEFAULT_PROVIDER_ORDER
        raw = "|".join([str(model), ",".join(provider), PROMPT_VERSION, paragraph])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _call(self, name: str, paragraph: str) -> tuple[dict | None, str]:
        message = (
            f"prompt_version: {PROMPT_VERSION}\n"
            "Extract one birth fact about the named person from the paragraph only.\n"
            "statement is born, age_at_date, or none.\n"
            "born_date is the date text when statement is born, otherwise null.\n"
            "age is the integer age when statement is age_at_date, otherwise null.\n"
            "reference_date is the date that age was observed, otherwise null.\n"
            "quote must be a verbatim substring of the paragraph.\n"
            f"name: {name}\n"
            "paragraph:\n"
            f"{paragraph}"
        )
        if self.transport is not None:
            ballots: list[str] = []
            value = None
            for _vote in range(3):
                self.calls += 1
                try:
                    suggested = self.transport(paragraph)
                except Exception:
                    return None, "vote_failed"
                if not isinstance(suggested, dict) or suggested.get("statement") not in _STATEMENTS:
                    return None, "vote_failed"
                if not _quoted(suggested, paragraph):
                    return None, "quote_miss"
                encoded = json.dumps(suggested, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                ballots.append(encoded)
                value = suggested
            if len(set(ballots)) != 1:
                return None, "disagreement"
            return value, "unanimous"
        if self.client is None:
            self.client = OpenRouterClient(call_budget=48, time_cap=1200.0)
        self.calls = self.client.calls
        extraction = self.client.extract(message, SCHEMA, schema_name="hit_note_dob")
        self.calls = self.client.calls
        if extraction.status != "ok" or not extraction.value:
            return None, extraction.detail
        if not _quoted(extraction.value, paragraph):
            return None, "quote_miss"
        return extraction.value, extraction.detail


def _quoted(value: dict, paragraph: str) -> bool:
    for key in ("quote", "born_date", "reference_date"):
        item = value.get(key)
        if isinstance(item, str) and item and item not in paragraph:
            return False
    return True
