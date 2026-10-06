# T12 model-free routing/scheduler harness — 2026-10-01

Owner: T12 test/tool additions. T20 owns primary-root integration. Root checkout stayed read-only.

## Handoff

- Patch: `T12-model-free-harness-root-current-v3-20261001.patch`; SHA-256 `EAD5246BD34A062D1B3897D22FF95222E3205D8A765DD66CBF9A67C3ACE05879`.
- Manifest: `T12-model-free-harness-root-current-v3-20261001.manifest.json`; SHA-256 `291FBEA579C0AA44D7AEBFEE04AFC4DA9B287572563FC4C9FE9AEB8A34DDD2FD`.
- Root HEAD at inspection: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Both destination paths were absent in root.
- Strict root `git apply --check --whitespace=error`: PASS. Patch rehearsal in root-source overlay: PASS.
- Candidate postimages (LF): `{'tools/t12_model_free_harness.py': '51091A7778D2C24555BF4258E27E203A8A746B3246284BF171D16EE7A3FBD9D8', 'tests/test_t12_model_free_harness.py': '19660CF9842551B386D362C24134893E3F97104FDAFEC6F6BD2214A28B73613B'}`.
- Root apply postimages (Windows CRLF): `{'tools/t12_model_free_harness.py': 'FAC3E7A5668B3BAD6F6187938B0A66FB95BAD32C9C23958A976475511D7DC9F6', 'tests/test_t12_model_free_harness.py': '464D8003FF81857A67D5F769B3A50A92CB51733E8B6EEF4DAC795F7A32DB7261'}`.
- Exact dependency source hashes are in the manifest (`hardware.py`, `router.py`, `scheduler.py`).

## Harness

Run: `python -B tools/t12_model_free_harness.py`.
Test: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t12_model_free_harness.py`.

- Candidate test: **1 passed in 4.68s**. Current-root source overlay: **1 passed in 4.58s**.
- CLI covered `integrated`, `balanced`, `high`, `max`: profile-specific `ModelRouter` targets; real `AffinityScheduler`; synthetic runtime records one preparation per model and two switches; bounded queue rejects third job; queue delay **25.386–25.729 ms**; service/inference callback durations measured; cross-tenant fairness uses deterministic virtual time **1000/2000 ms**.
- `python -m pyflakes tools/t12_model_free_harness.py tests/test_t12_model_free_harness.py`: pass, no output.

Report labels every run `synthetic_model_free`, `live_inference=false`, `quality=not_measured`, `vram_bytes=null`. Runtime fakes report no VRAM values. Harness proves deterministic routing/scheduler instrumentation paths only; it does not prove live provider behavior, GPU/VRAM, model quality, per-profile hardware acceptance, or T02 baseline comparison.
