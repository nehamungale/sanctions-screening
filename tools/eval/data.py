"""Load the data folder (dev/*.jsonl), ID index, hit facts, path categories and edge tags."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .constants import (
    AMBIGUOUS_VALUES,
    DEFAULT_LEGAL_FORMS,
    GENERIC_TOKENS,
    PATH_CATEGORY_RULES,
    PLACEHOLDERS,
    TERRITORIES,
)
from .parse import norm_text, parse_id_list, split_name_parts

YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _flat(value: Any) -> str:
    """One string per field, so JSONL lists read like the workbook's text cells."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(_flat(v) for v in value if v not in (None, "", [], {}))
    if isinstance(value, dict):
        return "; ".join(_flat(v) for v in value.values() if v not in (None, "", [], {}))
    return str(value)


def _jsonl_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            row: dict[str, str] = {}
            for key, value in rec.items():
                if key == "customer" and isinstance(value, dict):
                    # alerts.jsonl nests the screened customer; flatten to the workbook names.
                    for sub, subval in value.items():
                        row["customer_name" if sub == "name" else sub] = _flat(subval)
                    continue
                row[key] = _flat(value)
            rows.append(row)
    return rows


# data-folder file stem -> workbook sheet name (CSV fallback)
_TABLES = {
    "customers": "Customers",
    "hits": "Hits",
    "alerts": "Alerts",
    "accounts": "Accounts",
    "onboarding": "Onboarding",
    "kyc_checks": "KYC_checks",
    "notes": "Notes",
    "search_results": "Search_results",
}


def read_table(data_dir: Path, stem: str) -> list[dict[str, str]]:
    """Rows of one table from ``<data>/<stem>.jsonl`` or the workbook ``<Sheet>.csv``."""
    data_dir = Path(data_dir)
    jsonl = data_dir / f"{stem}.jsonl"
    if jsonl.is_file():
        return _jsonl_rows(jsonl)
    sheet = data_dir / f"{_TABLES[stem]}.csv"
    if sheet.is_file():
        return _csv_rows(sheet)
    raise FileNotFoundError(f"Neither {jsonl} nor {sheet} exists")


def _policy_json(policy_path: Path) -> dict | None:
    if policy_path is None or not Path(policy_path).is_file() or Path(policy_path).suffix.lower() != ".json":
        return None
    return json.loads(Path(policy_path).read_text(encoding="utf-8"))


def parse_name_variants(policy_path: Path) -> list[set[str]]:
    """Parse given-name variant groups from the name_variants section of Policy.txt."""
    groups: list[set[str]] = []
    data = _policy_json(policy_path)
    if data is not None:
        for group in data.get("groups") or []:
            parts = {norm_text(p) for p in group if norm_text(p)}
            if len(parts) >= 2:
                groups.append(parts)
        return groups
    if policy_path is None or not Path(policy_path).is_file():
        return groups
    text = policy_path.read_text(encoding="utf-8")
    start = text.lower().find("name_variants.json")
    body = text[start:] if start >= 0 else text
    end = re.search(r"company legal forms:", body, re.I)
    body = body[: end.start()] if end else body
    for line in body.splitlines():
        line = line.strip()
        if "," not in line or any(ch in line for ch in ".()[]"):
            continue
        parts = [norm_text(p) for p in line.split(",") if p.strip()]
        parts = [p for p in parts if p and re.fullmatch(r"[a-z]+", p)]
        if len(parts) >= 2:
            groups.append(set(parts))
    return groups


def parse_legal_forms(policy_path: Path) -> set[str]:
    data = _policy_json(policy_path)
    if data is not None:
        forms = {norm_text(p) for p in data.get("company_legal_forms") or [] if norm_text(p)}
        return forms or set(DEFAULT_LEGAL_FORMS)
    if policy_path is None or not Path(policy_path).is_file():
        return set(DEFAULT_LEGAL_FORMS)
    text = policy_path.read_text(encoding="utf-8")
    m = re.search(r"company legal forms:\s*(.+)$", text, re.I | re.M)
    if not m:
        return set(DEFAULT_LEGAL_FORMS)
    parts = [norm_text(p) for p in m.group(1).split(",") if p.strip()]
    return set(parts) or set(DEFAULT_LEGAL_FORMS)


