"""Contracts later stages must honour. Stage 1 does not decide hits.

Missing, unread, or unmappable evidence blocks a clear. It never causes one.
``NAME_MISMATCH_VERIFIED``, ``LOCATION_MISMATCH``, and ``DOB_MISMATCH`` are
allowed only when the matching helper below returns true.
"""

from __future__ import annotations

import re

from stage1.normalise import dates_compatible, parse_date

_CUS = re.compile(r"^CUS-[0-9]{6}$")
_HIT_FIELD = re.compile(r"^H-[0-9A-F]{6}#\w+$")


def name_mismatch_verified_allowed(person: dict) -> bool:
    """False when the legal name is unverified, too short, or came only from the LLM."""
    flags = set(person.get("flags") or [])
    if flags & {"BLOCK_NAME_MISMATCH_VERIFIED", "BLOCK_NAME_CLEAR", "BLOCK_DOB_AGE_NAME_CLEAR", "NAME_TOO_SHORT"}:
        return False
    legal = person.get("legal_name") or {}
    if not legal.get("verified"):
        return False
    if legal.get("blocks_name_clear"):
        return False
    if legal.get("method") == "llm" or legal.get("may_solely_support_different_entity") is False:
        return False
    return True


def location_mismatch_allowed(person: dict) -> bool:
    """False when a note was unread or a country could not be mapped."""
    flags = set(person.get("flags") or [])
    if "BLOCK_LOCATION_MISMATCH" in flags or "UNMAPPED_COUNTRY" in flags:
        return False
    if any(str(flag).startswith("NOTE_FLAGGED:") for flag in flags):
        return False
    return True


def dob_mismatch_allowed(person: dict, hit_value: object) -> bool:
    """True only when every declared date contradicts the hit.

    A missing, unparsed, or ambiguous hit date blocks the clear. So does any
    declared date that is missing or compatible with the hit. Hit slash dates
    are parsed in hit mode.
    """
    if "BLOCK_DOB_AGE_NAME_CLEAR" in set(person.get("flags") or []):
        return False
    hit, hit_flags = parse_date(hit_value, mode="hit")
    if hit is None or hit_flags:
        return False
    declared = person.get("declared_dobs") or []
    if not declared:
        return False
    for entry in declared:
        if not entry.get("comparable"):
            return False
        left, left_flags = parse_date(entry.get("value"), mode="customer")
        if left is None or left_flags or dates_compatible(left, hit):
            return False
    return True


def customer_record_id_for_output(person: dict) -> str | None:
    """One ``CUS-`` id. Never the internal ``P-`` person id."""
    record_ids = list(person.get("customer_record_ids") or [])
    for record_id in record_ids:
        if not _CUS.fullmatch(record_id):
            raise ValueError(f"output record id must be a CUS id, got {record_id!r}")
    if not record_ids:
        return None
    return record_ids[0]


def hit_field_evidence(hit_id: str, field: str) -> str:
    """``H-XXXXXX#field``, the form ``validate.py`` accepts for hit fields."""
    token = f"{hit_id}#{field}"
    if not _HIT_FIELD.fullmatch(token):
        raise ValueError(token)
    return token
