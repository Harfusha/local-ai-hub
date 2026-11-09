# Exclusive preprocessing activity mode implementation plan

> Execute in this checkout, preserve existing changes, and verify each boundary with focused tests.

**Goal:** Add a fourth activity mode that prioritizes complete preprocessing of registered projects using profile-specific resource limits.

**Architecture:** Extend the existing persistent operational mode and admission gates. Safely drain foreground work, then allow preprocessing and its dedicated backend while retaining GPU ownership fences. Select mode-specific limits without changing the normal mode or provider; expose effective limits and progress through existing controls.

**Tech stack:** Python, existing HTTP/MCP and dashboard controls, SQLite project queue, pytest.

1. Map request admission, active work cancellation/drain, backend and profile lifecycle, project queue ownership and concurrent execution. Define safe transitions and behavior for paused or failed projects.
2. Add failing tests for mode persistence, HTTP/MCP admission, operator controls, cross-process gating, active-work draining and return to active mode. Implement the mode and dashboard/CLI surfaces.
3. Add tests for per-profile effective limits, project concurrency, model parallelism, safe backend transitions, unavailable resources, and restored normal behavior. Implement scheduling and profile settings without bypassing project or GPU fences.
4. Update operator documentation and both canonical agent prompts. Run focused tests, indexed impact review and integration checks; report runtime and throughput only when measured. Preserve failures and incomplete project states explicitly.
5. Enrich prior unparsed-file stubs in exclusive mode without removing their usable cached cards before a validated replacement exists. Respect the mode-specific opt-out, file limits and skipped phases; test missing-model and unchanged-inventory cases.
