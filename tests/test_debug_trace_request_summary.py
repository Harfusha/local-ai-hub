from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.debug_traces import DebugTraceStore


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


if __name__ == "__main__":
    unittest.main()
