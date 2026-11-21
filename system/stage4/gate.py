"""Pre-clearance safety gate. Missing or model-read evidence blocks a clear.

It never creates a clearance and it never turns a confirmation into a clear.
An LLM-read fact blocks every code it feeds, even when an upstream flag says
that fact may solely support ``DIFFERENT_ENTITY``.
"""

from __future__ import annotations

from dataclasses import dataclass

from stage4.compare import type_contradicts
from stage4.model import Comparison

ALL_C = "ALL_C"
_CUSTOMER_CODES = frozenset({
    "TEMPORAL_IMPOSSIBILITY",
    "DOB_MISMATCH",
    "NAME_MISMATCH_VERIFIED",
    "LOCATION_MISMATCH",
})


@dataclass
class GateContext:
    hit: dict
    person: dict
    resolution: dict
    candidate: dict | None
    cmp: Comparison
    alert: dict


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reasons: list


def _issues(ctx: GateContext) -> set[str]:
    return set(ctx.cmp.issues)


def _person_flags(ctx: GateContext) -> set[str]:
    return set((ctx.person or {}).get("flags") or [])


def _contracts(ctx: GateContext) -> dict:
    return (ctx.person or {}).get("contracts") or {}


def _fragility(ctx: GateContext) -> set[str]:
    if ctx.candidate is not None:
        return set(ctx.candidate.get("fragility_flags") or [])
    return set((ctx.resolution or {}).get("fragility_flags") or [])


def _alert_flags(ctx: GateContext) -> set[str]:
    return set((ctx.resolution or {}).get("flags") or [])


def _quality(ctx: GateContext) -> str:
    return str((ctx.resolution or {}).get("resolution_quality") or "")


def _blocks(spec: frozenset, code: str, ctx: GateContext) -> bool:
    codes = set(spec)
    if ALL_C in codes:
        codes.discard(ALL_C)
        codes.update(_CUSTOMER_CODES)
        screened = ((ctx.alert or {}).get("customer") or {}).get("entity_type")
        # TYPE is part of ALL-C unless the screened type already differs from the hit.
        if not type_contradicts(screened, (ctx.hit or {}).get("entity_type")):
            codes.add("ENTITY_TYPE_MISMATCH")
    return code in codes


def _llm(ctx: GateContext, code: str) -> bool:
    return bool(ctx.cmp.dim(code).llm_used)


def _may_not_clear_name(ctx: GateContext, _code: str) -> bool:
    return "NAME_MAY_NOT_CLEAR" in _issues(ctx)


def _may_not_clear_dob(ctx: GateContext, _code: str) -> bool:
    return "DOB_MAY_NOT_CLEAR" in _issues(ctx) or bool(ctx.cmp.dob.detail.get("may_not_clear"))


def _flag(names: set[str]):
    def present(ctx: GateContext, _code: str) -> bool:
        flags = _person_flags(ctx)
        if flags & names:
            return True
        return any(str(flag).startswith("NOTE_FLAGGED:") for flag in flags) and "NOTE_FLAGGED" in names
    return present


def _legal(ctx: GateContext) -> dict:
    return (ctx.person or {}).get("legal_name") or {}


def _name_unverified(ctx: GateContext, _code: str) -> bool:
    """The UNVERIFIED flag is also set for a missing date of birth, so the name gate reads the legal name."""
    flags = _person_flags(ctx)
    if "BLOCK_NAME_MISMATCH_VERIFIED" in flags:
        return True
    legal = _legal(ctx)
    return legal.get("verified") is not True


def _name_short(ctx: GateContext, _code: str) -> bool:
    flags = _person_flags(ctx)
    if flags & {"BLOCK_NAME_CLEAR", "NAME_TOO_SHORT"}:
        return True
    legal = _legal(ctx)
    if legal.get("blocks_name_clear"):
        return True
    if legal.get("verified"):
        return False
    return any(entry.get("blocks_name_clear") for entry in (ctx.person or {}).get("names_all") or [])


def _screened_disagrees(ctx: GateContext) -> bool:
    screened = ((ctx.alert or {}).get("customer") or {}).get("entity_type")
    customer = ctx.cmp.entity_type.customer
    return bool(screened and customer and screened != customer)


