"""Reproducibility, explainability, accuracy and error-analysis scoring."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from .constants import (
    ALL_REASON_CODES,
    DECISION_COSTS,
    DECISIONS,
    DEFINITIVE_DECISIONS,
    EDGE_TAG_LABELS,
    GENERIC_TOKENS,
    PATH_CATEGORY_LABELS,
    PLACEHOLDERS,
    REASON_CODES_BY_DECISION,
)
from .data import DataIndex, edge_tags, path_categories
from .parse import norm_text, norm_ws

REPRO_FIELDS = ("decision", "reason_code", "cited_ids", "explanation")


def decision_cost(truth: str, predicted: str) -> int:
    """Official per-hit cost. Unknown / missing predictions are scored as REVIEW."""
    if predicted not in DECISIONS:
        predicted = "REVIEW"
    if truth not in DECISIONS:
        return 0
    return DECISION_COSTS[(truth, predicted)]


def official_decision_score(cost: int | float, baseline: int | float) -> float:
    """Share of cost saved versus sending every labelled hit to REVIEW."""
    if baseline <= 0:
        return 1.0 if cost <= 0 else 0.0
    return round(max(0.0, 1.0 - (cost / baseline)), 4)


def all_review_cost(labels: list[dict]) -> int:
    return sum(decision_cost(lab["decision"], "REVIEW") for lab in labels)


def cost_breakdown_table(cell_n: dict[tuple[str, str], int]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for truth in DECISIONS:
        for pred in DECISIONS:
            key = f"{truth} -> {pred}"
            n = cell_n.get((truth, pred), 0)
            unit = DECISION_COSTS[(truth, pred)]
            out[key] = {"n": n, "unit_cost": unit, "cost": n * unit}
    return out


def per_run_score_summary(
    run_names: list[str],
    run_accuracies: list[dict],
) -> dict:
    per_run = []
    for name, acc in zip(run_names, run_accuracies):
        per_run.append({
            "run": name,
            "cost": acc["decision_cost"],
            "cost_all_review": acc["cost_all_review"],
            "decision_score": acc["decision_score"],
            "n_missing": acc["n_missing"],
        })
    scores = [row["decision_score"] for row in per_run]
    costs = [row["cost"] for row in per_run]
    return {
        "per_run_decision_scores": per_run,
        "decision_score_min": min(scores) if scores else None,
        "decision_score_mean": round(sum(scores) / len(scores), 4) if scores else None,
        "decision_score_max": max(scores) if scores else None,
        "decision_cost_min": min(costs) if costs else None,
        "decision_cost_mean": round(sum(costs) / len(costs), 4) if costs else None,
        "decision_cost_max": max(costs) if costs else None,
    }



def explanation_mentions_facts(
    explanation: str, facts: set[str], legal_forms: set[str]
) -> tuple[bool, list[str]]:
    if not norm_text(explanation):
        return False, []
    text = norm_text(explanation)
    padded = f" {text} "
    mentioned: list[str] = []
    skip = GENERIC_TOKENS | PLACEHOLDERS | legal_forms
    for fact in sorted(facts, key=len, reverse=True):
        if not fact or len(fact) < 3 or fact in skip:
            continue
        if " " in fact or "-" in fact:
            if fact in text:
                mentioned.append(fact)
        elif re.search(rf"(?<![a-z0-9]){re.escape(fact)}(?![a-z0-9])", padded):
            mentioned.append(fact)
        if len(mentioned) >= 8:
            break
    return bool(mentioned), mentioned


def grade_explainability(
    rows: list[dict[str, Any]],
    data: DataIndex,
    boilerplate_min: int = 3,
) -> dict[str, Any]:
    empty: list[dict[str, Any]] = []
    missing_facts: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    invalid_decision: list[dict[str, Any]] = []
    invalid_reason: list[dict[str, Any]] = []
    norm_explanations: dict[str, list[str]] = defaultdict(list)
    per_hit: dict[str, dict[str, Any]] = {}

    for row in rows:
        hid = row["hit_id"] or f"<missing-id:line {row['line_no']}>"
        expl = row["explanation"]
        key = norm_text(expl)
        if key:
            norm_explanations[key].append(hid)

        issues: list[str] = []
        if not row["hit_id"]:
            issues.append("missing_hit_id")
        if row["decision"] not in DECISIONS:
            issues.append("invalid_decision")
            invalid_decision.append({"hit_id": hid, "decision": row["decision"]})
        codes = row["reason_codes"]
        if not codes:
            issues.append("missing_reason_code")
            invalid_reason.append({"hit_id": hid, "reason_codes": codes})
        else:
            bad = [c for c in codes if c not in ALL_REASON_CODES]
            if bad:
                issues.append("unknown_reason_code")
                invalid_reason.append({"hit_id": hid, "reason_codes": codes})
            elif row["decision"] in REASON_CODES_BY_DECISION:
                allowed = set(REASON_CODES_BY_DECISION[row["decision"]])
                if not any(c in allowed for c in codes):
                    issues.append("reason_code_does_not_belong_to_decision")
                    invalid_reason.append({
                        "hit_id": hid,
                        "decision": row["decision"],
                        "reason_codes": codes,
                    })

        if not norm_ws(expl):
            issues.append("empty_explanation")
            empty.append({"hit_id": hid})

        missing_ids = [eid for eid in row["evidence"] if not data.id_exists(eid)]
        if missing_ids:
            issues.append("unsupported_citations")
            unsupported.append({"hit_id": hid, "unsupported_ids": missing_ids})

        facts = data.facts_for_hit(row["hit_id"], row["evidence"], row["customer_record_id"])
        mentioned_ok, mentioned = explanation_mentions_facts(expl, facts, data.legal_forms)
        if norm_ws(expl) and not mentioned_ok:
            issues.append("explanation_missing_hit_facts")
            missing_facts.append({"hit_id": hid, "explanation": expl[:240]})

        per_hit[hid] = {
            "issues": issues,
            "mentioned_facts": mentioned,
            "unsupported_ids": missing_ids,
        }

    boilerplate: list[dict[str, Any]] = []
    for text, hit_ids in norm_explanations.items():
        uniq = list(dict.fromkeys(hit_ids))
        if len(uniq) >= boilerplate_min:
            boilerplate.append({
                "hit_count": len(uniq),
                "hit_ids": uniq,
                "explanation": text[:300],
            })
            for hid in uniq:
                if hid in per_hit and "boilerplate_explanation" not in per_hit[hid]["issues"]:
                    per_hit[hid]["issues"].append("boilerplate_explanation")

    n = len(rows) or 1
    return {
        "n_rows": len(rows),
        "n_hits_with_issues": sum(1 for v in per_hit.values() if v["issues"]),
        "empty_explanations": empty,
        "missing_hit_facts": missing_facts,
        "unsupported_citations": unsupported,
        "boilerplate_explanations": boilerplate,
        "invalid_decisions": invalid_decision,
        "invalid_or_mismatched_reason_codes": invalid_reason,
        "empty_explanation_rate": round(len(empty) / n, 4),
        "unsupported_citation_rate": round(len(unsupported) / n, 4),
        "missing_facts_rate": round(len(missing_facts) / n, 4),
        "boilerplate_group_count": len(boilerplate),
        "per_hit": per_hit,
    }


def _row_by_hit(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["hit_id"] and row["hit_id"] not in out:
            out[row["hit_id"]] = row
    return out


def _fingerprint(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {
            "present": False,
            "decision": None,
            "reason_code": None,
            "cited_ids": None,
            "explanation": None,
            "customer_record_id": None,
        }
    return {
        "present": True,
        "decision": row["decision"] or None,
        "reason_code": tuple(sorted(row["reason_codes"])),
        "cited_ids": tuple(sorted(row["evidence"])),
        "explanation": norm_text(row["explanation"]),
        "customer_record_id": row["customer_record_id"],
    }


def grade_reproducibility(runs: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    run_maps = [(name, _row_by_hit(rows)) for name, rows in runs]
    all_hits = sorted({hid for _, m in run_maps for hid in m})
    differing: list[dict[str, Any]] = []
    for hid in all_hits:
        fps = [(name, _fingerprint(m.get(hid))) for name, m in run_maps]
        changed: list[str] = []
        values: dict[str, list[Any]] = {}
        present = [fp["present"] for _, fp in fps]
        if len(set(present)) > 1:
            changed.append("presence")
            values["presence"] = [{"run": n, "present": fp["present"]} for n, fp in fps]
        for field in REPRO_FIELDS + ("customer_record_id",):
            vals = [fp[field] for _, fp in fps]
            compact = {json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for v in vals}
            if len(compact) > 1:
                changed.append(field)
                values[field] = [
                    {"run": n, "value": list(v) if isinstance(v, tuple) else v}
                    for n, v in zip((x[0] for x in fps), vals)
                ]
        if changed:
            differing.append({"hit_id": hid, "changed_fields": changed, "values": values})
    n_runs = len(runs)
    n_same_decision_and_reason = 0
    for hid in all_hits:
        fps = [_fingerprint(m.get(hid)) for _, m in run_maps]
        if all(fp["present"] for fp in fps):
            if len({fp["decision"] for fp in fps}) == 1 and len({fp["reason_code"] for fp in fps}) == 1:
                n_same_decision_and_reason += 1
    official_rate = (
        round(n_same_decision_and_reason / len(all_hits), 4) if all_hits else 1.0
    )
    return {
        "n_runs": n_runs,
        "n_hits_compared": len(all_hits),
        "n_hits_differing": len(differing),
        "stable": n_runs >= 2 and len(differing) == 0,
        "enough_runs": n_runs >= 5,
        "differing_hits": differing,
        "run_names": [name for name, _ in runs],
        "run_row_counts": {name: len(rows) for name, rows in runs},
        "official_repro_identical": n_same_decision_and_reason,
        "official_repro_rate": official_rate,
    }


def primary_row_map(runs: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, dict[str, Any]]:
    return _row_by_hit(runs[0][1])


def grade_accuracy(
    labels: list[dict[str, Any]],
    predicted: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    n = len(labels)
    correct_decision = 0
    accepted_reason = 0
    accepted_reason_given_correct = 0
    evidence_recalls: list[float] = []
    evidence_precs: list[float] = []
    micro_inter = 0
    micro_gold = 0
    micro_pred = 0
    false_clears: list[dict[str, Any]] = []
    review_overuse: list[dict[str, Any]] = []
    missing: list[str] = []
    extra_hits: list[dict[str, Any]] = []
    customer_ok = 0
    per_hit: dict[str, dict[str, Any]] = {}
    confusion: Counter[tuple[str, str]] = Counter()
    cost_cells: Counter[tuple[str, str]] = Counter()
    total_cost = 0
    baseline = all_review_cost(labels)

    for lab in labels:
        hid = lab["hit_id"]
        pred = predicted.get(hid)
        gold_d = lab["decision"]
        if pred is None:
            missing.append(hid)
            # Official score treats a missing prediction as REVIEW and flags it.
            scored_d = "REVIEW"
            hit_cost = decision_cost(gold_d, scored_d)
            total_cost += hit_cost
            cost_cells[(gold_d, scored_d)] += 1
            confusion[(gold_d, "<MISSING>")] += 1
            evidence_recalls.append(0.0)
            evidence_precs.append(0.0)
            micro_gold += len(lab["evidence"])
            per_hit[hid] = {
                "gold_decision": gold_d,
                "pred_decision": None,
                "scored_decision": scored_d,
                "decision_correct": False,
                "reason_accepted": False,
                "evidence_recall": 0.0,
                "evidence_precision": 0.0,
                "n_gold_evidence": len(lab["evidence"]),
                "n_pred_evidence": 0,
                "n_evidence_overlap": 0,
                "extra_evidence_ids": [],
                "cost": hit_cost,
                "false_clear": False,
                "review_overuse": False,
                "missing": True,
            }
            continue

        pred_d = pred["decision"]
        decision_correct = pred_d == gold_d
        if decision_correct:
            correct_decision += 1
        confusion[(gold_d, pred_d or "<EMPTY>")] += 1

        pred_codes = set(pred["reason_codes"])
        gold_codes = set(lab["reason_codes"])
        reason_ok = bool(pred_codes & gold_codes)
        if reason_ok:
            accepted_reason += 1
            if decision_correct:
                accepted_reason_given_correct += 1

        gold_ev = set(lab["evidence"])
        pred_ev = set(pred["evidence"])
        inter = len(gold_ev & pred_ev)
        recall = (inter / len(gold_ev)) if gold_ev else 1.0
        precision = (inter / len(pred_ev)) if pred_ev else 1.0
        evidence_recalls.append(recall)
        evidence_precs.append(precision)
        micro_inter += inter
        micro_gold += len(gold_ev)
        micro_pred += len(pred_ev)
        extra_ids = sorted(pred_ev - gold_ev)
        if extra_ids:
            extra_hits.append({
                "hit_id": hid,
                "extra_ids": extra_ids,
                "pred_evidence": pred["evidence"],
                "gold_evidence": lab["evidence"],
            })

        scored_d = pred_d if pred_d in DECISIONS else "REVIEW"
        hit_cost = decision_cost(gold_d, scored_d)
        total_cost += hit_cost
        cost_cells[(gold_d, scored_d)] += 1

        is_false_clear = gold_d in {"SAME_ENTITY", "REVIEW"} and pred_d == "DIFFERENT_ENTITY"
        if is_false_clear:
            false_clears.append({
                "hit_id": hid,
                "gold_decision": gold_d,
                "pred_decision": pred_d,
                "pred_reason_codes": pred["reason_codes"],
            })
        is_review_overuse = pred_d == "REVIEW" and gold_d in DEFINITIVE_DECISIONS
        if is_review_overuse:
            review_overuse.append({"hit_id": hid, "gold_decision": gold_d, "pred_decision": pred_d})

        gold_cust = set(lab["customer_record_ids"])
        pred_cust = pred["customer_record_id"]
        if "AMBIGUOUS" in gold_cust:
            cust_ok = pred_cust == "AMBIGUOUS"
        elif not gold_cust:
            cust_ok = pred_cust in (None, "")
        else:
            cust_ok = pred_cust in gold_cust
        if cust_ok:
            customer_ok += 1

        per_hit[hid] = {
            "gold_decision": gold_d,
            "pred_decision": pred_d,
            "scored_decision": scored_d,
            "decision_correct": decision_correct,
            "gold_reason_codes": lab["reason_codes"],
            "pred_reason_codes": pred["reason_codes"],
            "reason_accepted": reason_ok,
            "evidence_recall": round(recall, 4),
            "evidence_precision": round(precision, 4),
            "n_gold_evidence": len(gold_ev),
            "n_pred_evidence": len(pred_ev),
            "n_evidence_overlap": inter,
            "extra_evidence_ids": extra_ids,
            "gold_evidence": lab["evidence"],
            "pred_evidence": pred["evidence"],
            "customer_record_id_accepted": cust_ok,
            "cost": hit_cost,
            "false_clear": is_false_clear,
            "review_overuse": is_review_overuse,
            "missing": False,
        }

    macro = sum(evidence_recalls) / n if n else 0.0
    micro = (micro_inter / micro_gold) if micro_gold else 0.0
    prec_macro = sum(evidence_precs) / n if n else 0.0
    prec_micro = (micro_inter / micro_pred) if micro_pred else 1.0
    return {
        "n_labels": n,
        "n_missing": len(missing),
        "missing_hit_ids": missing,
        "missing_treated_as_review": list(missing),
        "decision_accuracy": round(correct_decision / n, 4) if n else 0.0,
        "decision_correct": correct_decision,
        "reason_code_accepted_rate": round(accepted_reason / n, 4) if n else 0.0,
        "reason_code_accepted": accepted_reason,
        "reason_code_accepted_given_correct_decision": (
            round(accepted_reason_given_correct / correct_decision, 4) if correct_decision else 0.0
        ),
        "decision_cost": total_cost,
        "cost_all_review": baseline,
        "decision_score": official_decision_score(total_cost, baseline),
        "cost_breakdown": cost_breakdown_table(cost_cells),
        "evidence_recall_macro": round(macro, 4),
        "evidence_recall_micro": round(micro, 4),
        "evidence_precision_macro": round(prec_macro, 4),
        "evidence_precision_micro": round(prec_micro, 4),
        "n_extra_evidence_hits": len(extra_hits),
        "extra_evidence_hits": extra_hits,
        "customer_record_id_accepted_rate": round(customer_ok / n, 4) if n else 0.0,
        "false_clears": false_clears,
        "n_false_clears": len(false_clears),
        "review_overuse": review_overuse,
        "n_review_overuse": len(review_overuse),
        "confusion": {f"{g} -> {p}": c for (g, p), c in sorted(confusion.items())},
        "per_hit": per_hit,
    }


def _group_stats(hit_ids: list[str], accuracy: dict[str, Any]) -> dict[str, Any]:
    per = accuracy["per_hit"]
    ids = [h for h in hit_ids if h in per]
    n = len(ids)
    if not n:
        return {"n": 0}
    correct = sum(1 for h in ids if per[h]["decision_correct"])
    reason_ok = sum(1 for h in ids if per[h]["reason_accepted"])
    ev = [per[h]["evidence_recall"] for h in ids]
    prec = [per[h]["evidence_precision"] for h in ids]
    false_clears = [h for h in ids if per[h]["false_clear"]]
    review_over = [h for h in ids if per[h]["review_overuse"]]
    errors = [h for h in ids if not per[h]["decision_correct"]]
    group_cost = sum(per[h]["cost"] for h in ids)
    group_baseline = sum(decision_cost(per[h]["gold_decision"], "REVIEW") for h in ids)
    overlap = sum(per[h].get("n_evidence_overlap", 0) for h in ids)
    pred_n = sum(per[h].get("n_pred_evidence", 0) for h in ids)
    return {
        "n": n,
        "decision_accuracy": round(correct / n, 4),
        "decision_correct": correct,
        "reason_code_accepted_rate": round(reason_ok / n, 4),
        "evidence_recall_macro": round(sum(ev) / n, 4),
        "evidence_precision_macro": round(sum(prec) / n, 4),
        "evidence_precision_micro": round((overlap / pred_n) if pred_n else 1.0, 4),
        "cost": group_cost,
        "cost_all_review": group_baseline,
        "decision_score": official_decision_score(group_cost, group_baseline),
        "n_false_clears": len(false_clears),
        "false_clear_ids": false_clears,
        "n_review_overuse": len(review_over),
        "review_overuse_ids": review_over,
        "error_ids": errors,
    }


def grade_error_analysis(
    labels: list[dict[str, Any]],
    accuracy: dict[str, Any],
    data: DataIndex,
) -> dict[str, Any]:
    by_path: dict[str, list[str]] = defaultdict(list)
    by_tag: dict[str, list[str]] = defaultdict(list)
    by_decision: dict[str, list[str]] = defaultdict(list)
    label_tags: dict[str, list[str]] = {}
    label_paths: dict[str, list[str]] = {}
    for lab in labels:
        hid = lab["hit_id"]
        cats = path_categories(lab["path"])
        tags = edge_tags(lab, data)
        label_paths[hid] = cats
        label_tags[hid] = tags
        by_decision[lab["decision"]].append(hid)
        for c in cats:
            by_path[c].append(hid)
        for t in tags:
            by_tag[t].append(hid)

    path_stats = {
        name: {**_group_stats(ids, accuracy), "label": PATH_CATEGORY_LABELS.get(name, name)}
        for name, ids in by_path.items()
    }
    tag_stats = {
        name: {**_group_stats(ids, accuracy), "label": EDGE_TAG_LABELS.get(name, name)}
        for name, ids in by_tag.items()
    }
    for name in EDGE_TAG_LABELS:
        tag_stats.setdefault(name, {**_group_stats([], accuracy), "label": EDGE_TAG_LABELS[name], "n": 0})

    return {
        "by_evidence_path": path_stats,
        "by_edge_tag": tag_stats,
        "by_gold_decision": {d: _group_stats(ids, accuracy) for d, ids in by_decision.items()},
        "label_path_categories": label_paths,
        "label_edge_tags": label_tags,
        "path_category_counts": {k: len(v) for k, v in by_path.items()},
        "edge_tag_counts": {
            k: sum(1 for tags in label_tags.values() if k in tags) for k in EDGE_TAG_LABELS
        },
    }
