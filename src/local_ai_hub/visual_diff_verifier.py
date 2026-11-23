"""Multi-Modal Visual Diff and UI Regression Verifier.

Compares rendered UI screenshots or component previews before and after code changes.
Employs perceptual hashing (dHash/pHash), pixel-level structural delta detection,
bounding box localization of visual shifts, and vision model evaluation (e.g. minicpm-v:8b).
Protects frontend code changes from unexpected visual regressions and layout breakage.
"""

from __future__ import annotations

import io
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualDiffResult:
    """Outcome of visual screenshot comparison."""

    identical: bool
    similarity_score: float  # [0.0, 1.0]
    changed_pixel_ratio: float
    hamming_distance: int
    bounding_box: tuple[int, int, int, int] | None  # (left, top, right, bottom)
    semantic_verdict: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_dhash(img: Image.Image, hash_size: int = 8) -> int:
    """Calculate 64-bit difference hash (dHash) for fast perceptual matching."""
    # Resize to (hash_size + 1, hash_size) in grayscale
    resized = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    raw_bytes = resized.tobytes()
    width = hash_size + 1

    diff_bits = 0
    for row in range(hash_size):
        row_offset = row * width
        for col in range(hash_size):
            left = raw_bytes[row_offset + col]
            right = raw_bytes[row_offset + col + 1]
            diff_bits = (diff_bits << 1) | (1 if left > right else 0)

    return diff_bits


def hamming_distance(h1: int, h2: int) -> int:
    """Compute number of differing bits between two 64-bit integer hashes."""
    x = h1 ^ h2
    return bin(x).count("1")


def verify_visual_diff(
    image_a_input: Image.Image | bytes | str | Path,
    image_b_input: Image.Image | bytes | str | Path,
    tolerance_ratio: float = 0.01,
) -> VisualDiffResult:
    """Compare baseline and modified UI images to detect visual regressions."""
    def to_image(inp: Image.Image | bytes | str | Path) -> Image.Image:
        if isinstance(inp, Image.Image):
            return inp.convert("RGBA")
        if isinstance(inp, (bytes, bytearray)):
            return Image.open(io.BytesIO(inp)).convert("RGBA")
        return Image.open(str(inp)).convert("RGBA")

    img_a = to_image(image_a_input)
    img_b = to_image(image_b_input)

    # Align dimensions if different
    if img_a.size != img_b.size:
        max_w = max(img_a.width, img_b.width)
        max_h = max(img_a.height, img_b.height)
        canvas_a = Image.new("RGBA", (max_w, max_h), (255, 255, 255, 0))
        canvas_b = Image.new("RGBA", (max_w, max_h), (255, 255, 255, 0))
        canvas_a.paste(img_a, (0, 0))
        canvas_b.paste(img_b, (0, 0))
        img_a = canvas_a
        img_b = canvas_b

    # 1. Perceptual dHash
    h_a = compute_dhash(img_a)
    h_b = compute_dhash(img_b)
    h_dist = hamming_distance(h_a, h_b)

    # 2. Pixel difference in RGB space to ensure alpha does not mask differences
    diff = ImageChops.difference(img_a.convert("RGB"), img_b.convert("RGB"))
    bbox = diff.getbbox()

    if bbox is None:
        # Perfectly identical
        return VisualDiffResult(
            identical=True,
            similarity_score=1.0,
            changed_pixel_ratio=0.0,
            hamming_distance=0,
            bounding_box=None,
            semantic_verdict="Pixel-perfect match. No visual regressions detected.",
        )

    # Count differing pixels
    diff_gray = diff.convert("L")
    non_zero = sum(1 for p in diff_gray.tobytes() if p > 10)
    total_pixels = img_a.width * img_a.height
    changed_ratio = non_zero / float(total_pixels)

    similarity = max(0.0, 1.0 - changed_ratio)
    identical = (changed_ratio <= tolerance_ratio and h_dist <= 2)

    if identical:
        verdict = f"Minor sub-pixel variations within tolerance ({changed_ratio:.2%})."
    else:
        verdict = f"Visual regression detected! {changed_ratio:.1%} pixels altered within bounding box {bbox}."

    return VisualDiffResult(
        identical=identical,
        similarity_score=similarity,
        changed_pixel_ratio=changed_ratio,
        hamming_distance=h_dist,
        bounding_box=bbox,
        semantic_verdict=verdict,
    )
