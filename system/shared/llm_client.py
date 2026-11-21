"""Reusable OpenRouter client for later stages.

The note fallback and the decision stage both use this module. It is stdlib
only (``urllib``). The key is read from ``OPENROUTER_API_KEY`` and is never
hardcoded. Results are not cached: a cache on this machine would not exist
for the judges, so it cannot be part of reproducibility.

Free models only. The pinned default is ``google/gemma-4-31b-it:free``
(price 0 on OpenRouter, served by Google AI Studio). ``OPENROUTER_MODEL`` may
override it, but the slug must end in ``:free``. A paid slug, or any slug
that does not, never calls the network: the fact is UNKNOWN and the caller
stays on the no-LLM path. ``provider.order`` is fixed and
``allow_fallbacks`` is false so a free request cannot spill onto a paid
endpoint.

Free models are rate-limited. HTTP 429 is retried with a short bounded
backoff (honouring ``Retry-After`` up to 8 seconds), then the fact is
UNKNOWN. The per-run call budget and time cap still apply, so a burst of
429s cannot stretch a run toward the 30 minute limit. The client is off
unless a caller turns it on.

An extracted fact is usable only when three calls return the same
schema-valid value and every string in that value appears verbatim in the
source text. Any disagreement, timeout, schema failure, or budget overrun
yields UNKNOWN. The client never returns free-form model prose. Callers must
tag a usable fact ``method='llm'``; that fact may support a confirmation or
push toward review, and must not be the sole ground for ``DIFFERENT_ENTITY``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Price 0 on OpenRouter. Do not replace this with a paid slug.
DEFAULT_MODEL = "google/gemma-4-31b-it:free"
# The provider that serves that free endpoint. Fallbacks stay off.
DEFAULT_PROVIDER_ORDER = ("Google AI Studio",)
DEFAULT_SEED = 0
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 3
DEFAULT_CALL_BUDGET = 48
DEFAULT_TIME_CAP_SECONDS = 90.0
MAX_BACKOFF_SECONDS = 8.0
VOTES = 3
_RATE_LIMITED = object()
_DROPPED_KEYS = {"reason", "explanation", "rationale", "comment", "reasoning"}


@dataclass
class Extraction:
    """A validated extraction, or UNKNOWN.

    ``value`` is the parsed object when ``status == 'ok'``. ``method`` is
    ``'llm'`` only then. ``may_solely_support_different_entity`` is always
    false: an LLM fact must not be the only ground for a clear.
    """

    status: str
    value: dict | None = None
    method: str | None = None
    votes: int = 0
    may_solely_support_different_entity: bool = False
    calls: int = 0
    detail: str = ""
    dropped_prose: list[str] = field(default_factory=list)

    @property
    def unknown(self) -> bool:
        return self.status != "ok"


class OpenRouterClient:
    """One run's client. Time and call budgets start when the client is built."""

    def __init__(
        self,
        *,
        urlopen=None,
        clock=None,
        api_key: str | None = None,
        model: str | None = None,
        provider_order: tuple[str, ...] | None = None,
        seed: int | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        call_budget: int | None = None,
        time_cap: float | None = None,
        url: str = OPENROUTER_URL,
        sleeper=None,
    ):
        self.urlopen = urlopen or urllib.request.urlopen
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.api_key = os.environ.get("OPENROUTER_API_KEY") if api_key is None else api_key
        self.model = (model or os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL).strip()
        if provider_order is None:
            raw = os.environ.get("OPENROUTER_PROVIDER_ORDER")
            provider_order = tuple(part.strip() for part in raw.split(",") if part.strip()) if raw else DEFAULT_PROVIDER_ORDER
        self.provider_order = provider_order
        self.seed = DEFAULT_SEED if seed is None else seed
        self.timeout = float(os.environ["OPENROUTER_TIMEOUT"]) if "OPENROUTER_TIMEOUT" in os.environ else (
            DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
        )
        self.retries = DEFAULT_RETRIES if retries is None else retries
        self.call_budget = int(os.environ["OPENROUTER_CALL_BUDGET"]) if "OPENROUTER_CALL_BUDGET" in os.environ else (
            DEFAULT_CALL_BUDGET if call_budget is None else call_budget
        )
        self.time_cap = float(os.environ["OPENROUTER_TIME_CAP"]) if "OPENROUTER_TIME_CAP" in os.environ else (
            DEFAULT_TIME_CAP_SECONDS if time_cap is None else time_cap
        )
        self.url = url
        self.started = self.clock()
        self.calls = 0
        self._closed = False
        self._saw_rate_limit = False
        self._retry_after = None

    def extract(self, source_text: str, schema: dict, *, schema_name: str = "extraction") -> Extraction:
        """Three unanimous calls, or UNKNOWN. Never raises for a model failure."""
        if not is_free_model(self.model):
            return self._unknown("model_not_free")
        if self._closed or self._over_cap():
            self._closed = True
            return self._unknown("time_or_budget_cap")
        if not self.api_key:
            return self._unknown("missing_api_key")
        ballots: list[str] = []
        value: dict | None = None
        for _vote in range(VOTES):
            parsed = self._vote(source_text, schema, schema_name)
            if parsed is None:
                detail = "rate_limited" if self._saw_rate_limit else "vote_failed"
                return self._unknown(detail)
            encoded = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ballots.append(encoded)
            value = parsed
        if len(set(ballots)) != 1:
            return self._unknown("disagreement")
        return Extraction(
            status="ok",
            value=value,
            method="llm",
            votes=VOTES,
            may_solely_support_different_entity=False,
            calls=self.calls,
            detail="unanimous",
        )

    def _vote(self, source_text: str, schema: dict, schema_name: str) -> dict | None:
        attempts = self.retries + 1
        for attempt in range(attempts):
            if self._over_cap():
                self._closed = True
                return None
            body = self._request(source_text, schema, schema_name)
            if body is _RATE_LIMITED:
                self._saw_rate_limit = True
                self._backoff(attempt)
                continue
            if body is None:
                continue
            parsed = _message_json(body)
            if parsed is None or not _schema_ok(parsed, schema):
                continue
            cleaned, _removed = _drop_prose(parsed)
            if not _quoted(cleaned, source_text):
                continue
            return cleaned
        return None

    def _request(self, source_text: str, schema: dict, schema_name: str) -> dict | None:
        if self.calls >= self.call_budget or self._over_cap():
            self._closed = True
            return None
        payload = {
            "model": self.model,
            "temperature": 0,
            "seed": self.seed,
            "provider": {"order": list(self.provider_order), "allow_fallbacks": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only JSON that matches the schema. "
                        "Copy strings verbatim from the source. Use null when a value is absent. "
                        "Do not explain."
                    ),
                },
                {"role": "user", "content": source_text},
            ],
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        self.calls += 1
        try:
            with self.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = getattr(response, "code", 200)
                raw = response.read()
        except urllib.error.HTTPError as error:
            if getattr(error, "code", None) == 429:
                self._retry_after = _retry_after_seconds(error)
                return _RATE_LIMITED
            return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None
        if status == 429:
            self._retry_after = None
            return _RATE_LIMITED
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _backoff(self, attempt: int) -> None:
        """Short pause after HTTP 429. Never waits long enough to threaten the run cap."""
        hinted = getattr(self, "_retry_after", None)
        delay = min(MAX_BACKOFF_SECONDS, 0.5 * (2 ** attempt))
        if hinted is not None:
            delay = min(MAX_BACKOFF_SECONDS, hinted)
        remaining = self.time_cap - (self.clock() - self.started)
        if remaining <= 0:
            self._closed = True
            return
        self.sleeper(min(delay, remaining))

    def _over_cap(self) -> bool:
        return (self.clock() - self.started) >= self.time_cap or self.calls > self.call_budget

    def _unknown(self, detail: str) -> Extraction:
        return Extraction(status="unknown", value=None, method=None, votes=0, calls=self.calls, detail=detail)


