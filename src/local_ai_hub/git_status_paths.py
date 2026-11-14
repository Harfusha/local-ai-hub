"""Fail-closed parsing for Git porcelain-v1 NUL-delimited path records."""

import os


def parse_porcelain_status_paths(output: bytes) -> list[str] | None:
    """Return changed paths, or ``None`` when Git returned malformed records."""
    if not isinstance(output, bytes) or (output and not output.endswith(b"\0")):
        return None

    records = os.fsdecode(output).split("\0")[:-1]
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4 or record[2] != " " or not record[3:]:
            return None
        paths.append(record[3:])
        if "R" in record[:2] or "C" in record[:2]:
            if index >= len(records) or not records[index]:
                return None
            paths.append(records[index])
            index += 1
    return paths
