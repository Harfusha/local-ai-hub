"""Bounded GitHub Actions diagnostics for CI failures."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import traceback
from collections.abc import Callable
from typing import Any


MAX_FAILURES = 10
MAX_MESSAGE_CHARS = 3000
_ERROR_HEADER = "::error title=Local AI Hub CI failure::"
_TRUNCATION_MARKER = "\n...[truncated]...\n"
_emitted = 0
_omitted_count = 0
_omitted_ids: list[str] = []


def pytest_sessionstart(session: Any) -> None:
    """Reset state when pytest is invoked repeatedly in the same process."""
    global _emitted, _omitted_count
    _emitted = 0
    _omitted_count = 0
    _omitted_ids.clear()


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
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        escaped = escaped.encode(encoding, errors="backslashreplace").decode(encoding)
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

    global _emitted, _omitted_count
    if os.environ.get("GITHUB_ACTIONS") != "true" or not getattr(report, "failed", False):
        return
    if _emitted >= MAX_FAILURES - 1:
        _omitted_count += 1
        nodeid = str(getattr(report, "nodeid", ""))[:300]
        if sum(map(len, _omitted_ids)) + len(nodeid) <= 2000:
            _omitted_ids.append(nodeid)
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


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    """Reserve the last annotation for identities beyond the detailed cap."""
    if _omitted_count:
        print()
        emit_error(f"{_omitted_count} additional failed reports (bounded node IDs):\n" + "\n".join(_omitted_ids))


def export_coverage(output_path: Path, data_file: Path | None = None) -> int:
    """Export coverage to JSON if data exists; emit diagnostic JSON if data is absent."""
    resolved_data = data_file or Path(os.environ.get("COVERAGE_FILE", ".coverage"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not resolved_data.is_file() or resolved_data.stat().st_size == 0:
        diagnostic = {
            "status": "NOT_COLLECTED",
            "reason": "coverage_data_absent",
            "coverage_file": str(resolved_data),
        }
        output_path.write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8")
        return 0

    cov = None
    try:
        import coverage

        cov = coverage.Coverage(data_file=str(resolved_data))
        cov.load()
        cov.json_report(outfile=str(output_path))
        return 0
    except Exception as exc:
        diagnostic = {
            "status": "NOT_COLLECTED",
            "reason": "coverage_export_failed",
            "error": str(exc),
            "coverage_file": str(resolved_data),
        }
        output_path.write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8")
        emit_error(f"Coverage export failure: {exc}")
        return 0
    finally:
        if cov is not None:
            try:
                data = cov.get_data()
                if hasattr(data, "close"):
                    data.close()
            except Exception:
                pass


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", help="Run selftest wrapped in diagnostics")
    parser.add_argument("--export-coverage", type=Path, default=None, help="Safely export JSON coverage report")
    parser.add_argument("--coverage-data", type=Path, default=None, help="Explicit coverage data file path")
    args = parser.parse_args()

    if args.export_coverage is not None:
        raise SystemExit(export_coverage(args.export_coverage, args.coverage_data))

    if args.selftest:
        from tools.selftest import main

        raise SystemExit(run_selftest(main))

    parser.error("one of --selftest or --export-coverage is required")


if __name__ == "__main__":
    _cli()
