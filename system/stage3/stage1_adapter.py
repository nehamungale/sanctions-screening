"""Load the Stage 1 record-level cache Stage 3 matches against.

Reads only the artefacts in ``system/stage1/SCHEMA.md``:

- ``record_view.jsonl``
- ``index_account_record_id.json``
- ``index_login_record_id.json``
- ``index_email_record_id.json``
- ``index_name_part_record_id.json``

``index_name.json`` is intentionally not opened. The record view is not
rebuilt from ``customers.jsonl``. That file is read only to recover a
company's declared date of birth, because ``record_view.dob`` may be the
registry incorporation date instead.
The cache directory is ``SANCTIONS_CACHE`` or ``working/``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass

from stage1.normalise import NameTools, parse_date
from stage1.normalise_text import norm_text
from stage3.blocking import PartBlock

RECORD_VIEW = "record_view.jsonl"
INDEX_ACCOUNT = "index_account_record_id.json"
INDEX_LOGIN = "index_login_record_id.json"
INDEX_EMAIL = "index_email_record_id.json"
INDEX_NAME_PART = "index_name_part_record_id.json"

_NAME_FIELDS = ("full_name", "preferred_name", "login_name")
_COUNTRY_FIELDS = ("residence_country", "nationality")


@dataclass
class Prepared:
    """One customer record, reduced to the fields name search compares.

    ``country_facts`` is ``(canonical name, from_note)``. A note-derived value is
    only possible when Stage 1 has tagged the residence or nationality source
    as a note. Search does not read note text or add note countries itself.
    """

    record_id: str
    person_id: str
    entity_type: str | None
    names: tuple[tuple[str, tuple[str, ...]], ...]
    dob: dict | None
    countries: tuple[str, ...]
    country_facts: tuple[tuple[str, bool], ...]
    city_norm: str | None
    address_norm: str | None


class Catalog:
    """In-memory Stage 1 record view plus the record-level indexes."""

    def __init__(
        self,
        prepared: dict[str, Prepared],
        by_person: dict[str, tuple[str, ...]],
        by_type: dict[str | None, tuple[str, ...]],
        account_index: dict[str, tuple[str, ...]],
        login_index: dict[str, tuple[str, ...]],
        email_index: dict[str, tuple[str, ...]],
        names: NameTools,
        blocking: PartBlock,
    ):
        self.prepared = prepared
        self.by_person = by_person
        self.by_type = by_type
        self.type_sets = {key: set(value) for key, value in by_type.items()}
        self.all_ids = tuple(sorted(prepared))
        self.account_index = account_index
        self.login_index = login_index
        self.email_index = email_index
        self.names = names
        self.blocking = blocking


def load_catalog(cache_dir: str, name_variants: dict | None, customers_path: str | None = None) -> Catalog:
    """Load the record view and record-level indexes from ``cache_dir``."""
    view_path = _require(cache_dir, RECORD_VIEW)
    account_index = _load_index(_require(cache_dir, INDEX_ACCOUNT))
    login_index = _casefold_keys(_load_index(_require(cache_dir, INDEX_LOGIN)))
    email_index = _load_index(_require(cache_dir, INDEX_EMAIL))
    name_index = _load_index(_require(cache_dir, INDEX_NAME_PART))
    prepared = _load_records(view_path)
    by_person: dict[str, list[str]] = defaultdict(list)
    by_type: dict[str | None, list[str]] = defaultdict(list)
    for record_id in sorted(prepared):
        row = prepared[record_id]
        by_person[row.person_id].append(record_id)
        by_type[row.entity_type].append(record_id)
    if customers_path:
        _overlay_company_declared_dobs(prepared, customers_path)
    names = NameTools(name_variants)
    return Catalog(
        prepared=prepared,
        by_person={key: tuple(by_person[key]) for key in sorted(by_person)},
        by_type={key: tuple(by_type[key]) for key in by_type},
        account_index=account_index,
        login_index=login_index,
        email_index=email_index,
        names=names,
        blocking=PartBlock(name_index, names),
    )


def _require(cache_dir: str, name: str) -> str:
    path = os.path.join(cache_dir, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"{path} (run system/run on the data folder first; "
            "cache is SANCTIONS_CACHE or working/)"
        )
    return path


def _load_index(path: str) -> dict[str, tuple[str, ...]]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    index: dict[str, tuple[str, ...]] = {}
    for key, value in payload.items():
        if not isinstance(value, list):
            raise ValueError(f"{path} key {key!r} is not a list")
        index[str(key)] = tuple(sorted({str(item) for item in value}))
    return index


def _casefold_keys(index: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """Login handles are stored trimmed. Match them case-insensitively."""
    folded: dict[str, set[str]] = defaultdict(set)
    for key, record_ids in index.items():
        folded[str(key).strip().casefold()].update(record_ids)
    return {key: tuple(sorted(folded[key])) for key in sorted(folded)}


def _overlay_company_declared_dobs(prepared: dict[str, Prepared], customers_path: str) -> None:
    """Search compares a company's declared ``customers.dob``, not the registry date.

    ``record_view.dob`` for a company is the incorporation date: the latest
    approved registry extract when one exists, otherwise the declared date.
    POLICY principle 2 filters on the date the customer typed. That declared
    value is not a separate record_view field once a registry date wins, so it
    is read from ``customers.jsonl``. Individuals already carry the declared
    date on ``record_view.dob`` and are left unchanged.
    """
    with open(customers_path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            record = prepared.get(row.get("record_id"))
            if record is None or record.entity_type != "Company":
                continue
            parsed, _flags = parse_date(row.get("dob"), mode="customer")
            record.dob = parsed


def _load_records(path: str) -> dict[str, Prepared]:
    prepared: dict[str, Prepared] = {}
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            record_id = row.get("record_id")
            person_id = row.get("person_id")
            if not record_id or not person_id:
                raise ValueError(f"{path}:{line_number} needs record_id and person_id")
            if record_id in prepared:
                raise ValueError(f"duplicate record_id {record_id}")
            country_facts = _country_facts(row)
            prepared[str(record_id)] = Prepared(
                record_id=str(record_id),
                person_id=str(person_id),
                entity_type=_entity_type(row),
                names=_names(row),
                dob=_dob(row.get("dob")),
                countries=tuple(value for value, _from_note in country_facts),
                country_facts=country_facts,
                city_norm=_place(row.get("city")),
                address_norm=_place(row.get("address")),
            )
    return prepared


def _entity_type(row: dict) -> str | None:
    fact = row.get("entity_type") or {}
    value = fact.get("value") if isinstance(fact, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _names(row: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    names = []
    for field in _NAME_FIELDS:
        fact = row.get(field) or {}
        parts = fact.get("parts") if isinstance(fact, dict) else None
        if not parts:
            continue
        names.append((field, tuple(str(part) for part in parts if part)))
    return tuple(names)


def _dob(fact: object) -> dict | None:
    """Parsed declared date, or a company's incorporation date. Missing stays missing."""
    if not isinstance(fact, dict):
        return None
    if not fact.get("comparable") or not fact.get("value"):
        return None
    parsed, _flags = parse_date(fact.get("value"), mode="customer")
    return parsed


def _country_facts(row: dict) -> tuple[tuple[str, bool], ...]:
    """Residence and nationality only. Note text is not consulted."""
    found: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for field in _COUNTRY_FIELDS:
        fact = row.get(field) or {}
        if not isinstance(fact, dict):
            continue
        value = fact.get("value")
        if not value or value in seen:
            continue
        seen.add(value)
        found.append((value, _from_note(fact)))
    return tuple(found)


def _from_note(fact: dict) -> bool:
    source = str(fact.get("source_id") or "")
    if source.startswith("NOTE-"):
        return True
    kind = f"{fact.get('kind') or ''} {fact.get('source_kind') or ''}".lower()
    return "note" in kind


def _place(fact: object) -> str | None:
    if not isinstance(fact, dict):
        return None
    normalised = fact.get("normalised")
    if isinstance(normalised, str) and normalised.strip():
        return normalised.strip()
    raw = fact.get("raw")
    if isinstance(raw, str) and raw.strip():
        folded = norm_text(raw.strip())
        return folded or None
    return None
