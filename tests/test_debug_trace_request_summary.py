from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.debug_traces import DebugTraceObserver, DebugTraceStore


class DebugTraceRequestSummaryTests(unittest.TestCase):
    def _store(self, state_dir: str) -> DebugTraceStore:
        return DebugTraceStore({"server": {"state_dir": state_dir}, "debug_traces": {"enabled": True}})

    def test_command_list_row_has_redacted_summary_only(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", action="/api/command", request_id="req-1")
            store.update(trace_id, request={"action": "run", "command": "python tools/check_dashboard.py --api-token SUPERSECRET123"})

            item = store.list(limit=10)["items"][0]

            self.assertEqual(item["request_summary"], "run · python tools/check_dashboard.py --api-token [redacted]")
            self.assertNotIn("SUPERSECRET123", json.dumps(item))
            self.assertNotIn("request_json", item)
            self.assertNotIn("request", item)

    def test_other_route_request_text_is_not_returned_in_list(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", action="/api/reason", request_id="req-2")
            store.update(trace_id, request={"task": "private prompt content"})

            item = store.list(limit=10)["items"][0]

            self.assertEqual(item["request_summary"], "")
            self.assertNotIn("private prompt content", json.dumps(item))

    def test_list_row_exposes_compact_project_label(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", action="/api/search", request_id="req-project")
            store.update(trace_id, request={"root": "C:/workspace/hub", "query": "trace"})

            item = store.list(limit=10)["items"][0]

            self.assertEqual(item["project"], "hub")
            self.assertNotIn("C:/workspace", json.dumps(item))

    def test_http_trace_capture_keeps_complete_local_payload(self):
        from local_ai_hub.http_server import Handler

        captured = Handler._safe_debug_trace_request(
            {
                "task": "inspect",
                "api_key": "api-secret",
                "client_secret": "client-secret",
                "clientSecret": "camel-secret",
                "X-LocalAI-Token": "local-token",
                "nested": {
                    "authorization": "Bearer authorization-secret",
                    "auth.token": "dot-token-secret",
                    "credentials.apiKey": "dotted-camel-secret",
                    "safe": "kept",
                },
                "headers": {"x-api-key": "header-api-secret"},
                "large": "x" * 10_000,
                "binary": b"\x00\xff",
            }
        )

        self.assertEqual(captured["task"], "inspect")
        self.assertEqual(captured["large"], "x" * 10_000)
        self.assertEqual(captured["nested"]["safe"], "kept")
        captured_json = json.dumps(captured)
        for secret in (
            "api-secret", "client-secret", "camel-secret", "local-token",
            "dot-token-secret", "dotted-camel-secret", "header-api-secret",
        ):
            self.assertIn(secret, captured_json)
        self.assertIn("safe", captured_json)
        self.assertIn("camel-secret", json.dumps(captured))
        self.assertIn("local-token", json.dumps(captured))
        self.assertIn("dot-token-secret", json.dumps(captured))
        self.assertIn("dotted-camel-secret", json.dumps(captured))
        self.assertIn("header-api-secret", json.dumps(captured))
        binary_request = Handler._safe_debug_trace_request(b"\x00\x01")
        self.assertEqual(binary_request, {"encoding": "base64", "data": "AAE="})
        large_body = "x" * 100_000
        large_request = Handler._safe_debug_trace_request({"body": large_body})
        self.assertEqual(large_request["body"], large_body)
        self.assertNotIn("capture_status", large_request)

    def test_enabled_observer_persists_complete_thinking_and_final_output(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", action="/api/review", request_id="req-thinking")
            observer = DebugTraceObserver(store, trace_id)

            observer.thinking_delta("private reasoning")
            observer.output_delta("final answer")
            detail = store.detail(trace_id)

            assert detail["session"]["thinking"] == "private reasoning"
            assert detail["session"]["output"] == "final answer"
            assert "private reasoning" in json.dumps(detail)
            assert "final answer" in json.dumps(detail)
            assert [event["event_type"] for event in detail["events"]] == ["thinking", "output_delta"]


if __name__ == "__main__":
    unittest.main()
