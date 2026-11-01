"""Persist operator-reviewed inspection cases; never run an evaluation or pull a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.work_orchestrator import _bounded_tool_qualification
from tools.local_model_eval_tool_harness import _loopback_url


def persist_qualification(store: Any, runtime: Any, cases: Any, *, reviewed: bool) -> str:
    """Validate all records before a single atomic artifact-store transaction."""
    if reviewed is not True or not isinstance(cases, dict) or set(cases) != {"C1", "C2", "C3"}:
        raise ValueError("manual review of exactly C1, C2 and C3 is required")
    first = cases["C1"]
    if not isinstance(first, dict) or not isinstance(first.get("model"), str):
        raise ValueError("invalid model evidence")
    model, digest = first["model"], first.get("model_digest")
    qualification = {"schema": "local_tool_qualification.v1", "model": model,
                     "model_digest": digest, "task_kind": "repository_inspect",
                     "operator_reviewed": True, "critical_failures": 0,
                     "cases": {case: {"status": "PASS", "artifact_id": case} for case in cases}}
    records = {"qualification": ("local-tool-qualification", qualification)}
    records.update({case: ("local-model-tool-case", value) for case, value in cases.items()})

    class Staged:
        def get(self, artifact_id: str, **_kwargs: Any) -> dict[str, Any]:
            kind, value = records[artifact_id]
            text = json.dumps(value, ensure_ascii=False)
            if len(text) > 50000:
                raise ValueError("case record exceeds artifact retrieval limit")
            return {"success": True, "artifact_id": artifact_id, "kind": kind,
                    "next_offset": None, "text": text}

    config = {"_hardware": {"profile": "high"}, "work_orchestrator": {"tool_exploration": {
        "enabled": True, "model": model, "qualification_artifact_id": "qualification"}}}
    if not _bounded_tool_qualification(config, Staged(), runtime).get("qualified"):
        raise ValueError("case evidence or installed model digest does not qualify")
    with store.batch() as batch:
        ids = {case: batch.put_json(cases[case], kind="local-model-tool-case") for case in ("C1", "C2", "C3")}
        qualification["cases"] = {case: {"status": "PASS", "artifact_id": ids[case]} for case in ids}
        return batch.put_json(qualification, kind="local-tool-qualification")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True, help="Existing Hub state directory")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    for case in ("c1", "c2", "c3"):
        parser.add_argument("--" + case, type=Path, required=True, help="Complete raw harness JSON")
    parser.add_argument("--reviewed-all-pass", action="store_true", required=True,
                        help="I manually scored C1/C2/C3 PASS with zero critical failures")
    args = parser.parse_args()
    if not args.state_dir.is_absolute() or not (args.state_dir / "artifacts.sqlite3").is_file():
        parser.error("--state-dir must be an absolute existing Hub state directory")
    records = {}
    try:
        for case in ("C1", "C2", "C3"):
            data = getattr(args, case.lower()).read_bytes()
            if len(data) > 50000:
                raise ValueError(f"{case} exceeds 50000 bytes")
            records[case] = json.loads(data)
        url = _loopback_url(args.ollama_url)
        runtime = OllamaRuntime({"server": {"ollama_url": url, "state_dir": str(args.state_dir)},
                                 "ollama": {"enabled": True}})
        artifact = persist_qualification(ArtifactStore(args.state_dir), runtime, records,
                                         reviewed=args.reviewed_all_pass)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"Qualification not created: {exc}\n")
    print(json.dumps({"qualification_artifact_id": artifact, "activated": False}))


if __name__ == "__main__":
    main()
