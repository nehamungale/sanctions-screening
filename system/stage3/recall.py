"""Compare name-index candidates with a full scan.

The part index stores exact normalised parts. Stage 3 expands those keys
through variant groups, POLICY edit distance, and joined or split forms, then
keeps a record only when the symmetric name rule agrees. This module checks
that the expanded index does not drop a record the full scan would keep.
"""

from __future__ import annotations

from stage3.names import record_name_agrees
from stage3.resolve import normalise_screened


def agreeing_records(catalog, screened_parts: tuple[str, ...], entity_type: str | None, *, use_index: bool) -> set[str]:
    """Record ids whose full, preferred, or login name agrees with ``screened_parts``."""
    if not screened_parts:
        return set()
    screened_parts = tuple(screened_parts)
    if use_index:
        pool = [
            catalog.prepared[record_id]
            for record_id in catalog.blocking.candidates(screened_parts)
            if record_id in catalog.prepared
        ]
    else:
        pool = list(catalog.prepared.values())
    grouped: dict[tuple, list[str]] = {}
    for prepared in pool:
        if entity_type and prepared.entity_type != entity_type:
            continue
        grouped.setdefault(prepared.names, []).append(prepared.record_id)
    found: set[str] = set()
    for record_names, record_ids in grouped.items():
        if record_name_agrees(catalog.names, screened_parts, record_names):
            found.update(record_ids)
    return found


def unlinked_recall(catalog, alerts: list[dict]) -> dict:
    """Index path versus a brute-force scan for every alert with no link."""
    compared = 0
    mismatches = []
    for alert in alerts:
        if _has_link(alert):
            continue
        customer = alert.get("customer") if isinstance(alert.get("customer"), dict) else {}
        screened = normalise_screened(customer, catalog.names)
        compared += 1
        indexed = agreeing_records(catalog, screened.parts, screened.entity_type, use_index=True)
        scanned = agreeing_records(catalog, screened.parts, screened.entity_type, use_index=False)
        if indexed != scanned:
            mismatches.append({
                "alert_id": alert.get("alert_id"),
                "index_only": sorted(indexed - scanned),
                "scan_only": sorted(scanned - indexed),
            })
    return {
        "compared": compared,
        "match": not mismatches,
        "mismatches": mismatches,
    }


def _has_link(alert: dict) -> bool:
    account = alert.get("account_ref")
    if isinstance(account, str) and account.strip():
        return True
    login = alert.get("login_handle")
    if isinstance(login, str) and login.strip():
        return True
    email = alert.get("email")
    return isinstance(email, str) and bool(email.strip())
