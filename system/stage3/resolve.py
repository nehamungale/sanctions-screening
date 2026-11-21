"""Resolve one screening alert to the Stage 1 person it is about.

Links are followed when they hit a record. A joint account is narrowed with the
same name, date, country and city filters as a search, and only on its holders.
A link that hits nothing falls back to name search and is flagged
``DANGLING_LINK``. A link that contradicts the screened name or date of birth
is still followed and flagged ``link_contradicts_screened``. The resolution is
not clean, and Stage 4 must not clear it.

Name search uses each record's full, preferred and login name. The verified
legal name is not on the record view and is not consulted. A record with no
date of birth, or no city, is kept: unknown is not a mismatch.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass

from stage1.countries import norm_country
from stage1.normalise import dates_compatible, norm_email, parse_date
from stage1.normalise_text import norm_text
from stage3.names import agree_symmetric

_FLAG_ORDER = (
    "DANGLING_LINK",
    "RECORD_DOB_MISSING_KEPT",
    "NAME_TOO_SHORT",
)
_FRAGILITY = (
    "candidate_kept_on_missing_field",
    "dob_partial_only",
    "joint_account_tiebreak",
    "link_contradicts_screened",
    "name_match_fuzzy_only",
    "resolved_via_note_country",
)
_RESOLUTION_METHOD = {
    "LINK_ACCOUNT": "link_account",
    "LINK_ACCOUNT_JOINT": "link_account",
    "LINK_EMAIL": "link_email",
    "LINK_LOGIN": "link_login",
    "NAME_SEARCH": "name_search",
}
_SELECTION_FILTERS = ("name", "dob", "country", "city")
_FILTER_LABELS = (
    ("F0_type", "type"),
    ("F1_name", "name"),
    ("F2_dob", "dob"),
    ("F3_country", "country"),
    ("F4_city", "city"),
)
@dataclass
class Screened:
    """Alert customer block after Stage 1 normalisation."""

    name: str | None
    parts: tuple[str, ...]
    name_given: bool
    entity_type: str | None
    dob: dict | None
    dob_unparsed: bool
    country: str | None
    country_skipped: bool
    city: str | None
    city_norm: str | None

    def to_dict(self) -> dict:
        dob = None
        if self.dob is not None:
            dob = {"precision": self.dob["precision"], "value": self.dob["value"]}
        return {
            "city": self.city,
            "country": self.country,
            "dob": dob,
            "entity_type": self.entity_type,
            "name": self.name,
            "parts": list(self.parts),
        }


def normalise_screened(customer: dict, names) -> Screened:
    """Parse the alert's screened customer with the Stage 1 normalisers."""
    raw_name = customer.get("name")
    name_given = isinstance(raw_name, str) and bool(raw_name.strip())
    name = raw_name.strip() if name_given else None
    entity = customer.get("entity_type")
    if isinstance(entity, str) and entity.strip():
        entity_type = entity.strip()
    else:
        entity_type = None
    parts, _placeholder = names.split(name, entity_type) if name_given else ([], False)
    parsed, date_flags = parse_date(customer.get("dob"), mode="customer")
    raw_country = customer.get("country")
    country, _country_flags = norm_country(raw_country)
    country_present = isinstance(raw_country, str) and bool(raw_country.strip())
    raw_city = customer.get("city")
    if isinstance(raw_city, str) and raw_city.strip():
        city = raw_city.strip()
        city_norm = norm_text(city) or None
    else:
        city = None
        city_norm = None
    return Screened(
        name=name,
        parts=tuple(parts),
        name_given=name_given,
        entity_type=entity_type,
        dob=parsed,
        dob_unparsed=parsed is None and "UNPARSED_DATE" in date_flags,
        country=country,
        country_skipped=country_present and country is None,
        city=city,
        city_norm=city_norm,
    )


def resolve_alerts(alerts: list[dict], catalog) -> list[dict]:
    """Resolve every alert. Output order is ``alert_id``, independent of input order."""
    resolver = Resolver(catalog)
    ordered = sorted(alerts, key=lambda item: str(item.get("alert_id") or ""))
    return [resolver.resolve(alert) for alert in ordered]