# One row per gate. ``blocks`` lists reason codes, or ALL_C for the customer-fact set.
GATE_TABLE = (
    ("LLM_FACT", frozenset({
        "ENTITY_TYPE_MISMATCH", "DECEASED", "TEMPORAL_IMPOSSIBILITY",
        "DOB_MISMATCH", "NAME_MISMATCH_VERIFIED", "LOCATION_MISMATCH",
    }), _llm),
    ("NAME_MAY_NOT_CLEAR", frozenset({"NAME_MISMATCH_VERIFIED"}), _may_not_clear_name),
    ("DOB_MAY_NOT_CLEAR", frozenset({"DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"}), _may_not_clear_dob),
    ("BLOCK_NAME_MISMATCH_VERIFIED", frozenset({"NAME_MISMATCH_VERIFIED"}), _name_unverified),
    ("BLOCK_NAME_CLEAR", frozenset({"NAME_MISMATCH_VERIFIED"}), _name_short),
    ("BLOCK_DOB_AGE_NAME_CLEAR", frozenset({
        "DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY", "NAME_MISMATCH_VERIFIED",
    }), _flag({"BLOCK_DOB_AGE_NAME_CLEAR"})),
    ("BLOCK_LOCATION_MISMATCH", frozenset({"LOCATION_MISMATCH"}), _flag({
        "BLOCK_LOCATION_MISMATCH", "UNMAPPED_COUNTRY", "NOTE_FLAGGED",
    })),
    ("MULTI_VERIFICATION_CONFLICT", frozenset({
        "DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY", "NAME_MISMATCH_VERIFIED",
    }), _flag({"MULTI_VERIFICATION_CONFLICT"})),
    ("TYPE_CONFLICT", frozenset({"ENTITY_TYPE_MISMATCH"}), _flag({"TYPE_CONFLICT"})),
    ("DECLARED_DOB_AGREES", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "DECLARED_DOB_AGREES" in _issues(ctx)),
    ("NOTE_DOB_UNRESOLVED", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "NOTE_DOB_UNRESOLVED" in _issues(ctx)),
    ("HIT_UNPARSED_DATE", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "HIT_UNPARSED_DATE" in _issues(ctx)),
    ("WEAK_DOB_RULE", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "WEAK_DOB_RULE" in _issues(ctx)),
    ("BORN_CUE_SEARCH_DOB", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "BORN_CUE_SEARCH_DOB" in _issues(ctx)),
    ("LLM_DOB_UNKNOWN", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "LLM_DOB_UNKNOWN" in _issues(ctx)),
    ("MULTI_SR_CONFLICT", frozenset({"DOB_MISMATCH"}), lambda ctx, _code: "MULTI_SR_CONFLICT" in _issues(ctx)),
    ("NON_EXHAUSTIVE_NAME", frozenset({"NAME_MISMATCH_VERIFIED"}), lambda ctx, _code: "NON_EXHAUSTIVE_NAME" in _issues(ctx)),
    ("NON_EXHAUSTIVE_BLOCKS_LOCATION", frozenset({"LOCATION_MISMATCH"}), lambda ctx, _code: "NON_EXHAUSTIVE_BLOCKS_LOCATION" in _issues(ctx)),
    ("NAME_ORDER_DEPENDENT", frozenset({"NAME_MISMATCH_VERIFIED"}), lambda ctx, _code: "NAME_ORDER_DEPENDENT" in _issues(ctx)),
    ("HIT_UNMAPPED_COUNTRY", frozenset({"LOCATION_MISMATCH"}), lambda ctx, _code: "HIT_UNMAPPED_COUNTRY" in _issues(ctx)),
    ("NON_LATIN_ALIAS", frozenset({"NAME_MISMATCH_VERIFIED"}), lambda ctx, _code: "NON_LATIN_ALIAS" in _issues(ctx)),
    ("SCREENED_TYPE_DISAGREES", frozenset({"ENTITY_TYPE_MISMATCH"}), lambda ctx, _code: _screened_disagrees(ctx)),
    ("LINK_SUSPECT", frozenset({ALL_C}), lambda ctx, _code: _quality(ctx) == "LINK_SUSPECT" or "link_contradicts_screened" in _fragility(ctx)),
    ("DANGLING_LINK", frozenset({ALL_C}), lambda ctx, _code: _quality(ctx) == "DANGLING_LINK_fallback" or "DANGLING_LINK" in _alert_flags(ctx)),
    ("name_match_fuzzy_only", frozenset({ALL_C}), lambda ctx, _code: "name_match_fuzzy_only" in _fragility(ctx)),
    ("resolved_via_note_country", frozenset({ALL_C}), lambda ctx, _code: "resolved_via_note_country" in _fragility(ctx)),
    ("joint_account_tiebreak", frozenset({ALL_C}), lambda ctx, _code: "joint_account_tiebreak" in _fragility(ctx)),
    ("candidate_kept_on_missing_field", frozenset({ALL_C}), lambda ctx, _code: (
        "candidate_kept_on_missing_field" in _fragility(ctx) or "RECORD_DOB_MISSING_KEPT" in _alert_flags(ctx)
    )),
    ("dob_partial_only", frozenset({"DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"}), lambda ctx, _code: "dob_partial_only" in _fragility(ctx)),
    ("SCREENED_NAME_TOO_SHORT", frozenset({"NAME_MISMATCH_VERIFIED"}), lambda ctx, _code: "NAME_TOO_SHORT" in _alert_flags(ctx)),
    ("contract_block_name", frozenset({"NAME_MISMATCH_VERIFIED"}), lambda ctx, _code: bool(
        _contracts(ctx).get("block_name_mismatch_verified") or _contracts(ctx).get("block_name_clear")
    )),
    ("contract_block_dob", frozenset({"DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY", "NAME_MISMATCH_VERIFIED"}), lambda ctx, _code: bool(
        _contracts(ctx).get("block_dob_age_name_clear")
    )),
    ("contract_block_location", frozenset({"LOCATION_MISMATCH"}), lambda ctx, _code: bool(_contracts(ctx).get("block_location_mismatch"))),
)


