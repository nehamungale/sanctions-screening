"""Exhaustive one-to-one name agreement.

Both the customer golden record and the hit track should call ``agree_parts``.
Greedy longest-first matching can accept a long join that blocks two shorter
matches, so names that agree under the SOP look like they do not. This search
tries every non-overlapping pairing. Written-together and written-apart joins
are generated on both sides, and a join may run across a variant group
(``yusuf`` + ``smith`` agrees with ``josephsmith``).

Tie-break, in order: a pairing that agrees, then more matches, then more
covered parts, then the lexicographically smaller pair list. The search order
is fixed, so the result does not depend on hash randomisation.
"""

from __future__ import annotations

from collections.abc import Callable

PartsMatch = Callable[[str, str], bool]
_NODE_CAP = 250_000


def agree_parts(left: list[str], right: list[str], parts_match: PartsMatch) -> dict:
    """Return ``{agree, matched_pairs, reason, exhaustive}``."""
    if not left or not right:
        return {"agree": False, "matched_pairs": [], "reason": "no agree", "exhaustive": True}
    shorter = len(left) if len(left) <= len(right) else len(right)
    shorter_is_left = len(left) <= len(right)
    targets = [(index,) for index in range(len(right))]
    targets += [(index, index + 1) for index in range(len(right) - 1)]
    best: dict = {"key": None, "pairs": ()}
    nodes = {"n": 0, "capped": False}

    def consider(matches: int, cov_left: int, cov_right: int, pairs: tuple[str, ...]) -> None:
        # Equal lengths: either side being fully covered is agreement, so
        # 'Abdulsalam Zed' agrees with 'Abdul Salam' and the swap does too.
        if len(left) == len(right):
            either = len(left) > 0 and (cov_left == len(left) or cov_right == len(right))
            agree = matches >= 2 or either
        else:
            shorter_cov = cov_left if shorter_is_left else cov_right
            agree = matches >= 2 or (shorter > 0 and shorter_cov == shorter)
        key = (1 if agree else 0, matches, cov_left + cov_right, pairs)
        current = best["key"]
        if current is None or key[0] > current[0] or (
            key[0] == current[0] and (key[1] > current[1] or (
                key[1] == current[1] and (key[2] > current[2] or (key[2] == current[2] and key[3] < current[3]))
            ))
        ):
            best["key"] = key
            best["pairs"] = pairs

    def rec(index: int, mask: int, matches: int, cov_left: int, cov_right: int, pairs: tuple[str, ...]) -> None:
        nodes["n"] += 1
        if nodes["n"] > _NODE_CAP:
            nodes["capped"] = True
            return
        if index >= len(left):
            consider(matches, cov_left, cov_right, pairs)
            return
        rec(index + 1, mask, matches, cov_left, cov_right, pairs)
        if nodes["capped"]:
            return
        _try(index, (index,), mask, matches, cov_left, cov_right, pairs)
        if index + 1 < len(left) and not nodes["capped"]:
            _try(index, (index, index + 1), mask, matches, cov_left, cov_right, pairs)

    def _try(index, cover, mask, matches, cov_left, cov_right, pairs) -> None:
        for target in targets:
            bits = 0
            for part in target:
                bits |= 1 << part
            if mask & bits:
                continue
            if not _covers_match(left, cover, right, target, parts_match):
                continue
            label = f"{''.join(left[part] for part in cover)}={''.join(right[part] for part in target)}"
            rec(
                index + len(cover),
                mask | bits,
                matches + 1,
                cov_left + len(cover),
                cov_right + len(target),
                pairs + (label,),
            )
            if nodes["capped"]:
                return

    consider(0, 0, 0, ())
    rec(0, 0, 0, 0, 0, ())
    key = best["key"]
    pairs = list(best["pairs"])
    agree = bool(key[0]) if key else False
    match_count = key[1] if key else 0
    if not agree:
        reason = "no agree"
    elif match_count >= 2:
        reason = f"{match_count} parts"
    else:
        reason = "shorter covered"
    return {
        "agree": agree,
        "matched_pairs": pairs,
        "reason": reason,
        "exhaustive": not nodes["capped"],
    }


def _covers_match(left, left_idx, right, right_idx, parts_match: PartsMatch) -> bool:
    left_parts = [left[index] for index in left_idx]
    right_parts = [right[index] for index in right_idx]
    if len(left_parts) == 1 and len(right_parts) == 1:
        return parts_match(left_parts[0], right_parts[0])
    if len(left_parts) == 2 and len(right_parts) == 1:
        return _join_matches(left_parts[0], left_parts[1], right_parts[0], parts_match)
    if len(left_parts) == 1 and len(right_parts) == 2:
        return _join_matches(right_parts[0], right_parts[1], left_parts[0], parts_match)
    return (
        (parts_match(left_parts[0], right_parts[0]) and parts_match(left_parts[1], right_parts[1]))
        or parts_match(left_parts[0] + left_parts[1], right_parts[0] + right_parts[1])
        or _join_matches(left_parts[0], left_parts[1], right_parts[0] + right_parts[1], parts_match)
        or _join_matches(right_parts[0], right_parts[1], left_parts[0] + left_parts[1], parts_match)
    )


def _join_matches(first: str, second: str, whole: str, parts_match: PartsMatch) -> bool:
    """A two-part name matches one token, including across a variant group."""
    if parts_match(first + second, whole):
        return True
    for split in range(1, len(whole)):
        if parts_match(whole[:split], first) and parts_match(whole[split:], second):
            return True
    return False