def summarise(rows: list[dict]) -> dict:
    """Counts for a resolution file. Elapsed time is not included."""
    status = Counter(row["status"] for row in rows)
    method = Counter(row["method"] for row in rows)
    flags = Counter(flag for row in rows for flag in row["flags"])
    resolution_status = Counter(row["resolution_status"] for row in rows)
    resolution_method = Counter(row["resolution_method"] for row in rows)
    resolution_quality = Counter(row["resolution_quality"] for row in rows)
    fragility = Counter(flag for row in rows for flag in row["fragility_flags"])
    joint = [row for row in rows if row["method"] == "LINK_ACCOUNT_JOINT"]
    linked = [row for row in rows if row["method"] != "NAME_SEARCH"]
    unlinked = [
        row for row in rows
        if row["method"] == "NAME_SEARCH" and "DANGLING_LINK" not in row["flags"]
    ]
    unlinked_status = Counter(row["status"] for row in unlinked)
    return {
        "alerts": len(rows),
        "flags": {key: flags[key] for key in sorted(flags)},
        "fragility_flags": {key: fragility[key] for key in sorted(fragility)},
        "joint_alerts": len(joint),
        "joint_resolved": sum(
            row["status"] == "RESOLVED" and len(row["chosen_person_ids"]) == 1 for row in joint
        ),
        "linked_alerts": len(linked),
        "method": {key: method[key] for key in sorted(method)},
        "resolution_clean": sum(1 for row in rows if row["resolution_clean"]),
        "resolution_method": {key: resolution_method[key] for key in sorted(resolution_method)},
        "resolution_quality": {key: resolution_quality[key] for key in sorted(resolution_quality)},
        "resolution_status": {key: resolution_status[key] for key in sorted(resolution_status)},
        "status": {key: status[key] for key in sorted(status)},
        "unlinked_alerts": len(unlinked),
        "unlinked_status": {key: unlinked_status[key] for key in sorted(unlinked_status)},
    }


def label_matches(row: dict, expected_record_ids: list[str]) -> tuple[bool, str]:
    """Whether one practice label's customer resolution matches this alert.

    ``["AMBIGUOUS"]`` matches status AMBIGUOUS. Any other list must be exactly
    the resolved person's record ids, and ``customer_record_id`` one of them.
    """
    expected = list(expected_record_ids)
    if expected == ["AMBIGUOUS"]:
        if row["status"] != "AMBIGUOUS" or row["customer_record_id"] != "AMBIGUOUS":
            return False, f"expected AMBIGUOUS, got {row['status']} {row['customer_record_id']!r}"
        if not row["candidates"] or not row["chosen_person_ids"]:
            return False, "ambiguous alert dropped its candidates"
        return True, ""
    if row["status"] != "RESOLVED":
        return False, f"status {row['status']}"
    record_id = row["customer_record_id"]
    if not isinstance(record_id, str) or record_id.startswith("P-"):
        return False, f"customer_record_id {record_id!r}"
    chosen = row["chosen_person_ids"]
    if len(chosen) != 1:
        return False, f"chosen {chosen}"
    candidate = next((item for item in row["candidates"] if item["person_id"] == chosen[0]), None)
    if candidate is None:
        return False, "missing candidate"
    if set(candidate["record_ids"]) != set(expected):
        return False, f"records {candidate['record_ids']} != {sorted(expected)}"
    if record_id not in set(expected):
        return False, f"customer_record_id {record_id} not in {sorted(expected)}"
    return True, ""


def dumps_jsonl(rows: list[dict]) -> str:
    """Canonical file body. Two calls on the same rows are byte-identical."""
    return "".join(dump_line(row) + "\n" for row in rows)