class DataIndex:
    """IDs and identifying facts drawn from the data folder."""

    def __init__(self, sheets_dir: Path, policy_path: Path | None = None):
        self.sheets_dir = Path(sheets_dir)
        if policy_path is None:
            policy_path = self.sheets_dir / "name_variants.json"
        self.ids: dict[str, str] = {}
        self.facts: dict[str, set[str]] = defaultdict(set)
        self.hits: dict[str, dict[str, str]] = {}
        self.alerts: dict[str, dict[str, str]] = {}
        self.customers: dict[str, dict[str, str]] = {}
        self.kyc: dict[str, dict[str, str]] = {}
        self.notes: dict[str, dict[str, str]] = {}
        self.search: dict[str, dict[str, str]] = {}
        self.hit_to_alert: dict[str, str] = {}
        self.variant_groups = parse_name_variants(policy_path)
        self.variant_of: dict[str, int] = {}
        for i, group in enumerate(self.variant_groups):
            for part in group:
                self.variant_of[part] = i
        self.legal_forms = parse_legal_forms(policy_path)
        self._load()

    def _register(self, record_id: str, table: str, fields: Iterable[str | None]) -> None:
        if not record_id:
            return
        self.ids[record_id] = table
        bag = self.facts[record_id]
        bag.add(norm_text(record_id))
        for raw in fields:
            if not raw:
                continue
            text = str(raw).strip()
            if not text:
                continue
            cleaned = re.sub(r"\s*\[[^\]]+\]", "", text)
            bag.add(norm_text(cleaned))
            for part in split_name_parts(cleaned, PLACEHOLDERS):
                if part not in self.legal_forms and part not in GENERIC_TOKENS and len(part) >= 3:
                    bag.add(part)
            for m in YEAR_RE.finditer(cleaned):
                bag.add(m.group(0))
            for m in DATE_ISO_RE.finditer(cleaned):
                bag.add(m.group(0))
            for piece in re.split(r"[;,|/]", cleaned):
                piece = piece.strip()
                if len(piece) >= 3:
                    bag.add(norm_text(piece))
                    last = piece.split(",")[-1].strip()
                    if len(last) >= 3:
                        bag.add(norm_text(last))

    def _load(self) -> None:
        sheets = self.sheets_dir
        if not sheets.is_dir():
            raise FileNotFoundError(f"Data folder not found: {sheets}")

        for row in read_table(sheets, "customers"):
            rid = row["record_id"]
            self.customers[rid] = row
            self._register(rid, "Customers", (
                row.get("full_name"), row.get("preferred_name"), row.get("login_name"),
                row.get("dob"), row.get("nationality"), row.get("residence_country"),
                row.get("city"), row.get("address"), row.get("email"),
            ))

        for row in read_table(sheets, "hits"):
            hid = row["hit_id"]
            self.hits[hid] = row
            self.hit_to_alert[hid] = row.get("alert_id") or ""
            self._register(hid, "Hits", (
                row.get("name"), row.get("aliases"), row.get("dobs"),
                row.get("place_of_birth"), row.get("deceased_date"),
                row.get("nationality"), row.get("citizenship"), row.get("countries"),
                row.get("addresses"),
            ))

        for row in read_table(sheets, "alerts"):
            aid = row["alert_id"]
            self.alerts[aid] = row
            self._register(aid, "Alerts", (
                row.get("customer_name"), row.get("dob"), row.get("country"),
                row.get("city"), row.get("email"), row.get("account_ref"),
                row.get("login_handle"),
            ))
            for hid in parse_id_list(row.get("hit_ids")):
                self.hit_to_alert.setdefault(hid, aid)

        for row in read_table(sheets, "accounts"):
            self._register(row["account_id"], "Accounts", (
                row.get("account_id"), row.get("customer_id"), row.get("login_handle"),
            ))

        for row in read_table(sheets, "onboarding"):
            if row.get("kyc_applicant_id"):
                self._register(row["kyc_applicant_id"], "Onboarding", (
                    row.get("kyc_applicant_id"), row.get("account_id"), row.get("customer_id"),
                ))
            if row.get("account_id"):
                self.ids.setdefault(row["account_id"], "Accounts")

        for row in read_table(sheets, "kyc_checks"):
            kid = row["check_id"]
            self.kyc[kid] = row
            self._register(kid, "KYC_checks", (
                row.get("verified_name"), row.get("verified_dob"),
                row.get("document_country"), row.get("document_number"),
                row.get("applicant_id"),
            ))
            if row.get("applicant_id"):
                self.ids.setdefault(row["applicant_id"], "Onboarding")

        for row in read_table(sheets, "notes"):
            nid = row["note_id"]
            self.notes[nid] = row
            text = row.get("text") or ""
            self._register(nid, "Notes", (nid, row.get("requester_email"), text[:400]))

        for row in read_table(sheets, "search_results"):
            sid = row["result_id"]
            self.search[sid] = row
            self._register(sid, "Search_results", (
                row.get("title"), row.get("snippet"), row.get("query"),
            ))

    def id_exists(self, record_id: str) -> bool:
        return record_id in self.ids

    def facts_for_hit(self, hit_id: str, cited_ids: Iterable[str], customer_id: str | None) -> set[str]:
        bag: set[str] = set()
        if hit_id in self.facts:
            bag |= self.facts[hit_id]
        alert_id = self.hit_to_alert.get(hit_id)
        if alert_id and alert_id in self.facts:
            bag |= self.facts[alert_id]
        for cid in cited_ids:
            if cid in self.facts:
                bag |= self.facts[cid]
        if customer_id and customer_id.lower() not in AMBIGUOUS_VALUES and customer_id in self.facts:
            bag |= self.facts[customer_id]
        return bag


