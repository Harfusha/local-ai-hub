from __future__ import annotations

from .json_utils import dumps as json_dumps

from . import __version__
import copy
import json
import time
from typing import Any

from .cache import stable_hash
from .model_policy import ModelExecutionPolicy
from .ollama_subagents import OllamaSubagentCatalog, OllamaSubagentProfile
from .prompt_contracts import build_prompt
from .trace_context import observer


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "preprocessed_context",
            "description": "Get tiny cached project/file/module semantic cards relevant to the task. Prefer this first.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deterministic_facts",
            "description": "Query cached deterministic facts (symbols, callers, routes, tests, dependencies, commands, config/env, entry points) before any semantic search.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_search",
            "description": "Cached lexical source search returning exact snippets and file hashes.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 10}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Cached semantic search over the prebuilt workspace RAG index.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 8}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_profile",
            "description": "Get cached languages, manifests, tooling and validation commands.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "repo_map",
            "description": "Get cached repository shape and representative symbols.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_slice",
            "description": "Read an exact bounded source range only when search/card evidence is insufficient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1, "maximum": 1000000},
                },
                "required": ["path", "start_line", "end_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_index",
            "description": "Query the deterministic symbol/reference/call/import index. Prefer this before broad text search for symbol relationships.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_symbols",
            "description": "Use Serena semantic/LSP intelligence for precise symbol lookup, references, file symbol overview, or code-pattern search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["find_symbol", "references", "overview", "search"]},
                    "query": {"type": "string"}, "path": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_graph",
            "description": "Use CodeGraphContext for callers/callees/imports/inheritance, dead-code, complexity, repository graph search and impact relationships.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["callers", "callees", "imports", "importers", "inheritance", "relationships", "search", "dead_code", "complexity", "stats"]},
                    "query": {"type": "string"}, "path": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evidence_get",
            "description": "Fetch one exact immutable evidence slice by id only when its raw source is needed.",
            "parameters": {"type": "object", "properties": {"evidence_id": {"type": "string"}}, "required": ["evidence_id"]},
        },
    },
]


