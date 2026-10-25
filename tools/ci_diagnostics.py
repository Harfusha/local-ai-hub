"""Bounded GitHub Actions diagnostics for CI failures."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Callable
from typing import Any


MAX_FAILURES = 10
MAX_MESSAGE_CHARS = 3000
_ERROR_HEADER = "::error title=Local AI Hub CI failure::"
_TRUNCATION_MARKER = "\n...[truncated]...\n"
_emitted = 0


def _bounded_text(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    available = MAX_MESSAGE_CHARS - len(_TRUNCATION_MARKER)
    head_size = available // 2
    tail_size = available - head_size
    return text[:head_size] + _TRUNCATION_MARKER + text[-tail_size:]


def emit_error(text: str) -> None:
    """Emit one bounded workflow annotation only on a GitHub Actions runner."""

    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    message = _bounded_text(str(text))
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"{_ERROR_HEADER}{escaped}", flush=True)


class TailTee:
    """Forward every write while retaining only a bounded tail for diagnostics."""

    def __init__(self, target: Any) -> None:
        self.target = target
        self.tail = ""

    def write(self, text: str) -> int | None:
        result = self.target.write(text)
        if len(text) >= MAX_MESSAGE_CHARS:
            self.tail = text[-MAX_MESSAGE_CHARS:]
        else:
            self.tail = (self.tail + text)[-MAX_MESSAGE_CHARS:]
        return result

    def flush(self) -> Any:
        return self.target.flush()


def run_selftest(main_callable: Callable[[], int]) -> int:
    """Tee self-test output and report failure without changing its exit code."""

    original_stdout = sys.stdout
    tee = TailTee(original_stdout)
    sys.stdout = tee  # type: ignore[assignment]
    try:
        try:
            exit_code = main_callable()
        except Exception:
            emit_error(traceback.format_exc())
            raise
        if exit_code != 0:
            emit_error(tee.tail)
        return exit_code
    finally:
        sys.stdout = original_stdout


def pytest_runtest_logreport(report: Any) -> None:
    """Emit bounded annotations for failed pytest reports only."""

    global _emitted
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or not getattr(report, "failed", False) or _emitted >= MAX_FAILURES):
        return
    _emitted += 1
    nodeid = getattr(report, "nodeid", "")
    longreprtext = getattr(report, "longreprtext", "")
    message = f"{_bounded_text(str(nodeid))}\n{_bounded_text(str(longreprtext))}"
    stderr_tail = ""
    sections = getattr(report, "sections", ())
    if isinstance(sections, (list, tuple)):
        for section in sections[-4:]:
            if (isinstance(section, (list, tuple)) and len(section) == 2
                    and isinstance(section[0], str) and "stderr" in section[0].lower()
                    and isinstance(section[1], str) and section[1]):
                stderr_tail = section[1][-1200:]
    if stderr_tail:
        if len(message) > 1500:
            message = message[:700] + "\n...[failure excerpt bounded]...\n" + message[-700:]
        message += "\nCaptured stderr tail:\n" + stderr_tail
    print()  # Pytest may have just written a progress character without a newline.
    emit_error(message)


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", required=True)
    parser.parse_args()
    from tools.selftest import main

    raise SystemExit(run_selftest(main))


if __name__ == "__main__":
    _cli()
