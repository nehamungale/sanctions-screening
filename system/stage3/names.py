"""Symmetric name agreement for Stage 3.

``shared.names.agree_parts`` currently checks full coverage of the left name
when both names have the same number of parts. A pair can therefore agree in
one argument order and not the other. Stage 3 calls it both ways and keeps the
match only when both calls agree. ``system/shared`` is not modified.
"""

from __future__ import annotations

from stage1.normalise import NameTools


def agree_symmetric(names: NameTools, left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> dict:
    """Return agreement only when both argument orders agree.

    ``matched_pairs`` come from the left-to-right call. They are empty when the
    two calls disagree, so a one-sided match cannot be cited.
    """
    forward = names.names_agree(list(left), list(right))
    backward = names.names_agree(list(right), list(left))
    agree = bool(forward["agree"] and backward["agree"])
    return {
        "agree": agree,
        "backward": bool(backward["agree"]),
        "forward": bool(forward["agree"]),
        "matched_pairs": list(forward["matched_pairs"]) if agree else [],
        "reason": forward["reason"] if agree else "asymmetric",
    }


def record_name_agrees(names: NameTools, screened_parts: tuple[str, ...] | list[str], record_names) -> bool:
    """True when any record name agrees with the screened parts in both orders."""
    if not screened_parts:
        return False
    for _field, parts in record_names:
        if parts and agree_symmetric(names, screened_parts, parts)["agree"]:
            return True
    return False
