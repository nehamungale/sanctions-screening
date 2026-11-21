"""Read the data folder once, the same way for every stage.

Unseen data may differ from the development set in small ways: an optional
file left out, a list field written as a single string, an entity type spelled
``individual`` or ``Organisation``, or a line that is not valid JSON. None of
those should stop the run. Here they become the shapes the stages expect:

* ``customers``, ``alerts`` and ``hits`` are required. Every other table is
  optional and reads as empty when its file is missing.
* A line that is not a JSON object is skipped and counted in ``SKIPPED``.
* ``entity_type`` on customers, hits and the screened customer of an alert is
  mapped to ``Individual`` or ``Company`` when the spelling is a known synonym.
  Anything else is kept as written, so it never matches by accident.
* List fields on hits (and ``hit_ids`` on alerts) given as one string become a
  one-item list. ``None`` becomes an empty list.

Values the development set already writes in canonical form pass through
unchanged, so output on that folder does not move.
"""

from __future__ import annotations

import json
import os
import sys

REQUIRED = frozenset({"customers.jsonl", "alerts.jsonl", "hits.jsonl"})

_INDIVIDUAL = frozenset({"individual", "person", "natural person", "private individual"})
_COMPANY = frozenset({
    "company", "organisation", "organization", "corporation", "corporate", "business",
    "entity", "legal entity", "legal person",
})
_HIT_LISTS = ("aliases", "dobs", "nationality", "citizenship", "countries", "addresses", "categories")

SKIPPED: dict[str, int] = {}


def canonical_entity_type(value: object) -> object:
    """``Individual`` / ``Company`` for known spellings, otherwise the value unchanged."""
    if not isinstance(value, str):
        return value
    folded = " ".join(value.replace("_", " ").split()).casefold()
    if folded in _INDIVIDUAL:
        return "Individual"
    if folded in _COMPANY:
        return "Company"
    return value


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float)):
        return [value]
    return []


def clean_row(name: str, row: dict) -> dict:
    """Normalise one row of ``name`` in place and return it."""
    if name in ("customers.jsonl", "hits.jsonl") and "entity_type" in row:
        row["entity_type"] = canonical_entity_type(row["entity_type"])
    if name == "hits.jsonl":
        for key in _HIT_LISTS:
            if key in row:
                row[key] = _as_list(row[key])
    if name == "alerts.jsonl":
        customer = row.get("customer")
        if not isinstance(customer, dict):
            row["customer"] = {}
        elif "entity_type" in customer:
            customer["entity_type"] = canonical_entity_type(customer["entity_type"])
        if "hit_ids" in row:
            row["hit_ids"] = _as_list(row["hit_ids"])
    return row


def read_jsonl(path: str, required: bool = True, clean_as: str | None = None) -> list[dict]:
    """Rows of a JSON Lines file. A missing optional file is ``[]``; bad lines are skipped."""
    if not os.path.isfile(path):
        if required:
            raise FileNotFoundError(path)
        return []
    rows: list[dict] = []
    skipped = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(row, dict):
                skipped += 1
                continue
            rows.append(clean_row(clean_as, row) if clean_as else row)
    if skipped:
        SKIPPED[os.path.basename(path)] = SKIPPED.get(os.path.basename(path), 0) + skipped
        print(f"warning: skipped {skipped} unreadable line(s) in {path}", file=sys.stderr)
    return rows


def read_json(path: str, required: bool = True, default: object = None) -> object:
    if not os.path.isfile(path):
        if required:
            raise FileNotFoundError(path)
        return {} if default is None else default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_table(folder: str, name: str) -> list[dict]:
    """One data-room table, cleaned. Only ``REQUIRED`` files may be missing-is-an-error."""
    return read_jsonl(os.path.join(folder, name), required=name in REQUIRED, clean_as=name)


def load_variants(folder: str) -> dict:
    """``name_variants.json``, or no variants when it is missing or not an object."""
    payload = read_json(os.path.join(folder, "name_variants.json"), required=False)
    return payload if isinstance(payload, dict) else {}


def write_jsonl(path: str, rows: list[dict]) -> None:
    """Cache format: UTF-8, compact separators, sorted keys, one object per line."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            handle.write("\n")


def write_json(path: str, payload: object) -> None:
    """Cache format for one JSON value."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
