from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_offscreen_redaction_mask_scales_and_rejects_unbounded_regions() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            "node",
            str(root / "tests/fixtures/browser_bridge/offscreen_privacy_harness.js"),
            str(root / "browser_bridge/offscreen.js"),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    evidence = json.loads(result.stdout)
    assert evidence == {
        "success": True,
        "cases": ["scaled-device-pixels", "reject-negative-region", "reject-outside-region", "opaque-pixel-mask"],
    }


def test_popup_requires_consent_and_extra_ack_for_full_capture() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            "node",
            str(root / "tests/fixtures/browser_bridge/popup_privacy_harness.js"),
            str(root / "browser_bridge/popup.js"),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    evidence = json.loads(result.stdout)
    assert evidence == {
        "success": True,
        "cases": ["redacted-consent", "screenshot-consent", "full-mode-extra-ack", "first-notice-required", "reject-unknown-mode"],
    }
