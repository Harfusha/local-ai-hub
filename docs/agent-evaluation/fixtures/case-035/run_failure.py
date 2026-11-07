"""Emit a deterministic oversized failure log inside a disposable root."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import uuid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve(strict=True)
    log_path = Path(args.log)
    if not log_path.is_absolute():
        log_path = root / log_path
    log_path = log_path.resolve()
    if not log_path.is_relative_to(root) or log_path == root:
        raise ValueError("log path must remain below the disposable root")

    run_id = uuid.uuid4().hex[:12]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", encoding="utf-8", newline="\n") as log:
        for index in range(1, 10_001):
            if index == 1:
                line = f"RUN_ID={run_id} status=started"
            elif index == 9_999:
                line = f"ERROR run_id={run_id} code=FIXTURE-035 exception=ValueError message=staged_failure"
            else:
                line = f"INFO run_id={run_id} step={index:05d} state=ok"
            print(line)
            log.write(line + "\n")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