def path_categories(path_text: str) -> list[str]:
    cats: list[str] = []
    for name, pattern in PATH_CATEGORY_RULES:
        if re.search(pattern, path_text or "", re.I):
            cats.append(name)
    return cats


def _collect_names(label: dict, data: DataIndex) -> list[str]:
    names: list[str] = []
    hit = data.hits.get(label["hit_id"], {})
    alert = data.alerts.get(label["alert_id"], {})
    names.extend([hit.get("name") or "", hit.get("aliases") or "", alert.get("customer_name") or ""])
    for cid in label["customer_record_ids"]:
        rec = data.customers.get(cid, {})
        names.extend([rec.get("full_name") or "", rec.get("preferred_name") or "", rec.get("login_name") or ""])
    for eid in label["evidence"]:
        if eid in data.kyc:
            names.append(data.kyc[eid].get("verified_name") or "")
        if eid in data.customers:
            rec = data.customers[eid]
            names.extend([rec.get("full_name") or "", rec.get("preferred_name") or ""])
    return [n for n in names if n]


def _collect_places(label: dict, data: DataIndex) -> list[str]:
    places: list[str] = []
    hit = data.hits.get(label["hit_id"], {})
    alert = data.alerts.get(label["alert_id"], {})
    for key in ("countries", "nationality", "citizenship", "addresses", "place_of_birth"):
        if hit.get(key):
            places.append(hit[key])
    for key in ("country", "city"):
        if alert.get(key):
            places.append(alert[key])
    for cid in label["customer_record_ids"]:
        rec = data.customers.get(cid, {})
        for key in ("nationality", "residence_country", "city", "address"):
            if rec.get(key):
                places.append(rec[key])
    for eid in label["evidence"]:
        if eid in data.kyc and data.kyc[eid].get("document_country"):
            places.append(data.kyc[eid]["document_country"])
        if eid in data.customers:
            rec = data.customers[eid]
            for key in ("nationality", "residence_country", "city", "address"):
                if rec.get(key):
                    places.append(rec[key])
    return places


def _has_placeholder_name(names: list[str]) -> bool:
    for name in names:
        cleaned = re.sub(r"\([^)]*\)", " ", name)
        tokens = [t for t in re.split(r"[\s,;/|._-]+", cleaned) if t]
        if not tokens:
            if norm_text(cleaned) in PLACEHOLDERS:
                return True
            continue
        real = [t for t in tokens if norm_text(t) not in PLACEHOLDERS and not t.isdigit()]
        if tokens and not real:
            return True
        if any(norm_text(t) in PLACEHOLDERS for t in tokens):
            return True
    return False


def _has_joined_name_parts(names: list[str], legal_forms: set[str] | None = None) -> bool:
    legal_forms = legal_forms or set()
    part_lists = [split_name_parts(n, PLACEHOLDERS) for n in names]
    # CamelCase join inside a token (AbdulBasit). Skip legal forms such as GmbH,
    # which also match [a-z][A-Z].
    for name in names:
        cleaned = re.sub(r"\([^)]*\)", " ", name)
        for token in re.findall(r"[A-Za-z]+", cleaned):
            if norm_text(token) in legal_forms:
                continue
            if re.search(r"[a-z][A-Z]", token):
                return True
    # A part in one name equals two consecutive parts of another (Abdul Salam vs Abdulsalam).
    for pl in part_lists:
        for i in range(len(pl) - 1):
            concat = pl[i] + pl[i + 1]
            if any(concat in other and other is not pl for other in part_lists):
                return True
    return False


def _has_name_variants(names: list[str], data: DataIndex) -> bool:
    part_lists = [split_name_parts(n, PLACEHOLDERS) for n in names]
    for i, pl1 in enumerate(part_lists):
        for pl2 in part_lists[i + 1:]:
            for p1 in pl1:
                g1 = data.variant_of.get(p1)
                if g1 is None:
                    continue
                for p2 in pl2:
                    if p1 != p2 and data.variant_of.get(p2) == g1:
                        return True
    return False


def _has_territory(places: list[str]) -> bool:
    for raw in places:
        for piece in re.split(r"[;,|/]", raw):
            piece = re.sub(r"\s*\[[^\]]+\]", "", piece).strip()
            for cand in (piece, piece.split(",")[-1].strip()):
                if norm_text(cand) in TERRITORIES:
                    return True
    return False


def edge_tags(label: dict, data: DataIndex) -> list[str]:
    tags: list[str] = []
    names = _collect_names(label, data)
    places = _collect_places(label, data)
    if _has_placeholder_name(names):
        tags.append("placeholder_names")
    if _has_joined_name_parts(names, data.legal_forms):
        tags.append("joined_name_parts")
    if _has_name_variants(names, data):
        tags.append("name_variants")
    if _has_territory(places):
        tags.append("territories")
    path = (label.get("path") or "").lower()
    cust = label.get("customer_record_ids") or []
    if (
        "joint holder" in path
        or "different people fit" in path
        or "each is decided separately" in path
        or any(str(c).upper() == "AMBIGUOUS" for c in cust)
    ):
        tags.append("multi_person_matches")
    return tags
