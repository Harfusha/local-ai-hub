from __future__ import annotations

import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
CANDIDATE = Path(__file__).resolve().parents[1]
WORKER = r'''
import json, sys, time
from local_ai_hub.commands import CommandBroker
class Artifacts:
    def put(self, *_args, **_kwargs): return "microbench-artifact"
class RepoState:
    def fingerprint(self, _cwd): return {"fingerprint":"static-fixture","stale":False,"degraded":False}
fixture, state_dir = sys.argv[1:]
config = {"server":{"state_dir":state_dir},"commands":{"enabled":True,"allow_unknown":False,"max_output_chars":1024,"inline_output_chars":512}}
broker = CommandBroker(config, Artifacts(), RepoState())
for line in sys.stdin:
    request = json.loads(line)
    started = time.perf_counter_ns()
    result = broker.run_project_command("bench", fixture, tenant="t15-config-microbench", force=True)
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    print(json.dumps({"success":result.get("success"),"stdout":result.get("stdout"),"elapsed_ms":elapsed}), flush=True)
'''


def _hashes(root: Path) -> dict[str, str]:
    names = ("src/local_ai_hub/commands.py", "src/local_ai_hub/project_config.py", "src/local_ai_hub/services.py")
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def _worker(root: Path, fixture: Path, state: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    worker_env = dict(env)
    worker_env["PYTHONPATH"] = str(root / "src")
    return subprocess.Popen(
        [sys.executable, "-B", "-u", "-c", WORKER, str(fixture), str(state)],
        cwd=root,
        env=worker_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )


def main() -> None:
    harness_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    before = {"root": _hashes(ROOT), "candidate": _hashes(CANDIDATE)}
    argv = [sys.executable, "-B", "-c", "print(sum(i*i for i in range(20000)))"]
    with tempfile.TemporaryDirectory(prefix="t15-cpu-pair-") as temp:
        base = Path(temp)
        fixture = base / "fixture"
        fixture.mkdir()
        (fixture / ".local-ai.toml").write_text(
            "[commands.bench]\nargv = " + json.dumps(argv) + "\n", encoding="utf-8"
        )
        workers = {
            "root": _worker(ROOT, fixture, base / "state-root", os.environ),
            "candidate": _worker(CANDIDATE, fixture, base / "state-candidate", os.environ),
        }
        rng = random.Random(1501)
        pairs = []
        try:
            for index in range(7):
                order = ["root", "candidate"]
                if rng.getrandbits(1):
                    order.reverse()
                sample = {}
                for arm in order:
                    process = workers[arm]
                    assert process.stdin is not None and process.stdout is not None
                    process.stdin.write("{}\n")
                    process.stdin.flush()
                    sample[arm] = json.loads(process.stdout.readline())
                    assert sample[arm]["success"] is True
                    assert sample[arm]["stdout"] == "2666466670000\n"
                pairs.append({"index": index + 1, "order": order, "samples": sample})
        finally:
            for process in workers.values():
                if process.stdin:
                    process.stdin.close()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        root_ms = [pair["samples"]["root"]["elapsed_ms"] for pair in pairs]
        candidate_ms = [pair["samples"]["candidate"]["elapsed_ms"] for pair in pairs]
        after = {"root": _hashes(ROOT), "candidate": _hashes(CANDIDATE)}
        assert before == after
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == harness_sha256
        report = {
            "kind": "model-free paired command-config microbenchmark",
            "acceptance": False,
            "root_head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
            "candidate_head": subprocess.check_output(["git", "-C", str(CANDIDATE), "rev-parse", "HEAD"], text=True).strip(),
            "source_sha256_before_after": before,
            "harness_sha256": harness_sha256,
            "fixture": "same temporary project config and fixed Python sum(range(20000)) command for both arms",
            "pairs": pairs,
            "timing_ms_no_tracing": {"n": len(pairs), "root_median": statistics.median(root_ms), "candidate_median": statistics.median(candidate_ms)},
            "limits": ["single Windows host", "no GPU", "no network or shared ports", "not release/performance acceptance"],
        }
        output = CANDIDATE / "handoff" / "t15-config-parity-microbench-slot-v1.json"
        if output.exists():
            raise FileExistsError(f"refusing to overwrite immutable receipt: {output}")
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "root_median_ms": report["timing_ms_no_tracing"]["root_median"], "candidate_median_ms": report["timing_ms_no_tracing"]["candidate_median"], "pairs": len(pairs)}))


if __name__ == "__main__":
    main()
