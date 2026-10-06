# T13 root-current review fixes — 2026-10-01

Prepared separate production and test patches in the T13 worktree. T20 applied them to root; Main then removed exactly one duplicate gaming `if` line from the stale-unload block. No root files were edited by T13. Root HEAD is `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Invalid UTF-8 operational mode state

- `handoff/T13-rootcurrent-invalid-utf8-production.patch` — SHA-256 `77B66B47B74D7A0C8DF4280E05CE7AE169E1A9AF97DE785A8C133386DC2EAFD9`; PASS `git apply --check`.
- `handoff/T13-rootcurrent-invalid-utf8-test.patch` — SHA-256 `A8191AD36E3BB4D2248A224C6B91353C9644C0C63270170E5D01E0A75A8F1EAF`; PASS `git apply --check`.
- Regression selector: `tests/test_operational_mode.py::test_mode_invalid_utf8_fails_closed_and_can_recover`.
- Source catches `UnicodeError` at `Path.read_text()` and returns degraded maintenance. Test verifies invalid UTF-8 fails closed and a later valid mode write recovers.

## Stale gaming unload after resume

- `handoff/T13-rootcurrent-stale-unload-production.patch` — corrected SHA-256 `8EB8BEB962B4AFFC45DF21A67A4406ADE0C7A68563E54F33AC59966C421877CA`. The transformed source overlay `handoff/root-overlay/T13-stale-mode/src/local_ai_hub/http_server.py` parses with Python AST; overlay SHA-256 `43761D357376C5BF983CFDA19ED1D007A1B03FA85D5438E0476CBC096FAFB007`. Root's repaired `http_server.py` SHA-256 is `C619AE6297F9B99466304722E95455994BFFDF88258E32B1487FED247F159E15` (Main reports AST parse passed).
- `handoff/T13-rootcurrent-stale-unload-test.patch` — SHA-256 `C31121EF9BD14AB45B44D517FCE045E7CCC3B3BB726AD0FA6ED30C17E7BED192`; PASS `git apply --check`.
- Regression selector: `tests/test_operational_mode.py::test_http_mode_skips_gaming_unload_after_later_resume`.
- Before runtime or accelerator release, reacquire the mode-change guard, reread the snapshot, and require gaming mode plus matching revision. Hold guard through release. Stale transitions skip release and report failure.

Main reports the invalid-UTF8, stale-unload, and existing mode-guard selectors passed together: 3 passed in 0.42s, exit 0. Earlier collection hit an `IndentationError` before the stale-unload test body ran; count it as zero behavior-test failures. T20 released the test slot. Preserve hard-pause behavior: drain already admitted checkpoint work if required, but do not start new GPU inference after pause. These patches do not modify inference admission.
