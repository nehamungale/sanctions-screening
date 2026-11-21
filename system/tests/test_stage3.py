"""Stage 3 alert resolution. Every customer row is synthetic."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage1.normalise import NameTools, parse_date
from stage1.normalise_text import norm_text
from stage3.cli import main as stage3_main
from stage3.names import agree_symmetric
from stage3.recall import agreeing_records, unlinked_recall
from stage3.resolve import dumps_jsonl, label_matches, resolve_alerts
from stage3.stage1_adapter import load_catalog

SYSTEM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(SYSTEM)


def _dev_folder():
    for candidate in (
        os.environ.get("STAGE3_DEV"),
        os.environ.get("SANCTIONS_DEV"),
        "/tmp/screening-dev/dev",
        "/cursor/stores/bot/hackathon/dev",
    ):
        if candidate and os.path.isfile(os.path.join(candidate, "alerts.jsonl")):
            return candidate
    return None

VARIANTS = {
    "groups": [
        ["tony", "anthony"],
        ["joe", "joseph"],
    ],
    "company_legal_forms": ["ltd", "gmbh", "limited", "inc", "co"],
}

METHODS = {"LINK_ACCOUNT", "LINK_ACCOUNT_JOINT", "LINK_LOGIN", "LINK_EMAIL", "NAME_SEARCH"}
STATUSES = {"RESOLVED", "AMBIGUOUS", "NOT_FOUND", "UNRESOLVED_LINK"}
FLAGS = ("DANGLING_LINK", "RECORD_DOB_MISSING_KEPT", "NAME_TOO_SHORT")
FRAGILITY = (
    "candidate_kept_on_missing_field",
    "dob_partial_only",
    "joint_account_tiebreak",
    "link_contradicts_screened",
    "name_match_fuzzy_only",
    "resolved_via_note_country",
)
RESOLUTION_METHODS = {"link_account", "link_login", "link_email", "name_search"}
RESOLUTION_STATUSES = {"resolved_single", "ambiguous", "not_found"}


def name_fact(record_id, parts):
    parts = list(parts or [])
    return {
        "parts": parts,
        "real_part_count": len(parts),
        "source_id": record_id,
        "value": " ".join(parts) if parts else None,
    }


def view(
    record_id,
    full,
    *,
    person_id=None,
    entity="Individual",
    preferred=None,
    login=None,
    dob=None,
    city=None,
    address=None,
    nationality=None,
    residence=None,
    residence_source=None,
    residence_kind=None,
    email=None,
    role=None,
):
    """One record_view row. ``full`` / ``preferred`` / ``login`` are part lists."""
    person_id = person_id or f"P-{record_id}"

    def country_fact(value, source_id=None, kind=None):
        fact = {"source_id": source_id or record_id, "unmapped": False, "value": value}
        if kind:
            fact["kind"] = kind
        return fact

    def place_fact(value):
        if not value:
            return {"normalised": None, "raw": None, "source_id": record_id}
        text = str(value).strip()
        return {"normalised": norm_text(text) or None, "raw": text, "source_id": record_id}

    if role is None:
        role = "incorporation" if entity == "Company" else "declared"
    if dob:
        parsed, _flags = parse_date(dob, mode="customer")
        dob_fact = {
            "comparable": parsed is not None,
            "precision": parsed["precision"] if parsed else None,
            "role": role,
            "source_id": record_id,
            "source_kind": "record",
            "unparsed": parsed is None,
            "value": parsed["value"] if parsed else None,
        }
    else:
        dob_fact = {
            "comparable": False,
            "precision": None,
            "role": role,
            "source_id": record_id,
            "source_kind": "record",
            "unparsed": False,
            "value": None,
        }
    return {
        "address": place_fact(address),
        "city": place_fact(city),
        "dob": dob_fact,
        "email": {"source_id": record_id, "value": email},
        "entity_type": {"source_id": record_id, "value": entity},
        "full_name": name_fact(record_id, full),
        "login_name": name_fact(record_id, login),
        "nationality": country_fact(nationality),
        "person_id": person_id,
        "preferred_name": name_fact(record_id, preferred),
        "record_id": record_id,
        "residence_country": country_fact(residence, residence_source, residence_kind),
    }


def alert(alert_id, name, *, entity="Individual", dob=None, country=None, city=None, account=None, login=None, email=None):
    return {
        "account_ref": account,
        "alert_id": alert_id,
        "customer": {
            "city": city,
            "country": country,
            "dob": dob,
            "entity_type": entity,
            "name": name,
        },
        "email": email,
        "hit_ids": ["H-000001"],
        "login_handle": login,
        "screened_at": "2026-01-01",
    }


def write_cache(cache, records, accounts=None, logins=None, emails=None):
    os.makedirs(cache, exist_ok=True)
    parts = defaultdict(set)
    derived_email = defaultdict(set)
    for row in records:
        for field in ("full_name", "preferred_name", "login_name"):
            for part in (row.get(field) or {}).get("parts") or []:
                parts[part].add(row["record_id"])
        email = (row.get("email") or {}).get("value")
        if email:
            derived_email[email].add(row["record_id"])

    def dump(name, payload):
        with open(os.path.join(cache, name), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.write("\n")

    dump("index_name_part_record_id.json", {key: sorted(value) for key, value in parts.items()})
    dump("index_account_record_id.json", {key: sorted(value) for key, value in (accounts or {}).items()})
    dump("index_login_record_id.json", {key: sorted(value) for key, value in (logins or {}).items()})
    email_index = derived_email if emails is None else emails
    dump("index_email_record_id.json", {key: sorted(value) for key, value in email_index.items()})
    with open(os.path.join(cache, "record_view.jsonl"), "w", encoding="utf-8") as handle:
        for row in sorted(records, key=lambda item: item["record_id"]):
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
            handle.write("\n")


class Stage3Tests(unittest.TestCase):
    def resolve(self, records, alerts, customers=None, **cache_kwargs):
        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "cache")
            write_cache(cache, records, **cache_kwargs)
            customers_path = None
            if customers is not None:
                customers_path = os.path.join(folder, "customers.jsonl")
                with open(customers_path, "w", encoding="utf-8") as handle:
                    for row in customers:
                        handle.write(json.dumps(row) + "\n")
            catalog = load_catalog(cache, VARIANTS, customers_path)
            rows = resolve_alerts(alerts, catalog)
        for row in rows:
            self.assert_shape(row)
        return rows

    def assert_quality(self, row):
        quality = row["resolution_quality"]
        self.assertIn(quality, {
            "DANGLING_LINK_fallback",
            "LINK_SUSPECT",
            "ambiguous",
            "clean_link",
            "joint_account_pick",
            "not_found",
            "unique_search_match",
        })
        if row["resolution_reason"] == "dangling_link":
            self.assertEqual(quality, "DANGLING_LINK_fallback")
        elif "link_contradicts_screened" in row["fragility_flags"]:
            self.assertEqual(quality, "LINK_SUSPECT")
        elif row["method"] == "LINK_ACCOUNT_JOINT" and row["status"] == "RESOLVED":
            self.assertEqual(quality, "joint_account_pick")
        elif row["status"] == "AMBIGUOUS":
            self.assertEqual(quality, "ambiguous")
        elif row["status"] in ("NOT_FOUND", "UNRESOLVED_LINK"):
            self.assertEqual(quality, "not_found")
        elif row["method"] == "NAME_SEARCH" and row["status"] == "RESOLVED":
            self.assertEqual(quality, "unique_search_match")
        elif row["status"] == "RESOLVED":
            self.assertEqual(quality, "clean_link")

    def assert_shape(self, row):
        required = {
            "alert_id",
            "candidates",
            "chosen_person_ids",
            "considered_ids",
            "customer_record_id",
            "evidence_ids",
            "filter_counts",
            "flags",
            "fragility_flags",
            "method",
            "rejected_holders",
            "resolution_clean",
            "resolution_method",
            "resolution_quality",
            "resolution_reason",
            "resolution_status",
            "screened",
            "status",
            "trace",
        }
        self.assertTrue(required <= set(row))
        self.assertIn(row["method"], METHODS)
        self.assertIn(row["status"], STATUSES)
        self.assertIn(row["resolution_method"], RESOLUTION_METHODS)
        self.assertIn(row["resolution_status"], RESOLUTION_STATUSES)
        self.assertEqual(row["flags"], [flag for flag in FLAGS if flag in row["flags"]])
        self.assertEqual(row["fragility_flags"], [flag for flag in FRAGILITY if flag in row["fragility_flags"]])
        self.assertEqual(row["evidence_ids"], sorted(set(row["evidence_ids"])))
        self.assertEqual(row["considered_ids"], sorted(set(row["considered_ids"])))
        self.assertFalse(set(row["evidence_ids"]) & set(row["considered_ids"]))
        expect_clean = row["resolution_status"] == "resolved_single" and not row["fragility_flags"]
        self.assertEqual(row["resolution_clean"], expect_clean)
        if row["status"] == "UNRESOLVED_LINK":
            self.assertEqual(row["resolution_status"], "not_found")
            self.assertEqual(row["resolution_reason"], "unresolved_joint_link")
            self.assertFalse(row["resolution_clean"])
        self.assert_quality(row)
        if row["resolution_status"] == "not_found":
            self.assertIsNone(row["customer_record_id"])
        if row["resolution_status"] == "ambiguous":
            for candidate in row["candidates"]:
                self.assertGreaterEqual(len(candidate["record_ids"]), 1)
        person_ids = [candidate["person_id"] for candidate in row["candidates"]]
        self.assertEqual(person_ids, sorted(person_ids))
        self.assertEqual(row["chosen_person_ids"], person_ids)
        rejected = [item["record_id"] for item in row["rejected_holders"]]
        self.assertEqual(rejected, sorted(rejected))
        value = row["customer_record_id"]
        if row["status"] == "RESOLVED":
            self.assertIsInstance(value, str)
            self.assertTrue(value.startswith("CUS-"), value)
            self.assertEqual(len(person_ids), 1)
            self.assertIn(value, row["candidates"][0]["matched_records"])
        elif row["status"] == "AMBIGUOUS":
            self.assertEqual(value, "AMBIGUOUS")
            self.assertGreaterEqual(len(person_ids), 2)
        else:
            self.assertIsNone(value)
            self.assertEqual(row["candidates"], [])
        for candidate in row["candidates"]:
            self.assertTrue(candidate["person_id"].startswith("P-"))
            self.assertEqual(candidate["record_ids"], sorted(candidate["record_ids"]))
            self.assertEqual(candidate["matched_records"], sorted(candidate["matched_records"]))
            self.assertTrue(set(candidate["fragility_flags"]) <= set(row["fragility_flags"]))
            filters = candidate["filters"]
            self.assertEqual(list(filters), ["applied", "passed", "skipped_missing"])
            for record_id in candidate["record_ids"]:
                self.assertTrue(record_id.startswith("CUS-"))

    def test_account_link_single_holder(self):
        rows = self.resolve(
            [view("CUS-000010", ["alice", "smith"], dob="1980-01-02", residence="Ireland")],
            [alert("A-000001", "Alice Smith", dob="1980-01-02", country="Ireland", account="ACC-1")],
            accounts={"ACC-1": ["CUS-000010"]},
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["method"], "LINK_ACCOUNT")
        self.assertEqual(row["customer_record_id"], "CUS-000010")
        self.assertEqual(row["chosen_person_ids"], ["P-CUS-000010"])
        self.assertEqual(row["candidates"][0]["record_ids"], ["CUS-000010"])
        self.assertEqual(row["rejected_holders"], [])
        self.assertEqual(row["flags"], [])
        self.assertEqual(row["filter_counts"], {})
        self.assertEqual(row["resolution_method"], "link_account")
        self.assertEqual(row["resolution_status"], "resolved_single")
        self.assertTrue(row["resolution_clean"])
        self.assertEqual(row["fragility_flags"], [])
        self.assertIn("CUS-000010", row["evidence_ids"])
        self.assertIn("ACC-1", row["evidence_ids"])

    def test_joint_one_holder_fits_and_records_the_other(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland", city="Dublin"),
            view("CUS-000020", ["bob", "jones"], dob="1980-05-02", residence="Ireland", city="Dublin"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", city="Dublin", account="ACC-9")],
            accounts={"ACC-9": ["CUS-000010", "CUS-000020"]},
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["method"], "LINK_ACCOUNT_JOINT")
        self.assertEqual(row["customer_record_id"], "CUS-000010")
        self.assertEqual(row["filter_counts"]["F1_name"], 1)
        self.assertEqual(row["filter_counts"]["F2_dob"], 1)
        self.assertEqual([item["record_id"] for item in row["rejected_holders"]], ["CUS-000020"])
        self.assertEqual(row["rejected_holders"][0]["why"]["name"], "no agree")
        self.assertNotIn("LINK_SUSPECT", row["flags"])
        self.assertIn("joint_account_tiebreak", row["fragility_flags"])
        self.assertEqual(row["resolution_method"], "link_account")
        self.assertEqual(row["resolution_status"], "resolved_single")
        self.assertFalse(row["resolution_clean"])
        self.assertIn("CUS-000020", row["considered_ids"])
        self.assertNotIn("CUS-000020", row["evidence_ids"])
        self.assertTrue(any(line.startswith("joint pick:") for line in row["trace"]))

    def test_joint_both_fit_is_ambiguous(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland"),
            view("CUS-000020", ["alice", "smith"], dob="1980-05-02", residence="Ireland"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="IE", account="ACC-9")],
            accounts={"ACC-9": ["CUS-000010", "CUS-000020"]},
        )
        row = rows[0]
        self.assertEqual(row["status"], "AMBIGUOUS")
        self.assertEqual(row["method"], "LINK_ACCOUNT_JOINT")
        self.assertEqual(row["customer_record_id"], "AMBIGUOUS")
        self.assertEqual(row["chosen_person_ids"], ["P-CUS-000010", "P-CUS-000020"])
        self.assertEqual(row["rejected_holders"], [])
        self.assertEqual(row["filter_counts"]["F1_name"], 2)
        self.assertEqual(row["resolution_status"], "ambiguous")
        self.assertNotIn("joint_account_tiebreak", row["fragility_flags"])
        self.assertFalse(row["resolution_clean"])
        self.assertEqual(len(row["candidates"]), 2)

    def test_joint_neither_fit_does_not_search_the_rest(self):
        records = [
            view("CUS-000010", ["bob", "jones"], dob="1970-01-01"),
            view("CUS-000020", ["cara", "nguyen"], dob="1971-01-01"),
            view("CUS-000030", ["alice", "smith"], dob="1980-05-02", residence="Ireland"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", account="ACC-9")],
            accounts={"ACC-9": ["CUS-000010", "CUS-000020"]},
        )
        row = rows[0]
        self.assertEqual(row["status"], "UNRESOLVED_LINK")
        self.assertEqual(row["resolution_status"], "not_found")
        self.assertEqual(row["resolution_reason"], "unresolved_joint_link")
        self.assertEqual(row["method"], "LINK_ACCOUNT_JOINT")
        self.assertEqual(row["resolution_method"], "link_account")
        self.assertIsNone(row["customer_record_id"])
        self.assertEqual(row["evidence_ids"], [])
        self.assertEqual(row["considered_ids"], ["CUS-000010", "CUS-000020"])
        self.assertFalse(row["resolution_clean"])
        self.assertEqual(row["candidates"], [])
        self.assertEqual([item["record_id"] for item in row["rejected_holders"]], ["CUS-000010", "CUS-000020"])
        self.assertNotIn("CUS-000030", json.dumps(row))

    def test_login_and_email_links(self):
        records = [
            view("CUS-000010", ["ann", "lee"], email="ann@example.com"),
            view("CUS-000020", ["bob", "lee"]),
        ]
        rows = self.resolve(
            records,
            [
                alert("A-000002", "Wrong Name", login="  Ann.Lee  "),
                alert("A-000001", "Wrong Name", email="Ann@Example.com"),
                alert("A-000003", "Wrong Name", login="ann.lee"),
            ],
            logins={"Ann.Lee": ["CUS-000020"]},
        )
        by_id = {row["alert_id"]: row for row in rows}
        self.assertEqual([row["alert_id"] for row in rows], ["A-000001", "A-000002", "A-000003"])
        email_row = by_id["A-000001"]
        self.assertEqual(email_row["status"], "RESOLVED")
        self.assertEqual(email_row["method"], "LINK_EMAIL")
        self.assertEqual(email_row["customer_record_id"], "CUS-000010")
        login_row = by_id["A-000002"]
        self.assertEqual(login_row["status"], "RESOLVED")
        self.assertEqual(login_row["method"], "LINK_LOGIN")
        self.assertEqual(login_row["customer_record_id"], "CUS-000020")
        folded = by_id["A-000003"]
        self.assertEqual(folded["status"], "RESOLVED")
        self.assertEqual(folded["method"], "LINK_LOGIN")
        self.assertEqual(folded["customer_record_id"], "CUS-000020")
        self.assertEqual(folded["resolution_quality"], "LINK_SUSPECT")
        self.assertNotIn("DANGLING_LINK", folded["flags"])

    def test_dangling_link_falls_back_to_name_search(self):
        rows = self.resolve(
            [view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland")],
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", account="ACC-MISSING")],
            accounts={"ACC-1": ["CUS-000010"]},
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["method"], "NAME_SEARCH")
        self.assertEqual(row["resolution_method"], "name_search")
        self.assertEqual(row["resolution_reason"], "dangling_link")
        self.assertEqual(row["customer_record_id"], "CUS-000010")
        self.assertEqual(row["flags"], ["DANGLING_LINK"])
        self.assertTrue(any(line.startswith("dangling account ACC-MISSING") for line in row["trace"]))

    def test_linked_record_expands_to_the_whole_person(self):
        records = [
            view("CUS-000010", ["alice", "smith"], person_id="P-CUS-000010", dob="1980-05-02"),
            view("CUS-000020", ["alice", "smith"], person_id="P-CUS-000010", dob="1980-05-02"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", account="ACC-1")],
            accounts={"ACC-1": ["CUS-000020"]},
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["customer_record_id"], "CUS-000020")
        self.assertEqual(row["candidates"][0]["record_ids"], ["CUS-000010", "CUS-000020"])
        self.assertEqual(row["candidates"][0]["person_id"], "P-CUS-000010")
        self.assertEqual(len(row["chosen_person_ids"]), 1)

    def test_link_suspect_is_followed_not_replaced(self):
        records = [
            view("CUS-000010", ["bob", "jones"], dob="1970-01-01", residence="France"),
            view("CUS-000099", ["alice", "smith"], dob="1990-05-05", residence="Ireland"),
        ]
        rows = self.resolve(
            records,
            [
                alert("A-000001", "Alice Smith", dob="1990-05-05", account="ACC-1"),
                alert("A-000002", "Bob Jones", dob="1990-05-05", account="ACC-1"),
            ],
            accounts={"ACC-1": ["CUS-000010"]},
        )
        by_id = {row["alert_id"]: row for row in rows}
        both = by_id["A-000001"]
        self.assertEqual(both["status"], "RESOLVED")
        self.assertEqual(both["customer_record_id"], "CUS-000010")
        self.assertEqual(both["method"], "LINK_ACCOUNT")
        self.assertEqual(both["resolution_method"], "link_account")
        self.assertEqual(both["resolution_status"], "resolved_single")
        self.assertIn("link_contradicts_screened", both["fragility_flags"])
        self.assertIn("link_contradicts_screened", both["candidates"][0]["fragility_flags"])
        self.assertNotIn("LINK_SUSPECT", both["flags"])
        self.assertFalse(both["resolution_clean"])
        self.assertNotEqual(both["customer_record_id"], "CUS-000099")
        self.assertTrue(any("link_contradicts_screened" in line for line in both["trace"]))
        dob_only = by_id["A-000002"]
        self.assertEqual(dob_only["customer_record_id"], "CUS-000010")
        self.assertIn("link_contradicts_screened", dob_only["fragility_flags"])
        self.assertFalse(dob_only["resolution_clean"])
        self.assertTrue(any("dob" in line and "link_contradicts_screened" in line for line in dob_only["trace"]))

    def test_nickname_typo_join_and_order(self):
        records = [
            view("CUS-000010", ["anthony", "smith"]),
            view("CUS-000020", ["jonathan", "smith"]),
            view("CUS-000030", ["abdul", "salam"]),
            view("CUS-000040", ["josephsmith"]),
            view("CUS-000050", ["alice", "smith"]),
        ]
        rows = self.resolve(
            records,
            [
                alert("A-000001", "Tony Smith"),
                alert("A-000002", "Jonathon Smith"),
                alert("A-000003", "Abdulsalam"),
                alert("A-000004", "Joe Smith"),
                alert("A-000005", "Smith Alice"),
                alert("A-000006", "J.R. Smith"),
            ],
        )
        by_id = {row["alert_id"]: row for row in rows}
        self.assertEqual(by_id["A-000001"]["customer_record_id"], "CUS-000010")
        self.assertEqual(by_id["A-000001"]["candidates"][0]["why"]["name"]["field"], "full_name")
        self.assertEqual(by_id["A-000002"]["customer_record_id"], "CUS-000020")
        self.assertEqual(by_id["A-000003"]["customer_record_id"], "CUS-000030")
        self.assertEqual(by_id["A-000004"]["customer_record_id"], "CUS-000040")
        self.assertEqual(by_id["A-000005"]["customer_record_id"], "CUS-000050")
        jr = view("CUS-000060", ["jr", "smith"])
        jr_rows = self.resolve([jr], [alert("A-000007", "J.R. Smith")])
        self.assertEqual(jr_rows[0]["customer_record_id"], "CUS-000060")
        self.assertEqual(jr_rows[0]["screened"]["parts"], ["jr", "smith"])

    def test_preferred_and_login_names_not_only_full(self):
        records = [
            view("CUS-000010", ["robert", "jones"], preferred=["bob", "jones"]),
            view("CUS-000020", ["alice", "smith"], login=["xqvntblr"]),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Bob Jones"), alert("A-000002", "xqvntblr")],
        )
        by_id = {row["alert_id"]: row for row in rows}
        self.assertEqual(by_id["A-000001"]["customer_record_id"], "CUS-000010")
        self.assertEqual(by_id["A-000001"]["candidates"][0]["why"]["name"]["field"], "preferred_name")
        self.assertEqual(by_id["A-000002"]["customer_record_id"], "CUS-000020")
        self.assertEqual(by_id["A-000002"]["candidates"][0]["why"]["name"]["field"], "login_name")

    def test_year_only_dob_is_compatible_and_a_full_date_checks_the_day(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland"),
            view("CUS-000020", ["alice", "smith"], dob="1980-05-03", residence="Ireland"),
            view("CUS-000030", ["alice", "smith"], dob="1979-05-02", residence="Ireland"),
        ]
        rows = self.resolve(
            records,
            [
                alert("A-000001", "Alice Smith", dob="1980", country="Ireland"),
                alert("A-000002", "Alice Smith", dob="1980-05-02", country="Ireland"),
            ],
        )
        by_id = {row["alert_id"]: row for row in rows}
        year = by_id["A-000001"]
        self.assertEqual(year["status"], "AMBIGUOUS")
        self.assertEqual(sorted(item["matched_records"][0] for item in year["candidates"]), ["CUS-000010", "CUS-000020"])
        self.assertNotIn("CUS-000030", [item["matched_records"][0] for item in year["candidates"]])
        full = by_id["A-000002"]
        self.assertEqual(full["status"], "RESOLVED")
        self.assertEqual(full["customer_record_id"], "CUS-000010")
        self.assertEqual(full["candidates"][0]["why"]["dob"], "compatible")

    def test_record_without_dob_is_kept_and_flagged(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob=None, residence="Ireland"),
            view("CUS-000020", ["alice", "smith"], dob="1970-01-01", residence="Ireland"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland")],
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["customer_record_id"], "CUS-000010")
        self.assertEqual(row["flags"], ["RECORD_DOB_MISSING_KEPT"])
        self.assertEqual(row["candidates"][0]["why"]["dob"], "record dob missing -> unknown")
        self.assertEqual(row["filter_counts"]["F2_dob"], 1)

    def test_country_code_name_and_adjective(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-01-01", residence="United Kingdom"),
            view("CUS-000020", ["alice", "smith"], dob="1980-01-01", residence="France"),
            view("CUS-000030", ["bob", "jones"], dob="1980-01-01", residence="Macao"),
            view("CUS-000040", ["cara", "nunez"], dob="1980-01-01", residence="Palestine"),
            view("CUS-000050", ["dan", "kovac"], dob="1980-01-01", residence="Kosovo"),
        ]
        rows = self.resolve(
            records,
            [
                alert("A-000001", "Alice Smith", dob="1980-01-01", country="GB"),
                alert("A-000002", "Alice Smith", dob="1980-01-01", country="United Kingdom"),
                alert("A-000003", "Alice Smith", dob="1980-01-01", country="British"),
                alert("A-000004", "Alice Smith", dob="1980-01-01", country="France"),
                alert("A-000005", "Bob Jones", dob="1980-01-01", country="Macao SAR"),
                alert("A-000006", "Cara Nunez", dob="1980-01-01", country="Palestina"),
                alert("A-000007", "Dan Kovac", dob="1980-01-01", country="XK"),
            ],
        )
        by_id = {row["alert_id"]: row for row in rows}
        for alert_id in ("A-000001", "A-000002", "A-000003"):
            self.assertEqual(by_id[alert_id]["customer_record_id"], "CUS-000010", alert_id)
            self.assertEqual(by_id[alert_id]["screened"]["country"], "United Kingdom")
        self.assertEqual(by_id["A-000004"]["customer_record_id"], "CUS-000020")
        self.assertEqual(by_id["A-000005"]["customer_record_id"], "CUS-000030")
        self.assertEqual(by_id["A-000005"]["screened"]["country"], "Macao")
        self.assertEqual(by_id["A-000006"]["customer_record_id"], "CUS-000040")
        self.assertEqual(by_id["A-000007"]["customer_record_id"], "CUS-000050")
        self.assertEqual(by_id["A-000001"]["filter_counts"]["F3_country"], 1)

    def test_city_matches_via_address_and_a_missing_city_is_kept(self):
        records = [
            view("CUS-000010", ["alice", "smith"], city="Oslo", address="Marienplatz, München", residence="Germany"),
            view("CUS-000020", ["alice", "smith"], city="Paris", address="1 Rue de Rivoli, Paris", residence="Germany"),
            view("CUS-000030", ["bob", "jones"], city=None, address="1 High Street", residence="Germany"),
            view("CUS-000040", ["bob", "jones"], city="Paris", address="2 High Street, Paris", residence="Germany"),
        ]
        rows = self.resolve(
            records,
            [
                alert("A-000001", "Alice Smith", country="Germany", city="München"),
                alert("A-000002", "Alice Smith", country="Germany", city="Oslo"),
                alert("A-000003", "Bob Jones", country="Germany", city="Berlin"),
            ],
        )
        by_id = {row["alert_id"]: row for row in rows}
        via_address = by_id["A-000001"]
        self.assertEqual(via_address["customer_record_id"], "CUS-000010")
        self.assertEqual(via_address["candidates"][0]["why"]["city"], "address")
        via_city = by_id["A-000002"]
        self.assertEqual(via_city["customer_record_id"], "CUS-000010")
        self.assertEqual(via_city["candidates"][0]["why"]["city"], "city")
        missing = by_id["A-000003"]
        self.assertEqual(missing["status"], "RESOLVED")
        self.assertEqual(missing["customer_record_id"], "CUS-000030")
        self.assertEqual(missing["candidates"][0]["why"]["city"], "record city missing -> unknown")

    def test_company_uses_declared_dob_not_registry_incorporation(self):
        records = [
            view(
                "CUS-000010",
                ["acme", "holdings"],
                entity="Company",
                dob="2010-01-01",
                residence="Germany",
                role="incorporation",
            ),
            view(
                "CUS-000020",
                ["acme", "holdings"],
                entity="Company",
                dob="2010-01-01",
                residence="Germany",
                role="incorporation",
            ),
        ]
        customers = [
            {"record_id": "CUS-000010", "entity_type": "Company", "dob": "1998-08-11"},
            {"record_id": "CUS-000020", "entity_type": "Company", "dob": "1970-01-01"},
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Acme Limited", entity="Company", dob="1998", country="Germany")],
            customers=customers,
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["customer_record_id"], "CUS-000010")
        self.assertNotIn("NAME_TOO_SHORT", row["flags"])
        self.assertEqual(row["screened"]["parts"], ["acme"])
        self.assertNotIn("limited", row["screened"]["parts"])

    def test_other_entity_type_is_excluded_by_type_filter(self):
        rows = self.resolve(
            [view("CUS-000010", ["alice", "smith"], entity="Individual", dob="1980-01-01")],
            [alert("A-000001", "Alice Smith", entity="Vessel", dob="1980-01-01")],
        )
        row = rows[0]
        self.assertEqual(row["status"], "NOT_FOUND")
        self.assertIsNone(row["customer_record_id"])
        self.assertEqual(row["filter_counts"]["F0_type"], 0)
        self.assertEqual(row["filter_counts"]["F1_name"], 0)

    def test_two_records_of_one_person_are_not_ambiguous(self):
        records = [
            view("CUS-000001", ["other", "person"], person_id="P-CUS-000001", dob="1980-05-02", residence="Ireland"),
            view("CUS-000009", ["alice", "smith"], person_id="P-CUS-000001", dob="1980-05-02", residence="Ireland"),
            view("CUS-000020", ["alice", "smith"], person_id="P-CUS-000001", dob="1980-05-02", residence="Ireland"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland")],
        )
        row = rows[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["chosen_person_ids"], ["P-CUS-000001"])
        self.assertEqual(row["customer_record_id"], "CUS-000009")
        self.assertEqual(row["candidates"][0]["record_ids"], ["CUS-000001", "CUS-000009", "CUS-000020"])
        self.assertEqual(row["candidates"][0]["matched_records"], ["CUS-000009", "CUS-000020"])

    def test_two_persons_stay_ambiguous_with_counts(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland", city="Dublin"),
            view("CUS-000020", ["alice", "smith"], dob="1980-05-02", residence="Ireland", city="Dublin"),
            view("CUS-000030", ["alice", "smith"], dob="1970-01-01", residence="Ireland", city="Dublin"),
            view("CUS-000040", ["bob", "jones"], dob="1980-05-02", residence="Ireland", city="Dublin"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980", country="Ireland", city="Dublin")],
        )
        row = rows[0]
        self.assertEqual(row["status"], "AMBIGUOUS")
        self.assertEqual(row["customer_record_id"], "AMBIGUOUS")
        self.assertEqual(row["chosen_person_ids"], ["P-CUS-000010", "P-CUS-000020"])
        self.assertEqual(row["filter_counts"], {"F0_type": 4, "F1_name": 3, "F2_dob": 2, "F3_country": 2, "F4_city": 2})
        self.assertTrue(any("name 3" in line and "dob 2" in line for line in row["trace"]))

    def test_nobody_survives(self):
        rows = self.resolve(
            [view("CUS-000010", ["alice", "smith"], dob="1980-01-01", residence="Ireland")],
            [alert("A-000001", "Zora Quill", dob="1980-01-01", country="Ireland")],
        )
        row = rows[0]
        self.assertEqual(row["status"], "NOT_FOUND")
        self.assertIsNone(row["customer_record_id"])
        self.assertEqual(row["candidates"], [])
        self.assertEqual(row["method"], "NAME_SEARCH")
        self.assertEqual(row["filter_counts"]["F1_name"], 0)

    def test_placeholders_removed_and_short_name_flagged(self):
        rows = self.resolve(
            [view("CUS-000010", ["alice", "berg"], dob="1980-01-01")],
            [alert("A-000001", "N/A Alice", dob="1980-01-01")],
        )
        row = rows[0]
        self.assertEqual(row["screened"]["parts"], ["alice"])
        self.assertNotIn("na", row["screened"]["parts"])
        self.assertIn("NAME_TOO_SHORT", row["flags"])
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["customer_record_id"], "CUS-000010")

    def test_verified_style_name_is_not_used_when_record_names_differ(self):
        records = [view("CUS-000010", ["alice", "smith"], dob="1980-01-01", residence="Ireland")]
        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "cache")
            write_cache(cache, records)
            with open(os.path.join(cache, "index_name.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"by_part": {"verified": ["CUS-000010"], "person": ["CUS-000010"]}},
                    handle,
                )
            catalog = load_catalog(cache, VARIANTS)
            rows = resolve_alerts(
                [alert("A-000001", "Verified Person", dob="1980-01-01", country="Ireland")],
                catalog,
            )
        self.assert_shape(rows[0])
        self.assertEqual(rows[0]["status"], "NOT_FOUND")
        self.assertIsNone(rows[0]["customer_record_id"])

    def test_determinism_and_output_order(self):
        records = [
            view("CUS-000020", ["bob", "jones"], dob="1970-01-01"),
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland"),
        ]
        alerts = [
            alert("A-000002", "Nobody Here", dob="1980-01-01"),
            alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", account="ACC-9"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "cache")
            write_cache(cache, records, accounts={"ACC-9": ["CUS-000010", "CUS-000020"]})
            first_catalog = load_catalog(cache, VARIANTS)
            second_catalog = load_catalog(cache, VARIANTS)
            first = resolve_alerts(alerts, first_catalog)
            second = resolve_alerts(list(reversed(alerts)), first_catalog)
            third = resolve_alerts(alerts, second_catalog)
        self.assertEqual(dumps_jsonl(first), dumps_jsonl(second))
        self.assertEqual(dumps_jsonl(first), dumps_jsonl(third))
        self.assertEqual([row["alert_id"] for row in first], ["A-000001", "A-000002"])
        for row in first:
            self.assert_shape(row)

    def test_cli_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            data = os.path.join(folder, "data")
            cache = os.path.join(folder, "cache")
            os.makedirs(data)
            records = [view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland")]
            write_cache(cache, records)
            with open(os.path.join(data, "name_variants.json"), "w", encoding="utf-8") as handle:
                json.dump(VARIANTS, handle)
            with open(os.path.join(data, "alerts.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps(alert("A-000002", "Zora Quill")) + "\n")
                handle.write(json.dumps(alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland")) + "\n")
            env = os.environ.copy()
            env["PYTHONPATH"] = SYSTEM
            env["SANCTIONS_CACHE"] = cache
            out_a = os.path.join(folder, "a.jsonl")
            out_b = os.path.join(folder, "b.jsonl")
            for output in (out_a, out_b):
                completed = subprocess.run(
                    [sys.executable, "-m", "stage3", data, output],
                    cwd=REPO,
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            with open(out_a, "rb") as handle:
                body_a = handle.read()
            with open(out_b, "rb") as handle:
                body_b = handle.read()
            self.assertEqual(body_a, body_b)
            self.assertTrue(body_a.endswith(b"\n"))
            lines = body_a.decode("utf-8").splitlines()
            self.assertEqual(json.loads(lines[0])["alert_id"], "A-000001")
            self.assertEqual(json.loads(lines[1])["status"], "NOT_FOUND")
            missing = subprocess.run(
                [sys.executable, "-m", "stage3", data, os.path.join(folder, "c.jsonl")],
                cwd=REPO,
                env={**env, "SANCTIONS_CACHE": os.path.join(folder, "absent")},
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(stage3_main(["only-one"]), 2)

    def test_fragility_flags_and_resolution_clean(self):
        exact = view(
            "CUS-000010",
            ["alice", "smith"],
            dob="1980-05-02",
            residence="Ireland",
            city="Dublin",
            address="1 High Street, Dublin",
        )
        fuzzy = view(
            "CUS-000020",
            ["jonathan", "quill"],
            dob="1980-05-02",
            residence="Ireland",
            city="Dublin",
            address="2 High Street, Dublin",
        )
        partial = view(
            "CUS-000030",
            ["alice", "smith"],
            dob="1981-06-07",
            residence="Ireland",
            city="Dublin",
            address="3 High Street, Dublin",
        )
        missing_dob = view(
            "CUS-000040",
            ["nora", "keane"],
            dob=None,
            residence="Ireland",
            city="Dublin",
            address="4 High Street, Dublin",
        )
        note_country = view(
            "CUS-000050",
            ["piotr", "nowak"],
            dob="1975-03-03",
            residence="Ireland",
            residence_source="NOTE-00A1B2",
            city="Dublin",
            address="5 High Street, Dublin",
        )
        plain = view(
            "CUS-000060",
            ["piotr", "nowak"],
            dob="1975-03-03",
            residence="France",
            city="Lyon",
            address="6 Rue, Lyon",
        )
        rows = self.resolve(
            [exact, fuzzy, partial, missing_dob, note_country, plain],
            [
                alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", city="Dublin"),
                alert("A-000002", "Jonathon Quille", dob="1980-05-02", country="Ireland", city="Dublin"),
                alert("A-000003", "Alice Smith", dob="1981", country="Ireland", city="Dublin"),
                alert("A-000004", "Nora Keane", dob="1990-01-01", country="Ireland", city="Dublin"),
                alert("A-000005", "Piotr Nowak", dob="1975-03-03", country="Ireland", city="Dublin"),
                alert("A-000006", "Alice Smith", dob="1980-05-02", country="Ireland"),
            ],
        )
        by_id = {row["alert_id"]: row for row in rows}
        clean = by_id["A-000001"]
        self.assertEqual(clean["resolution_status"], "resolved_single")
        self.assertEqual(clean["fragility_flags"], [])
        self.assertTrue(clean["resolution_clean"])
        self.assertEqual(clean["candidates"][0]["filters"]["passed"], ["name", "dob", "country", "city"])
        self.assertEqual(clean["candidates"][0]["filters"]["skipped_missing"], [])
        self.assertEqual(clean["evidence_ids"], ["CUS-000010"])

        fuzzy_row = by_id["A-000002"]
        self.assertIn("name_match_fuzzy_only", fuzzy_row["fragility_flags"])
        self.assertNotIn("dob_partial_only", fuzzy_row["fragility_flags"])
        self.assertFalse(fuzzy_row["resolution_clean"])

        partial_row = by_id["A-000003"]
        self.assertIn("dob_partial_only", partial_row["fragility_flags"])
        self.assertNotIn("name_match_fuzzy_only", partial_row["fragility_flags"])
        self.assertFalse(partial_row["resolution_clean"])

        missing = by_id["A-000004"]
        self.assertIn("candidate_kept_on_missing_field", missing["fragility_flags"])
        self.assertIn("RECORD_DOB_MISSING_KEPT", missing["flags"])
        skips = missing["candidates"][0]["filters"]["skipped_missing"]
        self.assertIn({"filter": "dob", "side": "record"}, skips)
        self.assertFalse(missing["resolution_clean"])

        noted = by_id["A-000005"]
        self.assertEqual(noted["customer_record_id"], "CUS-000050")
        self.assertIn("resolved_via_note_country", noted["fragility_flags"])
        self.assertNotIn("CUS-000060", noted["evidence_ids"])
        self.assertFalse(noted["resolution_clean"])

        no_city = by_id["A-000006"]
        self.assertIn("candidate_kept_on_missing_field", no_city["fragility_flags"])
        self.assertIn({"filter": "city", "side": "alert"}, no_city["candidates"][0]["filters"]["skipped_missing"])
        self.assertFalse(no_city["resolution_clean"])

    def test_ambiguous_fragility_is_per_candidate(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland", city="Dublin"),
            view("CUS-000020", ["alyce", "smyth"], dob="1980-05-02", residence="Ireland", city="Dublin"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", city="Dublin")],
        )
        row = rows[0]
        self.assertEqual(row["resolution_status"], "ambiguous")
        self.assertFalse(row["resolution_clean"])
        by_person = {candidate["person_id"]: candidate for candidate in row["candidates"]}
        self.assertEqual(by_person["P-CUS-000010"]["fragility_flags"], [])
        self.assertEqual(by_person["P-CUS-000020"]["fragility_flags"], ["name_match_fuzzy_only"])
        self.assertEqual(row["fragility_flags"], ["name_match_fuzzy_only"])
        self.assertEqual(row["evidence_ids"], ["CUS-000010", "CUS-000020"])
        self.assertEqual(len(row["candidates"]), 2)

    def test_note_text_is_not_added_to_the_country_filter(self):
        record = view(
            "CUS-000010",
            ["alice", "smith"],
            dob="1980-05-02",
            residence="France",
            city="Lyon",
        )
        record["notes"] = [{"country": "Ireland", "source_id": "NOTE-00FFFF"}]
        rows = self.resolve(
            [record],
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", city="Lyon")],
        )
        self.assertEqual(rows[0]["status"], "NOT_FOUND")
        self.assertNotIn("resolved_via_note_country", rows[0]["fragility_flags"])

    def test_nickname_with_an_exact_part_is_not_fuzzy_only(self):
        rows = self.resolve(
            [view("CUS-000010", ["anthony", "smith"], dob="1980-05-02", residence="Ireland", city="Dublin")],
            [alert("A-000001", "Tony Smith", dob="1980-05-02", country="Ireland", city="Dublin")],
        )
        self.assertEqual(rows[0]["customer_record_id"], "CUS-000010")
        self.assertNotIn("name_match_fuzzy_only", rows[0]["fragility_flags"])
        self.assertTrue(rows[0]["resolution_clean"])

    def test_missing_country_is_kept(self):
        records = [
            view("CUS-000010", ["alice", "smith"], dob="1980-05-02", residence="Ireland", city="Dublin"),
            view("CUS-000020", ["alice", "smith"], dob="1980-05-02", residence=None, city="Dublin"),
            view("CUS-000030", ["alice", "smith"], dob="1980-05-02", residence="France", city="Dublin"),
        ]
        rows = self.resolve(
            records,
            [alert("A-000001", "Alice Smith", dob="1980-05-02", country="Ireland", city="Dublin")],
        )
        row = rows[0]
        self.assertEqual(row["resolution_quality"], "ambiguous")
        ids = {candidate["person_id"] for candidate in row["candidates"]}
        self.assertEqual(ids, {"P-CUS-000010", "P-CUS-000020"})
        blank = next(candidate for candidate in row["candidates"] if candidate["person_id"] == "P-CUS-000020")
        self.assertIn("candidate_kept_on_missing_field", blank["fragility_flags"])
        self.assertIn({"filter": "country", "side": "record"}, blank["filters"]["skipped_missing"])
        self.assertNotIn("P-CUS-000030", ids)

    def test_symmetric_name_agreement_rejects_one_sided_match(self):
        names = NameTools(VARIANTS)
        left = ["abdul", "salam"]
        right = ["abdulsalam", "khan"]
        forward = names.names_agree(left, right)
        backward = names.names_agree(right, left)
        self.assertNotEqual(bool(forward["agree"]), bool(backward["agree"]))
        wrapped = agree_symmetric(names, left, right)
        self.assertFalse(wrapped["agree"])
        self.assertEqual(wrapped["matched_pairs"], [])
        both = agree_symmetric(names, ["alice", "smith"], ["smith", "alice"])
        self.assertTrue(both["agree"])

    def test_index_candidates_match_a_full_scan(self):
        records = [
            view("CUS-000010", ["jonathan", "quill"]),
            view("CUS-000020", ["abdul", "salam"]),
            view("CUS-000030", ["anthony", "smith"]),
            view("CUS-000040", ["zora", "unrelated"]),
        ]
        with tempfile.TemporaryDirectory() as folder:
            cache = os.path.join(folder, "cache")
            write_cache(cache, records)
            catalog = load_catalog(cache, VARIANTS)
            tools = NameTools(VARIANTS)
            for screened_name in ("Jonathon Quille", "Abdulsalam", "Tony Smith", "Zora Unrelated"):
                parts = tuple(tools.parts(screened_name, "Individual"))
                indexed = agreeing_records(catalog, parts, "Individual", use_index=True)
                scanned = agreeing_records(catalog, parts, "Individual", use_index=False)
                self.assertEqual(indexed, scanned, screened_name)
            self.assertIn("CUS-000010", agreeing_records(
                catalog, tuple(tools.parts("Jonathon Quille", "Individual")), "Individual", use_index=True
            ))
            self.assertIn("CUS-000020", agreeing_records(
                catalog, tuple(tools.parts("Abdulsalam", "Individual")), "Individual", use_index=True
            ))
            self.assertIn("CUS-000030", agreeing_records(
                catalog, tuple(tools.parts("Tony Smith", "Individual")), "Individual", use_index=True
            ))

    def test_label_matcher(self):
        resolved = {
            "alert_id": "A-1",
            "status": "RESOLVED",
            "customer_record_id": "CUS-000010",
            "chosen_person_ids": ["P-CUS-000010"],
            "candidates": [{
                "person_id": "P-CUS-000010",
                "record_ids": ["CUS-000010", "CUS-000020"],
                "matched_records": ["CUS-000020"],
                "why": {},
            }],
        }
        good, reason = label_matches(resolved, ["CUS-000020", "CUS-000010"])
        self.assertTrue(good, reason)
        bad, reason = label_matches(resolved, ["CUS-000010"])
        self.assertFalse(bad)
        self.assertIn("records", reason)
        ambiguous = {
            "status": "AMBIGUOUS",
            "customer_record_id": "AMBIGUOUS",
            "chosen_person_ids": ["P-1", "P-2"],
            "candidates": [{"person_id": "P-1"}, {"person_id": "P-2"}],
        }
        good, reason = label_matches(ambiguous, ["AMBIGUOUS"])
        self.assertTrue(good, reason)
        person_id = dict(resolved)
        person_id["customer_record_id"] = "P-CUS-000010"
        bad, _reason = label_matches(person_id, ["CUS-000010", "CUS-000020"])
        self.assertFalse(bad)

    @unittest.skipUnless(_dev_folder(), "dev data is not on this machine")
    def test_unlinked_name_recall_matches_full_scan(self):
        from stage1.build import run_stage1

        data = _dev_folder()
        with tempfile.TemporaryDirectory() as cache:
            run_stage1(data, cache)
            with open(os.path.join(data, "name_variants.json"), encoding="utf-8") as handle:
                variants = json.load(handle)
            catalog = load_catalog(cache, variants, os.path.join(data, "customers.jsonl"))
            alerts = []
            with open(os.path.join(data, "alerts.jsonl"), encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        alerts.append(json.loads(line))
            report = unlinked_recall(catalog, alerts)
        self.assertGreater(report["compared"], 0)
        self.assertEqual(report["mismatches"], [], report["mismatches"][:5])
        self.assertTrue(report["match"])

    @unittest.skipUnless(os.environ.get("STAGE3_DEV"), "set STAGE3_DEV to run the 50-label regression")
    def test_practice_labels(self):
        data = os.environ["STAGE3_DEV"]
        cache = os.environ.get("SANCTIONS_CACHE", "working")
        catalog = load_catalog(cache, json.load(open(os.path.join(data, "name_variants.json"), encoding="utf-8")))
        alerts = []
        with open(os.path.join(data, "alerts.jsonl"), encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    alerts.append(json.loads(line))
        rows = {row["alert_id"]: row for row in resolve_alerts(alerts, catalog)}
        labels = []
        with open(os.path.join(data, "practice_labels.jsonl"), encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    labels.append(json.loads(line))
        misses = []
        for label in labels:
            good, reason = label_matches(rows[label["alert_id"]], label["customer_record_ids"])
            if not good:
                misses.append(f"{label['hit_id']} {label['alert_id']} {reason}")
        self.assertEqual(misses, [])
        self.assertEqual(len(labels), 50)


if __name__ == "__main__":
    unittest.main()
