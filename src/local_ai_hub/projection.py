from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any, Iterable


_DEFAULTS = {
    "generic": {"max_text": 1500, "max_evidence": 8, "raw_evidence": 2, "risks": "important", "relationships": False, "commands": True},
    "codex": {"max_text": 1150, "max_evidence": 7, "raw_evidence": 1, "risks": "critical", "relationships": False, "commands": True},
    "claude": {"max_text": 1700, "max_evidence": 10, "raw_evidence": 2, "risks": "all", "relationships": True, "commands": True},
    "gemini": {"max_text": 1450, "max_evidence": 9, "raw_evidence": 2, "risks": "important", "relationships": True, "commands": True},
    "cursor": {"max_text": 1250, "max_evidence": 8, "raw_evidence": 2, "risks": "important", "relationships": True, "commands": True},
    "windsurf": {"max_text": 1250, "max_evidence": 8, "raw_evidence": 2, "risks": "important", "relationships": True, "commands": True},
    "copilot": {"max_text": 1100, "max_evidence": 7, "raw_evidence": 2, "risks": "important", "relationships": False, "commands": True},
}

VENDOR_RE = re.compile(r"site-packages|dist-packages|node_modules|python\d+[\\/]lib|node:internal|\.venv[\\/]lib", re.IGNORECASE)


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

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.config = config
        self.cfg = config.get("agent_output", {}) if isinstance(config, dict) else {}
        self.ultra_compact = bool(self.cfg.get("ultra_compact", True))
        self.strip_empty = bool(self.cfg.get("strip_empty", self.ultra_compact))
        self.coalesce_snippets = bool(self.cfg.get("coalesce_snippets", self.ultra_compact))
        self.prune_stacktraces = bool(self.cfg.get("prune_stacktraces", self.ultra_compact))
        self.trim_diff_context = bool(self.cfg.get("trim_diff_context", self.ultra_compact))
        self.flat_symbols = bool(self.cfg.get("flat_symbols", self.ultra_compact))

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

    def project(
        self,
        value: Any,
        agent: str | None = None,
        task_kind: str = "general",
        extra_fields: Iterable[str] | None = None,
    ) -> Any:
        p = self.profile(agent, task_kind)
        extra_set = {str(x).strip() for x in (extra_fields or ()) if str(x).strip()}
        return self._project(value, p, task_kind, extra_fields=extra_set)


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

    def _project(self, value: Any, p: dict[str, Any], task_kind: str, extra_fields: set[str] | None = None) -> Any:
        extra = extra_fields or set()
        if isinstance(value, list):
            return [self._project(v, p, task_kind, extra_fields=extra) for v in value[:32]]
        if not isinstance(value, dict):
            return value
        data = copy.deepcopy(value)

        if "canonical" in data:
            data["canonical"] = self._compact_canonical(data.get("canonical"), p)

        # Runtime diagnostics stay behind status(detail=cache/full), never in normal cloud context.
        for key in (
            "load_duration_ns", "eval_count", "prompt_eval_count", "total_duration_ns",
            "job_id", "prompt_budget", "semantic_similarity", "coalesced",
            "prompt_eval_duration_ns", "eval_duration_ns",
        ):
            if key not in extra:
                data.pop(key, None)

        # Strip internal engine / plumbing metadata by default unless requested in extra_fields
        if task_kind not in {"status", "profile", "telemetry"}:
            for key in (
                "candidate_context_tokens_est", "original_estimated_tokens",
                "progressive_disclosure", "engine", "scanned_files", "cache_hit", "cache",
                "diff_sha256", "inventory_sha256", "file_sha256", "content_hash",
                "search_cache", "targeted", "preprocessed_hit",
            ):
                if key not in extra:
                    data.pop(key, None)

        # Strip task/model execution plumbing unless requested
        if "execution_profile" not in extra:
            data.pop("execution_profile", None)
        if "latency" not in extra:
            data.pop("latency", None)
        if "route" not in extra and task_kind != "route":
            data.pop("route", None)
        if not data.get("fallback_used") and "fallback_used" not in extra:
            data.pop("fallback_used", None)
        if data.get("requested_model") == data.get("model") and "requested_model" not in extra:
            data.pop("requested_model", None)

        # Strip profile boilerplate unless requested
        if task_kind == "profile":
            if "note" not in extra:
                data.pop("note", None)
            if "cache" not in extra:
                data.pop("cache", None)
            if not data.get("cache_hit") and "cache_hit" not in extra:
                data.pop("cache_hit", None)

        # Strip static phase enumerations from status
        if "phases" not in extra and isinstance(data.get("phases"), list):
            data.pop("phases", None)

        # Strip echo of caller's query terms
        if "terms" not in extra and task_kind not in {"status", "profile", "telemetry"}:
            data.pop("terms", None)

        # Optimize command broker outputs
        if task_kind == "command":
            if "repo_state" not in extra:
                data.pop("repo_state", None)
            else:
                rs = data.get("repo_state")
                if isinstance(rs, dict) and isinstance(rs.get("changed_paths"), list):
                    rs["changed_paths"] = rs["changed_paths"][:10]

            if "classification" not in extra:
                data.pop("classification", None)

            # Strip default false boolean flags that clutter agent context
            for flag in ("timed_out", "cancelled", "aborted_interactive", "output_truncated", "cache_hit", "coalesced"):
                if flag not in extra and not data.get(flag):
                    data.pop(flag, None)

            # Clean redundant summary
            if "summary" not in extra:
                summary_str = str(data.get("summary", "")).strip()
                stdout_str = str(data.get("stdout", "")).strip()
                stderr_str = str(data.get("stderr", "")).strip()
                if (
                    "completed with exit code 0" in summary_str.lower()
                    or "exit code 0" in summary_str.lower()
                    or summary_str == stdout_str
                    or summary_str == stderr_str
                ):
                    data.pop("summary", None)

            exit_code = data.get("exit_code")
            if exit_code == 0:
                if "stderr" not in extra:
                    data.pop("stderr", None)
            else:
                if not data.get("stdout") and "stdout" not in extra:
                    data.pop("stdout", None)

        if self.prune_stacktraces and "raw_trace" not in extra and "full_trace" not in extra:
            for k in ("stderr", "stdout", "summary", "text", "error"):
                if isinstance(data.get(k), str):
                    data[k] = self._prune_stacktrace(data[k])

        if self.trim_diff_context and "raw_diff" not in extra and "full_diff" not in extra:
            if isinstance(data.get("diff"), str):
                data["diff"] = self._trim_diff_context(data["diff"])

        if self.flat_symbols and isinstance(data.get("symbols"), list):
            data["symbols"] = self._flatten_symbols(data["symbols"], extra_fields=extra)

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
                container["evidence"] = [self._trim_evidence(x, task_kind, include_raw=(i < raw_count), extra_fields=extra) for i, x in enumerate(container["evidence"][:max_ev])]
                if total > max_ev:
                    container["evidence_omitted"] = total - max_ev

        if isinstance(data.get("results"), list):
            results = data["results"]
            if self.coalesce_snippets:
                results = self._coalesce_snippets(results)
            results = results[:24]
            # Search results backed by E-ids use progressive disclosure too. This
            # prevents 10-20 near-duplicate source snippets entering cloud context.
            if results and all(isinstance(v, dict) and v.get("path") for v in results):
                raw_count = max(0, int(p.get("raw_evidence", 2)))
                data["results"] = [
                    self._trim_evidence(v, task_kind, include_raw=(i < raw_count), extra_fields=extra)
                    if isinstance(v, dict) and (v.get("evidence_id") or v.get("start_line") or v.get("line"))
                    else self._project(v, p, task_kind, extra_fields=extra)
                    for i, v in enumerate(results)
                ]
            else:
                data["results"] = [self._project(v, p, task_kind, extra_fields=extra) for v in results]

            if "format:text" in extra:
                blocks = []
                for r in data["results"]:
                    if isinstance(r, dict):
                        p_path = r.get("path", "")
                        s_line = r.get("start_line")
                        e_line = r.get("end_line")
                        line_no = r.get("line")
                        if s_line is not None and e_line is not None:
                            hdr = f"--- {p_path}:{s_line}-{e_line} ---"
                        elif line_no is not None:
                            hdr = f"--- {p_path}:{line_no} ---"
                        elif p_path:
                            hdr = f"--- {p_path} ---"
                        else:
                            hdr = "---"
                        content = r.get("text") or r.get("raw") or ""
                        blocks.append(f"{hdr}\n{content}" if content else hdr)
                    elif isinstance(r, str):
                        blocks.append(r)
                data["text"] = "\n\n".join(blocks)
                data["format"] = "text"
                data.pop("results", None)

        # Codex benefits from action/evidence density; Claude/Gemini can use relationships.
        if not bool(p.get("relationships", False)) and "relationships" not in extra:
            for key in ("likely_dependents", "relationships", "dependency_graph", "repo_map"):
                if key in data and task_kind not in {"impact", "architecture"} and key not in extra:
                    data.pop(key, None)

        risk_mode = str(p.get("risks", "important"))
        if risk_mode == "critical" and isinstance(data.get("risks"), list):
            data["risks"] = [
                r for r in data["risks"]
                if isinstance(r, dict) and str(r.get("severity", "")).lower() in {"critical", "high"}
            ][:6]

        # Cache telemetry is useful only as one tiny provenance marker in normal calls.
        if "cache_layer" in data:
            if "cache" in extra or "cache_layer" in extra or task_kind in {"status", "profile"}:
                data["cache"] = data.pop("cache_layer")
            else:
                data.pop("cache_layer", None)
        if "token_saving" not in extra:
            data.pop("token_saving", None)
        if "workspace_cache" not in extra:
            data.pop("workspace_cache", None)

        if self.strip_empty:
            data = self._clean_empty(data)
        return data

    @staticmethod
    def _clean_empty(val: Any, preserve_keys: set[str] | None = None) -> Any:
        preserve = preserve_keys or {"results", "files", "symbols"}
        if isinstance(val, dict):
            cleaned = {}
            for k, v in val.items():
                if k not in preserve and v in (None, "", [], {}):
                    continue
                cv = AgentProjector._clean_empty(v, preserve_keys=preserve)
                if k not in preserve and cv in (None, "", [], {}):
                    continue
                cleaned[k] = cv
            return cleaned
        if isinstance(val, list):
            cleaned = []
            for item in val:
                ci = AgentProjector._clean_empty(item, preserve_keys=preserve)
                if ci in (None, "", [], {}):
                    continue
                cleaned.append(ci)
            return cleaned
        return val

    @staticmethod
    def _coalesce_snippets(results: list[Any]) -> list[Any]:
        if not results or not all(isinstance(r, dict) for r in results):
            return results
        by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for idx, item in enumerate(results):
            p = str(item.get("path", ""))
            if not p or "start_line" not in item or "end_line" not in item:
                by_path[f"__non_source_{idx}__"].append(item)
            else:
                by_path[p].append(item)

        merged_results: list[dict[str, Any]] = []
        for p, group in by_path.items():
            if p.startswith("__non_source_"):
                merged_results.extend(group)
                continue
            group.sort(key=lambda x: (int(x.get("start_line", 0)), int(x.get("end_line", 0))))
            curr = dict(group[0])
            for next_item in group[1:]:
                curr_end = int(curr.get("end_line", 0))
                next_start = int(next_item.get("start_line", 0))
                next_end = int(next_item.get("end_line", 0))

                if next_start <= curr_end + 1:
                    curr["end_line"] = max(curr_end, next_end)
                    if "score" in curr or "score" in next_item:
                        curr["score"] = max(float(curr.get("score", 0)), float(next_item.get("score", 0)))
                    text_a = curr.get("text")
                    text_b = next_item.get("text")
                    if isinstance(text_a, str) and isinstance(text_b, str):
                        lines_a = text_a.splitlines()
                        lines_b = text_b.splitlines()
                        line_dict: dict[int, str] = {}
                        has_num = False
                        for line in lines_a:
                            m = re.match(r"^(\d+):\s?(.*)$", line)
                            if m:
                                line_dict[int(m.group(1))] = line
                                has_num = True
                        for line in lines_b:
                            m = re.match(r"^(\d+):\s?(.*)$", line)
                            if m:
                                line_dict[int(m.group(1))] = line
                                has_num = True
                        if has_num and line_dict:
                            curr["text"] = "\n".join(line_dict[k] for k in sorted(line_dict))
                        else:
                            overlap = curr_end - next_start + 1
                            if 0 < overlap <= len(lines_b):
                                curr["text"] = "\n".join(lines_a + lines_b[overlap:])
                            else:
                                curr["text"] = "\n".join(lines_a + lines_b)
                else:
                    merged_results.append(curr)
                    curr = dict(next_item)
            merged_results.append(curr)
        return merged_results

    @staticmethod
    def _trim_evidence(item: Any, task_kind: str, include_raw: bool = True, extra_fields: set[str] | None = None) -> Any:
        if not isinstance(item, dict):
            return item
        extra = extra_fields or set()
        keep = {"path", "start_line", "end_line", "line", "symbol", "severity", "evidence_id", "raw", "text"} | extra
        out = {k: v for k, v in item.items() if k in keep}
        if not include_raw and "raw" not in extra and "text" not in extra:
            out.pop("raw", None); out.pop("text", None)
        # Lossless routed evidence may include exact raw lines. Bound each slice separately.
        for key in ("raw", "text"):
            if isinstance(out.get(key), str) and len(out[key]) > 1400:
                out[key] = _dense_text(out[key], 1400)
        return out

    @staticmethod
    def _prune_stacktrace(text: str) -> str:
        if not text or "File " not in text:
            return text
        lines = text.splitlines(keepends=True)
        out_lines: list[str] = []
        vendor_count = 0
        i = 0
        n = len(lines)
        nl = "\r\n" if "\r\n" in text else "\n"

        while i < n:
            line = lines[i]
            m = re.match(r'^\s*File "(.*?)"', line)
            if m:
                filepath = m.group(1)
                frame_lines = [line]
                j = i + 1
                while j < n:
                    next_line = lines[j]
                    if re.match(r'^\s*File "', next_line):
                        break
                    if next_line.strip() and not next_line.startswith((" ", "\t")):
                        break
                    frame_lines.append(next_line)
                    j += 1

                is_vendor = bool(VENDOR_RE.search(filepath))
                if is_vendor:
                    vendor_count += 1
                else:
                    if vendor_count > 0:
                        out_lines.append(f"  [... {vendor_count} vendor frames omitted ...]{nl}")
                        vendor_count = 0
                    out_lines.extend(frame_lines)
                i = j
            else:
                if vendor_count > 0:
                    out_lines.append(f"  [... {vendor_count} vendor frames omitted ...]{nl}")
                    vendor_count = 0
                out_lines.append(line)
                i += 1

        if vendor_count > 0:
            out_lines.append(f"  [... {vendor_count} vendor frames omitted ...]{nl}")
        return "".join(out_lines)

    @staticmethod
    def _trim_diff_context(diff_text: str, max_context: int = 1) -> str:
        if not diff_text or "@@" not in diff_text:
            return diff_text
        lines = diff_text.splitlines()
        out: list[str] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if line.startswith("@@ ") and " @@" in line:
                hunk_header = line
                hunk_lines: list[str] = []
                j = i + 1
                while j < n and not lines[j].startswith("@@ ") and not (lines[j].startswith("--- ") and j + 1 < n and lines[j + 1].startswith("+++ ")):
                    hunk_lines.append(lines[j])
                    j += 1

                change_indices = [
                    idx for idx, hl in enumerate(hunk_lines)
                    if hl.startswith(("+", "-")) and not hl.startswith(("+++", "---"))
                ]
                if not change_indices:
                    out.append(hunk_header)
                    out.extend(hunk_lines)
                else:
                    first_ch = change_indices[0]
                    last_ch = change_indices[-1]
                    start_idx = max(0, first_ch - max_context)
                    end_idx = min(len(hunk_lines), last_ch + 1 + max_context)
                    out.append(hunk_header)
                    out.extend(hunk_lines[start_idx:end_idx])
                i = j
            else:
                out.append(line)
                i += 1
        trailing_nl = "\n" if diff_text.endswith("\n") else ""
        return "\n".join(out) + trailing_nl

    @staticmethod
    def _flatten_symbols(symbols: list[Any], extra_fields: set[str] | None = None) -> list[Any]:
        if not isinstance(symbols, list):
            return symbols
        extra = extra_fields or set()
        keep = {"name", "path", "line", "kind", "symbol", "signature"} | extra
        flattened: list[Any] = []
        for item in symbols:
            if isinstance(item, dict):
                flat = {k: v for k, v in item.items() if k in keep}
                flattened.append(flat)
            else:
                flattened.append(item)
        return flattened
