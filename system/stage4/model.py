"""Shared decision objects. No I/O."""

from __future__ import annotations

from dataclasses import dataclass, field

AGREE = "AGREE"
CONTRADICT = "CONTRADICT"
UNKNOWN = "UNKNOWN"

PRIORITY = (
    "ENTITY_TYPE_MISMATCH",
    "DECEASED",
    "TEMPORAL_IMPOSSIBILITY",
    "DOB_MISMATCH",
    "NAME_MISMATCH_VERIFIED",
    "LOCATION_MISMATCH",
)

DIFFERENT_CODES = frozenset(PRIORITY)
SAME_INDIVIDUAL = ("NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH")
SAME_COMPANY = "NAME_LOCATION_MATCH"
RULES_VERSION = "stage4-r1"

OUTPUT_KEYS = (
    "hit_id",
    "alert_id",
    "decision",
    "reason_code",
    "customer_record_id",
    "reason",
    "evidence",
)


@dataclass
class Dim:
    status: str = UNKNOWN
    customer: object = None
    hit: object = None
    sources: list = field(default_factory=list)
    llm_used: bool = False
    detail: dict = field(default_factory=dict)


@dataclass
class Comparison:
    entity_type: Dim = field(default_factory=Dim)
    death: Dim = field(default_factory=Dim)
    time: Dim = field(default_factory=Dim)
    dob: Dim = field(default_factory=Dim)
    name: Dim = field(default_factory=Dim)
    location: Dim = field(default_factory=Dim)
    issues: list = field(default_factory=list)
    person_type: str | None = None

    def dim(self, code: str) -> Dim:
        return {
            "ENTITY_TYPE_MISMATCH": self.entity_type,
            "DECEASED": self.death,
            "TEMPORAL_IMPOSSIBILITY": self.time,
            "DOB_MISMATCH": self.dob,
            "NAME_MISMATCH_VERIFIED": self.name,
            "LOCATION_MISMATCH": self.location,
        }[code]

    def contradiction(self, code: str) -> bool:
        if code == "NAME_MISMATCH_VERIFIED":
            return self.name.detail.get("clear_status") == CONTRADICT
        return self.dim(code).status == CONTRADICT


@dataclass
class Decision:
    """One hit against one person, before ambiguity combination."""

    decision: str
    reason_code: str
    record: str | None = None
    reason: str = ""
    evidence: list = field(default_factory=list)
    passed: list = field(default_factory=list)
    fired: list = field(default_factory=list)
    blocked: dict = field(default_factory=dict)
    cmp: Comparison | None = None
    missing: str = ""
    fragility: str = "thin"
    llm_used: bool = False
    not_decided: bool = False
    errored: bool = False
    kind: str = "review"
    gate_note: str = ""
    screened_gaps: list = field(default_factory=list)
    person_id: str | None = None
    matched_records: list = field(default_factory=list)
    alternatives: list = field(default_factory=list)

    def finish(self, record: str | None) -> "Decision":
        self.record = record
        return self
