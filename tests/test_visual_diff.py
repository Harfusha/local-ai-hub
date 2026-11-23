"""Tests for Visual Diff and UI Regression Verifier."""

from PIL import Image

from src.local_ai_hub.visual_diff_verifier import (
    compute_dhash,
    hamming_distance,
    verify_visual_diff,
)


def test_dhash_identical_images():
    img1 = Image.new("RGB", (64, 64), color="blue")
    img2 = Image.new("RGB", (64, 64), color="blue")
    h1 = compute_dhash(img1)
    h2 = compute_dhash(img2)
    assert hamming_distance(h1, h2) == 0


def test_visual_diff_identical():
    img1 = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
    img2 = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
    result = verify_visual_diff(img1, img2)

    assert result.identical is True
    assert result.similarity_score == 1.0
    assert result.changed_pixel_ratio == 0.0
    assert result.bounding_box is None


def test_visual_diff_detects_shift():
    img1 = Image.new("RGBA", (100, 100), color=(255, 255, 255, 255))
    img2 = Image.new("RGBA", (100, 100), color=(255, 255, 255, 255))

    # Add red rectangle to img2 (e.g. shifted button)
    for x in range(20, 50):
        for y in range(30, 60):
            img2.putpixel((x, y), (255, 0, 0, 255))

    result = verify_visual_diff(img1, img2, tolerance_ratio=0.001)
    assert result.identical is False
    assert result.changed_pixel_ratio > 0.05
    assert result.bounding_box is not None
    assert result.bounding_box[0] == 20
    assert result.bounding_box[1] == 30
