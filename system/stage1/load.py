"""JSONL loader for the customer-side tables. Reads only the given folder."""

from __future__ import annotations

import json
import os


STAGE1_FILES = (
    "customers.jsonl",
    "accounts.jsonl",
    "onboarding.jsonl",
    "kyc_checks.jsonl",
    "notes.jsonl",
    "name_variants.json",
)


class DataStore:
    """Small interface over a data folder of JSONL files plus ``name_variants.json``."""

    def __init__(self, folder: str):
        self.folder = folder

    def path(self, name: str) -> str:
        return os.path.join(self.folder, name)

    def read_jsonl(self, name: str) -> list[dict]:
        path = self.path(name)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        rows: list[dict] = []
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def read_json(self, name: str) -> dict:
        path = self.path(name)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def load_stage1(self) -> dict:
        return {
            "customers": self.read_jsonl("customers.jsonl"),
            "accounts": self.read_jsonl("accounts.jsonl"),
            "onboarding": self.read_jsonl("onboarding.jsonl"),
            "kyc_checks": self.read_jsonl("kyc_checks.jsonl"),
            "notes": self.read_jsonl("notes.jsonl"),
            "name_variants": self.read_json("name_variants.json"),
        }
