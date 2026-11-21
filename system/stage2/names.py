"""Hit names. Parts come from the Stage 1 name normaliser.

Non-Latin aliases are kept and flagged. They are not transliterated: a value
with no ASCII letter gets an empty part list, even if Unicode decomposition
would otherwise invent Latin letters.
"""

from __future__ import annotations

import re

from stage1.normalise import NameTools

_TAG = re.compile(r"\s*\(([^)]*)\)\s*$")
_LATIN = re.compile(r"[A-Za-z]")


def _core_and_tag(value: str) -> tuple[str, str | None]:
    match = _TAG.search(value)
    if not match:
        return value, None
    return value[: match.start()].rstrip(), match.group(1)


def _entry(
    value: str,
    kind: str,
    source_field: str,
    source_id: str,
    tools: NameTools,
    entity_type: str,
) -> dict:
    core, tag = _core_and_tag(value)
    non_latin = _LATIN.search(core) is None
    if non_latin:
        parts: list[str] = []
        script = "non_latin"
    else:
        parts = tools.split(value, entity_type)[0]
        script = "latin"
    return {
        "value": value,
        "kind": kind,
        "tag": tag,
        "script": script,
        "parts": parts,
        "source_field": source_field,
        "source_id": source_id,
        "precision": None,
        "method": "field",
    }


def hit_names(hit: dict, tools: NameTools) -> tuple[list[dict], list[str]]:
    """Primary, aliases, best match, then the structured name if it is new."""
    hit_id = hit["hit_id"]
    entity_type = hit.get("entity_type")
    names = [_entry(str(hit.get("name") or ""), "primary", "name", f"{hit_id}#name", tools, entity_type)]
    for index, alias in enumerate(hit.get("aliases") or []):
        names.append(
            _entry(str(alias), "alias", f"aliases[{index}]", f"{hit_id}#aliases", tools, entity_type)
        )
    best = hit.get("best_matching_name")
    if best:
        names.append(
            _entry(
                str(best),
                "best_matching",
                "best_matching_name",
                f"{hit_id}#best_matching_name",
                tools,
                entity_type,
            )
        )
    structured = _structured_name(hit, tools, names)
    if structured is not None:
        names.append(structured)
    flags = ["NON_LATIN_ALIAS"] if any(entry["script"] == "non_latin" and entry["kind"] == "alias" for entry in names) else []
    return names, flags


def _structured_name(hit: dict, tools: NameTools, existing: list[dict]) -> dict | None:
    pieces = [hit.get("first_name"), hit.get("middle_name"), hit.get("last_name")]
    if not any(pieces):
        return None
    joined = " ".join(str(piece) for piece in pieces if piece)
    entry = _entry(joined, "structured", "structured", f"{hit['hit_id']}#structured", tools, hit.get("entity_type"))
    if entry["parts"] and any(entry["parts"] == other["parts"] for other in existing):
        return None
    return entry
