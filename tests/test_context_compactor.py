"""Unit tests for Laya Context Window Compactor."""

import json
from local_ai_hub.context_compactor import (
    CompactionOptions,
    compact_context,
    compact_import_blocks,
    compact_json_blocks,
    compact_stack_traces,
    compact_whitespace_and_dividers,
)


def test_compact_stack_traces_dedup() -> None:
    trace = """Traceback (most recent call last):
  File "engine.py", line 42, in process
    item = self.get()
  File "engine.py", line 42, in process
    item = self.get()
  File "engine.py", line 42, in process
    item = self.get()
ValueError: corrupted item"""
    compacted = compact_stack_traces(trace)
    assert "[... previous frame repeated 2 more times ...]" in compacted
    assert compacted.count('File "engine.py", line 42, in process') == 1


def test_compact_json_blocks_minification() -> None:
    markdown_doc = """Here is the system state:
```json
{
  "status": "healthy",
  "nodes": [
    {
      "id": 1,
      "active": true
    },
    {
      "id": 2,
      "active": false
    }
  ],
  "metrics": {
    "latency_ms": 12.5
  }
}
```
Next section of prompt."""
    res = compact_json_blocks(markdown_doc)
    assert "{\n  \"status\"" not in res
    assert '{"status":"healthy","nodes":[{"id":1,"active":true},{"id":2,"active":false}],"metrics":{"latency_ms":12.5}}' in res
    assert "Next section of prompt." in res


def test_compact_multiline_imports() -> None:
    code = """from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

def foo():
    pass"""
    compacted = compact_import_blocks(code)
    assert "from typing import Any, Dict, List, Optional, Tuple, Union" in compacted
    assert "def foo():" in compacted


def test_compact_whitespace_and_dividers() -> None:
    raw = """Title

==================================================



Some paragraph text.

--------------------------------------------------


End"""
    compacted = compact_whitespace_and_dividers(raw)
    assert "\n\n\n" not in compacted
    assert "---" in compacted
    assert "==================================================" not in compacted


def test_compact_context_end_to_end() -> None:
    text = """# Context Snapshot
====================================================

from os.path import (
    abspath,
    join,
)

```json
{
  "key": "value",
  "list": [1, 2, 3]
}
```



Traceback (most recent call last):
  File "app.py", line 10, in run
    step()
  File "app.py", line 10, in run
    step()
RuntimeError: fail
"""
    result = compact_context(text)
    assert result.saved_chars > 0
    assert result.saved_pct > 15.0
    assert result.tokens_saved_est > 0
    assert "---" in result.text
    assert '{"key":"value","list":[1,2,3]}' in result.text
    assert "[... previous frame repeated 1 more times ...]" in result.text
