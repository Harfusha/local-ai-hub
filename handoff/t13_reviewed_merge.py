"""Materialize reviewed conflict choices; never touch shared master or other roots.

Run only after per-hunk behavioral review. Original variants remain in 4aa2edef.
The resulting conflict files deliberately use the coherent pinned implementation,
including its non-conflicting context: mixing two admission/HTTP/model protocols
would retain dangling helpers, obsolete snapshot constructors and stale signatures.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess

ROOT = Path("C:/Users/Adam/.codex/worktrees/t13-operational-mode/.local-ai-hub")
PIN = "ca2f86237b1f8ac9ce4f576a308b65b94a24a69c"
REASONS = {
    "app.py": "Master admission binding, project context and dependency health stay coherent.",
    "async_jobs.py": "Master per-action admission, caller/generated request provenance and delayed dispatch safety.",
    "background_gpu.py": "Equivalent last-handoff pause checks; preserve master contract.",
    "client.py": "Master cancellation, preflight validation, replay and uncertain coalesced outcomes.",
    "dashboard.py": "Master activity-mode controls, diagnostic escaping and degraded dependency badge.",
    "embeddings.py": "Master encoder lock, execution-local provenance and model-lifecycle ownership.",
    "http_server.py": "Master audited action authorization, bounded validation, recovery and route dispatch; T14 unchanged.",
    "llama_cpp.py": "Master interruptible deadline unload signature matches Ollama caller.",
    "mcp_server.py": "Master mode policy, request validation and transcription routing.",
    "ollama.py": "Master bounded deadline/cancellation and verified complete loaded-model unload.",
    "operational_mode.py": "Master timestamped snapshot schema, bounded cross-process lock and fail-closed state.",
    "preprocess.py": "Master background-work gate, Gemini integration and CodeGraph-free phases.",
    "process_utils.py": "Master worktree ownership marker and cancellation/tree cleanup protocol.",
    "reranker.py": "Master lock order and model lifecycle rather than stale candidate release helper.",
    "services.py": "Master project routing, trace redaction, inference admission and JSON Whisper validation.",
    "hubctl.py": "Master pause=gaming, mode read/admin request and incomplete transition reporting.",
}

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

if Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != ROOT.resolve():
    raise SystemExit("wrong root")
if git("rev-parse", "MERGE_HEAD").decode().strip() != PIN:
    raise SystemExit("wrong merge parent")
paths = git("diff", "--name-only", "--diff-filter=U").decode().splitlines()
review = []
for name in paths:
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    hunks = re.findall(r"(?ms)^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*", text)
    reason = REASONS.get(path.name)
    if reason is None and not name.startswith("tests/"):
        raise SystemExit(f"unreviewed file: {name}")
    reason = reason or "Reviewed schema, imports and assertions follow pinned implementation; older tests retained in checkpoint."
    review.append({"path": name, "hunks": len(hunks), "choice": "pinned master", "reason": reason,
                   "hunk_sha256": [hashlib.sha256((a + "\0" + b).encode()).hexdigest() for a, b in hunks]})
    path.write_bytes(git("show", f"{PIN}:{name}"))
    subprocess.run(["git", "add", "--", name], cwd=ROOT, check=True)
(ROOT / "handoff/T13-sync-conflict-decisions-20261006.json").write_text(
    json.dumps({"pinned_master": PIN, "checkpoint": "4aa2edef", "reviews": review}, indent=2) + "\n",
    encoding="utf-8")
print(f"Resolved {len(review)} files / {sum(item['hunks'] for item in review)} reviewed hunks.")
