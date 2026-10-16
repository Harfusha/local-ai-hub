from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.process_utils import hidden_run_kwargs


class IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def validate_dashboard_html(html: str) -> tuple[bool, list[str]]:
    """Validate dashboard HTML structure: check unique IDs and script presence."""
    if not isinstance(html, str) or not html.strip():
        return False, ["Dashboard HTML is empty or invalid"]
    errors: list[str] = []
    parser = IdParser()
    try:
        parser.feed(html)
    except Exception as exc:
        return False, [f"Failed to parse dashboard HTML: {exc}"]

    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    if duplicates:
        errors.append(f"duplicate dashboard ids: {duplicates}")

    if "<script>" not in html or "</script>" not in html:
        errors.append("dashboard script block missing")

    return (len(errors) == 0, errors)


def main() -> int:
    valid, errors = validate_dashboard_html(DASHBOARD_HTML)
    if not valid:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    parser = IdParser()
    parser.feed(DASHBOARD_HTML)
    node = shutil.which("node")
    if node:
        js = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
        with tempfile.TemporaryDirectory(prefix="lah-dashboard-") as td:
            path = Path(td) / "dashboard.js"
            path.write_text(js, encoding="utf-8")
            cp = subprocess.run([node, "--check", str(path)], capture_output=True, check=False, timeout=10, **hidden_run_kwargs(text=True))
            if cp.returncode:
                print(cp.stderr, file=sys.stderr)
                return cp.returncode
    print(f"dashboard ok: {len(parser.ids)} unique ids; node={'yes' if node else 'not-installed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