def dump_line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Resolver:
    def __init__(self, catalog):
        self.catalog = catalog
        self._agree_cache: dict[tuple, tuple] = {}

    def resolve(self, alert: dict) -> dict:
        alert_id = alert.get("alert_id")
        if not isinstance(alert_id, str) or not alert_id:
            raise ValueError("alert missing alert_id")
        customer = alert.get("customer") if isinstance(alert.get("customer"), dict) else {}
        screened = normalise_screened(customer, self.catalog.names)
        flags: set[str] = set()
        if screened.name_given and screened.entity_type != "Company" and len(screened.parts) < 2:
            flags.add("NAME_TOO_SHORT")
        link = _extract_link(alert)
        if link is None:
            return self._search(alert_id, screened, flags, dangling=None)
        kind, value, method = link
        known = [record_id for record_id in self._lookup(kind, value) if record_id in self.catalog.prepared]
        if not known:
            flags.add("DANGLING_LINK")
            return self._search(alert_id, screened, flags, dangling=(kind, value))
        persons = sorted({self.catalog.prepared[record_id].person_id for record_id in known})
        if len(persons) == 1:
            return self._close(
                alert_id,
                screened,
                flags,
                method,
                survivors=sorted(known),
                counts={},
                prefix=_link_prefix(kind, value, known, 1, screened),
                holders=None,
                link=(kind, value),
                joint=False,
                detail_checks=[],
                examined=[],
                reason=None,
            )
        joint_method = "LINK_ACCOUNT_JOINT" if method == "LINK_ACCOUNT" else method
        return self._pick(alert_id, screened, flags, joint_method, kind, value, sorted(known))

    def _search(self, alert_id: str, screened: Screened, flags: set[str], dangling) -> dict:
        checks = _applicable(screened, joint=False)
        counts: dict[str, int] = {}
        if dangling is None:
            prefix = ["no link"]
        else:
            prefix = [f"dangling {dangling[0]} {dangling[1]} -> name search"]
        prefix.extend(_screened_notes(screened))
        if screened.name_given and not screened.parts:
            prefix.append("screened name has no real parts")
        if "type" in checks:
            pool = self.catalog.by_type.get(screened.entity_type, ())
            pool_set = self.catalog.type_sets.get(screened.entity_type, set())
            counts["F0_type"] = len(pool)
        else:
            pool = self.catalog.all_ids
            pool_set = None
        if "name" in checks:
            matched = []
            for record_id in self.catalog.blocking.candidates(screened.parts):
                if pool_set is not None and record_id not in pool_set:
                    continue
                prepared = self.catalog.prepared.get(record_id)
                if prepared is None:
                    continue
                if self._name_ok(prepared, screened):
                    matched.append(record_id)
            survivors = sorted(matched)
            counts["F1_name"] = len(survivors)
        else:
            survivors = list(pool)
        examined = list(survivors) if "name" in checks else []
        survivors = self._apply_attribute_filters(survivors, screened, checks, counts)
        self._flag_missing_dob(flags, counts, survivors)
        return self._close(
            alert_id,
            screened,
            flags,
            "NAME_SEARCH",
            survivors,
            counts,
            prefix,
            holders=None,
            link=None,
            joint=False,
            detail_checks=[check for check in checks if check != "type"],
            examined=examined,
            reason="dangling_link" if dangling else None,
        )

    def _pick(self, alert_id, screened, flags, method, kind, value, holders: list[str]) -> dict:
        checks = _applicable(screened, joint=True)
        counts: dict[str, int] = {}
        persons_before = len({self.catalog.prepared[record_id].person_id for record_id in holders})
        prefix = _link_prefix(kind, value, holders, persons_before, screened)
        survivors = list(holders)
        if "name" in checks:
            survivors = [
                record_id
                for record_id in survivors
                if self._name_ok(self.catalog.prepared[record_id], screened)
            ]
            counts["F1_name"] = len(survivors)
        survivors = self._apply_attribute_filters(survivors, screened, checks, counts)
        self._flag_missing_dob(flags, counts, survivors)
        return self._close(
            alert_id,
            screened,
            flags,
            method,
            survivors,
            counts,
            prefix,
            holders=holders,
            link=(kind, value),
            joint=True,
            detail_checks=checks,
            examined=list(holders),
            reason=None,
        )

    def _apply_attribute_filters(self, survivors, screened, checks, counts) -> list[str]:
        for check, key in (("dob", "F2_dob"), ("country", "F3_country"), ("city", "F4_city")):
            if check not in checks:
                continue
            survivors = [
                record_id
                for record_id in survivors
                if self._attribute_ok(self.catalog.prepared[record_id], screened, check)
            ]
            counts[key] = len(survivors)
        return survivors

    def _close(
        self,
        alert_id,
        screened,
        flags,
        method,
        survivors,
        counts,
        prefix,
        holders,
        link,
        joint,
        detail_checks,
        examined,
        reason,
    ) -> dict:
        by_person: dict[str, list[str]] = defaultdict(list)
        for record_id in survivors:
            by_person[self.catalog.prepared[record_id].person_id].append(record_id)
        person_ids = sorted(by_person)
        selection = joint or method == "NAME_SEARCH"
        candidates = []
        for person_id in person_ids:
            matched = sorted(by_person[person_id])
            matched_rows = [self.catalog.prepared[record_id] for record_id in matched]
            _ok, why = self._explain(matched_rows[0], screened, detail_checks)
            if link is not None:
                why["link"] = {"type": link[0], "value": link[1]}
            candidates.append({
                "filters": _candidate_filters(
                    matched_rows, screened, detail_checks, selection, self._agreeing_pairs
                ),
                "fragility_flags": _candidate_fragility(
                    matched_rows, screened, detail_checks, selection, self._agreeing_pairs
                ),
                "matched_records": matched,
                "person_id": person_id,
                "record_ids": list(self.catalog.by_person[person_id]),
                "why": why,
            })
        person_count = len(person_ids)
        if person_count == 0:
            status = "UNRESOLVED_LINK" if holders is not None else "NOT_FOUND"
            chosen: list[str] = []
            customer_record_id = None
        elif person_count == 1:
            status = "RESOLVED"
            chosen = person_ids
            customer_record_id = sorted(by_person[person_ids[0]])[0]
        else:
            status = "AMBIGUOUS"
            chosen = person_ids
            customer_record_id = "AMBIGUOUS"
        rejected = []
        if holders is not None:
            kept = set(survivors)
            for record_id in holders:
                if record_id in kept:
                    continue
                _ok, why = self._explain(self.catalog.prepared[record_id], screened, detail_checks)
                rejected.append({
                    "person_id": self.catalog.prepared[record_id].person_id,
                    "record_id": record_id,
                    "why": why,
                })
        trace = list(prefix)
        bits = [f"{label} {counts[key]}" for key, label in _FILTER_LABELS if key in counts]
        if joint:
            trace.append("joint pick: " + (" -> ".join(bits) if bits else "no screened filters"))
        elif method == "NAME_SEARCH":
            trace.append("name search: " + (" -> ".join(bits) if bits else "no filters"))
        contradicts = False
        if link is not None and status == "RESOLVED":
            sanity, contradicts = self._sanity_line(chosen[0], screened)
            trace.append(sanity)
        if contradicts:
            for candidate in candidates:
                candidate["fragility_flags"] = sorted(
                    set(candidate["fragility_flags"]) | {"link_contradicts_screened"}
                )
        if joint and status == "RESOLVED":
            for candidate in candidates:
                candidate["fragility_flags"] = sorted(
                    set(candidate["fragility_flags"]) | {"joint_account_tiebreak"}
                )
        fragility: set[str] = set()
        for candidate in candidates:
            fragility.update(candidate["fragility_flags"])
        trace.append(
            f"{_phrase(len(survivors), 'record')} -> {_phrase(person_count, 'person')} -> {status}"
        )
        if status == "RESOLVED":
            resolution_status = "resolved_single"
        elif status == "AMBIGUOUS":
            resolution_status = "ambiguous"
        else:
            resolution_status = "not_found"
        resolution_reason = reason
        if status == "UNRESOLVED_LINK":
            resolution_reason = "unresolved_joint_link"
        evidence, considered = _evidence_ids(
            link, survivors, examined, holders, person_ids, self.catalog.by_person, person_count
        )
        return {
            "alert_id": alert_id,
            "candidates": candidates,
            "chosen_person_ids": chosen,
            "considered_ids": considered,
            "customer_record_id": customer_record_id,
            "evidence_ids": evidence,
            "filter_counts": counts,
            "flags": [flag for flag in _FLAG_ORDER if flag in flags],
            "fragility_flags": [flag for flag in _FRAGILITY if flag in fragility],
            "method": method,
            "rejected_holders": rejected,
            "resolution_clean": resolution_status == "resolved_single" and not fragility,
            "resolution_method": _RESOLUTION_METHOD[method],
            "resolution_quality": _resolution_quality(
                method, status, resolution_reason, fragility, joint
            ),
            "resolution_reason": resolution_reason,
            "resolution_status": resolution_status,
            "screened": screened.to_dict(),
            "status": status,
            "trace": trace,
        }

    def _sanity_line(self, person_id: str, screened: Screened) -> tuple[str, bool]:
        reasons = self._contradicts(person_id, screened)
        checked = []
        if screened.parts:
            checked.append("name")
        if screened.dob is not None:
            checked.append("dob")
        if reasons:
            return (
                "link sanity: linked person contradicts screened "
                + " and ".join(reasons)
                + " -> link_contradicts_screened",
                True,
            )
        if not checked:
            return "link sanity: no screened name or dob to compare", False
        return "link sanity: screened " + " and ".join(checked) + " do not contradict", False

    def _contradicts(self, person_id: str, screened: Screened) -> list[str]:
        """Name or date of birth that disagrees with every record of the person."""
        records = [self.catalog.prepared[record_id] for record_id in self.catalog.by_person[person_id]]
        reasons = []
        if screened.parts:
            if not any(self._name_ok(prepared, screened) for prepared in records):
                reasons.append("name")
        if screened.dob is not None:
            comparable = [prepared.dob for prepared in records if prepared.dob is not None]
            if comparable and not any(dates_compatible(screened.dob, dob) for dob in comparable):
                reasons.append("dob")
        return reasons

    def _lookup(self, kind: str, value: str) -> tuple[str, ...]:
        if kind == "account":
            return self.catalog.account_index.get(value, ())
        if kind == "login":
            return self.catalog.login_index.get(value, ())
        return self.catalog.email_index.get(value, ())

    def _flag_missing_dob(self, flags: set[str], counts: dict[str, int], survivors: list[str]) -> None:
        if "F2_dob" not in counts:
            return
        for record_id in survivors:
            if self.catalog.prepared[record_id].dob is None:
                flags.add("RECORD_DOB_MISSING_KEPT")
                return

    def _name_ok(self, prepared, screened: Screened) -> bool:
        field, _pairs = self._best_name(prepared, screened)
        return field is not None

    def _best_name(self, prepared, screened: Screened) -> tuple[str | None, tuple[str, ...]]:
        if not screened.parts:
            return None, ()
        for field, parts in prepared.names:
            agree, pairs = self._agree(screened.parts, parts)
            if agree:
                return field, pairs
        return None, ()

    def _agreeing_pairs(self, prepared, screened: Screened) -> tuple[bool, tuple[str, ...]]:
        """Every pair from every record name that agrees. Exact parts count even on a later field."""
        if not screened.parts:
            return False, ()
        collected: list[str] = []
        agreed = False
        for _field, parts in prepared.names:
            agree, pairs = self._agree(screened.parts, parts)
            if agree:
                agreed = True
                collected.extend(pairs)
        return agreed, tuple(collected)

    def _agree(self, left: tuple[str, ...], right: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
        key = (left, right)
        cached = self._agree_cache.get(key)
        if cached is None:
            result = agree_symmetric(self.catalog.names, left, right)
            cached = (bool(result["agree"]), tuple(result["matched_pairs"]))
            self._agree_cache[key] = cached
        return cached

    def _attribute_ok(self, prepared, screened: Screened, check: str) -> bool:
        if check == "dob":
            return _dob_status(prepared, screened) != "incompatible"
        if check == "country":
            if not prepared.countries:
                return True
            return screened.country in prepared.countries
        if check == "city":
            return _city_status(prepared, screened) != "no"
        return True

    def _explain(self, prepared, screened: Screened, checks: list[str]) -> tuple[bool, dict]:
        why: dict = {}
        for check in checks:
            if check == "name":
                field, pairs = self._best_name(prepared, screened)
                if field is None:
                    why["name"] = "no agree"
                    return False, why
                why["name"] = {"field": field, "pairs": list(pairs)}
            elif check == "dob":
                status = _dob_status(prepared, screened)
                if status == "incompatible":
                    why["dob"] = "incompatible"
                    return False, why
                why["dob"] = "record dob missing -> unknown" if status == "missing" else "compatible"
            elif check == "country":
                if not prepared.countries:
                    why["country"] = "record country missing -> unknown"
                elif screened.country not in prepared.countries:
                    why["country"] = "no"
                    return False, why
                else:
                    why["country"] = screened.country
            elif check == "city":
                status = _city_status(prepared, screened)
                if status == "no":
                    why["city"] = "no"
                    return False, why
                why["city"] = "record city missing -> unknown" if status == "missing" else status
        return True, why


def _extract_link(alert: dict) -> tuple[str, str, str] | None:
    """First present link. Account, then login, then email. Dev alerts have only one."""
    account = alert.get("account_ref")
    if isinstance(account, str) and account.strip():
        return ("account", account.strip(), "LINK_ACCOUNT")
    login = alert.get("login_handle")
    if isinstance(login, str) and login.strip():
        return ("login", login.strip().casefold(), "LINK_LOGIN")
    email = norm_email(alert.get("email"))
    if email:
        return ("email", email, "LINK_EMAIL")
    return None


def _applicable(screened: Screened, joint: bool) -> list[str]:
    checks = []
    if not joint and screened.entity_type:
        checks.append("type")
    if screened.name_given:
        checks.append("name")
    if screened.dob is not None:
        checks.append("dob")
    if screened.country:
        checks.append("country")
    if screened.city_norm:
        checks.append("city")
    return checks


def _screened_notes(screened: Screened) -> list[str]:
    notes = []
    if screened.dob_unparsed:
        notes.append("screened dob unparsed, dob filter skipped")
    if screened.country_skipped:
        notes.append("screened country is not a country, country filter skipped")
    return notes


def _link_prefix(kind: str, value: str, records: list[str], persons: int, screened: Screened) -> list[str]:
    line = (
        f"link {kind} {value} -> {_phrase(len(records), 'record')}, {_phrase(persons, 'person')}"
    )
    return [line, *_screened_notes(screened)]


def _dob_status(prepared, screened: Screened) -> str:
    if prepared.dob is None:
        return "missing"
    if dates_compatible(screened.dob, prepared.dob):
        return "compatible"
    return "incompatible"


def _city_status(prepared, screened: Screened) -> str:
    city = screened.city_norm or ""
    if prepared.city_norm and prepared.city_norm == city:
        return "city"
    if prepared.address_norm and city and city in prepared.address_norm:
        return "address"
    if not prepared.city_norm:
        return "missing"
    return "no"


def _resolution_quality(method: str, status: str, reason: str | None, fragility: set[str], joint: bool) -> str:
    """How the alert was resolved. This is not the same thing as ``resolution_clean``."""
    if reason == "dangling_link":
        return "DANGLING_LINK_fallback"
    if "link_contradicts_screened" in fragility:
        return "LINK_SUSPECT"
    if joint and status == "RESOLVED":
        return "joint_account_pick"
    if status == "AMBIGUOUS":
        return "ambiguous"
    if status in ("NOT_FOUND", "UNRESOLVED_LINK"):
        return "not_found"
    if method == "NAME_SEARCH":
        return "unique_search_match"
    return "clean_link"


def _phrase(count: int, word: str) -> str:
    if count == 1:
        return f"1 {word}"
    return f"{count} {word}s"


def _alert_has(screened: Screened, filt: str) -> bool:
    if filt == "name":
        return bool(screened.parts)
    if filt == "dob":
        return screened.dob is not None
    if filt == "country":
        return bool(screened.country)
    if filt == "city":
        return bool(screened.city_norm)
    return False


def _candidate_filters(rows: list, screened: Screened, checks: list[str], selection: bool, best_name) -> dict:
    """Applied, positively passed, and skipped-because-missing filters for one person."""
    applied = []
    passed = []
    skipped = []
    check_set = set(checks)
    for filt in _SELECTION_FILTERS:
        if not _alert_has(screened, filt):
            if selection:
                skipped.append({"filter": filt, "side": "alert"})
            continue
        if filt not in check_set:
            continue
        applied.append(filt)
        if _filter_passed(rows, screened, filt, best_name):
            passed.append(filt)
        elif _filter_missing_on_every_record(rows, screened, filt):
            skipped.append({"filter": filt, "side": "record"})
    return {"applied": applied, "passed": passed, "skipped_missing": skipped}


def _filter_passed(rows: list, screened: Screened, filt: str, agreeing_pairs) -> bool:
    if filt == "name":
        return any(agreeing_pairs(row, screened)[0] for row in rows)
    if filt == "dob":
        return any(
            row.dob is not None and dates_compatible(screened.dob, row.dob) for row in rows
        )
    if filt == "country":
        return any(screened.country in row.countries for row in rows)
    if filt == "city":
        return any(_city_status(row, screened) in ("city", "address") for row in rows)
    return False


def _filter_missing_on_every_record(rows: list, screened: Screened, filt: str) -> bool:
    if not rows:
        return False
    if filt == "dob":
        return all(row.dob is None for row in rows)
    if filt == "country":
        return all(not row.countries for row in rows)
    if filt == "city":
        return all(_city_status(row, screened) == "missing" for row in rows)
    return False


def _candidate_fragility(rows: list, screened: Screened, checks: list[str], selection: bool, best_name) -> list[str]:
    flags: set[str] = set()
    filters = _candidate_filters(rows, screened, checks, selection, best_name)
    if filters["skipped_missing"]:
        flags.add("candidate_kept_on_missing_field")
    if "name" in filters["passed"] and _fuzzy_only(rows, screened, best_name):
        flags.add("name_match_fuzzy_only")
    if "dob" in filters["passed"] and _dob_partial_only(rows, screened):
        flags.add("dob_partial_only")
    if "country" in filters["passed"] and _note_country_only(rows, screened):
        flags.add("resolved_via_note_country")
    return [flag for flag in _FRAGILITY if flag in flags]


def _fuzzy_only(rows: list, screened: Screened, agreeing_pairs) -> bool:
    """True when agreement used no identical normalised parts."""
    any_exact = False
    any_agree = False
    for row in rows:
        agreed, pairs = agreeing_pairs(row, screened)
        if not agreed:
            continue
        any_agree = True
        if any(_pair_is_exact(pair) for pair in pairs):
            any_exact = True
    return any_agree and not any_exact


def _dob_partial_only(rows: list, screened: Screened) -> bool:
    if screened.dob is None:
        return False
    full = False
    partial = False
    for row in rows:
        if row.dob is None or not dates_compatible(screened.dob, row.dob):
            continue
        if screened.dob["precision"] == "day" and row.dob["precision"] == "day":
            full = True
        else:
            partial = True
    return partial and not full


def _note_country_only(rows: list, screened: Screened) -> bool:
    if not screened.country:
        return False
    plain = False
    note = False
    for row in rows:
        matches = [from_note for value, from_note in row.country_facts if value == screened.country]
        if any(not from_note for from_note in matches):
            plain = True
        elif matches:
            note = True
    return note and not plain


def _pair_is_exact(pair: str) -> bool:
    left, separator, right = pair.partition("=")
    return bool(separator) and left == right and left != ""


def _evidence_ids(link, survivors, examined, holders, person_ids, by_person, person_count) -> tuple[list[str], list[str]]:
    """Deciding ids, then ids that were only looked at."""
    evidence: set[str] = set(survivors) if person_count else set()
    if link is not None and link[0] == "account" and person_count:
        evidence.add(link[1])
    looked: set[str] = set(examined or [])
    if holders:
        looked.update(holders)
    for person_id in person_ids:
        looked.update(by_person[person_id])
    considered = sorted(looked - evidence)
    return sorted(evidence), considered
