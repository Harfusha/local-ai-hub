# T17 next acceptance plan — refreshed 2026-10-04

Candidate `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. T17 remains open. Current vision refactor, leases, exact dirty preimages/current SHA-256 values, contract checklist, and source/runtime boundary are in `handoff/t17-vision-request-decomposition-receipt-2026-10-04.md`.

T20 serial test slot remains closed. Run only after the next explicit T20 GO; no tests, benchmarks, or builds have run for the current hashes:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_browser_bridge.py tests/test_frontend_review.py tests/test_http_vision_routes.py tests/test_process_utils.py tests/test_transcription_contract.py tests/test_vision_contracts.py tests/test_vision_service.py
node tests/test_browser_bridge_background.js
```

Optional candidate adapter harness, only if included in GO: `node handoff/t17-browser-adapter-live-e2e.mjs`. Real browser permissions, live daemon expiry/replay, natural/multilingual speech WER, and live vision quality require separate real-runtime receipts.
