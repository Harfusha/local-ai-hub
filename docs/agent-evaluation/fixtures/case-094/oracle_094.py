"""Acceptance oracle for a disposable copy of the case-094 fixture."""

from collections import Counter
import threading
import unittest

from batch_export import ExportCancelled, process_batch


def exercise():
    started = threading.Event()
    release = threading.Event()
    calls = Counter()
    output = []
    items = [{"id": "valid"}, {"id": "invalid"}, {"id": "slow", "retry": True}, {"id": "cancelled"}]

    def export(item):
        key = item["id"]
        calls[key] += 1
        if key == "invalid":
            raise ValueError("invalid item")
        if key == "cancelled":
            raise ExportCancelled("cancelled by caller")
        if key == "slow":
            started.set()
            if not release.wait(2):
                raise TimeoutError("fixture gate was not released")
        return key + "-export"

    worker = threading.Thread(target=lambda: output.append(process_batch(items, export)), daemon=True)
    worker.start()
    if not started.wait(2):
        release.set()
        worker.join(2)
        raise AssertionError("slow item did not reach its gate")
    release.set()
    worker.join(2)
    if worker.is_alive() or len(output) != 1:
        raise AssertionError("batch did not finish after releasing the gate")
    return output[0], calls


class BatchOracle(unittest.TestCase):
    def test_per_item_results_keep_order_errors_and_cancellation(self):
        result, _ = exercise()
        self.assertEqual(
            [(item["id"], item["status"]) for item in result["items"]],
            [("valid", "ok"), ("invalid", "error"), ("slow", "ok"), ("cancelled", "cancelled")],
        )
        self.assertIn("invalid item", result["items"][1]["error"])

    def test_aggregate_success_reflects_partial_failure(self):
        result, _ = exercise()
        self.assertIs(result["success"], False)

    def test_successful_export_is_not_repeated(self):
        _, calls = exercise()
        self.assertEqual(calls, {"valid": 1, "invalid": 1, "slow": 1, "cancelled": 1})


if __name__ == "__main__":
    unittest.main()
