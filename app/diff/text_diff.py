"""Text / HTML diff helpers and persistence heuristics."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

# Patterns that often indicate something internal leaking to the user.
_INTERNAL_LEAK_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "uuid"),
    (r"\b/(usr|var|home|opt|tmp|srv)/[A-Za-z0-9_./-]+", "absolute_path"),
    (r"\borg_[A-Za-z0-9]{6,}\b", "org_id"),
    (r"\bteam_[A-Za-z0-9]{6,}\b", "team_id"),
    (r"\buser_[A-Za-z0-9]{6,}\b", "user_id"),
    (r"\b(sk|pk|key|token)_[A-Za-z0-9]{8,}\b", "secret_like"),
    (r"Traceback \(most recent call last\)", "stack_trace"),
)


@dataclass(frozen=True)
class PersistenceFinding:
    rule: str
    keyword: str
    severity_hint: str
    detail: str

    def to_summary_line(self) -> str:
        return f"[{self.severity_hint}] {self.rule}: keyword={self.keyword!r} - {self.detail}"


def _read(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def diff_text(before: str, after: str, *, n: int = 3) -> str:
    """Return a unified diff of two text blobs."""
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile="before",
        tofile="after",
        n=n,
    )
    return "".join(diff)


def detect_persistence(
    before: str,
    after: str,
    *,
    keywords: list[str] | None = None,
) -> list[PersistenceFinding]:
    """Apply Phase 1 heuristics for unexpected persistence.

    Heuristics:
      1. A keyword the operator declared as "should be gone" still appears in `after`.
      2. Internal-looking identifiers (uuids, abs paths, org/user/team IDs,
         stack traces, secret-like strings) appear in `after`.
      3. A line that was deleted from the visible UI is still present in `after`
         (catches "UI hides but data still there" when comparing UI vs export).
    """
    findings: list[PersistenceFinding] = []
    keywords = keywords or []

    for kw in keywords:
        if not kw:
            continue
        if kw.lower() in after.lower():
            findings.append(
                PersistenceFinding(
                    rule="declared_keyword_persisted",
                    keyword=kw,
                    severity_hint="needs_review",
                    detail=(
                        "Operator-declared keyword still present in `after`. "
                        "Confirm whether this surface should have been purged."
                    ),
                )
            )

    for pattern, label in _INTERNAL_LEAK_PATTERNS:
        for match in re.findall(pattern, after):
            findings.append(
                PersistenceFinding(
                    rule="internal_identifier_visible",
                    keyword=str(match)[:120],
                    severity_hint="medium" if label != "stack_trace" else "high",
                    detail=f"Looks like internal {label} surfaced post-transition.",
                )
            )

    before_lines = {line.strip() for line in before.splitlines() if line.strip()}
    after_lines = {line.strip() for line in after.splitlines() if line.strip()}
    still_present = before_lines & after_lines
    for kw in keywords:
        kw_lc = kw.lower()
        for line in still_present:
            if kw_lc in line.lower():
                findings.append(
                    PersistenceFinding(
                        rule="line_unchanged_after_transition",
                        keyword=kw,
                        severity_hint="low",
                        detail=(
                            "A line containing the declared keyword is identical "
                            "before and after the transition."
                        ),
                    )
                )
                break

    # De-duplicate (rule, keyword) pairs.
    seen: set[tuple[str, str]] = set()
    deduped: list[PersistenceFinding] = []
    for f in findings:
        key = (f.rule, f.keyword)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped
