# Dashboard signal and request history

## Goal

Reduce low-value dashboard navigation and make individual API requests easier to find and inspect.

## Steps

1. Remove the Database, Architecture, and Code Explorer pages and named low-value panels, including markup and dashboard-only handlers; retain shared controls and backend capabilities used elsewhere.
2. Add request-history search, endpoint/status/date filters, visible/total counts, and request-to-trace detail cues in Queue & requests.
3. Raise dashboard request history from 50 to the existing bounded maximum of 200; keep telemetry fields unchanged.
4. Review the diff and run the focused dashboard check plus relevant Python validation.

## Constraints

- Preserve unrelated working-tree edits, especially existing `dashboard.py` changes.
- Keep backend capabilities and telemetry contents intact; no commits.