def gate(code: str, ctx: GateContext, disabled: frozenset[str] | None = None) -> GateResult:
    """Return whether ``code`` may clear. Reasons are sorted flag names."""
    skipped = disabled or frozenset()
    reasons = []
    for name, blocks, present in GATE_TABLE:
        if name in skipped:
            continue
        if not _blocks(blocks, code, ctx):
            continue
        try:
            fired = present(ctx, code)
        except Exception:
            fired = True
        if fired:
            reasons.append(name)
    # A verified legal name that simply has not been checked is already
    # covered by BLOCK_NAME_MISMATCH_VERIFIED. An unverified name must not
    # be blocked twice by the contract row when the contract mirrors that
    # flag. Both names in the reason list are fine: they are sorted.
    return GateResult(ok=not reasons, reasons=sorted(set(reasons)))


def gate_words(reasons: list[str]) -> str:
    """One honest clause for a downgraded clearance."""
    phrases = {
        "LLM_FACT": "a fact was read by the model and cannot clear a hit",
        "DECLARED_DOB_AGREES": "another date the customer declared agrees with the hit",
        "BLOCK_LOCATION_MISMATCH": "one of the customer's notes could not be read for countries",
        "HIT_UNMAPPED_COUNTRY": "a country on the hit could not be mapped",
        "NON_LATIN_ALIAS": "the hit has a name in a script we do not compare",
        "NAME_ORDER_DEPENDENT": "the name comparison depends on which name is read first",
        "NON_EXHAUSTIVE_NAME": "the name comparison was not exhaustive",
        "joint_account_tiebreak": "the customer was chosen from a joint account by a tie-break",
        "candidate_kept_on_missing_field": "the customer was kept despite a missing screened field",
        "name_match_fuzzy_only": "the customer was matched only through a spelling variant",
        "dob_partial_only": "the screened date of birth matched only in part",
        "LINK_SUSPECT": "the alert link contradicts the screened details",
        "DANGLING_LINK": "the alert link does not point at a customer record",
        "resolved_via_note_country": "the customer was reached only through a country in a note",
        "BLOCK_NAME_CLEAR": "the customer's name has too few real parts to compare",
        "SCREENED_NAME_TOO_SHORT": "the screened name has too few real parts to compare",
        "BLOCK_DOB_AGE_NAME_CLEAR": "a verification note could not be fully read",
        "DOB_MAY_NOT_CLEAR": "the customer's date of birth is not a fact we can clear on",
        "NAME_MAY_NOT_CLEAR": "the customer's name is not a fact we can clear on",
        "WEAK_DOB_RULE": "a birth year on the hit came from a weak age pattern",
        "BORN_CUE_SEARCH_DOB": "the hit's profile mentions a birth fact the search result may have missed",
        "MULTI_SR_CONFLICT": "the hit's search results disagree on the birth year",
        "NOTE_DOB_UNRESOLVED": "a birth cue in the hit's profile could not be read",
        "SCREENED_TYPE_DISAGREES": "the screened entity type disagrees with the resolved customer",
    }
    if not reasons:
        return "the evidence is not strong enough to clear"
    return phrases.get(reasons[0], reasons[0].replace("_", " ").lower())
