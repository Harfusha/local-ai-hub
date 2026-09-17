# Trace Inspector Full-Width Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TraceInspector primary and model-chat content readable by stacking full-width panels and rendering structured model values safely.

**Architecture:** Keep the existing Python-generated HTML and dashboard JavaScript. Change only the embedded TraceInspector presentation CSS plus the smallest renderer helper needed to prevent object coercion. Preserve trace APIs, persistence, polling, redaction, tabs, and raw fallback.

**Tech Stack:** Python 3.11, pytest, Node.js runtime snippets, embedded browser JavaScript/CSS in `src/local_ai_hub/dashboard.py`.

---

### Task 1: Add failing TraceInspector layout and object-rendering tests

**Files:**
- Modify: `tests/test_dashboard_custom_modals.py` after `test_trace_inspector_prioritizes_input_output_and_demotes_technical_detail`

- [x] **Step 1: Write the failing tests**

Add these tests:

```python
def test_trace_inspector_stacks_primary_and_model_chat_panels_full_width() -> None:
    assert ".trace-primary-grid{display:grid;grid-template-columns:1fr" in DASHBOARD_HTML
    assert ".trace-chat-columns{display:grid;grid-template-columns:1fr" in DASHBOARD_HTML
    assert ".trace-optional-details{width:100%" in DASHBOARD_HTML


def test_trace_inspector_formats_generic_model_objects_without_object_coercion() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function promptText(value)") : DASHBOARD_HTML.index(
            "function promptBlock(text"
        )
    ]
    script = (
        source
        + "console.log(promptText({answer:'structured'}));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert "structured" in result.stdout
    assert "[object Object]" not in result.stdout
```

- [x] **Step 2: Run focused tests to verify RED**

Run:

```text
python -m pytest -q tests/test_dashboard_custom_modals.py -k "stacks_primary_and_model_chat_panels_full_width or formats_generic_model_objects_without_object_coercion" --tb=short
```

Expected: FAIL because current CSS uses two columns and `promptText()` returns an empty string for generic objects, while no full-width contract exists.

### Task 2: Implement full-width presentation and safe object formatting

**Files:**
- Modify: `src/local_ai_hub/dashboard.py:744` for TraceInspector presentation CSS
- Modify: `src/local_ai_hub/dashboard.py:1827-1837` for generic object formatting

- [x] **Step 1: Change primary and model-chat grids to one column**

Update the embedded TraceInspector style block so these selectors use one full-width column:

```css
.trace-primary-grid{display:grid;grid-template-columns:1fr;gap:10px}
.trace-chat-columns{display:grid;grid-template-columns:1fr;gap:10px;align-items:start}
.trace-optional-details{width:100%;box-sizing:border-box}
.trace-optional-body{min-width:0;overflow-wrap:anywhere}
```

Keep the existing `@media(max-width:700px)` fallback; the one-column desktop layout makes it harmless and preserves responsive behavior.

- [x] **Step 2: Format generic prompt values as bounded JSON text**

Keep existing string/array/content handling. Replace the generic object fallback in `promptText(value)` with a JSON-safe representation:

```javascript
if(value&&typeof value==='object'){
  if(value.text!==undefined)return promptText(value.text);
  if(value.content!==undefined)return promptText(value.content);
  if(value.messages!==undefined)return promptText(value.messages);
  try{return JSON.stringify(value,null,2)}catch{return '[unserializable object]';}
}
```

This keeps model cards readable and prevents implicit `String(object)` output.

- [x] **Step 3: Run focused tests to verify GREEN**

Run:

```text
python -m pytest -q tests/test_dashboard_custom_modals.py -k "trace_inspector or trace_presentation or trace_sequence" --tb=short
```

Expected: all selected tests pass, including the two new regression tests.

### Task 3: Verify browser behavior and regression surface

**Files:**
- Review: `src/local_ai_hub/dashboard.py`
- Review: `tests/test_dashboard_custom_modals.py`

- [x] **Step 1: Run repository checks through the command broker**

Run the focused dashboard suite, then the required repository checks:

```text
python -m pytest -q tests/test_dashboard_custom_modals.py --tb=short
python tools/release_check.py
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

Expected: focused suite, compile, full pytest, and selftest pass. Release-check may report pre-existing local/generated artifacts.

- [x] **Step 2: Smoke-test in Chrome**

Open the existing TraceInspector trace page and verify:

1. INPUT card spans detail width.
2. OUTPUT card appears below INPUT and spans detail width.
3. MODEL INPUT appears above MODEL OUTPUT, both full width.
4. No visible `[object Object]` text remains.
5. `Technical details · N optional views` expands; tabs and raw view remain available.

- [x] **Step 3: Review diff and commit**

Run:

```text
git diff --check
git diff --stat
```

Commit:

```text
git add src/local_ai_hub/dashboard.py tests/test_dashboard_custom_modals.py
git commit -m "fix: make Trace Inspector panels full width"
```
