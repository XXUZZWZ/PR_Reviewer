from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DiffHunk:
    """A single contiguous change region within a file."""

    header: str        # "@@ -1,5 +1,7 @@ context line"
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine]

    @property
    def added_lines(self) -> list[DiffLine]:
        return [l for l in self.lines if l.kind == "add"]

    @property
    def removed_lines(self) -> list[DiffLine]:
        return [l for l in self.lines if l.kind == "remove"]

    @property
    def context_lines(self) -> list[DiffLine]:
        return [l for l in self.lines if l.kind == "context"]


@dataclass
class DiffLine:
    kind: str   # "add", "remove", "context"
    content: str
    old_lineno: int | None
    new_lineno: int | None


@dataclass
class ParsedDiff:
    path: str
    hunks: list[DiffHunk]

    @property
    def added_count(self) -> int:
        return sum(len(h.added_lines) for h in self.hunks)

    @property
    def removed_count(self) -> int:
        return sum(len(h.removed_lines) for h in self.hunks)


def parse_unified_diff(diff_text: str) -> list[ParsedDiff]:
    """Parse a unified diff string into structured hunks per file."""
    diffs: list[ParsedDiff] = []
    current_path: str | None = None
    current_hunks: list[DiffHunk] = []

    for line in diff_text.split("\n"):
        if not line:
            continue

        # File header: "diff --git a/path b/path" or "+++ b/path"
        if line.startswith("diff --git "):
            if current_path and current_hunks:
                diffs.append(ParsedDiff(path=current_path, hunks=current_hunks))
            current_hunks = []
            current_path = _extract_path_from_diff_header(line)
        elif line.startswith("+++ b/") or line.startswith("--- a/"):
            if not current_path:
                current_path = line[6:] if line.startswith("+++ b/") else line[6:]
        elif line.startswith("@@") and current_path:
            hunk = _parse_hunk_header(line)
            current_hunks.append(hunk)
        elif current_hunks:
            kind, old_no, new_no = _classify_line(line)
            current_hunks[-1].lines.append(DiffLine(
                kind=kind,
                content=line[1:] if kind in ("add", "remove") else line,
                old_lineno=old_no,
                new_lineno=new_no,
            ))

    if current_path and current_hunks:
        diffs.append(ParsedDiff(path=current_path, hunks=current_hunks))

    return diffs


_HUNK_RE = re.compile(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*)")

def _parse_hunk_header(line: str) -> DiffHunk:
    m = _HUNK_RE.match(line)
    if not m:
        return DiffHunk(header=line, old_start=0, old_count=0, new_start=0, new_count=0, lines=[])
    old_start = int(m.group(1))
    old_count = int(m.group(2)) if m.group(2) else 1
    new_start = int(m.group(3))
    new_count = int(m.group(4)) if m.group(4) else 1
    return DiffHunk(
        header=line,
        old_start=old_start,
        old_count=old_count,
        new_start=new_start,
        new_count=new_count,
        lines=[],
    )


def _classify_line(line: str) -> tuple[str, int | None, int | None]:
    if line.startswith("+"):
        return ("add", None, None)
    elif line.startswith("-"):
        return ("remove", None, None)
    else:
        return ("context", None, None)


def _extract_path_from_diff_header(line: str) -> str:
    parts = line.split()
    if len(parts) >= 4:
        return parts[3][2:]  # remove "b/" prefix
    return ""
