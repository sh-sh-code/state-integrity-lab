"""Structural JSON diff."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MISSING = object()


@dataclass
class JsonDiff:
    added: list[tuple[str, Any]] = field(default_factory=list)
    removed: list[tuple[str, Any]] = field(default_factory=list)
    changed: list[tuple[str, Any, Any]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def summary(self) -> str:
        if self.is_empty:
            return "No structural differences."
        lines: list[str] = []
        for path, value in self.removed:
            lines.append(f"- {path}: {_short(value)}")
        for path, value in self.added:
            lines.append(f"+ {path}: {_short(value)}")
        for path, before, after in self.changed:
            lines.append(f"~ {path}: {_short(before)} -> {_short(after)}")
        return "\n".join(lines)


def _short(value: Any, limit: int = 80) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _walk(before: Any, after: Any, path: str, diff: JsonDiff) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = set(before) | set(after)
        for key in sorted(keys):
            sub_path = f"{path}.{key}" if path else key
            b = before.get(key, _MISSING)
            a = after.get(key, _MISSING)
            if b is _MISSING:
                diff.added.append((sub_path, a))
            elif a is _MISSING:
                diff.removed.append((sub_path, b))
            else:
                _walk(b, a, sub_path, diff)
        return
    if isinstance(before, list) and isinstance(after, list):
        max_len = max(len(before), len(after))
        for i in range(max_len):
            sub_path = f"{path}[{i}]"
            if i >= len(before):
                diff.added.append((sub_path, after[i]))
            elif i >= len(after):
                diff.removed.append((sub_path, before[i]))
            else:
                _walk(before[i], after[i], sub_path, diff)
        return
    if before != after:
        diff.changed.append((path or "$", before, after))


def diff_json(before: Any, after: Any) -> JsonDiff:
    diff = JsonDiff()
    _walk(before, after, "", diff)
    return diff


def diff_json_files(before_path: Path | str, after_path: Path | str) -> JsonDiff:
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))
    return diff_json(before, after)
