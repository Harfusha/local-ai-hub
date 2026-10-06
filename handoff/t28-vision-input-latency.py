from __future__ import annotations

import base64
import hashlib
import statistics
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from local_ai_hub.frontend_review import FrontendReviewError, build_model_context, parse_bounded_context
from local_ai_hub.json_utils import dumps as json_dumps
from local_ai_hub.vision_contracts import (
    VISION_MAX_BUNDLE_CHARS,
    VISION_MAX_IMAGE_BYTES,
    VISION_MAX_IMAGE_CHARS,
    image_dimensions,
)
from local_ai_hub.vision_inputs import VisionInputs, prepare_vision_inputs

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "handoff" / "t28-vision-root-current.patch"
HELPER = ROOT / "src" / "local_ai_hub" / "vision_inputs.py"
EXPECTED_HELPER_SHA256 = "FAA436CB9F4F0720409E27F45E7908A2BC1AB28EF90D20603A49098959EE1D40"


def legacy_function():
    patch_lines = PATCH.read_text(encoding="utf-8").splitlines()
    target = next(i for i, line in enumerate(patch_lines) if line == "-        def input_error(message: str, code: str = \"vision_input_error\") -> dict[str, Any]:")
    hunk_start = max(i for i in range(target) if patch_lines[i].startswith("@@"))
    hunk_end = next((i for i in range(target + 1, len(patch_lines)) if patch_lines[i].startswith(("@@", "diff --git "))), len(patch_lines))
    removed = [line[1:] for line in patch_lines[hunk_start:hunk_end] if line.startswith("-") and not line.startswith("---")]
    if not removed or not removed[0].lstrip().startswith("def input_error"):
        raise RuntimeError("root preimage input block unavailable in patch")
    body = []
    for line in removed:
        if line.strip():
            if not line.startswith("        "):
                raise RuntimeError("unexpected root preimage indentation")
            body.append(line[4:])
        else:
            body.append("")
    source = "\n".join([
        "def legacy_prepare_vision_inputs(*, args, image_path, prompt, tenant, artifacts):",
        "    self = SimpleNamespace(artifacts=artifacts)",
        *body,
        "    image_size = image_dimensions(base64.b64decode(images[0], validate=True))",
        "    return (images, image_artifact_id, bundle_artifact_id, bundle_context, frontend_bundle, model_context, image_size)",
    ])
    namespace: dict[str, Any] = globals().copy()
    exec(compile(source, "<root-vision-input-preimage>", "exec"), namespace)
    return namespace["legacy_prepare_vision_inputs"]


def normalize(value: Any) -> Any:
    if isinstance(value, VisionInputs):
        return (
            value.images,
            value.image_artifact_id,
            value.bundle_artifact_id,
            value.bundle_context,
            value.frontend_bundle,
            value.model_context,
            value.image_size,
        )
    return value


def batch_latency(function, args, repetitions: int = 1000, batches: int = 20) -> tuple[float, float]:
    for _ in range(100):
        function(**args)
    samples = []
    for _ in range(batches):
        started = time.perf_counter_ns()
        for _ in range(repetitions):
            function(**args)
        samples.append((time.perf_counter_ns() - started) / repetitions / 1_000_000)
    ordered = sorted(samples)
    return statistics.median(ordered), ordered[int(0.95 * (len(ordered) - 1))]


def main() -> None:
    actual = hashlib.sha256(HELPER.read_bytes()).hexdigest().upper()
    if actual != EXPECTED_HELPER_SHA256:
        raise SystemExit(f"helper hash mismatch: {actual}")
    old = legacy_function()
    artifacts = MagicMock()
    data_url = "data:image/png;base64," + base64.b64encode(b"fake-image-payload").decode("ascii")
    args = {"args": {"image": data_url}, "image_path": data_url, "prompt": "review", "tenant": "tenant-a", "artifacts": artifacts}
    old_value = old(**args)
    new_value = prepare_vision_inputs(**args)
    if normalize(old_value) != normalize(new_value):
        raise SystemExit("legacy/current prepared inputs differ")
    before = batch_latency(old, args)
    after = batch_latency(prepare_vision_inputs, args)
    print(f"parity=PASS repetitions=1000 batches=20 helper_sha256={actual}")
    print(f"before_inline_root_input_stage_median_ms={before[0]:.6f} p95_ms={before[1]:.6f}")
    print(f"after_candidate_helper_median_ms={after[0]:.6f} p95_ms={after[1]:.6f}")
    print(f"median_delta_percent={(after[0] / before[0] - 1.0) * 100.0:.2f}")
    print("scope=CPU-only input preparation; mocked artifact store; no model/runtime/network/GPU")


if __name__ == "__main__":
    main()
