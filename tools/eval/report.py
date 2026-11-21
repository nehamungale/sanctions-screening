"""Markdown scoreboard and JSON metrics assembly."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .constants import (
    ALL_REASON_CODES,
    DECISIONS,
    EDGE_TAG_LABELS,
    PATH_CATEGORY_LABELS,
    PATH_CATEGORY_ORDER,
)


def _pct(rate: float, num: int | None = None, den: int | None = None) -> str:
    if num is not None and den is not None:
        return f"{100 * rate:.1f}% ({num}/{den})"
    return f"{100 * rate:.1f}%"


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    if not rows:
        body = "| " + " | ".join("—" for _ in headers) + " |"
    else:
        body = "\n".join("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return "\n".join([line, sep, body])


def render_report(
    runs: list[tuple[str, list[dict[str, Any]]]],
    labels: list[dict[str, Any]],
    repro: dict[str, Any],
    explain: dict[str, Any],
    accuracy: dict[str, Any],
    analysis: dict[str, Any],
    generated_at: str,
) -> str:
    n = accuracy["n_labels"]
    lines: list[str] = []
    lines.append("# Sanctions screening — eval scoreboard")
    lines.append("")
    lines.append(f"Generated: {generated_at} (Europe/London).")
    extra = f" (plus {len(runs) - 1} further run(s) for reproducibility)." if len(runs) > 1 else "."
    lines.append(f"Graded run: `{runs[0][0]}`{extra}")
    lines.append(
        "Judging priorities: explainability first, reproducibility second, accuracy third."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    fc = accuracy["false_clears"]
    ro = accuracy["review_overuse"]
    if not repro["enough_runs"]:
        repro_s = "not evaluated (need N≥5 output files)"
        if repro["n_runs"] >= 2 and repro["n_hits_differing"]:
            repro_s += f"; already {repro['n_hits_differing']} hit(s) differ"
    elif repro["n_hits_differing"] == 0:
        repro_s = "stable across all runs"
    else:
        repro_s = f"{repro['n_hits_differing']} hit(s) differ across {repro['n_runs']} runs"
    official_repro = ""
    if repro.get("official_repro_rate") is not None and repro["n_runs"] >= 2:
        official_repro = (
            f"{_pct(repro['official_repro_rate'])} "
            f"({repro['official_repro_identical']}/{repro['n_hits_compared']} hits "
            f"have the same decision and reason code in all {repro['n_runs']} runs)"
        )
    elif repro["n_runs"] < 2:
        official_repro = "not evaluated (need N≥2 runs)"
    summary_rows = [
        ["Official decision score", (
            f"{accuracy['decision_score']:.4f} "
            f"(cost {accuracy['decision_cost']} / all-REVIEW baseline {accuracy['cost_all_review']})"
        )],
        ["Decision accuracy", _pct(accuracy["decision_accuracy"], accuracy["decision_correct"], n)],
        ["Reason code accepted", _pct(accuracy["reason_code_accepted_rate"], accuracy["reason_code_accepted"], n)],
        ["Evidence recall (macro / micro)", (
            f"{_pct(accuracy['evidence_recall_macro'])} / {_pct(accuracy['evidence_recall_micro'])}"
        )],
        ["Evidence precision (macro / micro)", (
            f"{_pct(accuracy['evidence_precision_macro'])} / {_pct(accuracy['evidence_precision_micro'])}"
        )],
        ["Hits citing extra evidence IDs", str(accuracy["n_extra_evidence_hits"])],
        ["FALSE CLEARS", f"{accuracy['n_false_clears']}" + (" — " + ", ".join(x["hit_id"] for x in fc) if fc else "")],
        ["REVIEW over-use", f"{accuracy['n_review_overuse']}" + (" — " + ", ".join(x["hit_id"] for x in ro) if ro else "")],
        ["Missing labelled hits", (
            f"{accuracy['n_missing']}"
            + (" (treated as REVIEW for the official score)" if accuracy["n_missing"] else "")
        )],
        ["Customer record ID accepted", _pct(accuracy["customer_record_id_accepted_rate"])],
        ["Official reproducibility", official_repro or repro_s],
        ["Reproducibility (field diffs)", repro_s],
        ["Explainability issues", f"{explain['n_hits_with_issues']} / {explain['n_rows']} output rows"],
        ["Empty explanations", str(len(explain["empty_explanations"]))],
        ["Unsupported citations", str(len(explain["unsupported_citations"]))],
        ["Explanations missing hit facts", str(len(explain["missing_hit_facts"]))],
        ["Boilerplate explanation groups", str(explain["boilerplate_group_count"])],
    ]
    lines.append(_md_table(["Metric", "Value"], summary_rows))
    lines.append("")

    lines.append("## Reproducibility")
    lines.append("")
    if repro.get("official_repro_rate") is not None and repro["n_runs"] >= 2:
        lines.append(
            f"Official measure: {repro['official_repro_identical']} of {repro['n_hits_compared']} hits "
            f"({_pct(repro['official_repro_rate'])}) have the same decision and reason code "
            f"in all {repro['n_runs']} runs."
        )
        lines.append("")
    if repro.get("per_run_decision_scores"):
        lines.append("Official decision score by run:")
        lines.append("")
        run_rows = [
            [row["run"], row["cost"], row["cost_all_review"], f"{row['decision_score']:.4f}", row["n_missing"]]
            for row in repro["per_run_decision_scores"]
        ]
        lines.append(_md_table(["Run", "Cost", "All-REVIEW baseline", "Decision score", "Missing labels"], run_rows))
        lines.append("")
        lines.append(
            f"Across runs: score min {repro['decision_score_min']:.4f}, "
            f"mean {repro['decision_score_mean']:.4f}, "
            f"max {repro['decision_score_max']:.4f}."
        )
        lines.append("")
    if not repro["enough_runs"]:
        lines.append(
            f"Only {repro['n_runs']} output file(s) were provided. "
            "Pass N≥5 runs on the same input to score reproducibility."
        )
        lines.append("")
    elif repro["n_hits_differing"] == 0:
        lines.append(
            f"All {repro['n_hits_compared']} hits are stable across {repro['n_runs']} runs "
            "(decision, reason code, cited IDs, explanation)."
        )
        lines.append("")
    if repro["n_hits_differing"]:
        lines.append(
            f"{repro['n_hits_differing']} of {repro['n_hits_compared']} hits differ across "
            f"{repro['n_runs']} runs ({', '.join(repro['run_names'])})."
        )
        lines.append("")
        rows = [[item["hit_id"], ", ".join(item["changed_fields"])] for item in repro["differing_hits"]]
        lines.append(_md_table(["Hit ID", "Changed fields"], rows))
        lines.append("")
        for item in repro["differing_hits"][:20]:
            lines.append(f"- `{item['hit_id']}`: {', '.join(item['changed_fields'])}")
            for field in item["changed_fields"]:
                vals = item["values"].get(field) or []
                shown = "; ".join(f"{v['run']}={v.get('value', v.get('present'))!r}" for v in vals)
                lines.append(f"  - {field}: {shown}")
        if len(repro["differing_hits"]) > 20:
            lines.append(f"- … {len(repro['differing_hits']) - 20} more (see metrics JSON).")
        lines.append("")

    lines.append("## Explainability")
    lines.append("")
    lines.append(
        f"Checked {explain['n_rows']} output row(s) from the first run. "
        "An explanation must be non-empty, mention facts from that hit's records "
        "(name parts, dates of birth, countries, or record IDs), and every cited ID "
        "must exist in the data folder. Repeated identical wording is flagged as boilerplate."
    )
    lines.append("")
    if explain["n_hits_with_issues"] == 0:
        lines.append("No explainability issues in the first run.")
        lines.append("")
    else:
        if explain["empty_explanations"]:
            ids = ", ".join(x["hit_id"] for x in explain["empty_explanations"][:25])
            extra = f" (+{len(explain['empty_explanations'])-25} more)" if len(explain["empty_explanations"]) > 25 else ""
            lines.append(f"- Empty explanations ({len(explain['empty_explanations'])}): {ids}{extra}")
        if explain["unsupported_citations"]:
            lines.append(f"- Unsupported citations ({len(explain['unsupported_citations'])}):")
            for item in explain["unsupported_citations"][:25]:
                lines.append(f"  - `{item['hit_id']}`: {', '.join(item['unsupported_ids'])}")
        if explain["missing_hit_facts"]:
            ids = ", ".join(x["hit_id"] for x in explain["missing_hit_facts"][:25])
            extra = f" (+{len(explain['missing_hit_facts'])-25} more)" if len(explain["missing_hit_facts"]) > 25 else ""
            lines.append(
                f"- Explanations that do not mention the hit's facts "
                f"({len(explain['missing_hit_facts'])}): {ids}{extra}"
            )
        if explain["boilerplate_explanations"]:
            lines.append(f"- Boilerplate explanation groups ({explain['boilerplate_group_count']}):")
            for item in explain["boilerplate_explanations"]:
                preview = item["explanation"][:160].replace("|", "/")
                lines.append(f"  - used on {item['hit_count']} hits: “{preview}”")
        if explain["invalid_decisions"]:
            lines.append(f"- Invalid decisions: {len(explain['invalid_decisions'])}")
        if explain["invalid_or_mismatched_reason_codes"]:
            lines.append(
                "- Missing / unknown / decision-mismatched reason codes: "
                f"{len(explain['invalid_or_mismatched_reason_codes'])}"
            )
        lines.append("")

    lines.append("## Accuracy vs practice labels")
    lines.append("")
    lines.append(
        f"{n} practice labels. The official decision score is "
        r"max(0, 1 − cost_system / cost_all_REVIEW). "
        "A missing prediction is treated as REVIEW for that score and flagged. "
        "A reason code is accepted if it is any of the codes listed on that label. "
        "Evidence recall is the share of the label's evidence IDs that the output cites; "
        "precision is the share of cited IDs that are on the label (cite only what decided the hit). "
        "FALSE CLEARS are labelled SAME_ENTITY or REVIEW but output DIFFERENT_ENTITY. "
        "REVIEW over-use is output REVIEW where the label is definitive."
    )
    lines.append("")
    lines.append("### Official cost breakdown")
    lines.append("")
    cost_rows = []
    for key, cell in accuracy["cost_breakdown"].items():
        cost_rows.append([key, cell["n"], cell["unit_cost"], cell["cost"]])
    lines.append(_md_table(["Truth → predicted", "N", "Unit cost", "Cost"], cost_rows))
    lines.append("")
    lines.append(
        f"Total cost {accuracy['decision_cost']}; all-REVIEW baseline {accuracy['cost_all_review']}; "
        f"official decision score {accuracy['decision_score']:.4f}."
    )
    lines.append("")
    lines.append(_md_table(["Gold → predicted", "Count"], [[k, v] for k, v in accuracy["confusion"].items()]))
    lines.append("")
    if accuracy["extra_evidence_hits"]:
        lines.append("### Hits citing extra evidence IDs")
        lines.append("")
        lines.append(_md_table(
            ["Hit ID", "Extra IDs"],
            [[x["hit_id"], ", ".join(x["extra_ids"])] for x in accuracy["extra_evidence_hits"]],
        ))
        lines.append("")
    if accuracy["false_clears"]:
        lines.append("### FALSE CLEARS")
        lines.append("")
        lines.append(_md_table(
            ["Hit ID", "Label", "Output reason"],
            [[x["hit_id"], x["gold_decision"], ", ".join(x["pred_reason_codes"])] for x in accuracy["false_clears"]],
        ))
        lines.append("")
    if accuracy["review_overuse"]:
        lines.append("### REVIEW over-use")
        lines.append("")
        lines.append(_md_table(
            ["Hit ID", "Label decision"],
            [[x["hit_id"], x["gold_decision"]] for x in accuracy["review_overuse"]],
        ))
        lines.append("")
    if accuracy["missing_hit_ids"]:
        lines.append("Missing labelled hits: " + ", ".join(f"`{h}`" for h in accuracy["missing_hit_ids"]))
        lines.append("")

    lines.append("## Error analysis by evidence path")
    lines.append("")
    lines.append(
        "A label can belong to several path categories (taken from the practice-label `path` column). "
        "Link types partition the 50 labels; KYC, notes, merges and search results can overlap."
    )
    lines.append("")
    path_rows = []
    for name in PATH_CATEGORY_ORDER:
        stats = analysis["by_evidence_path"].get(name)
        if not stats:
            continue
        path_rows.append([
            PATH_CATEGORY_LABELS[name],
            stats["n"],
            _pct(stats["decision_accuracy"], stats["decision_correct"], stats["n"]),
            _pct(stats["reason_code_accepted_rate"]),
            _pct(stats["evidence_recall_macro"]),
            _pct(stats["evidence_precision_macro"]),
            f"{stats['cost']} / {stats['cost_all_review']}",
            f"{stats['decision_score']:.4f}",
            stats["n_false_clears"],
            stats["n_review_overuse"],
            ", ".join(stats["error_ids"]) or "—",
        ])
    lines.append(_md_table(
        ["Path category", "N", "Decision acc.", "Reason accepted", "Ev. recall", "Ev. prec.", "Cost / baseline", "Score", "False clears", "REVIEW over-use", "Error hit IDs"],
        path_rows,
    ))
    lines.append("")

    lines.append("## Error analysis by edge-case tag")
    lines.append("")
    lines.append(
        "Tags are derived from the labelled hit, its alert, the resolved customer records "
        "and cited KYC/notes, plus the path text. A hit may have several tags."
    )
    lines.append("")
    tag_rows = []
    for name in EDGE_TAG_LABELS:
        stats = analysis["by_edge_tag"].get(name) or {"n": 0}
        if stats.get("n", 0) == 0:
            tag_rows.append([EDGE_TAG_LABELS[name], 0, "—", "—", "—", "—", "—", "—", "—", "—", "none in the 50 labels"])
            continue
        tag_rows.append([
            EDGE_TAG_LABELS[name],
            stats["n"],
            _pct(stats["decision_accuracy"], stats["decision_correct"], stats["n"]),
            _pct(stats["reason_code_accepted_rate"]),
            _pct(stats["evidence_recall_macro"]),
            _pct(stats["evidence_precision_macro"]),
            f"{stats['cost']} / {stats['cost_all_review']}",
            f"{stats['decision_score']:.4f}",
            stats["n_false_clears"],
            stats["n_review_overuse"],
            ", ".join(stats["error_ids"]) or "—",
        ])
    lines.append(_md_table(
        ["Edge-case tag", "N", "Decision acc.", "Reason accepted", "Ev. recall", "Ev. prec.", "Cost / baseline", "Score", "False clears", "REVIEW over-use", "Error hit IDs / notes"],
        tag_rows,
    ))
    lines.append("")

    lines.append("## Label snapshot")
    lines.append("")
    dec_counts = Counter(l["decision"] for l in labels)
    lines.append(
        "Decisions: "
        + ", ".join(f"{d} {dec_counts.get(d, 0)}" for d in DECISIONS)
        + f" (n={n})."
    )
    code_counts = Counter(c for l in labels for c in l["reason_codes"])
    lines.append(
        "Reason codes (a label may list more than one; any listed code is accepted): "
        + ", ".join(f"{c} {code_counts[c]}" for c in sorted(code_counts, key=lambda x: (-code_counts[x], x)))
        + "."
    )
    unused = [c for c in ALL_REASON_CODES if c not in code_counts]
    if unused:
        lines.append("Official codes unused in the practice labels: " + ", ".join(unused) + ".")
    lines.append(
        "Evidence-path counts: "
        + ", ".join(
            f"{PATH_CATEGORY_LABELS.get(k, k)} {v}"
            for k, v in sorted(
                analysis["path_category_counts"].items(),
                key=lambda kv: PATH_CATEGORY_ORDER.index(kv[0]) if kv[0] in PATH_CATEGORY_ORDER else 99,
            )
        )
        + "."
    )
    lines.append(
        "Edge-tag counts: "
        + ", ".join(f"{EDGE_TAG_LABELS[k]} {analysis['edge_tag_counts'].get(k, 0)}" for k in EDGE_TAG_LABELS)
        + "."
    )
    lines.append("")
    return "\n".join(lines)


def label_inventory(labels: list[dict[str, Any]], analysis: dict[str, Any]) -> dict[str, Any]:
    dec = Counter(l["decision"] for l in labels)
    codes = Counter(c for l in labels for c in l["reason_codes"])
    return {
        "n_labels": len(labels),
        "n_unique_hit_ids": len({l["hit_id"] for l in labels}),
        "n_unique_alert_ids": len({l["alert_id"] for l in labels}),
        "decisions": {d: dec.get(d, 0) for d in DECISIONS},
        "reason_codes": dict(codes),
        "unused_official_reason_codes": sorted(c for c in ALL_REASON_CODES if c not in codes),
        "path_category_counts": analysis["path_category_counts"],
        "edge_tag_counts": analysis["edge_tag_counts"],
    }
