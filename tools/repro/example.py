"""Synthetic repro.json used as a UI fixture. No real screening data."""

from __future__ import annotations

from tools.repro.report import assemble_run, build_report

EXAMPLE_STAMP = "2026-01-01T00:00:00+00:00"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _header(index: int) -> dict:
    return {
        "git_sha": _SHA_B if index == 4 else _SHA_A,
        "hashes": {
            "input": "input-hash",
            "name_variants": "variants-hash",
            "policy": "policy-hash",
            "prompts": {"read_note": "prompt-hash"},
        },
        "model": "openai/gpt-4o-mini",
        "provider": "ExampleProvider",
        "python_version": "3.12.3",
        "record_type": "run_header",
        "rules_version": "r1.0",
        "run_id": f"example-run-{index + 1}",
    }


def _output(hit_id: str, decision: str, code: str, evidence: list[str] | None = None) -> dict:
    return {
        "alert_id": "A-" + hit_id.split("-", 1)[1],
        "customer_record_id": "CUS-000001",
        "decision": decision,
        "evidence": ["KYC-000001"] if evidence is None else evidence,
        "hit_id": hit_id,
        "reason": "Synthetic reason. Not copied into repro.json.",
        "reason_code": code,
    }


def _trace(output: dict, steps: list[dict], llm_used: bool, fragility: str) -> dict:
    return {
        "alert_id": output["alert_id"],
        "badges": {"fragility": fragility, "llm_used": llm_used, "rules_version": "r1.0"},
        "hit_id": output["hit_id"],
        "steps": steps,
        "trace_schema": 1,
        "verdict": {
            "customer_record_id": output["customer_record_id"],
            "decision": output["decision"],
            "evidence": list(output["evidence"]),
            "reason": output["reason"],
            "reason_code": output["reason_code"],
        },
    }


def _policy_steps(dob: str = "fired", location: str = "not_fired") -> list[dict]:
    """Listed out of policy order on purpose; the report sorts them."""
    return [
        {"result": dob, "rule": "DOB_MISMATCH", "why": "dob rule"},
        {"result": "not_fired", "rule": "ENTITY_TYPE_MISMATCH", "why": "same type"},
        {"result": location, "rule": "LOCATION_MISMATCH", "why": "location rule"},
        {"result": "not_fired", "rule": "DECEASED", "why": "no death date"},
        {"result": "not_fired", "rule": "TEMPORAL_IMPOSSIBILITY", "why": "age ok"},
    ]


def build_example_report(generated_at: str = EXAMPLE_STAMP) -> dict:
    """Five synthetic runs: stable, decision flip, code flip, evidence flip, missing, step flip."""
    specs = []
    for index in range(5):
        rows = {
            "H-000001": _output("H-000001", "DIFFERENT_ENTITY", "DOB_MISMATCH"),
            "H-000002": _output(
                "H-000002",
                "REVIEW" if index == 4 else "SAME_ENTITY",
                "INSUFFICIENT_DATA" if index == 4 else "NAME_DOB_MATCH",
            ),
            "H-000003": _output(
                "H-000003",
                "REVIEW",
                "AMBIGUOUS_CUSTOMER_RECORD" if index == 1 else "INSUFFICIENT_DATA",
            ),
            "H-000004": _output(
                "H-000004",
                "DIFFERENT_ENTITY",
                "LOCATION_MISMATCH",
                ["KYC-000002"] if index == 2 else ["KYC-000001"],
            ),
            "H-000006": _output("H-000006", "DIFFERENT_ENTITY", "DOB_MISMATCH"),
        }
        if index != 3:
            rows["H-000005"] = _output("H-000005", "REVIEW", "INSUFFICIENT_DATA")
        specs.append(rows)

    runs = []
    for index, rows in enumerate(specs):
        traces = {}
        for hit_id, output in rows.items():
            if hit_id == "H-000006":
                steps = _policy_steps(
                    dob="not_fired" if index == 4 else "fired",
                    location="fired" if index == 4 else "not_fired",
                )
            else:
                steps = _policy_steps()
            if hit_id == "H-000002":
                llm_used, fragility = True, "borderline"
            elif hit_id == "H-000003":
                llm_used, fragility = False, "thin"
            elif hit_id == "H-000004":
                llm_used, fragility = False, "thin"
            else:
                llm_used, fragility = False, "solid"
            traces[hit_id] = _trace(output, steps, llm_used, fragility)
        runs.append(assemble_run(f"run-{index + 1:02d}", _header(index), rows, traces))

    off_rows = {hit_id: dict(specs[0][hit_id]) for hit_id in specs[0]}
    off_rows["H-000002"] = _output("H-000002", "REVIEW", "INSUFFICIENT_DATA")
    llm_off = assemble_run("llm-off", None, off_rows, {})
    return build_report(
        runs,
        llm_off,
        generated_at,
        {"llm_off_output": True, "outputs": True, "traces": True},
    )
