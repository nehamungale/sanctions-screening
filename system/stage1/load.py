"""Customer-side tables, read through ``shared.io`` (optional files read as empty)."""

from __future__ import annotations

from shared.io import load_table, load_variants


class DataStore:
    """Small interface over a data folder of JSONL files plus ``name_variants.json``."""

    def __init__(self, folder: str):
        self.folder = folder

    def read_jsonl(self, name: str) -> list[dict]:
        return load_table(self.folder, name)

    def read_json(self, name: str) -> dict:
        if name != "name_variants.json":
            raise ValueError(name)
        return load_variants(self.folder)

    def load_stage1(self) -> dict:
        return {
            "customers": self.read_jsonl("customers.jsonl"),
            "accounts": self.read_jsonl("accounts.jsonl"),
            "onboarding": self.read_jsonl("onboarding.jsonl"),
            "kyc_checks": self.read_jsonl("kyc_checks.jsonl"),
            "notes": self.read_jsonl("notes.jsonl"),
            "name_variants": load_variants(self.folder),
        }
