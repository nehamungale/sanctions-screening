"""Parse system outputs and practice labels into a canonical row shape."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from .constants import FIELD_ALIASES, NULL_VALUES, AMBIGUOUS_VALUES


def strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def norm_text(text: str) -> str:
    return norm_ws(strip_accents(text or "").lower())


def parse_id_list(value: Any) -> list[str]:
    """Parse record IDs from a list, JSON string, or delimited string."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(parse_id_list(item))
        return [x for x in out if x]
    text = str(value).strip()
    if not text or text.lower() in NULL_VALUES:
        return []
    if text.lower() in AMBIGUOUS_VALUES:
        return []
    if text[0] in "[{":
        try:
            return parse_id_list(json.loads(text))
        except json.JSONDecodeError:
            pass
    parts = [p.strip().strip("'\"") for p in re.split(r"[;,|]", text) if p.strip()]
    return [p for p in parts if p and p.lower() not in NULL_VALUES]


def parse_reason_codes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(parse_reason_codes(item))
        return [c for c in out if c]
    text = str(value).strip()
    if not text or text.lower() in NULL_VALUES:
        return []
    if text[0] in "[{":
        try:
            return parse_reason_codes(json.loads(text))
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in re.split(r"[;,|]", text) if p.strip()]


def parse_customer_id(value: Any) -> str | None:
    """Return a single customer_record_id, 'AMBIGUOUS', or None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        ids = [parse_customer_id(v) for v in value]
        ids = [i for i in ids if i]
        if not ids:
            return None
        if any((i or "").upper() == "AMBIGUOUS" for i in ids):
            return "AMBIGUOUS"
        return ids[0]
    text = str(value).strip()
    if not text or text.lower() in NULL_VALUES:
        return None
    if text.lower() in AMBIGUOUS_VALUES or text.upper() == "AMBIGUOUS":
        return "AMBIGUOUS"
    ids = parse_id_list(text)
    return ids[0] if ids else text


def split_name_parts(text: str, placeholders: set[str]) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"\([^)]*\)", " ", strip_accents(text))
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned.lower())
    parts = [p for p in re.split(r"[\s-]+", cleaned) if p]
    out: list[str] = []
    for part in parts:
        if part.isdigit() or part in placeholders or len(part) == 1:
            continue
        out.append(part)
    return out


def _alias_get(row: dict[str, Any], canonical: str) -> Any:
    keys = {k.lower().replace("-", "_"): k for k in row.keys()}
    for alias in FIELD_ALIASES[canonical]:
        real = keys.get(alias.lower())
        if real is not None:
            return row[real]
    return None


def normalize_output_row(row: dict[str, Any], source: str, line_no: int) -> dict[str, Any]:
    hit_id = _alias_get(row, "hit_id")
    hit_id = str(hit_id).strip() if hit_id is not None else ""
    decision_raw = _alias_get(row, "decision")
    decision = str(decision_raw).strip() if decision_raw is not None else ""
    if decision:
        decision = decision.upper().replace(" ", "_")
    alert_raw = _alias_get(row, "alert_id")
    expl = _alias_get(row, "explanation")
    return {
        "hit_id": hit_id,
        "alert_id": str(alert_raw).strip() if alert_raw not in (None, "") else None,
        "decision": decision,
        "reason_codes": parse_reason_codes(_alias_get(row, "reason_code")),
        "evidence": parse_id_list(_alias_get(row, "evidence")),
        "customer_record_id": parse_customer_id(_alias_get(row, "customer_record_id")),
        "explanation": "" if expl is None else str(expl),
        "source": source,
        "line_no": line_no,
    }


def _load_json_payload(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "{[":
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            if isinstance(payload, list):
                return [r for r in payload if isinstance(r, dict)]
            if isinstance(payload, dict):
                for key in ("hits", "results", "outputs", "records", "data"):
                    val = payload.get(key)
                    if isinstance(val, list):
                        return [r for r in val if isinstance(r, dict)]
                if any(k in payload for k in ("hit_id", "hitId")):
                    return [payload]
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {i} is not valid JSON: {exc}") from exc
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def load_output_file(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Output file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            raw_rows = list(csv.DictReader(fh))
    elif suffix in {".json", ".jsonl", ".ndjson"}:
        raw_rows = _load_json_payload(path)
    else:
        head = path.read_text(encoding="utf-8-sig")[:2048].lstrip()
        if head.startswith("{") or head.startswith("["):
            raw_rows = _load_json_payload(path)
        else:
            with path.open(newline="", encoding="utf-8-sig") as fh:
                raw_rows = list(csv.DictReader(fh))
    return [normalize_output_row(r, str(path), i) for i, r in enumerate(raw_rows, 1)]


def load_output_files(paths: Iterable[Path]) -> list[tuple[str, list[dict[str, Any]]]]:
    runs: list[tuple[str, list[dict[str, Any]]]] = []
    for i, path in enumerate(paths, 1):
        path = Path(path)
        rows = load_output_file(path)
        runs.append((path.name or f"run_{i}", rows))
    return runs


def load_labels(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        raw = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    elif path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            data = data.get("labels") or data.get("hits") or data.get("records") or []
        raw = list(data)
    else:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            raw = list(csv.DictReader(fh))
    labels: list[dict[str, Any]] = []
    for row in raw:
        raw_cust = row.get("customer_record_ids") or row.get("customer_record_id")
        if isinstance(raw_cust, (list, tuple)):
            raw_cust = [str(c).strip() for c in raw_cust]
            ambiguous = [c for c in raw_cust if c.upper() == "AMBIGUOUS"]
        else:
            raw_cust = str(raw_cust or "").strip()
            ambiguous = [raw_cust] if raw_cust.upper() == "AMBIGUOUS" else []
        if ambiguous:
            customer_ids = ["AMBIGUOUS"]
        else:
            customer_ids = parse_id_list(raw_cust)
        raw_path = row.get("path") or ""
        if isinstance(raw_path, (list, tuple)):
            raw_path = " \u2192 ".join(str(p) for p in raw_path)
        labels.append({
            "hit_id": str(row["hit_id"]).strip(),
            "alert_id": str(row.get("alert_id") or "").strip(),
            "decision": str(row["decision"]).strip(),
            "reason_codes": parse_reason_codes(row.get("reason_codes") or row.get("reason_code")),
            "customer_record_ids": customer_ids,
            "evidence": parse_id_list(row.get("evidence")),
            "reference_reason": str(row.get("reference_reason") or row.get("explanation") or ""),
            "path": str(raw_path),
        })
    return labels
