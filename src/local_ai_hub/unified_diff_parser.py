from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ParsedUnifiedDiff:
    files: list[str]
    additions: int
    deletions: int
    hunks: int
    added_lines: list[tuple[str, str]]
    file_diff_lines: dict[str, dict[str, list[str]]]


@dataclass
class _DiffParser:
    parsed: ParsedUnifiedDiff = field(
        default_factory=lambda: ParsedUnifiedDiff([], 0, 0, 0, [], defaultdict(lambda: {"added": [], "deleted": []}))
    )
    current_file: str = ""
    original_file: str = ""
    old_remaining: int = 0
    new_remaining: int = 0

    def consume_hunk_content(self, line: str, *, next_file_header: bool) -> bool:
        if not (self.old_remaining or self.new_remaining):
            return False
        # A malformed hunk may declare more lines than it actually contains.
        # A valid ---/+++ file-header pair always starts the next file, even
        # when its leading '-' could otherwise look like deleted source text.
        if next_file_header:
            self.old_remaining = self.new_remaining = 0
            return False
        if line.startswith("+") and self.new_remaining:
            self.parsed.additions += 1
            self.new_remaining -= 1
            self.parsed.added_lines.append((self.current_file, line[1:]))
            if self.current_file:
                self.parsed.file_diff_lines[self.current_file]["added"].append(line[1:])
            return True
        if line.startswith("-") and self.old_remaining:
            self.parsed.deletions += 1
            self.old_remaining -= 1
            target = self.current_file or self.original_file
            if target:
                self.parsed.file_diff_lines[target]["deleted"].append(line[1:])
            return True
        if line.startswith(" ") and self.old_remaining and self.new_remaining:
            self.old_remaining -= 1
            self.new_remaining -= 1
            return True
        if line.startswith("\\ No newline"):
            return True
        self.old_remaining = self.new_remaining = 0
        return False

    def consume_file_header(self, line: str) -> bool:
        if line.startswith("--- a/"):
            self.original_file = line[6:].strip()
            self.current_file = ""
        elif line.startswith("+++ b/"):
            self.current_file = line[6:].strip()
            if self.current_file and self.current_file not in self.parsed.files:
                self.parsed.files.append(self.current_file)
        elif line.startswith("+++ /dev/null") and self.original_file:
            self.current_file = self.original_file
            if self.current_file not in self.parsed.files:
                self.parsed.files.append(self.current_file)
        else:
            return False
        return True

    def consume_hunk_header(self, line: str) -> bool:
        if not line.startswith("@@"):
            return False
        self.parsed.hunks += 1
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match:
            self.old_remaining = int(match.group(2) or "1")
            self.new_remaining = int(match.group(4) or "1")
        return True

    def consume_source_line(self, line: str) -> None:
        if line.startswith("+") and not line.startswith("+++"):
            self.parsed.additions += 1
            self.parsed.added_lines.append((self.current_file, line[1:]))
            if self.current_file:
                self.parsed.file_diff_lines[self.current_file]["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            self.parsed.deletions += 1
            target = self.current_file or self.original_file
            if target:
                self.parsed.file_diff_lines[target]["deleted"].append(line[1:])

    def finish(self) -> ParsedUnifiedDiff:
        self.parsed.file_diff_lines = dict(self.parsed.file_diff_lines)
        return self.parsed


def _is_next_file_header(lines: list[str], index: int) -> bool:
    if not lines[index].startswith("--- a/") or index + 1 >= len(lines):
        return False
    next_line = lines[index + 1]
    if not (next_line.startswith("+++ b/") or next_line.startswith("+++ /dev/null")):
        return False
    # Within a hunk, a deleted line beginning with '--- a/' followed by
    # added text beginning with '+++ b/' is still source code. A new
    # unified-diff file section must be followed by a hunk header.
    return index + 2 < len(lines) and lines[index + 2].startswith("@@ ")


def parse_unified_diff(diff: str) -> ParsedUnifiedDiff:
    # Unicode separators inside source text must not become diff headers.
    lines = diff.replace("\r\n", "\n").split("\n")
    parser = _DiffParser()
    for index, line in enumerate(lines):
        if parser.consume_hunk_content(line, next_file_header=_is_next_file_header(lines, index)):
            continue
        if parser.consume_file_header(line) or parser.consume_hunk_header(line):
            continue
        parser.consume_source_line(line)
    return parser.finish()
