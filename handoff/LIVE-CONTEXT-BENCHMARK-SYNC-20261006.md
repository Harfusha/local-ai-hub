# Benchmark reconciliation

Original unfinished work: deaa4005. Pinned master: 2458f72c.
The add/add conflict represented two different benchmarks, not disposable
duplicates. Preserve the current master benchmark under its existing name;
retain the historical live/offline implementation as
tools/benchmark_context_pack_live_quality.py and point its existing tests there.
No production context-pack implementation is changed. This is preservation
and reconciliation, not evidence of live backend or release acceptance.
Verification: `python -B -m pytest -q -p no:cacheprovider tests/test_context_pack_live_benchmark.py --tb=short --maxfail=3`:
15 passed in 1.55 seconds. This validates benchmark helpers, not live model
quality, runtime performance, or release acceptance.
