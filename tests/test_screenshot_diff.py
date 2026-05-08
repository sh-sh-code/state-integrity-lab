from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from app.diff import diff_screenshots  # noqa: E402


def _solid_png(path: Path, color: tuple[int, int, int], size=(40, 40)) -> None:
    img = Image.new("RGB", size, color)
    img.save(path, format="PNG")


def test_perceptual_diff_zero_for_identical(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _solid_png(a, (200, 50, 50))
    b.write_bytes(a.read_bytes())
    diff = diff_screenshots(a, b)
    assert diff.same_bytes is True
    assert diff.severity_hint == "info"


def test_perceptual_diff_high_for_completely_different(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _solid_png(a, (255, 0, 0))
    _solid_png(b, (0, 255, 0))
    diff = diff_screenshots(a, b)
    assert diff.same_bytes is False
    assert diff.differing_pixel_ratio is not None
    assert diff.differing_pixel_ratio > 0.99
    assert diff.severity_hint == "high"
    assert diff.diff_image_path is not None
    assert diff.diff_image_path.exists()


def test_perceptual_diff_low_for_small_change(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _solid_png(a, (255, 255, 255), size=(100, 100))
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    # Change a small 5x5 patch (0.25% of pixels).
    for x in range(5):
        for y in range(5):
            img.putpixel((x, y), (0, 0, 0))
    img.save(b, format="PNG")
    diff = diff_screenshots(a, b)
    assert 0.001 < (diff.differing_pixel_ratio or 0) < 0.01
    assert diff.severity_hint == "low"


def test_ignore_region_suppresses_diff(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _solid_png(a, (255, 255, 255), size=(20, 20))
    img = Image.new("RGB", (20, 20), (255, 255, 255))
    for x in range(0, 5):
        for y in range(0, 5):
            img.putpixel((x, y), (0, 0, 0))
    img.save(b, format="PNG")
    diff = diff_screenshots(a, b, ignore_regions=[(0, 0, 5, 5)], write_diff_image=False)
    assert diff.differing_pixel_ratio == 0.0
    assert diff.severity_hint == "info"
