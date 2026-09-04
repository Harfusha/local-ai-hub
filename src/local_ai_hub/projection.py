from __future__ import annotations

import copy
import re
from typing import Any


_DEFAULTS = {
    "generic": {"max_text": 1500, "max_evidence": 8, "raw_evidence": 2, "risks": "important", "relationships": False, "commands": True},
    "codex": {"max_text": 1150, "max_evidence": 7, "raw_evidence": 1, "risks": "critical", "relationships": False, "commands": True},
    "claude": {"max_text": 1700, "max_evidence": 10, "raw_evidence": 2, "risks": "all", "relationships": True, "commands": True},
    "gemini": {"max_text": 1450, "max_evidence": 9, "raw_evidence": 2, "risks": "important", "relationships": True, "commands": True},
    "cursor": {"max_text": 1250, "max_evidence": 8, "raw_evidence": 2, "risks": "important", "relationships": True, "commands": True},
    "windsurf": {"max_text": 1250, "max_evidence": 8, "raw_evidence": 2, "risks": "important", "relationships": True, "commands": True},
    "copilot": {"max_text": 1100, "max_evidence": 7, "raw_evidence": 2, "risks": "important", "relationships": False, "commands": True},
}


def _normalize_agent(agent: str | None) -> str:
    value = (agent or "generic").strip().lower()
    if "claude" in value:
        return "claude"
    if "gemini" in value:
        return "gemini"
    if "cursor" in value:
        return "cursor"
    if "windsurf" in value or "codeium" in value:
        return "windsurf"
    if "copilot" in value or "vscode" in value or "github" in value:
        return "copilot"
    if "codex" in value or "openai" in value:
        return "codex"
    return "generic"


def _dense_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    newline = cut.rfind("\n")
    if newline > max_chars * 0.65:
        cut = cut[:newline]
    return cut + "\n[…more available via artifact…]"


