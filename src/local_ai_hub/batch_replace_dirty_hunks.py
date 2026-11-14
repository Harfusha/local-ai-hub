from __future__ import annotations


def parse_dirty_hunks(diff_stdout: bytes) -> list[tuple[int, int]]:
    """Parse changed current-file line ranges, failing closed to the full file."""
    ranges: list[tuple[int, int]] = []
    for diff_line in diff_stdout.decode("utf-8", errors="replace").splitlines():
        if not diff_line.startswith("@@") or " +" not in diff_line:
            continue
        new_range = diff_line.split(" +", 1)[1].split(" ", 1)[0]
        start_text, separator, count_text = new_range.partition(",")
        try:
            start_line = int(start_text)
            line_count = int(count_text) if separator else 1
        except ValueError:
            return [(1, 2**31 - 1)]

        # A deletion has no current-file line; its insertion point is protected.
        first = max(1, start_line)
        last = max(first, start_line + line_count - 1)
        ranges.append((first, last))
    return ranges or [(1, 2**31 - 1)]
