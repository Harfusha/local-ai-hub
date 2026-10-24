from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest


def _memory_formatter_source():
    from local_ai_hub.dashboard import DASHBOARD_HTML

    marked = re.search(
        r"// BEGIN memory provenance display\n(.*?)// END memory provenance display",
        DASHBOARD_HTML,
        re.S,
    )
    if marked:
        return DASHBOARD_HTML, marked.group(1)
    # Before a dedicated formatter exists, exercise the actual table callback
    # instead of failing merely because a proposed helper/marker is absent.
    callback = re.search(
        r"rows\('agentOsMemoryBody',filteredMem,m=>\{(.*?)\},7,agentOsMemories\.length",
        DASHBOARD_HTML,
        re.S,
    )
    assert callback, "memory row renderer must remain extractable"
    return DASHBOARD_HTML, "function formatAgentOsMemoryCells(m){" + callback.group(1) + "}"


def test_memory_provenance_formatter_shows_recorded_identity_escaped_and_datetime():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; browser verification remains separate")
    _, formatter = _memory_formatter_source()
    harness = r"""
const esc=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const clickableRow=(_record,cells)=>cells;
"""
    records = [
        {
            "scope": "repository",
            "kind": "fact",
            "key": "<script>key</script>",
            "value": "<img src=x onerror=alert(1)>",
            "confidence": 0.75,
            "source": "agent<&>",
            "provenance": {"root": "C:/work/<private>&", "repository_id": "repo<&>"},
            "created_at": 1735787045,
        },
        {"scope": "session", "kind": "fact", "key": "missing", "source": "agent", "created_at": None},
        {"scope": "repository", "kind": "fact", "key": "invalid", "provenance": {"root": ""}, "created_at": "not-a-time"},
    ]
    script = harness + formatter + "\nconst rows=" + json.dumps(records) + ".map(formatAgentOsMemoryCells);\nprocess.stdout.write(JSON.stringify(rows));\n"
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=10, check=True, env={**os.environ, "TZ": "UTC"})
    rows = json.loads(result.stdout)
    assert len(rows) == 3
    assert all(row.count("<td") == 7 for row in rows)

    actual = rows[0]
    assert "agent&lt;&amp;&gt;" in actual
    assert "C:/work/&lt;private&gt;&amp;" in actual
    assert "repo&lt;&amp;&gt;" in actual
    assert "<script>" not in actual and "<img" not in actual
    assert "&lt;script&gt;key&lt;/script&gt;" in actual
    assert "&lt;img src=x onerror=alert(1)&gt;" in actual
    assert "2025" in actual
    assert re.search(r"\d{1,2}:\d{2}(:\d{2})?.*(UTC|GMT)", actual)

    for unknown in rows[1:]:
        assert "Unknown root" in unknown
        assert "Unknown repository" in unknown
        assert "Unknown date/time" in unknown


def test_memory_table_keeps_seven_columns_mobile_overflow_and_click_detail():
    from local_ai_hub.dashboard import DASHBOARD_HTML as html

    class MemoryTableHeader(HTMLParser):
        def __init__(self):
            super().__init__()
            self.table_headers = []
            self.memory_headers = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "table":
                self.table_headers.append(0)
            elif tag == "th" and self.table_headers:
                self.table_headers[-1] += 1
            elif tag == "tbody" and attrs.get("id") == "agentOsMemoryBody" and self.table_headers:
                self.memory_headers = self.table_headers[-1]

        def handle_endtag(self, tag):
            if tag == "table" and self.table_headers:
                self.table_headers.pop()

    parser = MemoryTableHeader()
    parser.feed(html)
    assert parser.memory_headers == 7
    assert re.search(r"\.table-wrap\{[^}]*overflow:auto", html)
    assert re.search(r"clickableRow\(m,.*?'memory',", html)
    assert "No memories match the current filters." in html
    assert "No memories recorded." in html