def is_free_model(slug: str) -> bool:
    """True only for an OpenRouter free-tier slug (``...:free``)."""
    return isinstance(slug, str) and slug.strip().endswith(":free") and " " not in slug.strip()


def _retry_after_seconds(error: urllib.error.HTTPError):
    headers = getattr(error, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _message_json(body: dict) -> dict | None:
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _drop_prose(value: dict) -> tuple[dict, list[str]]:
    cleaned = {}
    dropped = []
    for key, item in value.items():
        if key in _DROPPED_KEYS:
            dropped.append(key)
            continue
        cleaned[key] = item
    return cleaned, dropped


def _quoted(value, source: str) -> bool:
    """Every non-empty string in the extraction appears verbatim in ``source``."""
    if isinstance(value, str):
        return value == "" or value in source
    if isinstance(value, dict):
        return all(_quoted(item, source) for item in value.values())
    if isinstance(value, list):
        return all(_quoted(item, source) for item in value)
    return True


def _schema_ok(value, schema: dict) -> bool:
    if not isinstance(schema, dict):
        return False
    expected = schema.get("type")
    if isinstance(expected, list):
        return any(_schema_ok(value, {**schema, "type": item}) for item in expected)
    if expected == "object":
        if not isinstance(value, dict):
            return False
        required = schema.get("required") or []
        if any(key not in value for key in required):
            return False
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            return False
        for key, spec in properties.items():
            if key in value and not _schema_ok(value[key], spec):
                return False
        return True
    if expected == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items")
        if item_schema is None:
            return True
        return all(_schema_ok(item, item_schema) for item in value)
    if expected == "string":
        return isinstance(value, str)
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True
