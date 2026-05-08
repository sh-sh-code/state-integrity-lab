"""Screenshot diff.

Phase 2: perceptual diff using Pillow + ImageChops.

- Loads both screenshots, normalizes to the same size (smaller-of-two).
- Optionally blanks out caller-supplied ignore regions (dynamic UI such as
  timestamps, avatars).
- Returns the percentage of differing pixels and writes a diff image
  (`diff_<sha>.png`) next to the after artifact.

Falls back to byte / size comparison if Pillow is unavailable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]


IgnoreRegion = tuple[int, int, int, int]  # (x, y, w, h)


@dataclass
class ScreenshotDiff:
    same_bytes: bool
    before_size: int
    after_size: int
    before_sha256: str
    after_sha256: str
    differing_pixel_ratio: float | None = None
    diff_image_path: Path | None = None
    width: int | None = None
    height: int | None = None
    ignore_regions: list[IgnoreRegion] = field(default_factory=list)

    @property
    def severity_hint(self) -> str:
        if self.same_bytes:
            return "info"
        if self.differing_pixel_ratio is None:
            return "needs_review"
        ratio = self.differing_pixel_ratio
        if ratio < 0.0005:
            return "info"
        if ratio < 0.01:
            return "low"
        if ratio < 0.05:
            return "medium"
        if ratio < 0.20:
            return "needs_review"
        return "high"

    def summary(self) -> str:
        if self.same_bytes:
            return "Screenshots are byte-identical."
        if self.differing_pixel_ratio is None:
            delta = self.after_size - self.before_size
            return (
                f"Screenshots differ. before={self.before_size}B "
                f"after={self.after_size}B (Δ={delta:+d}B). "
                "Pillow unavailable; perceptual diff skipped."
            )
        pct = self.differing_pixel_ratio * 100
        parts = [f"Screenshots differ in {pct:.3f}% of pixels."]
        if self.width is not None and self.height is not None:
            parts.append(f"Compared at {self.width}x{self.height}.")
        if self.ignore_regions:
            parts.append(f"Ignored {len(self.ignore_regions)} region(s).")
        if self.diff_image_path is not None:
            parts.append(f"Diff image: {self.diff_image_path}")
        return " ".join(parts)


def _hash(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def diff_screenshots(
    before_path: Path | str,
    after_path: Path | str,
    *,
    ignore_regions: list[IgnoreRegion] | None = None,
    write_diff_image: bool = True,
) -> ScreenshotDiff:
    bp = Path(before_path)
    ap = Path(after_path)
    before_size, before_hash = _hash(bp)
    after_size, after_hash = _hash(ap)
    same = before_hash == after_hash
    result = ScreenshotDiff(
        same_bytes=same,
        before_size=before_size,
        after_size=after_size,
        before_sha256=before_hash,
        after_sha256=after_hash,
        ignore_regions=list(ignore_regions or []),
    )
    if same or Image is None:
        return result

    try:
        before_img = Image.open(bp).convert("RGB")
        after_img = Image.open(ap).convert("RGB")
    except Exception:
        return result

    width = min(before_img.width, after_img.width)
    height = min(before_img.height, after_img.height)
    before_img = before_img.crop((0, 0, width, height))
    after_img = after_img.crop((0, 0, width, height))
    result.width = width
    result.height = height

    if ignore_regions:
        for img in (before_img, after_img):
            draw = ImageDraw.Draw(img)
            for x, y, w, h in ignore_regions:
                draw.rectangle((x, y, x + w, y + h), fill=(0, 0, 0))

    chops_diff = ImageChops.difference(before_img, after_img)
    bbox = chops_diff.getbbox()
    if bbox is None:
        result.differing_pixel_ratio = 0.0
        return result

    grayscale = chops_diff.convert("L")
    iter_pixels = getattr(grayscale, "get_flattened_data", grayscale.getdata)
    pixels = list(iter_pixels())
    differing = sum(1 for px in pixels if int(px) > 0)
    total = width * height
    result.differing_pixel_ratio = differing / total if total else 0.0

    if write_diff_image:
        diff_path = ap.with_name(f"diff_{after_hash[:12]}.png")
        chops_diff.save(diff_path)
        result.diff_image_path = diff_path

    return result