class AgentProjector:
    """Project one canonical local result into the minimum useful agent payload."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.cfg = config.get("agent_output", {})

    def profile(self, agent: str | None, task_kind: str = "general") -> dict[str, Any]:
        name = _normalize_agent(agent)
        merged = dict(_DEFAULTS[name])
        custom = self.cfg.get(name, {}) if isinstance(self.cfg, dict) else {}
        if isinstance(custom, dict):
            merged.update(custom)
        # Reviews need slightly more evidence; command/status need substantially less prose.
        if task_kind in {"review", "review_diff", "impact"}:
            merged["max_evidence"] = max(int(merged["max_evidence"]), 9)
            merged["raw_evidence"] = max(int(merged.get("raw_evidence", 1)), 3)
        if task_kind in {"command", "status", "profile"}:
            merged["max_text"] = min(int(merged["max_text"]), 900)
        return merged

    def project(self, value: Any, agent: str | None = None, task_kind: str = "general") -> Any:
        p = self.profile(agent, task_kind)
        return self._project(value, p, task_kind)


    @staticmethod
    def _compact_canonical(canonical: Any, p: dict[str, Any]) -> Any:
        """Drop internal local-agent chatter while preserving decision-grade state.

        Expensive explorer/worker/critic JSON remains in stage cache/artifacts. The
        cloud client only receives compact conclusions, evidence IDs and planner
        provenance needed to decide the next action.
        """
        if not isinstance(canonical, dict):
            return canonical
        out: dict[str, Any] = {}
        for key in ("task", "risk", "plan"):
            if key in canonical:
                out[key] = canonical[key]
        deterministic = canonical.get("deterministic")
        if isinstance(deterministic, dict):
            det: dict[str, Any] = {k: deterministic[k] for k in ("intent", "confidence") if k in deterministic}
            for key in ("test_candidates", "scripts", "dependencies", "evidence"):
                vals = deterministic.get(key)
                if isinstance(vals, list) and vals:
                    det[key] = vals[:6]
            facts = deterministic.get("facts")
            if isinstance(facts, list) and facts:
                det["facts"] = [{k: x.get(k) for k in ("kind", "name", "path", "line") if k in x} for x in facts[:6] if isinstance(x, dict)]
            if det:
                out["deterministic"] = det
        graph = canonical.get("code_index")
        if isinstance(graph, dict):
            compact_graph: dict[str, Any] = {}
            for key in ("confidence", "terms"):
                if key in graph:
                    compact_graph[key] = graph[key]
            for key in ("symbols", "references", "edges"):
                vals = graph.get(key)
                if isinstance(vals, list):
                    compact_graph[key] = vals[:6]
                    if len(vals) > 6:
                        compact_graph[key + "_omitted"] = len(vals) - 6
            if compact_graph:
                out["code_index"] = compact_graph
        for role in ("explorer", "worker", "critic"):
            meta = canonical.get(role)
            if isinstance(meta, dict):
                out[role] = {k: meta[k] for k in ("used", "model", "cache_hit") if k in meta}

        # Structured stage payloads can be large. Keep only the final actionable
        # fields, never whole hidden local-agent traces.
        structured = canonical.get("structured")
        if isinstance(structured, dict):
            chosen = structured.get("worker") or structured.get("explorer")
            critic = structured.get("critic")
            compact: dict[str, Any] = {}
            if isinstance(chosen, dict):
                for key in ("summary", "confidence", "actions", "risks", "missing_evidence", "candidate_files", "evidence_ids"):
                    value = chosen.get(key)
                    if value not in (None, "", [], {}):
                        compact[key] = value[:12] if isinstance(value, list) else value
            if isinstance(critic, dict):
                critic_compact = {k: critic[k] for k in ("summary", "confidence", "risks", "missing_evidence", "evidence_ids") if k in critic and critic[k] not in (None, "", [], {})}
                for key, value in list(critic_compact.items()):
                    if isinstance(value, list):
                        critic_compact[key] = value[:8]
                if critic_compact:
                    compact["critic"] = critic_compact
            if compact:
                out["result"] = compact
        return out

    def _project(self, value: Any, p: dict[str, Any], task_kind: str) -> Any:
        if isinstance(value, list):
            return [self._project(v, p, task_kind) for v in value[:32]]
        if not isinstance(value, dict):
            return value
        data = copy.deepcopy(value)

        if "canonical" in data:
            data["canonical"] = self._compact_canonical(data.get("canonical"), p)

        # Runtime diagnostics stay behind status(detail=cache/full), never in normal cloud context.
        for key in (
            "load_duration_ns", "eval_count", "prompt_eval_count", "total_duration_ns",
            "job_id", "prompt_budget", "semantic_similarity", "coalesced",
        ):
            data.pop(key, None)

        max_text = max(300, int(p.get("max_text", 1400)))
        if isinstance(data.get("text"), str):
            data["text"] = _dense_text(data["text"], max_text)
        if isinstance(data.get("summary"), str):
            data["summary"] = _dense_text(data["summary"], min(max_text, 1000))

        # Raw command streams are intentionally tiny. Full content is artifact-backed.
        stream_limit = max(160, min(650, max_text // 3))
        if isinstance(data.get("stdout"), str):
            data["stdout"] = _dense_text(data["stdout"], stream_limit)
        if isinstance(data.get("stderr"), str) and len(data["stderr"]) > stream_limit:
            data["stderr"] = "[…head omitted…]\n" + data["stderr"][-stream_limit:]

        max_ev = max(1, int(p.get("max_evidence", 8)))
        for container in (data, data.get("repo_context") if isinstance(data.get("repo_context"), dict) else None):
            if isinstance(container, dict) and isinstance(container.get("evidence"), list):
                total = len(container["evidence"])
                raw_count = max(0, int(p.get("raw_evidence", 4)))
                container["evidence"] = [self._trim_evidence(x, task_kind, include_raw=(i < raw_count)) for i, x in enumerate(container["evidence"][:max_ev])]
                if total > max_ev:
                    container["evidence_omitted"] = total - max_ev

        if isinstance(data.get("results"), list):
            results = data["results"][:24]
            # Search results backed by E-ids use progressive disclosure too. This
            # prevents 10-20 near-duplicate source snippets entering cloud context.
            if results and all(isinstance(v, dict) and v.get("path") for v in results):
                raw_count = max(0, int(p.get("raw_evidence", 2)))
                data["results"] = [
                    self._trim_evidence(v, task_kind, include_raw=(i < raw_count))
                    if isinstance(v, dict) and (v.get("evidence_id") or v.get("start_line") or v.get("line"))
                    else self._project(v, p, task_kind)
                    for i, v in enumerate(results)
                ]
            else:
                data["results"] = [self._project(v, p, task_kind) for v in results]

        # Codex benefits from action/evidence density; Claude/Gemini can use relationships.
        if not bool(p.get("relationships", False)):
            for key in ("likely_dependents", "relationships", "dependency_graph", "repo_map"):
                if key in data and task_kind not in {"impact", "architecture"}:
                    data.pop(key, None)

        risk_mode = str(p.get("risks", "important"))
        if risk_mode == "critical" and isinstance(data.get("risks"), list):
            data["risks"] = [
                r for r in data["risks"]
                if isinstance(r, dict) and str(r.get("severity", "")).lower() in {"critical", "high"}
            ][:6]

        # Cache telemetry is useful only as one tiny provenance marker in normal calls.
        if "cache_layer" in data:
            data["cache"] = data.pop("cache_layer")
        data.pop("token_saving", None)
        data.pop("workspace_cache", None)
        return data

    @staticmethod
    def _trim_evidence(item: Any, task_kind: str, include_raw: bool = True) -> Any:
        if not isinstance(item, dict):
            return item
        keep = {"path", "start_line", "end_line", "line", "symbol", "severity", "file_sha256", "content_hash", "evidence_id", "raw", "text"}
        out = {k: v for k, v in item.items() if k in keep}
        if not include_raw:
            out.pop("raw", None); out.pop("text", None)
        # Lossless routed evidence may include exact raw lines. Bound each slice separately.
        for key in ("raw", "text"):
            if isinstance(out.get(key), str) and len(out[key]) > 1400:
                out[key] = _dense_text(out[key], 1400)
        return out
