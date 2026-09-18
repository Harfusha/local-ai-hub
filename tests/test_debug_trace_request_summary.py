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
        return DebugTraceStore({"server": {"state_dir": state_dir}})

    def test_command_list_row_has_redacted_summary_only(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", tenant="test", action="/api/command", request_id="req-1")
            store.update(trace_id, request={"action": "run", "command": "python tools/check_dashboard.py --api-token SUPERSECRET123"})

            item = store.list(limit=10)["items"][0]

            self.assertEqual(item["request_summary"], "run · python tools/check_dashboard.py --api-token [redacted]")
            self.assertNotIn("SUPERSECRET123", json.dumps(item))
            self.assertNotIn("request_json", item)
            self.assertNotIn("request", item)

    def test_other_route_request_text_is_not_returned_in_list(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", tenant="test", action="/api/reason", request_id="req-2")
            store.update(trace_id, request={"task": "private prompt content"})

            item = store.list(limit=10)["items"][0]

            self.assertEqual(item["request_summary"], "")
            self.assertNotIn("private prompt content", json.dumps(item))

    def test_list_row_exposes_compact_project_label(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", tenant="test", action="/api/search", request_id="req-project")
            store.update(trace_id, request={"root": "C:/workspace/hub", "query": "trace"})

            item = store.list(limit=10)["items"][0]

            self.assertEqual(item["project"], "hub")
            self.assertNotIn("C:/workspace", json.dumps(item))

    def test_http_trace_capture_redacts_nested_sensitive_values_and_omits_large_or_binary_data(self):
        from local_ai_hub.http_server import Handler

        captured = Handler._safe_debug_trace_request(
            {
                "task": "inspect",
                "api_key": "api-secret",
                "nested": {"authorization": "Bearer authorization-secret", "safe": "kept"},
            }
        )

        self.assertEqual(captured["api_key"], "[redacted]")
        self.assertEqual(captured["nested"]["authorization"], "[redacted]")
        self.assertEqual(captured["nested"]["safe"], "kept")
        self.assertNotIn("api-secret", json.dumps(captured))
        self.assertEqual(Handler._safe_debug_trace_request(b"\x00\x01")["capture_status"], "omitted")
        self.assertEqual(
            Handler._safe_debug_trace_request({"body": "x" * (Handler.DEBUG_TRACE_REQUEST_CAPTURE_BYTES + 1)})[
                "capture_status"
            ],
            "omitted",
        )

    def test_observer_persists_thinking_separately_from_final_output(self):
        with tempfile.TemporaryDirectory() as state_dir:
            store = self._store(state_dir)
            trace_id = store.start(kind="api_request", tenant="test", action="/api/review", request_id="req-thinking")
            observer = DebugTraceObserver(store, trace_id)

            observer.thinking_delta("private reasoning")
            observer.output_delta("final answer")
            detail = store.detail(trace_id)

            assert detail["session"]["thinking"] == "private reasoning"
            assert detail["session"]["output"] == "final answer"
            assert [event["event_type"] for event in detail["events"]] == ["thinking", "output_delta"]


if __name__ == "__main__":
    unittest.main()
