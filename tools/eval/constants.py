"""Shared constants for the sanctions screening eval harness."""

from __future__ import annotations

from pathlib import Path

# The official data folder (never committed; see .gitignore). Labels and name
# variants default to files inside it.
DEFAULT_DATA_DIR = Path("dev")
LABELS_FILENAME = "practice_labels.jsonl"
NAME_VARIANTS_FILENAME = "name_variants.json"

DECISIONS = ("SAME_ENTITY", "DIFFERENT_ENTITY", "REVIEW")
DEFINITIVE_DECISIONS = frozenset({"SAME_ENTITY", "DIFFERENT_ENTITY"})

REASON_CODES_BY_DECISION: dict[str, tuple[str, ...]] = {
    "DIFFERENT_ENTITY": (
        "TEMPORAL_IMPOSSIBILITY",
        "DOB_MISMATCH",
        "LOCATION_MISMATCH",
        "NAME_MISMATCH_VERIFIED",
        "ENTITY_TYPE_MISMATCH",
        "DECEASED",
    ),
    "SAME_ENTITY": (
        "NAME_DOB_LOCATION_MATCH",
        "NAME_DOB_MATCH",
        "NAME_LOCATION_MATCH",
    ),
    "REVIEW": (
        "INSUFFICIENT_DATA",
        "AMBIGUOUS_CUSTOMER_RECORD",
    ),
}
ALL_REASON_CODES = frozenset(c for cs in REASON_CODES_BY_DECISION.values() for c in cs)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "hit_id": ("hit_id", "hitId", "id"),
    "alert_id": ("alert_id", "alertId"),
    "decision": ("decision", "verdict"),
    "reason_code": ("reason_code", "reason_codes", "reasonCode", "reasonCodes"),
    "evidence": (
        "evidence",
        "cited_ids",
        "cited_record_ids",
        "citations",
        "cited_records",
        "record_ids",
    ),
    "customer_record_id": (
        "customer_record_id",
        "customer_record_ids",
        "customerRecordId",
        "customerRecordIds",
        "resolved_customer_id",
    ),
    "explanation": (
        "explanation",
        "reason",
        "reference_reason",
        "rationale",
        "reason_text",
    ),
}

PLACEHOLDERS = frozenset({
    "na", "n/a", "n.a", "n.a.", "test", "unknown", "unk", "xxx", "xxxx",
    "none", "null", "nil", "tbd", "dummy", "missing", "placeholder",
})

GENERIC_TOKENS = frozenset({
    "the", "and", "or", "for", "with", "from", "that", "this", "hit",
    "customer", "name", "date", "birth", "linked", "only", "both",
    "agrees", "agree", "record", "records", "nothing", "cannot",
    "cleared", "confirmed", "decision", "entity", "person", "company",
    "listed", "profile", "notes", "check", "approved", "verified",
})

TERRITORIES = frozenset({
    "hong kong", "hong-kong", "macau", "macao", "taiwan", "puerto rico",
    "guam", "american samoa", "us virgin islands", "u.s. virgin islands",
    "united states virgin islands", "british virgin islands", "cayman islands",
    "bermuda", "gibraltar", "isle of man", "jersey", "guernsey", "greenland",
    "faroe islands", "aruba", "curacao", "curaçao", "sint maarten",
    "saint martin", "martinique", "guadeloupe", "reunion", "réunion",
    "mayotte", "new caledonia", "french polynesia", "french guiana",
    "falkland islands", "cook islands", "northern mariana islands", "kosovo",
    "palestine", "palestinian territories", "state of palestine",
    "west bank", "gaza", "western sahara", "aland", "åland", "svalbard",
    "tokelau", "niue", "anguilla", "montserrat", "turks and caicos",
    "turks and caicos islands", "saint barthelemy", "saint barthélemy",
    "saint pierre and miquelon", "wallis and futuna",
    "british indian ocean territory", "christmas island", "cocos islands",
    "norfolk island", "taiwan, province of china", "hong kong sar",
    "macao sar", "macau sar",
})

PATH_CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("link_account_ref", r"\baccount_ref\b"),
    ("link_login_handle", r"\blogin_handle\b"),
    ("link_email", r"(?:^|->|→)\s*email\b"),
    ("link_unlinked", r"name,\s*date of birth, country and city"),
    ("kyc", r"\bkyc-|\bapproved check\b|\bkyc\b"),
    ("notes", r"\bnotes\b|NOTE-"),
    ("one_person_merge", r"one person:|same phone and date of birth|same document number"),
    ("search_results", r"search result|SR-"),
    ("joint_holders", r"joint holder"),
    ("multi_person_fit", r"different people fit|each is decided separately"),
)

PATH_CATEGORY_LABELS = {
    "link_account_ref": "link: account_ref",
    "link_login_handle": "link: login_handle",
    "link_email": "link: email",
    "link_unlinked": "link: unlinked (name, date of birth, country and city)",
    "kyc": "KYC (latest approved check)",
    "notes": "notes",
    "one_person_merge": "one-person merge (shared phone+DOB or document number)",
    "search_results": "search results",
    "joint_holders": "joint holders",
    "multi_person_fit": "multi-person fit (several people; each decided separately)",
}

PATH_CATEGORY_ORDER = [
    "link_account_ref", "link_login_handle", "link_email", "link_unlinked",
    "kyc", "notes", "one_person_merge", "search_results", "joint_holders", "multi_person_fit",
]

EDGE_TAG_LABELS = {
    "placeholder_names": "placeholder names",
    "joined_name_parts": "joined name parts",
    "name_variants": "name variants",
    "territories": "territories",
    "multi_person_matches": "multi-person matches",
}

NULL_VALUES = frozenset({"", "null", "none", "nil", "n/a"})
AMBIGUOUS_VALUES = frozenset({"ambiguous"})

DEFAULT_LEGAL_FORMS = {
    "ab", "ag", "as", "asa", "bv", "co", "company", "corp", "corporation",
    "gmbh", "inc", "kg", "limited", "llc", "llp", "lp", "ltd", "na", "nv",
    "oy", "oyj", "plc", "sa", "sarl", "sas", "se", "sf", "sl", "spa", "srl",
}

# Official decision costs from the brief, section 6: (truth, predicted) -> cost.
# Lower is better. Unsafe clearances (SAME or REVIEW predicted as DIFFERENT_ENTITY) cost 60.
DECISION_COSTS: dict[tuple[str, str], int] = {
    ("DIFFERENT_ENTITY", "DIFFERENT_ENTITY"): 0,
    ("DIFFERENT_ENTITY", "SAME_ENTITY"): 3,
    ("DIFFERENT_ENTITY", "REVIEW"): 3,
    ("SAME_ENTITY", "DIFFERENT_ENTITY"): 60,
    ("SAME_ENTITY", "SAME_ENTITY"): 0,
    ("SAME_ENTITY", "REVIEW"): 2,
    ("REVIEW", "DIFFERENT_ENTITY"): 60,
    ("REVIEW", "SAME_ENTITY"): 2,
    ("REVIEW", "REVIEW"): 0,
}
