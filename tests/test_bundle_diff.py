from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

from app.diff import diff_bundles


def _make_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def _make_tar(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_bundle_diff_detects_added_removed_changed(tmp_path: Path) -> None:
    before = tmp_path / "before.zip"
    after = tmp_path / "after.zip"
    _make_zip(
        before,
        {
            "kept.txt": b"unchanged",
            "removed.txt": b"goodbye",
            "data.json": json.dumps({"x": 1}).encode(),
        },
    )
    _make_zip(
        after,
        {
            "kept.txt": b"unchanged",
            "added.txt": b"new content",
            "data.json": json.dumps({"x": 2}).encode(),
        },
    )

    diff = diff_bundles(before, after)
    kinds = {m.name: m.kind for m in diff.members}
    assert kinds["kept.txt"] == "equal"
    assert kinds["removed.txt"] == "removed"
    assert kinds["added.txt"] == "added"
    assert kinds["data.json"] == "changed"
    summary = diff.summary()
    assert "data.json" in summary
    assert "removed.txt" in summary
    assert "added.txt" in summary


def test_bundle_diff_persistence_keyword_in_after(tmp_path: Path) -> None:
    before = tmp_path / "before.tar.gz"
    after = tmp_path / "after.tar.gz"
    _make_tar(before, {"export.csv": b"id,name\n1,foo\n"})
    # operator deletes 'foo', but export still mentions 'foo'.
    _make_tar(after, {"export.csv": b"id,name\n1,foo\n"})

    diff = diff_bundles(before, after, keywords=["foo"])
    csv_member = next(m for m in diff.members if m.name == "export.csv")
    assert csv_member.kind == "equal"
    assert any("declared_keyword_persisted" in p for p in csv_member.persistence)


def test_bundle_diff_identical_summary(tmp_path: Path) -> None:
    before = tmp_path / "b.zip"
    after = tmp_path / "a.zip"
    _make_zip(before, {"x.txt": b"same"})
    _make_zip(after, {"x.txt": b"same"})
    diff = diff_bundles(before, after)
    assert diff.changed_members == []
    assert "identical" in diff.summary()
