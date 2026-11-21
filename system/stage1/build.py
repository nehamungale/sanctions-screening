"""Cluster customers into persons and select the golden facts for each."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from itertools import combinations

from stage1.countries import norm_country
from stage1.load import DataStore
from stage1.normalise import (
    NameTools,
    dates_compatible,
    norm_docno,
    norm_email,
    norm_phone,
    parse_date,
)
from stage1.notes import parse_note

_PRECISION_RANK = {"day": 3, "month": 2, "year": 1}


class UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}
        self.rank = {item: 0 for item in items}

    def find(self, item: str) -> str:
        parent = self.parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, left: str, right: str) -> bool:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False
        if (self.rank[left_root], left_root) < (self.rank[right_root], right_root):
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1
        return True


def build_from_tables(tables: dict, use_llm: bool | None = None) -> tuple[list[dict], dict, dict]:
    """Return ``(people, indexes, stats)`` from already-loaded tables."""
    customers = list(tables.get("customers") or [])
    accounts = list(tables.get("accounts") or [])
    onboarding = list(tables.get("onboarding") or [])
    checks = list(tables.get("kyc_checks") or [])
    notes = list(tables.get("notes") or [])
    names = NameTools(tables.get("name_variants"))

    customers_by_id = {}
    for row in customers:
        customers_by_id[row["record_id"]] = row
    record_ids = sorted(customers_by_id)

    applicants_by_customer: dict[str, list[str]] = defaultdict(list)
    for row in onboarding:
        customer_id = row.get("customer_id")
        applicant_id = row.get("kyc_applicant_id")
        if customer_id and applicant_id:
            applicants_by_customer[customer_id].append(applicant_id)
    for customer_id, applicant_ids in applicants_by_customer.items():
        applicants_by_customer[customer_id] = sorted(set(applicant_ids))

    checks_by_applicant: dict[str, list[dict]] = defaultdict(list)
    for row in checks:
        checks_by_applicant[row["applicant_id"]].append(row)
    for applicant_id, rows in checks_by_applicant.items():
        rows.sort(key=lambda item: item.get("check_id") or "")

    accounts_by_customer: dict[str, list[dict]] = defaultdict(list)
    for row in accounts:
        if row.get("customer_id"):
            accounts_by_customer[row["customer_id"]].append(row)

    notes_by_email: dict[str, list[dict]] = defaultdict(list)
    parsed_by_id: dict[str, dict] = {}
    note_stats = {
        "notes": 0,
        "kyc": 0,
        "noise": 0,
        "residence": 0,
        "ignored": 0,
        "flagged": 0,
        "kyc_name": 0,
        "kyc_dob": 0,
        "kyc_doc_country": 0,
        "kyc_document_type": 0,
        "kyc_provider": 0,
        "kyc_check_date": 0,
        "flag_counts": {},
    }
    flag_counts: dict[str, int] = defaultdict(int)
    for note in notes:
        parsed = parse_note(note, use_llm=use_llm)
        parsed_by_id[note["note_id"]] = parsed
        email = norm_email(note.get("requester_email"))
        if email:
            notes_by_email[email].append(note)
        note_stats["notes"] += 1
        kind = parsed["kind"]
        if kind == "verification":
            note_stats["kyc"] += 1
            event = parsed["event"]
            note_stats["kyc_name"] += event.get("name") is not None
            note_stats["kyc_dob"] += event.get("dob") is not None
            note_stats["kyc_doc_country"] += event.get("doc_country") is not None
            note_stats["kyc_document_type"] += event.get("document_type") is not None
            note_stats["kyc_provider"] += event.get("provider") is not None
            note_stats["kyc_check_date"] += bool(event.get("date")) and "check_date_missing" not in parsed["flags"]
        elif kind == "noise":
            note_stats["noise"] += 1
        elif kind == "residence":
            note_stats["residence"] += 1
        else:
            note_stats["ignored"] += 1
        if parsed["flags"]:
            note_stats["flagged"] += 1
            for flag in parsed["flags"]:
                flag_counts[flag.split(":", 1)[0]] += 1
    note_stats["flag_counts"] = {key: flag_counts[key] for key in sorted(flag_counts)}

    union = UnionFind(record_ids)
    phone_edges, doc_edges, doc_new = _cluster(
        union, record_ids, customers_by_id, applicants_by_customer, checks_by_applicant
    )

    members: dict[str, list[str]] = defaultdict(list)
    for record_id in record_ids:
        members[union.find(record_id)].append(record_id)

    person_of: dict[str, str] = {}
    clusters: dict[str, list[str]] = {}
    for root, grouped in members.items():
        grouped.sort()
        person_id = "P-" + grouped[0]
        clusters[person_id] = grouped
        for record_id in grouped:
            person_of[record_id] = person_id

    edges_by_person: dict[str, list[dict]] = defaultdict(list)
    for edge in phone_edges + doc_edges:
        edges_by_person[person_of[edge["records"][0]]].append(edge)

    people = []
    for person_id in sorted(clusters):
        people.append(
            _assemble_person(
                person_id,
                clusters[person_id],
                edges_by_person.get(person_id, []),
                customers_by_id,
                accounts_by_customer,
                applicants_by_customer,
                checks_by_applicant,
                notes_by_email,
                parsed_by_id,
                names,
            )
        )

    indexes = _indexes(people)
    multi = sum(1 for person in people if len(person["record_ids"]) > 1)
    stats = {
        "records": len(record_ids),
        "persons": len(people),
        "phone_dob_edges": len(phone_edges),
        "doc_edges": len(doc_edges),
        "doc_edges_new_components": doc_new,
        "multi_record_persons": multi,
        "notes": note_stats,
        "person_flag_counts": _person_flag_counts(people),
    }
    return people, indexes, stats


def run_stage1(data_folder: str, cache_dir: str, use_llm: bool | None = None) -> dict:
    """Load ``data_folder``, write golden artefacts under ``cache_dir``, return stats."""
    started = time.perf_counter()
    tables = DataStore(data_folder).load_stage1()
    people, indexes, stats = build_from_tables(tables, use_llm=use_llm)
    os.makedirs(cache_dir, exist_ok=True)
    _write_jsonl(os.path.join(cache_dir, "person_golden.jsonl"), people)
    _write_json(os.path.join(cache_dir, "index_record_id.json"), indexes["record_id"])
    _write_json(os.path.join(cache_dir, "index_account_id.json"), indexes["account_id"])
    _write_json(os.path.join(cache_dir, "index_login_handle.json"), indexes["login_handle"])
    _write_json(os.path.join(cache_dir, "index_email.json"), indexes["email"])
    _write_json(os.path.join(cache_dir, "index_name.json"), indexes["name"])
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    stats["cache_dir"] = cache_dir
    return stats


def _cluster(union, record_ids, customers_by_id, applicants_by_customer, checks_by_applicant):
    phone_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record_id in record_ids:
        row = customers_by_id[record_id]
        phone = norm_phone(row.get("phone"))
        parsed, _flags = parse_date(row.get("dob"))
        if not phone or not parsed or parsed["precision"] != "day":
            continue
        phone_groups[(phone, parsed["value"])].append(record_id)

    phone_edges = []
    for (phone, dob), grouped in sorted(phone_groups.items()):
        unique = sorted(set(grouped))
        if len(unique) < 2:
            continue
        for left, right in combinations(unique, 2):
            phone_edges.append({
                "rule": "PHONE_DOB",
                "phone": phone,
                "dob": dob,
                "records": [left, right],
            })
            union.union(left, right)

    doc_groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for record_id in record_ids:
        for applicant_id in applicants_by_customer.get(record_id, []):
            for check in checks_by_applicant.get(applicant_id, []):
                if check.get("result") != "approved":
                    continue
                document = norm_docno(check.get("document_number"))
                if not document:
                    continue
                doc_groups[document][record_id].append(check.get("check_id") or "")

    doc_edges = []
    doc_new = 0
    for document, by_record in sorted(doc_groups.items()):
        unique = sorted(by_record)
        if len(unique) < 2:
            continue
        for left, right in combinations(unique, 2):
            doc_new += int(union.union(left, right))
            doc_edges.append({
                "rule": "DOC_NO",
                "document_number": document,
                "records": [left, right],
                "checks": sorted(set(by_record[left] + by_record[right])),
            })
    return phone_edges, doc_edges, doc_new


def _assemble_person(
    person_id,
    record_ids,
    edges,
    customers_by_id,
    accounts_by_customer,
    applicants_by_customer,
    checks_by_applicant,
    notes_by_email,
    parsed_by_id,
    names: NameTools,
) -> dict:
    flags: list[str] = []
    records = [customers_by_id[record_id] for record_id in record_ids]
    type_values = sorted({record.get("entity_type") for record in records})
    if len(type_values) == 1 and type_values[0] is not None:
        entity_type = {"value": type_values[0], "source_id": record_ids[0]}
        agreed_type = type_values[0]
    else:
        entity_type = {"value": None, "source_id": None}
        agreed_type = None
        flags.append("TYPE_CONFLICT")

    account_ids = []
    login_handles = []
    for record_id in record_ids:
        for account in accounts_by_customer.get(record_id, []):
            if account.get("account_id"):
                account_ids.append(account["account_id"])
            if account.get("login_handle"):
                login_handles.append(account["login_handle"])
    account_ids = sorted(set(account_ids))
    login_handles = sorted(set(login_handles))

    applicant_ids: list[str] = []
    for record_id in record_ids:
        applicant_ids.extend(applicants_by_customer.get(record_id, []))
    applicant_ids = sorted(set(applicant_ids))

    checks_ok = []
    checks_ignored = []
    for applicant_id in applicant_ids:
        for check in checks_by_applicant.get(applicant_id, []):
            if check.get("result") == "approved":
                checks_ok.append(check)
            else:
                checks_ignored.append(check)
    checks_ok.sort(key=lambda item: item.get("check_id") or "")
    checks_ignored.sort(key=lambda item: item.get("check_id") or "")

    emails = sorted({email for email in (norm_email(record.get("email")) for record in records) if email})
    phones = sorted({phone for phone in (norm_phone(record.get("phone")) for record in records) if phone})
    registration_numbers = sorted({
        str(record.get("registration_number")).strip()
        for record in records
        if record.get("registration_number")
    })

    attached_notes = []
    seen_notes = set()
    for email in emails:
        for note in notes_by_email.get(email, []):
            if note["note_id"] not in seen_notes:
                seen_notes.add(note["note_id"])
                attached_notes.append(note)
    attached_notes.sort(key=lambda note: note["note_id"])

    verification_events = [_check_event(check, flags) for check in checks_ok]
    residence_events = []
    note_countries = []
    for note in attached_notes:
        parsed = parsed_by_id.get(note["note_id"])
        if parsed is None:
            parsed = parse_note(note)
        if parsed["flags"]:
            flags.append(f"NOTE_FLAGGED:{note['note_id']}")
            flags.append("BLOCK_LOCATION_MISMATCH")
        if parsed.get("verification_like") and not parsed.get("fully_parsed_verification"):
            flags.append("BLOCK_DOB_AGE_NAME_CLEAR")
        if parsed.get("kind") != "noise" and parsed.get("location_unresolved"):
            flags.append("BLOCK_LOCATION_MISMATCH")
        for canonical in parsed.get("countries") or []:
            note_countries.append((canonical, note["note_id"]))
        if parsed["kind"] == "verification":
            verification_events.append(parsed["event"])
        elif parsed["kind"] == "residence":
            residence_events.append(parsed["event"])

    verification_events.sort(key=lambda event: (event.get("date") or "", _kind_rank(event), event.get("source_id") or ""))
    residence_events.sort(key=lambda event: event.get("note_id") or "")
    primary = max(verification_events, key=_primary_sort) if verification_events else None
    if len(verification_events) >= 2 and _events_conflict(verification_events, names, agreed_type):
        flags.append("MULTI_VERIFICATION_CONFLICT")

    legal_name = _legal_name(primary, records, record_ids, names, agreed_type, flags)
    dob = _dob(primary, records, record_ids, flags)
    incorporation = _incorporation(agreed_type, checks_ok, records, record_ids, flags)
    countries = _countries(
        record_ids, records, checks_ok, verification_events, residence_events, note_countries, flags
    )
    declared = _declared_dobs(records, record_ids, flags)
    names_all = _names_all(legal_name, records, record_ids, names, flags)

    edges = sorted(edges, key=lambda edge: (
        edge.get("rule") or "",
        tuple(edge.get("records") or []),
        edge.get("phone") or edge.get("document_number") or "",
    ))
    if "UNMAPPED_COUNTRY" in flags:
        flags.append("BLOCK_LOCATION_MISMATCH")
    flag_list = sorted(set(flags))
    customer_record_ids = list(record_ids)
    return {
        "person_id": person_id,
        "record_ids": customer_record_ids,
        "customer_record_ids": customer_record_ids,
        "cluster_edges": edges,
        "entity_type": entity_type,
        "legal_name": legal_name,
        "dob": dob,
        "declared_dobs": declared,
        "incorporation_date": incorporation,
        "countries": countries,
        "names_all": names_all,
        "verification_events": verification_events,
        "ignored_checks": [
            {"check_id": check.get("check_id"), "result": check.get("result"), "reason": "not approved"}
            for check in checks_ignored
        ],
        "registration_numbers": registration_numbers,
        "emails": emails,
        "phones": phones,
        "account_ids": account_ids,
        "login_handles": login_handles,
        "applicant_ids": applicant_ids,
        "check_ids_ok": [check.get("check_id") for check in checks_ok],
        "check_ids_ignored": [check.get("check_id") for check in checks_ignored],
        "note_ids_verification": [
            event["source_id"] for event in verification_events if event.get("kind") == "kyc_note"
        ],
        "note_ids_residence": [event["note_id"] for event in residence_events],
        "flags": flag_list,
        "contracts": _contracts(customer_record_ids, flag_list),
    }


def _check_event(check: dict, flags: list[str]) -> dict:
    parsed, date_flags = parse_date(check.get("verified_dob"))
    if "UNPARSED_DATE" in date_flags:
        flags.append("UNPARSED_DATE")
    country, country_flags = norm_country(check.get("document_country"))
    if "UNMAPPED_COUNTRY" in country_flags:
        flags.append("UNMAPPED_COUNTRY")
    checked, checked_flags = parse_date(check.get("checked_at"))
    if "UNPARSED_DATE" in checked_flags:
        flags.append("UNPARSED_DATE")
    return {
        "source_id": check.get("check_id"),
        "kind": "kyc_check",
        "date": checked["value"] if checked else (str(check.get("checked_at")).strip() if check.get("checked_at") else ""),
        "name": check.get("verified_name") or None,
        "dob": parsed["value"] if parsed else None,
        "dob_precision": parsed["precision"] if parsed else None,
        "doc_country": country,
        "document_type": check.get("document_type"),
        "provider": check.get("provider"),
        "method": "regex",
        "may_solely_support_different_entity": True,
    }


def _kind_rank(event: dict) -> int:
    return 0 if event.get("kind") == "kyc_check" else 1


def _primary_sort(event: dict):
    """Latest date, then a KYC check over a note, then the smallest source id."""
    return (
        event.get("date") or "",
        1 if event.get("kind") == "kyc_check" else 0,
        tuple(-ord(ch) for ch in (event.get("source_id") or "")),
    )


def _events_conflict(events: list[dict], names: NameTools, entity_type: str | None) -> bool:
    for index, left in enumerate(events):
        for right in events[index + 1:]:
            if left.get("name") and right.get("name"):
                agreed = names.names_agree(left["name"], right["name"], entity_type, entity_type)
                if not agreed["agree"]:
                    return True
            if left.get("dob") and right.get("dob"):
                left_dob, _left_flags = parse_date(left["dob"])
                right_dob, _right_flags = parse_date(right["dob"])
                if not dates_compatible(left_dob, right_dob):
                    return True
    return False


def _name_type(agreed_type: str | None, record: dict | None) -> str | None:
    if agreed_type:
        return agreed_type
    if record is not None:
        return record.get("entity_type")
    return "Individual"


def _legal_name(primary, records, record_ids, names: NameTools, agreed_type, flags: list[str]) -> dict:
    verified = False
    source_kind = "record"
    source_id = None
    raw = None
    record_for_type = records[0] if records else None
    if primary and primary.get("name"):
        raw = primary["name"]
        source_id = primary.get("source_id")
        source_kind = "kyc_check" if primary.get("kind") == "kyc_check" else "kyc_note"
        verified = True
    else:
        for record in records:
            if record.get("full_name"):
                raw = record["full_name"]
                source_id = record["record_id"]
                record_for_type = record
                break
        flags.append("UNVERIFIED")
        flags.append("BLOCK_NAME_MISMATCH_VERIFIED")
    parts, had_placeholder = names.split(raw, _name_type(agreed_type, record_for_type))
    if had_placeholder:
        flags.append("PLACEHOLDER_NAME")
    individual = (agreed_type or (record_for_type or {}).get("entity_type")) == "Individual"
    blocks_name_clear = bool(individual and len(parts) < 2)
    placeholder_only = bool(had_placeholder and len(parts) == 0) or blocks_name_clear and had_placeholder and len(parts) < 2
    if blocks_name_clear or placeholder_only:
        flags.append("NAME_TOO_SHORT")
        flags.append("BLOCK_NAME_CLEAR")
    method = "record"
    may_clear = False
    if verified and primary is not None:
        method = primary.get("method") or "regex"
        may_clear = method != "llm" and not blocks_name_clear
        if method == "llm":
            flags.append("BLOCK_NAME_MISMATCH_VERIFIED")
    return {
        "value": raw,
        "parts": parts,
        "real_part_count": len(parts),
        "blocks_name_clear": blocks_name_clear or placeholder_only,
        "source_id": source_id,
        "source_kind": source_kind,
        "verified": verified,
        "method": method,
        "may_solely_support_different_entity": may_clear,
    }


def _dob(primary, records, record_ids, flags: list[str]) -> dict:
    if primary and primary.get("dob"):
        method = primary.get("method") or "regex"
        return {
            "value": primary["dob"],
            "precision": primary.get("dob_precision"),
            "source_id": primary.get("source_id"),
            "verified": True,
            "method": method,
            "may_solely_support_different_entity": method != "llm",
        }
    chosen = _agreed_declared(records, flags)
    flags.append("UNVERIFIED")
    if chosen is None:
        return {
            "value": None, "precision": None, "source_id": None, "verified": False,
            "method": "record", "may_solely_support_different_entity": False,
        }
    parsed, source_id = chosen
    return {
        "value": parsed["value"],
        "precision": parsed["precision"],
        "source_id": source_id,
        "verified": False,
        "method": "record",
        "may_solely_support_different_entity": False,
    }


def _agreed_declared(records, flags: list[str]):
    parsed_rows = []
    for record in records:
        parsed, date_flags = parse_date(record.get("dob"))
        if "UNPARSED_DATE" in date_flags:
            flags.append("UNPARSED_DATE")
        if parsed:
            parsed_rows.append((parsed, record["record_id"]))
    if not parsed_rows:
        return None
    anchor = parsed_rows[0][0]
    if any(not dates_compatible(anchor, parsed) for parsed, _source in parsed_rows):
        return None
    parsed_rows.sort(key=lambda item: (-_PRECISION_RANK[item[0]["precision"]], item[1]))
    return parsed_rows[0]


def _incorporation(agreed_type, checks_ok, records, record_ids, flags: list[str]):
    if agreed_type != "Company":
        return None
    registry = []
    for check in checks_ok:
        if (check.get("document_type") or "").lower() != "registry extract":
            continue
        parsed, date_flags = parse_date(check.get("verified_dob"))
        if "UNPARSED_DATE" in date_flags:
            flags.append("UNPARSED_DATE")
        if parsed:
            registry.append((check, parsed))
    if registry:
        check, parsed = max(registry, key=lambda item: (
            item[0].get("checked_at") or "",
            tuple(-ord(ch) for ch in (item[0].get("check_id") or "")),
        ))
        return {
            "value": parsed["value"],
            "precision": parsed["precision"],
            "source_id": check.get("check_id"),
            "verified": True,
        }
    chosen = _agreed_declared(records, flags)
    if chosen is None:
        return {
            "value": None, "precision": None, "source_id": None, "verified": False,
            "method": "record", "may_solely_support_different_entity": False,
        }
    parsed, source_id = chosen
    return {
        "value": parsed["value"],
        "precision": parsed["precision"],
        "source_id": source_id,
        "verified": False,
        "method": "record",
        "may_solely_support_different_entity": False,
    }


def _countries(record_ids, records, checks_ok, verification_events, residence_events, note_countries, flags: list[str]):
    countries = []
    for record in records:
        for field, kind in (("nationality", "nationality"), ("residence_country", "residence")):
            value, country_flags = norm_country(record.get(field))
            if "UNMAPPED_COUNTRY" in country_flags:
                flags.append("UNMAPPED_COUNTRY")
            if value:
                countries.append({"kind": kind, "source_id": record["record_id"], "value": value})
    for check in checks_ok:
        value, country_flags = norm_country(check.get("document_country"))
        if "UNMAPPED_COUNTRY" in country_flags:
            flags.append("UNMAPPED_COUNTRY")
        if value:
            countries.append({"kind": "doc_country", "source_id": check.get("check_id"), "value": value})
    for event in verification_events:
        if event.get("kind") != "kyc_note" or not event.get("doc_country"):
            continue
        value, country_flags = norm_country(event["doc_country"])
        if "UNMAPPED_COUNTRY" in country_flags:
            flags.append("UNMAPPED_COUNTRY")
        if value:
            countries.append({"kind": "doc_country", "source_id": event.get("source_id"), "value": value})
    for event in residence_events:
        value, country_flags = norm_country(event.get("country"))
        if "UNMAPPED_COUNTRY" in country_flags:
            flags.append("UNMAPPED_COUNTRY")
        if value:
            countries.append({
                "kind": "residence_note",
                "source_id": event.get("note_id"),
                "value": value,
                "years": [event["year_from"], event["year_to"]],
            })
    seen = {(item["source_id"], item["value"]) for item in countries}
    for canonical, source_id in note_countries:
        value, country_flags = norm_country(canonical)
        if "UNMAPPED_COUNTRY" in country_flags:
            flags.append("UNMAPPED_COUNTRY")
            flags.append("BLOCK_LOCATION_MISMATCH")
        if not value or (source_id, value) in seen:
            continue
        countries.append({"kind": "note_country", "source_id": source_id, "value": value})
        seen.add((source_id, value))
    return countries


def _declared_dobs(records, record_ids, flags: list[str]):
    """Every record keeps its declared date, including ones that cannot be compared.

    Later stages may emit DOB_MISMATCH only when every entry contradicts the hit.
    A missing or unparsed entry blocks that clear.
    """
    declared = []
    for record in records:
        parsed, date_flags = parse_date(record.get("dob"))
        if "UNPARSED_DATE" in date_flags:
            flags.append("UNPARSED_DATE")
        declared.append({
            "comparable": parsed is not None,
            "precision": parsed["precision"] if parsed else None,
            "source_id": record["record_id"],
            "value": parsed["value"] if parsed else None,
        })
    return declared


def _names_all(legal_name, records, record_ids, names: NameTools, flags: list[str]):
    rows = []
    if legal_name.get("value"):
        rows.append({
            "blocks_name_clear": bool(legal_name.get("blocks_name_clear")),
            "kind": "legal_name",
            "parts": list(legal_name["parts"]),
            "real_part_count": legal_name.get("real_part_count", len(legal_name["parts"])),
            "source_id": legal_name.get("source_id"),
            "value": legal_name["value"],
        })
    for record in records:
        for field, kind in (("full_name", "full_name"), ("preferred_name", "preferred_name"), ("login_name", "login_name")):
            raw = record.get(field)
            if not raw:
                continue
            parts, had_placeholder = names.split(raw, record.get("entity_type"))
            if had_placeholder:
                flags.append("PLACEHOLDER_NAME")
            individual = record.get("entity_type") != "Company"
            blocks = bool(individual and len(parts) < 2)
            rows.append({
                "blocks_name_clear": blocks,
                "kind": kind,
                "parts": parts,
                "real_part_count": len(parts),
                "source_id": record["record_id"],
                "value": raw,
            })
    return rows


def _person_flag_counts(people: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for person in people:
        seen = set()
        for flag in person.get("flags") or []:
            key = "NOTE_FLAGGED" if str(flag).startswith("NOTE_FLAGGED:") else flag
            if key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _contracts(customer_record_ids: list[str], flags: list[str]) -> dict:
    """Machine-readable rules for the decision stage. Do not emit ``person_id``."""
    present = set(flags)
    return {
        "block_dob_age_name_clear": "BLOCK_DOB_AGE_NAME_CLEAR" in present,
        "block_location_mismatch": "BLOCK_LOCATION_MISMATCH" in present or "UNMAPPED_COUNTRY" in present,
        "block_name_clear": "BLOCK_NAME_CLEAR" in present or "NAME_TOO_SHORT" in present,
        "block_name_mismatch_verified": "BLOCK_NAME_MISMATCH_VERIFIED" in present or "NAME_TOO_SHORT" in present,
        "customer_record_ids": list(customer_record_ids),
        "dob_mismatch_only_if_every_declared_contradicts": True,
        "emit_customer_record_id_not_person_id": True,
        "llm_method_cannot_solely_support_different_entity": True,
    }


def _indexes(people: list[dict]) -> dict:
    record_index = {}
    account_index = defaultdict(set)
    login_index = defaultdict(set)
    email_index = defaultdict(set)
    by_part = defaultdict(set)
    by_name = defaultdict(set)
    for person in people:
        person_id = person["person_id"]
        for record_id in person["record_ids"]:
            record_index[record_id] = person_id
        for account_id in person["account_ids"]:
            account_index[account_id].add(person_id)
        for handle in person["login_handles"]:
            login_index[handle].add(person_id)
        for email in person["emails"]:
            email_index[email].add(person_id)
        for entry in person["names_all"]:
            parts = entry.get("parts") or []
            if parts:
                by_name["|".join(sorted(parts))].add(person_id)
            for part in parts:
                by_part[part].add(person_id)
    return {
        "record_id": record_index,
        "account_id": {key: sorted(account_index[key]) for key in sorted(account_index)},
        "login_handle": {key: sorted(login_index[key]) for key in sorted(login_index)},
        "email": {key: sorted(email_index[key]) for key in sorted(email_index)},
        "name": {
            "by_name_key": {key: sorted(by_name[key]) for key in sorted(by_name)},
            "by_part": {key: sorted(by_part[key]) for key in sorted(by_part)},
        },
    }


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            handle.write("\n")
