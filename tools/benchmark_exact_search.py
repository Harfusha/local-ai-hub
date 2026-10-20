import time
from pathlib import Path
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.config import load_config

import os
import sys

cfg = load_config('config.toml')
tools = RepositoryTools(cfg)
root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('BENCHMARK_ROOT', str(Path.cwd()))
query = sys.argv[2] if len(sys.argv) > 2 else 'WorldRuntimePerformanceCaptureTests'

print(f"Testing search in {root} for query {query!r}...")
t0 = time.perf_counter()
res = tools.search(root, query, exact_count=True)
dur_ms = (time.perf_counter() - t0) * 1000

print(f"Current duration: {dur_ms:.1f}ms")
print(f"Success: {res.get('success')}, total_matches: {res.get('total_matches')}, scanned: {res.get('scanned_files')}")
if res.get('results'):
    for r in res['results'][:3]:
        print(f"  Match: {r.get('path')}:{r.get('start_line')} (score={r.get('score')})")
