# Trace Inspector full-width presentation

## Goal

Make TraceInspector readable at desktop width: primary input/output content and model chat content must use full-width stacked cards, while technical details remains a usable expandable section.

## Scope

- Change dashboard presentation CSS and the existing client-side renderer in `src/local_ai_hub/dashboard.py`.
- Add focused contract tests in `tests/test_dashboard_custom_modals.py`.
- Keep debug-trace API, SQLite schema, redaction, polling, tabs, and trace data unchanged.

## Design

`trace-primary-grid` becomes a single-column layout for the primary INPUT/OUTPUT cards. The same one-column rule applies to `trace-chat-columns`, so model input appears before model output without squeezing either panel into half-width columns. Existing narrow-screen behavior remains compatible.

The presentation renderer continues to use `renderAny()` for structured values. Model output must pass through the structured renderer or bounded JSON-safe path, preventing JavaScript object coercion to `[object Object]`. Long strings and nested values keep existing wrapping and bounded rendering.

`Technical details` remains a full-width native `<details>` block after the human presentation. Its summary stays keyboard-accessible; body padding, wrapping, and overflow rules prevent clipped content or horizontal scrolling.

## Validation

Tests assert the stacked CSS contract, structured object rendering, and preserved technical-details markup. Chrome smoke verification opens a retained trace, checks full-width stacked INPUT/OUTPUT and model panels, confirms no `[object Object]`, then expands `Technical details`.

## Acceptance criteria

1. INPUT and OUTPUT render one after another across the detail pane.
2. MODEL INPUT and MODEL OUTPUT render one after another across the detail pane.
3. Structured output never renders as `[object Object]`.
4. Technical details is visible as a full-width expandable section and content is readable.
5. Focused tests pass; no API or persistence changes occur.
