"""Diff two export bundles (.zip / .tar / .tar.gz).

Phase 2 implementation:

- Open both archives read-only.
- For each member name in `union(before, after)`:
    * `removed` if only in before
    * `added` if only in after
    * for shared members: structural JSON diff (.json), unified text diff
      (.txt / .md / .csv / .html), or byte-equality check otherwise.
- For text-like members, also run the keyword persistence check on the AFTER
  member's content so an operator can spot leftover deleted items.

Archives are extracted to a temporary directory and removed before return.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from app.diff.json_diff import diff_json
from app.diff.text_diff import detect_persistence, diff_text

_TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".html", ".htm", ".log", ".yaml", ".yml"}
_JSON_EXTS = {".json"}


@dataclass
class BundleMemberDiff:
    name: str
    kind: str  # added / removed / changed / equal
    detail: str = ""
    persistence: list[str] = field(default_factory=list)


@dataclass
class BundleDiff:
    before: str
    after: str
    members: list[BundleMemberDiff]
    keywords: list[str]

    @property
    def changed_members(self) -> list[BundleMemberDiff]:
        return [m for m in self.members if m.kind != "equal"]

    def summary(self) -> str:
        if not self.changed_members:
            return "Bundles contain identical members."
        lines: list[str] = []
        added = [m for m in self.members if m.kind == "added"]
        removed = [m for m in self.members if m.kind == "removed"]
        changed = [m for m in self.members if m.kind == "changed"]
        if removed:
            lines.append("== Members only in BEFORE bundle ==")
            for m in removed:
                lines.append(f"- {m.name}")
        if added:
            lines.append("")
            lines.append("== Members only in AFTER bundle ==")
            for m in added:
                lines.append(f"+ {m.name}")
        if changed:
            lines.append("")
            lines.append("== Members that changed ==")
            for m in changed:
                lines.append(f"~ {m.name}")
                if m.detail:
                    snippet = m.detail.strip().splitlines()
                    for ln in snippet[:20]:
                        lines.append(f"    {ln}")
                    if len(snippet) > 20:
                        lines.append(f"    ... (+{len(snippet) - 20} lines)")
        # Persistence findings across the whole bundle.
        all_persistence = [(m.name, p) for m in self.members for p in m.persistence]
        if all_persistence:
            lines.append("")
            lines.append("== Keyword persistence in AFTER bundle ==")
            for name, finding in all_persistence:
                lines.append(f"! {name}: {finding}")
        return "\n".join(lines)


class _Archive:
    """Uniform interface over zip / tar archives."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if zipfile.is_zipfile(path):
            self._kind = "zip"
            self._zip = zipfile.ZipFile(path, "r")
        elif tarfile.is_tarfile(path):
            self._kind = "tar"
            self._tar = tarfile.open(path, "r:*")
        else:
            raise ValueError(f"Unsupported archive format: {path}")

    def names(self) -> list[str]:
        if self._kind == "zip":
            return [n for n in self._zip.namelist() if not n.endswith("/")]
        return [m.name for m in self._tar.getmembers() if m.isfile()]

    def open(self, name: str) -> IO[bytes]:
        if self._kind == "zip":
            return self._zip.open(name, "r")
        member = self._tar.getmember(name)
        f = self._tar.extractfile(member)
        if f is None:
            return io.BytesIO(b"")
        return f

    def read_bytes(self, name: str) -> bytes:
        with self.open(name) as fh:
            return fh.read()

    def read_text(self, name: str) -> str:
        return self.read_bytes(name).decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._kind == "zip":
            self._zip.close()
        else:
            self._tar.close()


def _classify(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in _JSON_EXTS:
        return "json"
    if suffix in _TEXT_EXTS:
        return "text"
    return "binary"


def _normalize_path_for_match(name: str) -> str:
    return re.sub(r"^\./", "", name)


def diff_bundles(
    before_path: Path | str,
    after_path: Path | str,
    *,
    keywords: Iterable[str] = (),
) -> BundleDiff:
    bp = Path(before_path)
    ap = Path(after_path)
    keywords_list = [k for k in keywords if k]

    before_arc = _Archive(bp)
    after_arc = _Archive(ap)
    try:
        before_names = {_normalize_path_for_match(n): n for n in before_arc.names()}
        after_names = {_normalize_path_for_match(n): n for n in after_arc.names()}

        members: list[BundleMemberDiff] = []
        all_keys = sorted(set(before_names) | set(after_names))
        for key in all_keys:
            in_before = key in before_names
            in_after = key in after_names
            if in_before and not in_after:
                members.append(BundleMemberDiff(name=key, kind="removed"))
                continue
            if in_after and not in_before:
                member = BundleMemberDiff(name=key, kind="added")
                _attach_persistence(after_arc, after_names[key], member, keywords_list)
                members.append(member)
                continue
            # Both: compare.
            before_bytes = before_arc.read_bytes(before_names[key])
            after_bytes = after_arc.read_bytes(after_names[key])
            if before_bytes == after_bytes:
                member = BundleMemberDiff(name=key, kind="equal")
                _attach_persistence(after_arc, after_names[key], member, keywords_list)
                members.append(member)
                continue
            kind_label = _classify(key)
            detail = ""
            if kind_label == "json":
                try:
                    b = json.loads(before_bytes.decode("utf-8", errors="replace"))
                    a = json.loads(after_bytes.decode("utf-8", errors="replace"))
                    detail = diff_json(b, a).summary()
                except Exception:
                    detail = "(invalid json - falling back to byte-different)"
            elif kind_label == "text":
                detail = diff_text(
                    before_bytes.decode("utf-8", errors="replace"),
                    after_bytes.decode("utf-8", errors="replace"),
                )
            else:
                detail = (
                    f"binary differs (before={len(before_bytes)}B, "
                    f"after={len(after_bytes)}B)"
                )
            member = BundleMemberDiff(name=key, kind="changed", detail=detail)
            _attach_persistence(after_arc, after_names[key], member, keywords_list)
            members.append(member)

        return BundleDiff(
            before=str(bp),
            after=str(ap),
            members=members,
            keywords=keywords_list,
        )
    finally:
        before_arc.close()
        after_arc.close()


def _attach_persistence(
    arc: _Archive,
    name: str,
    member: BundleMemberDiff,
    keywords: list[str],
) -> None:
    if not keywords or _classify(name) == "binary":
        return
    try:
        text = arc.read_text(name)
    except Exception:
        return
    findings = detect_persistence("", text, keywords=keywords)
    member.persistence = [f.to_summary_line() for f in findings]