class ToolAwareLocalAgent:
    """Bounded read-only Ollama agent loop over Local AI Hub's own cached tooling."""

    def __init__(self, config: dict[str, Any], services: Any, preprocessor: Any, rag: Any, code_index: Any | None = None, evidence: Any | None = None, deterministic: Any | None = None, external_tools: Any | None = None):
        self.config = config
        self.services = services
        self.model_policy = getattr(services, "model_policy", ModelExecutionPolicy(config))
        self.profile_catalog = OllamaSubagentCatalog(config)
        self.preprocessor = preprocessor
        self.rag = rag
        self.code_index = code_index
        self.evidence = evidence
        self.deterministic = deterministic
        self.external_tools = external_tools
        cfg = config.get("local_tools", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.max_steps = max(1, int(cfg.get("max_steps", 4)))
        self.max_calls = max(1, int(cfg.get("max_tool_calls", 8)))
        self.max_tool_chars = max(800, int(cfg.get("max_tool_result_chars", 6500)))
        self.pre_context_chars = max(0, int(cfg.get("preprocessed_context_chars", 2800)))
        self.semantic_bypass_confidence = float(cfg.get("semantic_bypass_confidence", 0.94))
        self.bootstrap_deterministic_tools = bool(cfg.get("bootstrap_deterministic_tools", True))
        self.auto_register_project = bool(cfg.get("auto_register_project", False))
        self.runs = 0
        self.cache_hits = 0
        self.tool_calls = 0
        self.failures = 0
        self.semantic_bypasses = 0

    @staticmethod
    def _tools_for_role(role: str) -> list[dict[str, Any]]:
        """Expose only tools useful to the current role.

        Ollama receives tool schemas in its prompt, so fewer schemas directly reduce
        local prompt processing latency. Every role keeps deterministic/exact escape
        hatches; broad discovery helpers are limited mainly to explorers.
        """
        role = str(role).lower()
        if role == "critic":
            allowed = {"deterministic_facts", "code_index", "semantic_symbols", "code_graph", "repo_search", "evidence_get", "file_slice"}
        elif role == "worker":
            allowed = {"preprocessed_context", "deterministic_facts", "code_index", "semantic_symbols", "code_graph", "repo_search", "rag_search", "evidence_get", "file_slice"}
        else:
            allowed = {t["function"]["name"] for t in TOOLS}
        return [t for t in TOOLS if t["function"]["name"] in allowed]

    @staticmethod
    def _tools_for_profile(profile: OllamaSubagentProfile) -> list[dict[str, Any]]:
        allowed = set(profile.tools)
        return [t for t in TOOLS if t["function"]["name"] in allowed]

    @staticmethod
    def _arguments(call: dict[str, Any]) -> dict[str, Any]:
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        args = fn.get("arguments", {}) if isinstance(fn, dict) else {}
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return args if isinstance(args, dict) else {}

    def _trim(self, value: Any) -> str:
        text = json_dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(text) > self.max_tool_chars:
            return text[: self.max_tool_chars] + "\n[…tool result truncated…]"
        return text

    def _execute_tool(self, name: str, args: dict[str, Any], root: str, tenant: str, workspace: str) -> dict[str, Any]:
        if not isinstance(args, dict):
            args = {}
        if name == "preprocessed_context":
            return self.preprocessor.lookup(root, str(args.get("query", "")), limit=5)
        if name == "deterministic_facts":
            if self.deterministic is None:
                return {"success": False, "error": "deterministic engine unavailable"}
            limit_val = max(1, min(int(args.get("limit") or 20), 30))
            result = self.services.deterministic_query(root, str(args.get("query", "")), limit_val) if hasattr(self.services, "deterministic_query") else self.deterministic.query(root, str(args.get("query", "")), limit_val)
            if isinstance(result, dict):
                result = copy.deepcopy(result)
                # Progressive disclosure for local models too: facts/coordinates first,
                # immutable raw lines only through evidence_get/file_slice on demand.
                if isinstance(result.get("evidence"), list):
                    result["evidence"] = [{k: v for k, v in x.items() if k != "text"} for x in result["evidence"][:12]]
                if isinstance(result.get("facts"), list): result["facts"] = result["facts"][:20]
                if isinstance(result.get("dependencies"), list): result["dependencies"] = result["dependencies"][:20]
                if isinstance(result.get("scripts"), list): result["scripts"] = result["scripts"][:16]
            return result
        if name == "repo_search":
            query = str(args.get("query", ""))
            top_k = max(1, min(int(args.get("top_k") or 6), 10))
            try:
                paths = self.preprocessor.candidate_paths(root, query, limit=max(16, top_k * 4))
            except Exception:
                paths = []
            if paths:
                targeted = self.services.repo_tools.search_paths(root, query, paths, top_k)
                if targeted.get("results"):
                    result = targeted
                else:
                    result = self.services.repo_search(root, query, top_k)
            else:
                result = self.services.repo_search(root, query, top_k)
            # Progressive disclosure: return coordinates/evidence ids first, raw text only on evidence_get.
            if self.evidence is not None and isinstance(result.get("results"), list):
                enriched = self.evidence.put_many(str(result.get("root", root)), result["results"])
                result = dict(result)
                result["results"] = [{k:v for k,v in x.items() if k != "text"} for x in enriched]
                result["progressive_disclosure"] = True
            return result
        if name == "rag_search":
            query = str(args.get("query", ""))
            # Enforce deterministic-first below the prompt layer too. Even if a local
            # model asks for RAG prematurely, strong exact facts/graph evidence can
            # satisfy the request without query embeddings, vector scan or reranker.
            if self.deterministic is not None:
                try:
                    det = self.services.deterministic_query(root, query, max(12, min(int(args.get("top_k") or 6) * 3, 24))) if hasattr(self.services, "deterministic_query") else self.deterministic.query(root, query, max(12, min(int(args.get("top_k") or 6) * 3, 24)))
                    if (det.get("direct_answer") and float(det.get("confidence", 0.0)) >= self.semantic_bypass_confidence):
                        self.semantic_bypasses += 1
                        return {
                            "success": True, "semantic_skipped": True, "reason": "deterministic-evidence-sufficient",
                            "intent": det.get("intent"), "confidence": det.get("confidence"),
                            "facts": det.get("facts", [])[:16], "dependencies": det.get("dependencies", [])[:16],
                            "scripts": det.get("scripts", [])[:12], "evidence": det.get("evidence", [])[:10],
                        }
                except Exception:
                    pass
            result = self.rag.search(query, tenant, workspace, max(1, min(int(args.get("top_k") or 6), 8)), True)
            if isinstance(result.get("results"), list):
                # RAG chunks are hints; send coordinates/score first and let the agent request exact source via search/file slice.
                result = dict(result)
                result["results"] = [{k:v for k,v in x.items() if k not in {"text", "embedding"}} for x in result["results"]]
                result["progressive_disclosure"] = True
            return result
        if name == "repo_profile":
            return self.services.repo_profile(root)
        if name == "repo_map":
            return self.services.repo_map(root, 180)
        if name == "code_index":
            if self.code_index is None:
                return {"success": False, "error": "code index unavailable"}
            return self.services.code_query(root, str(args.get("query", "")), max(1, min(int(args.get("limit") or 20), 30))) if hasattr(self.services, "code_query") else self.code_index.query(root, str(args.get("query", "")), max(1, min(int(args.get("limit") or 20), 30)))
        if name in {"semantic_symbols", "code_graph"}:
            if self.external_tools is None:
                return {"success": False, "error": "external code intelligence unavailable"}
            backend = "serena" if name == "semantic_symbols" else "codegraph"
            return self.external_tools.query(
                root, str(args.get("query", "")), backend=backend,
                action=str(args.get("action", "search")), path=str(args.get("path", "")), limit=20,
            )
        if name == "evidence_get":
            if self.evidence is None:
                return {"success": False, "error": "evidence store unavailable"}
            return self.evidence.get(str(args.get("evidence_id", "")), verify=True)
        if name == "file_slice":
            start = max(1, int(args.get("start_line") or 1))
            end = max(start, int(args.get("end_line") or (start + 120)))
            if end - start > 220:
                end = start + 220
            return self.services.repo_tools.file_slice(root, str(args.get("path", "")), start, end, self.max_tool_chars)
        return {"success": False, "error": f"unknown local tool: {name}"}

    @staticmethod
    def _parse_structured(content: str, role: str) -> dict[str, Any] | None:
        text = content.strip()
        if not text:
            return None
        # Accept fenced JSON too; local templates vary.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                value.setdefault("role", role)
                return value
        except Exception:
            return None
        return None

    def run(
        self,
        model: str,
        role: str,
        task: str,
        root: str,
        tenant: str,
        max_tokens: int,
        priority: int,
        *,
        workspace: str | None = None,
        seed_context: str = "",
        system_suffix: str = "",
        bootstrap: dict[str, Any] | None = None,
        profile: OllamaSubagentProfile | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "unsupported": True, "error": "local tooling disabled"}
        try:
            root = str(self.services.repo_tools._root(root))
            workspace = workspace or self.rag.workspace_id(root)
        except Exception as exc:
            return {"success": False, "unsupported": False, "error": f"invalid repository root: {exc}", "model": model}
        try:
            if self.auto_register_project:
                self.preprocessor.register(root, source="tool-agent")
            else:
                self.preprocessor.touch_if_registered(root)
        except Exception:
            pass

        # The answer cache is checked from cheap repository/context revisions only.
        # Expensive deterministic/Serena/CodeGraph bootstrap work happens exclusively
        # inside the cache-miss computation below.
        try:
            state = self.services._repo_cache_state(root)
        except Exception:
            state = self.services.repo_state.fingerprint(root)
        try:
            context_revision = self.preprocessor.context_revision(root)
        except Exception:
            context_revision = "cold"
        execution_hint = self.model_policy.profile(
            model, role=role, input_tokens=max(1, (len(task) + len(seed_context)) // 4), output_tokens=int(max_tokens)
        ).cache_scope()
        cache_key = stable_hash({
            "app_version": __version__, "model": model, "role": role, "profile": profile.name if profile else "", "task": task,
            "root": root, "workspace": workspace, "state": state.get("fingerprint"),
            "context_revision": context_revision, "seed": stable_hash(seed_context),
            "max_tokens": int(max_tokens), "execution": execution_hint,
        })
        wrapped_key = stable_hash({"tool-agent": cache_key})

        def compute() -> dict[str, Any]:
            self.runs += 1
            started = time.perf_counter()
            pre = self.preprocessor.compact_context(root, task, self.pre_context_chars)
            prepared_bootstrap: dict[str, Any] = copy.deepcopy(bootstrap) if isinstance(bootstrap, dict) else {}
            if self.bootstrap_deterministic_tools and not prepared_bootstrap:
                try:
                    det = self.services.deterministic_query(root, task, 16) if hasattr(self.services, "deterministic_query") else self.deterministic.query(root, task, 16)
                    if isinstance(det, dict):
                        det = copy.deepcopy(det)
                        if isinstance(det.get("evidence"), list):
                            det["evidence"] = [{k: v for k, v in x.items() if k != "text"} for x in det["evidence"][:8]]
                        for key in ("facts", "dependencies", "scripts", "test_candidates"):
                            if isinstance(det.get(key), list):
                                det[key] = det[key][:12]
                        prepared_bootstrap["deterministic"] = det
                except Exception:
                    pass
                try:
                    graph = self.services.code_query(root, task, 12) if hasattr(self.services, "code_query") else self.code_index.query(root, task, 12)
                    if isinstance(graph, dict):
                        prepared_bootstrap["code_index"] = graph
                except Exception:
                    pass
                if self.external_tools is not None:
                    task_low = task.lower()
                    relation_terms = ("caller", "callee", "calls ", "call path", "reference", "inherit", "impact", "dependency graph", "dead code", "complexity")
                    semantic_terms = ("symbol", "definition", "implementation", "reference", "rename", "class ", "method ", "function ")
                    try:
                        if any(term in task_low for term in relation_terms):
                            ext = self.external_tools.query(root, task, backend="codegraph", action="relationships", limit=12)
                            if ext.get("success"):
                                prepared_bootstrap["codegraph"] = ext
                        if any(term in task_low for term in semantic_terms):
                            ext = self.external_tools.query(root, task, backend="serena", action="find_symbol", limit=12)
                            if ext.get("success"):
                                prepared_bootstrap["serena"] = ext
                    except Exception:
                        pass
            if prepared_bootstrap:
                self.tool_calls += len(prepared_bootstrap)

            context_parts = []
            if pre:
                context_parts.append(f"PREPROCESSED CACHE:\n{pre}")
            if prepared_bootstrap:
                context_parts.append("PRECOMPUTED INTELLIGENCE:\n" + self._trim(prepared_bootstrap))
            if seed_context:
                context_parts.append(f"SEED EVIDENCE:\n{seed_context}")
            package = build_prompt(
                operation=role,
                model=model,
                profile=str(getattr(self.services, "config", {}).get("_hardware", {}).get("profile", "auto")),
                task=task,
                context="\n\n".join(context_parts),
            )
            system = (
                self.profile_catalog.system_contract(profile, task, prompt=package.system) if profile else package.system
            ) + system_suffix
            user = package.user

            # High-confidence deterministic evidence usually needs synthesis, not a
            # multi-turn tool-selection loop. Avoid sending all tool schemas in that
            # common warm path; fall back to the tool loop for uncertain work.
            det_boot = prepared_bootstrap.get("deterministic", {}) if isinstance(prepared_bootstrap, dict) else {}
            direct_threshold = float(self.config.get("local_tools", {}).get("direct_synthesis_confidence", 0.90))
            direct = bool(det_boot.get("direct_answer") and float(det_boot.get("confidence", 0.0) or 0.0) >= direct_threshold)
            messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            tools = [] if direct else self._tools_for_profile(profile) if profile else self._tools_for_role(role)
            call_count = 0
            max_steps = profile.max_steps if profile else self.max_steps
            max_calls = profile.max_tool_calls if profile else self.max_calls
            temperature = profile.temperature if profile else 0.2

            for step in range(1 if direct else max_steps):
                payload: dict[str, Any] = {
                    "model": model, "messages": messages, "stream": False,
                    "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
                    "options": {"num_predict": int(max_tokens), "temperature": temperature},
                }
                if tools:
                    payload["tools"] = tools
                request_payload, _profile = self.model_policy.apply_payload(
                    model, payload, role=role,
                    input_tokens=max(1, len(json_dumps(messages, ensure_ascii=False, default=str)) // 4),
                    output_tokens=int(max_tokens), preserve_explicit_think=False,
                )
                trace_observer = observer()
                if trace_observer is not None:
                    trace_observer.model_request(request_payload)
                    response = self.services.runtime.request_stream(
                        "/api/chat", request_payload, trace_observer.output_delta,
                        on_thinking=getattr(trace_observer, "thinking_delta", None),
                    )
                else:
                    response = self.services.runtime.request("/api/chat", request_payload)
                if "error" in response or response.get("_lah_repetition_loop_detected"):
                    self.failures += 1
                    error = str(response.get("error") or "model output repetition loop detected")
                    loop_detected = bool(response.get("_lah_repetition_loop_detected"))
                    return {
                        "success": False,
                        "unsupported": "tool" in error.lower(),
                        "error": error,
                        "model": model,
                        "terminal": loop_detected,
                        "retryable": not loop_detected,
                        "repetition_loop_detected": loop_detected,
                        "_lah_repetition_loop_detected": loop_detected,
                    }
                message = response.get("message", {}) if isinstance(response.get("message"), dict) else {}
                calls = message.get("tool_calls", []) if isinstance(message, dict) else []
                if direct or not isinstance(calls, list) or not calls:
                    content = str(message.get("content", "")).strip()
                    return {
                        "success": True, "model": model, "text": content, "structured": self._parse_structured(content, role),
                        "tool_agent": {"role": role, "steps": step + 1, "tool_calls": call_count, "workspace": workspace, "direct_synthesis": direct, "preprocessed": bool(pre), "bootstrap_sources": sorted(prepared_bootstrap)},
                        "total_duration_ns": response.get("total_duration", 0), "load_duration_ns": response.get("load_duration", 0),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                messages.append(message)
                for call in calls:
                    call_id = str(call.get("id") or call.get("tool_call_id") or "")
                    if call_count >= max_calls:
                        messages.append({"role": "tool", "tool_name": "limit", "tool_call_id": call_id, "content": "tool call budget exhausted; finish from current evidence"})
                        continue
                    fn = call.get("function", {}) if isinstance(call, dict) else {}
                    name = str(fn.get("name", ""))
                    args = self._arguments(call)
                    if trace_observer is not None:
                        trace_observer.tool_call({"name": name, "arguments": args, "call_id": call_id, "step": step})
                    try:
                        result = self._execute_tool(name, args, root, tenant, workspace)
                    except Exception as exc:
                        result = {"success": False, "error": str(exc)}
                    if trace_observer is not None:
                        trace_observer.tool_result({"name": name, "result": result, "call_id": call_id, "step": step})
                    call_count += 1
                    self.tool_calls += 1
                    messages.append({"role": "tool", "tool_name": name or "unknown", "tool_call_id": call_id, "content": self._trim(result)})

            final_messages = messages + [{"role": "user", "content": "Tool budget ended. Finish now using only collected evidence."}]
            request_payload, _profile = self.model_policy.apply_payload(
                model,
                {"model": model, "messages": final_messages, "stream": False, "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"), "options": {"num_predict": int(max_tokens), "temperature": temperature}},
                role=role, input_tokens=max(1, len(json_dumps(final_messages, ensure_ascii=False, default=str)) // 4), output_tokens=int(max_tokens), preserve_explicit_think=False,
            )
            trace_observer = observer()
            if trace_observer is not None:
                trace_observer.model_request(request_payload)
                response = self.services.runtime.request_stream(
                    "/api/chat", request_payload, trace_observer.output_delta,
                    on_thinking=getattr(trace_observer, "thinking_delta", None),
                )
            else:
                response = self.services.runtime.request("/api/chat", request_payload)
            if "error" in response:
                return {"success": False, "error": response["error"], "model": model}
            content = str(response.get("message", {}).get("content", "")).strip()
            return {
                "success": True, "model": model, "text": content, "structured": self._parse_structured(content, role),
                "tool_agent": {"role": role, "steps": max_steps + 1, "tool_calls": call_count, "workspace": workspace, "bounded": True, "preprocessed": bool(pre), "bootstrap_sources": sorted(prepared_bootstrap)},
                "total_duration_ns": response.get("total_duration", 0), "load_duration_ns": response.get("load_duration", 0),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }

        def scheduled_compute() -> dict[str, Any]:
            try:
                return self.services.scheduler.submit(
                    model, tenant, f"tool-agent:{role}", compute, priority=priority,
                    wait_timeout=float(self.config.get("resilience", {}).get("scheduler_wait_timeout_seconds", 330)),
                )
            except Exception as exc:
                return {"success": False, "error": str(exc), "model": model}

        raw, hit, coalesced = self.services.generation_cache.get_or_compute(wrapped_key, scheduled_compute)
        result = copy.deepcopy(raw) if isinstance(raw, dict) else {"success": False, "error": "invalid cached local-agent result"}
        if hit:
            self.cache_hits += 1
        result["tool_agent_cache"] = {"hit": bool(hit), "coalesced": bool(coalesced), "revision": context_revision}
        return result

    def run_profile(
        self,
        profile_name: str,
        task: str,
        root: str,
        tenant: str,
        *,
        workspace: str | None = None,
        seed_context: str = "",
        priority: int = 5,
    ) -> dict[str, Any]:
        if not self.profile_catalog.enabled:
            return {"success": False, "unsupported": True, "error": "Ollama subagent profiles disabled"}
        try:
            available = set(str(x) for x in self.services.runtime.installed_models())
        except Exception:
            available = None
        try:
            profile = self.profile_catalog.resolve(profile_name, available_models=available)
        except ValueError as exc:
            return {"success": False, "unsupported": True, "error": str(exc)}
        if available and profile.model not in available:
            return {
                "success": False,
                "unsupported": True,
                "error": f"profile model unavailable: {profile.model}",
                "profile": profile.name,
                "model": profile.model,
                "declared_model": profile.declared_model,
                "model_fallback": profile.model_fallback,
                "model_fallback_reason": profile.model_fallback_reason,
            }
        result = self.run(
            profile.model,
            profile.role,
            task,
            root,
            tenant,
            profile.max_tokens,
            priority,
            workspace=workspace,
            seed_context=seed_context,
            profile=profile,
        )
        result.update({
            "profile": profile.name,
            "language": self.profile_catalog.detect_language(task),
            "advisory_only": profile.advisory_only,
            "declared_model": profile.declared_model,
            "resolved_model": profile.model,
            "model_fallback": profile.model_fallback,
            "model_fallback_reason": profile.model_fallback_reason,
            "tools_used": list(profile.tools),
        })
        return result

    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "runs": self.runs, "cache_hits": self.cache_hits,
            "tool_calls": self.tool_calls, "failures": self.failures, "semantic_bypasses": self.semantic_bypasses,
            "max_steps": self.max_steps, "max_tool_calls": self.max_calls,
            "tool_schemas": {role: len(self._tools_for_role(role)) for role in ("explorer", "worker", "critic")},
            "bootstrap_deterministic_tools": self.bootstrap_deterministic_tools,
            "auto_register_project": self.auto_register_project, "external_code_intelligence": bool(self.external_tools),
        }
