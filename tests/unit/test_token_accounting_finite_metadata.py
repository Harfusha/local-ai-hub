"""Deferred wire-safety checks for metadata supplied by timing producers."""

import json

import pytest

from local_ai_hub.token_accounting import token_efficiency_metadata


@pytest.mark.parametrize("wait", [float("inf"), float("-inf"), float("nan"), 10**400])
def test_nonfinite_queue_wait_metadata_remains_strict_json_safe(wait):
    metadata = token_efficiency_metadata(queue_wait_ms=wait)

    assert metadata["queue_wait_ms"] == 0.0
    json.dumps(metadata, allow_nan=False)


def test_finite_queue_wait_metadata_keeps_existing_precision():
    metadata = token_efficiency_metadata(queue_wait_ms=12.34)

    assert metadata["queue_wait_ms"] == 12.3
    json.dumps(metadata, allow_nan=False)
