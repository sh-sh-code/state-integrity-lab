"""Screenshot diff (Phase 1: byte / size comparison only).

Phase 2 will add a real perceptual diff (e.g. via Pillow + ImageChops).
The Phase 1 implementation reports "different" / "same" / "size changed"
based on file metadata, so reports can at least flag whether visual review
is required.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScreenshotDiff:
    same_bytes: bool
    before_size: int
    after_size: int
    before_sha256: str
    after_sha256: str

    def summary(self) -> str:
        if self.same_bytes:
            return "Screenshots are byte-identical."
        delta = self.after_size - self.before_size
        return (
            f"Screenshots differ. before={self.before_size}B "
            f"after={self.after_size}B (Δ={delta:+d}B). "
            "Visual review required (perceptual diff is Phase 2)."
        )


def _hash(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def diff_screenshots(before_path: Path | str, after_path: Path | str) -> ScreenshotDiff:
    bp = Path(before_path)
    ap = Path(after_path)
    before_size, before_hash = _hash(bp)
    after_size, after_hash = _hash(ap)
    return ScreenshotDiff(
        same_bytes=before_hash == after_hash,
        before_size=before_size,
        after_size=after_size,
        before_sha256=before_hash,
        after_sha256=after_hash,
    )
