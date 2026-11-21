"""OpenRouter client tests. HTTP is mocked; no network and no API key."""

import json
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.llm_client import (
    DEFAULT_ITEM_CALL_BUDGET,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER_ORDER,
    DEFAULT_TIME_CAP_SECONDS,
    OpenRouterClient,
    is_free_model,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "dob"],
    "properties": {
        "name": {"type": ["string", "null"]},
        "dob": {"type": ["string", "null"]},
    },
}
SOURCE = "ADA LOVELACE born 1990-01-01 in the file."


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _urlopen_factory(contents):
    calls = []

    def urlopen(request, timeout=None):
        calls.append({
            "timeout": timeout,
            "body": json.loads(request.data.decode("utf-8")),
            "header": request.get_header("Authorization"),
        })
        content = contents[len(calls) - 1] if len(calls) <= len(contents) else contents[-1]
        return _Response({"choices": [{"message": {"content": json.dumps(content)}}]})

    return urlopen, calls


class ClientTests(unittest.TestCase):
    def test_unanimous_quote_checked_value_cannot_solely_clear(self):
        urlopen, calls = _urlopen_factory([
            {"name": "ADA LOVELACE", "dob": "1990-01-01", "reason": "because I said so"},
            {"name": "ADA LOVELACE", "dob": "1990-01-01"},
            {"name": "ADA LOVELACE", "dob": "1990-01-01"},
        ])
        # The strict schema rejects the extra reason key, so give the agreeing
        # votes a schema that allows and then drops prose.
        loose = {
            "type": "object",
            "additionalProperties": True,
            "required": ["name", "dob"],
            "properties": SCHEMA["properties"],
        }
        client = OpenRouterClient(urlopen=urlopen, api_key="test-key", clock=lambda: 0.0)
        result = client.extract(SOURCE, loose)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value, {"name": "ADA LOVELACE", "dob": "1990-01-01"})
        self.assertNotIn("reason", result.value)
        self.assertEqual(result.method, "llm")
        self.assertFalse(result.may_solely_support_different_entity)
        self.assertEqual(result.votes, 3)
        self.assertEqual(len(calls), 3)
        body = calls[0]["body"]
        self.assertEqual(body["model"], DEFAULT_MODEL)
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["seed"], 0)
        self.assertEqual(body["provider"]["order"], list(DEFAULT_PROVIDER_ORDER))
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(calls[0]["timeout"], client.timeout)
        self.assertTrue(calls[0]["header"].startswith("Bearer "))
        self.assertNotIn("sk-", calls[0]["header"])

    def test_disagreement_is_unknown(self):
        urlopen, _calls = _urlopen_factory([
            {"name": "ADA LOVELACE", "dob": "1990-01-01"},
            {"name": "ADA LOVELACE", "dob": "1991-01-01"},
            {"name": "ADA LOVELACE", "dob": "1990-01-01"},
        ])
        client = OpenRouterClient(urlopen=urlopen, api_key="test-key", clock=lambda: 0.0)
        result = client.extract(SOURCE + " 1991-01-01", SCHEMA)
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.value)
        self.assertFalse(result.may_solely_support_different_entity)

    def test_quote_miss_timeout_missing_key_and_caps(self):
        urlopen, calls = _urlopen_factory([{"name": "NOT PRESENT", "dob": None}])
        client = OpenRouterClient(urlopen=urlopen, api_key="test-key", clock=lambda: 0.0, retries=1)
        result = client.extract(SOURCE, SCHEMA)
        self.assertEqual(result.status, "unknown")
        self.assertGreaterEqual(len(calls), 2)

        def explode(_request, timeout=None):
            raise TimeoutError("slow")

        client = OpenRouterClient(urlopen=explode, api_key="test-key", clock=lambda: 0.0, retries=1)
        self.assertEqual(client.extract(SOURCE, SCHEMA).status, "unknown")

        called = {"n": 0}

        def forbidden(_request, timeout=None):
            called["n"] += 1
            raise AssertionError("network")

        client = OpenRouterClient(urlopen=forbidden, api_key="", clock=lambda: 0.0)
        self.assertEqual(client.extract(SOURCE, SCHEMA).detail, "missing_api_key")
        self.assertEqual(called["n"], 0)

        now = {"t": 0.0}

        def clock():
            return now["t"]

        urlopen, calls = _urlopen_factory([{"name": "ADA LOVELACE", "dob": None}])
        client = OpenRouterClient(urlopen=urlopen, api_key="test-key", clock=clock, time_cap=5)
        now["t"] = 5
        result = client.extract(SOURCE, SCHEMA)
        self.assertEqual(result.detail, "time_or_budget_cap")
        self.assertEqual(calls, [])

        urlopen, calls = _urlopen_factory([{"name": "ADA LOVELACE", "dob": None}])
        client = OpenRouterClient(urlopen=urlopen, api_key="test-key", clock=lambda: 0.0, call_budget=0)
        self.assertEqual(client.extract(SOURCE, SCHEMA).status, "unknown")
        self.assertEqual(calls, [])

    def test_free_model_only_and_bounded_429_backoff(self):
        self.assertEqual(DEFAULT_TIME_CAP_SECONDS, 1200.0)
        self.assertEqual(DEFAULT_ITEM_CALL_BUDGET, 12)
        self.assertLess(DEFAULT_TIME_CAP_SECONDS, 30 * 60)
        self.assertTrue(DEFAULT_MODEL.endswith(":free"))
        self.assertTrue(is_free_model(DEFAULT_MODEL))
        self.assertFalse(is_free_model("openai/gpt-4o-mini"))

        called = {"n": 0}

        def forbidden(_request, timeout=None):
            called["n"] += 1
            raise AssertionError("paid model must not call the network")

        client = OpenRouterClient(
            urlopen=forbidden, api_key="test-key", clock=lambda: 0.0, model="openai/gpt-4o-mini-2024-07-18"
        )
        refused = client.extract(SOURCE, SCHEMA)
        self.assertEqual(refused.status, "unknown")
        self.assertEqual(refused.detail, "model_not_free")
        self.assertIsNone(refused.value)
        self.assertEqual(called["n"], 0)

        delays = []

        def sleeper(seconds):
            delays.append(seconds)

        attempts = {"n": 0}

        def rate_limit(request, timeout=None):
            attempts["n"] += 1
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", None, None)

        client = OpenRouterClient(
            urlopen=rate_limit,
            api_key="test-key",
            clock=lambda: 0.0,
            sleeper=sleeper,
            retries=2,
        )
        limited = client.extract(SOURCE, SCHEMA)
        self.assertEqual(limited.status, "unknown")
        self.assertEqual(limited.detail, "rate_limited")
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(len(delays), 3)
        self.assertTrue(all(0 < delay <= 8 for delay in delays))

        seen = {"n": 0}

        def then_ok(request, timeout=None):
            seen["n"] += 1
            if seen["n"] == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", None, None)
            content = {"name": "ADA LOVELACE", "dob": "1990-01-01"}
            return _Response({"choices": [{"message": {"content": json.dumps(content)}}]})

        client = OpenRouterClient(
            urlopen=then_ok,
            api_key="test-key",
            clock=lambda: 0.0,
            sleeper=sleeper,
            retries=2,
        )
        recovered = client.extract(SOURCE, SCHEMA)
        self.assertEqual(recovered.status, "ok")
        self.assertEqual(recovered.method, "llm")
        self.assertFalse(recovered.may_solely_support_different_entity)

    def test_item_budget_leaves_the_run_open(self):
        calls = {"n": 0}

        def urlopen(_request, timeout=None):
            calls["n"] += 1
            content = {"name": "NOT PRESENT", "dob": None}
            return _Response({"choices": [{"message": {"content": json.dumps(content)}}]})

        client = OpenRouterClient(
            urlopen=urlopen,
            api_key="test-key",
            clock=lambda: 0.0,
            item_call_budget=1,
            call_budget=4,
            retries=3,
        )
        first = client.extract(SOURCE, SCHEMA)
        self.assertEqual(first.detail, "item_call_budget")
        self.assertFalse(client._closed)
        used = calls["n"]
        second = client.extract(SOURCE, SCHEMA)
        self.assertEqual(second.detail, "item_call_budget")
        self.assertGreater(calls["n"], used)
        self.assertLessEqual(calls["n"], 4)


if __name__ == "__main__":
    unittest.main()
