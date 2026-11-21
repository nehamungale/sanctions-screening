#!/usr/bin/env python3
"""Run the real Stage 4 pipeline (system/run) on a small synthetic data folder and keep its trace.

Usage: python3 tests/make-real-trace.py <repo checkout> <out dir>

Writes into <out dir>:
  data/            the synthetic input folder (temp IDs the pipeline accepts, e.g. CUS-999001)
  output.jsonl     the official per-hit output
  trace.raw.jsonl  the pipeline's trace, untouched (hit lines + appended alert summaries)
  trace.jsonl      the same trace with every ID rewritten to the synthetic form (H-SYN..., CUS-SYN...)
  alerts.jsonl     the input alerts.jsonl, IDs rewritten the same way

The pipeline only accepts CUS-<6 digits> customer ids, so it runs on numeric temp ids and the ids are
rewritten afterwards; nothing else in the trace is touched. No dev/ data is read. Model calls are off.
"""

import json
import os
import re
import subprocess
import sys

VARIANTS = {"groups": [["robert", "bob"]], "company_legal_forms": ["ltd", "inc"]}


def person(n, name, dob, country, check=True):
    rec = {
        "record_id": f"CUS-99900{n}", "entity_type": "Individual", "full_name": name, "preferred_name": None,
        "login_name": None, "dob": dob, "nationality": country, "residence_country": country, "city": "Example City",
        "address": f"{n} Example Street", "email": f"user{n}@example.com", "phone": f"+353 1 000000{n}",
        "registration_number": None,
    }
    acc = {"account_id": f"ACC-00000{n}", "customer_id": rec["record_id"], "login_handle": f"user{n}", "phone": rec["phone"]}
    onb = {"account_id": acc["account_id"], "customer_id": rec["record_id"], "kyc_applicant_id": f"APP-00000{n}", "onboarded_at": "2020-01-01"}
    kyc = {
        "check_id": f"KYC-0000C{n}", "applicant_id": f"APP-00000{n}", "provider": "Example", "verified_name": name.upper(),
        "verified_dob": dob, "document_type": "passport", "document_number": f"EX00{n}", "document_country": country,
        "result": "approved", "checked_at": "2024-01-01",
    } if check else None
    return rec, acc, onb, kyc


def hit(n, alert, name, dobs, countries, entity="Individual", life="Alive", deceased=None):
    return {
        "hit_id": f"H-0000B{n}", "alert_id": alert, "match_score": 90, "entity_type": entity, "name": name, "aliases": [],
        "dobs": dobs, "nationality": [], "citizenship": [], "countries": countries, "addresses": [], "categories": ["PEP"],
        "primary_category": "PEP", "profile_notes": None, "life_status": life, "deceased_date": deceased,
    }


def alert(n, acc, name, dob, country, hit_ids):
    return {
        "alert_id": f"A-0000A{n}", "screened_at": "2026-02-01",
        "customer": {"name": name, "entity_type": "Individual", "dob": dob, "country": country, "city": "Example City"},
        "account_ref": acc, "login_handle": None, "email": None, "hit_ids": hit_ids,
    }


def write_data(data):
    people = [
        person(1, "Jane Example", "1990-04-02", "Ireland"),
        person(2, "Marlo Fictus", "1975-09-30", "Portugal"),
        person(3, "Tamsin Grovewell", "1988-01-15", "United Kingdom", check=False),
    ]
    hits = [
        hit(1, "A-0000A1", "Example, Oliver", ["1961-07-15"], ["Canada"]),
        hit(2, "A-0000A1", "Jane Example Holdings Ltd", [], ["Ireland"], entity="Company"),
        hit(3, "A-0000A2", "Fictus, Marlo", ["1975-09-30"], ["Portugal"]),
        hit(4, "A-0000A2", "Marlo Fictus", [], []),
        hit(5, "A-0000A3", "Tamsin Grovewell", [], []),
        hit(6, "A-0000A3", "Tamsin Grovewell", [], [], life="Deceased", deceased="2001-03-01"),
        hit(7, "A-0000A4", "Nobody Known", ["1950-01-01"], ["Chile"]),
        hit(8, "A-0000A5", "Example, Jane", ["1944-02-02"], ["Peru"]),
    ]
    alerts = [
        alert(1, "ACC-000001", "Jane Example", "1990-04-02", "Ireland", ["H-0000B1", "H-0000B2"]),
        alert(2, "ACC-000002", "Marlo Fictus", "1975-09-30", "Portugal", ["H-0000B3", "H-0000B4"]),
        alert(3, "ACC-000003", "Tamsin Grovewell", "1988-01-15", "United Kingdom", ["H-0000B5", "H-0000B6"]),
        alert(4, "ACC-999999", "Nobody Known", None, None, ["H-0000B7"]),
        # H-0000B9 is listed but has no hit record: the pipeline marks it not decided.
        alert(5, "ACC-000001", "Jane Example", "1990-04-02", "Ireland", ["H-0000B8", "H-0000B9"]),
    ]

    def dump(name, rows):
        with open(os.path.join(data, name), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    dump("customers.jsonl", [p[0] for p in people])
    dump("accounts.jsonl", [p[1] for p in people])
    dump("onboarding.jsonl", [p[2] for p in people])
    dump("kyc_checks.jsonl", [p[3] for p in people if p[3]])
    dump("notes.jsonl", [])
    dump("hits.jsonl", hits)
    dump("search_results.jsonl", [])
    dump("alerts.jsonl", alerts)
    with open(os.path.join(data, "name_variants.json"), "w", encoding="utf-8") as handle:
        json.dump(VARIANTS, handle)


REWRITES = [
    (re.compile(r"\bCUS-99900(\d)\b"), r"CUS-SYN00\1"),
    (re.compile(r"\bKYC-0000C(\d)\b"), r"KYC-SYN10\1"),
    (re.compile(r"\bH-0000B(\d)\b"), r"H-SYN10\1"),
    (re.compile(r"\bA-0000A(\d)\b"), r"A-SYN10\1"),
]


def rewrite(text):
    for pattern, repl in REWRITES:
        text = pattern.sub(repl, text)
    return text


def main():
    repo, out = sys.argv[1], sys.argv[2]
    data = os.path.join(out, "data")
    os.makedirs(data, exist_ok=True)
    write_data(data)
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "SANCTIONS_LLM": "0", "USE_LLM_NOTES": "0", "USE_LLM_HITS": "0", "USE_LLM_VETO": "0",
                "SANCTIONS_CACHE": os.path.join(out, "cache"), "TRACE_PATH": os.path.join(out, "trace.raw.jsonl")})
    run = subprocess.run([os.path.join(repo, "system", "run"), data, os.path.join(out, "output.jsonl")],
                         capture_output=True, text=True, env=env)
    if run.returncode != 0:
        sys.stderr.write(run.stderr)
        return run.returncode
    for src, dst in (("trace.raw.jsonl", "trace.jsonl"), ("data/alerts.jsonl", "alerts.jsonl")):
        with open(os.path.join(out, src), encoding="utf-8") as handle:
            text = rewrite(handle.read())
        with open(os.path.join(out, dst), "w", encoding="utf-8") as handle:
            handle.write(text)
    print(f"trace written to {os.path.join(out, 'trace.jsonl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
