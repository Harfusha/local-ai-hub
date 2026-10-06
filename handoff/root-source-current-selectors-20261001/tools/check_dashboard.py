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


def main() -> int:
    parser = IdParser()
    parser.feed(DASHBOARD_HTML)
    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    if duplicates:
        print(f"duplicate dashboard ids: {duplicates}", file=sys.stderr)
        return 1
    if "<script>" not in DASHBOARD_HTML or "</script>" not in DASHBOARD_HTML:
        print("dashboard script block missing", file=sys.stderr)
        return 1
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
