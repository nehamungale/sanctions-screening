"""Optional veto. Off unless SANCTIONS_LLM=1 and USE_LLM_VETO=1.

It may turn DIFFERENT_ENTITY into REVIEW. It cannot create a clearance,
change SAME_ENTITY, or change a reason code it does not veto.
"""

from __future__ import annotations

import os

from shared.time_budget import VETO_MAX_HITS

PROMPT_VERSION = "veto-1"
_VETO_CODES = {"LOCATION_MISMATCH", "DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"}
_RANK = {"borderline": 0, "thin": 1, "solid": 2}


def enabled() -> bool:
    return (
        os.environ.get("SANCTIONS_LLM") == "1"
        and os.environ.get("USE_LLM_VETO") == "1"
        and bool(os.environ.get("OPENROUTER_API_KEY"))
    )


def apply_veto(items: list[dict], transport=None, budget: int | None = None) -> list[dict]:
    """``items`` are ``{decision, texts}`` in hit_id order. Returns the same list.

    ``transport(text) -> dict`` is the test double. Three identical replies
    that quote ``texts`` and undermine the contradiction become REVIEW.
    """
    if transport is None and not enabled():
        return items
    limit = VETO_MAX_HITS if budget is None else budget
    ranked = sorted(
        (item for item in items if _eligible(item)),
        key=lambda item: (_RANK.get(item["decision"].fragility, 9), item["decision"].record or "", item["hit_id"]),
    )
    # Stable hit order is the tie-break. Fragility rank is the primary key.
    ranked.sort(key=lambda item: (_RANK.get(item["decision"].fragility, 9), item["hit_id"]))
    for index, item in enumerate(ranked):
        decision = item["decision"]
        if index >= limit:
            item["veto"] = "skipped_budget"
            continue
        outcome = _ask(item.get("texts") or {}, transport)
        item["llm_calls"] = outcome["calls"]
        if outcome["veto"]:
            decision.decision = "REVIEW"
            decision.reason_code = "INSUFFICIENT_DATA"
            decision.kind = "review_veto"
            decision.llm_used = True
            decision.missing = "a note may mention a further country or date"
            decision.reason = (
                "A note may mention a further country or date, so the contradiction is not used. "
                "The hit is left for review."
            )
            if outcome.get("source_id"):
                decision.evidence = sorted(set(decision.evidence + [outcome["source_id"]]))
            item["veto"] = "vetoed"
        else:
            item["veto"] = "none"
    return items


def _eligible(item: dict) -> bool:
    decision = item["decision"]
    return decision.decision == "DIFFERENT_ENTITY" and decision.reason_code in _VETO_CODES


def _ask(texts: dict, transport) -> dict:
    if transport is None:
        return {"veto": False, "calls": []}
    ballots = []
    calls = []
    for _vote in range(3):
        try:
            reply = transport(texts)
        except Exception:
            return {"veto": False, "calls": calls}
        if not isinstance(reply, dict):
            return {"veto": False, "calls": calls}
        calls.append({"prompt_version": PROMPT_VERSION, "found": reply.get("found")})
        ballots.append(json_key(reply))
    if len(set(ballots)) != 1:
        return {"veto": False, "calls": calls}
    reply = transport(texts) if False else _decode(ballots[0])
    if not reply.get("found"):
        return {"veto": False, "calls": calls}
    source = str(reply.get("source_id") or "")
    quote = reply.get("quote") or ""
    body = texts.get(source) or ""
    if not quote or quote not in body:
        return {"veto": False, "calls": calls}
    return {"veto": True, "calls": calls, "source_id": source}


def json_key(reply: dict) -> str:
    import json
    kept = {key: reply.get(key) for key in ("found", "kind", "source_id", "quote")}
    return json.dumps(kept, sort_keys=True, separators=(",", ":"))


def _decode(blob: str) -> dict:
    import json
    return json.loads(blob)
