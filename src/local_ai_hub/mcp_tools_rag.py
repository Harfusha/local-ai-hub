from __future__ import annotations

from typing import Any, Literal, TypeAlias

from local_ai_hub.operation_contracts import operation_actions

RagAction: TypeAlias = Literal.__getitem__(operation_actions("local_ai_rag"))

def local_ai_rag(
    action: RagAction,
    root: str = ".",
    workspace: str = "",
    query: str = "",
    top_k: int = 6,
    limit: int = 0,
    task: str = "",
    extra_fields: list[str] | None = None,
    max_response_tokens: int = 0,
    response_profile: str = "",
    reuse_key: str = "",
    content: str = "",
    title: str = "",
    metadata: dict[str, Any] | None = None,
    image_path: str = "",
    caption: str = "",
    name: str = "",
    text: str = "",
    path: str = "",
    file: str = "",
) -> dict[str, Any]:
    """Fallback semantic retrieval after deterministic and indexed repository evidence. Search defaults workspace to the explicit repository root. RAG index submits through the durable job queue on cold start or when measured latency exceeds its 30-second budget; use local_ai_task status/wait/result with its returned job_id. Optional reranking is enabled by default on every hardware profile and can be disabled with `features.local_reranking=false`; CUDA is preferred on NVIDIA, with CPU fallback. Document ingestion requires non-empty content; title and metadata are optional. Diagram ingestion requires image_path; caption and metadata are optional. Raster diagrams are indexed as metadata-only; SVG text nodes are indexed with their extraction provenance. Use when: cheaper indexed paths are insufficient. Skip when: deterministic or indexed evidence already answers the question."""
    from . import mcp_server as services_module
    if not services_module.FEATURES.rag:
        return {"success": False, "unsupported": True, "error": "RAG backend is disabled (features.rag=false in config.toml)"}
    valid_actions = tuple(services_module.RagAction.__args__)
    if not isinstance(action, str) or action not in valid_actions:
        action_label = action if isinstance(action, str) else f"<{type(action).__name__}>"
        return services_module._invalid_action("local_ai_rag", action_label, valid_actions, "Use RAG only when cheaper Local AI Hub evidence is insufficient.")
    if name and not workspace:
        workspace = name
    if limit > 0:
        top_k = limit
    if task and not query:
        query = task
    if action == "search" and not query and content:
        query = content
    if action == "search" and not query and text:
        query = text
    if (path or file) and not image_path and action == "ingest_diagram":
        image_path = path or file
    if (path or file) and not content and action == "ingest_document":
        doc_p = path or file
        from pathlib import Path as _P
        cand_p = _P(doc_p) if _P(doc_p).is_absolute() else (_P(root) / doc_p)
        if cand_p.is_file():
            try:
                content = cand_p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if action == "ingest_document" and not content and text:
        content = text
    if action in {"index", "search", "docset_index", "ingest_document", "ingest_diagram"}:
        explicit_root = str(root or "").strip()
        if not services_module.is_rooted_path(explicit_root):
            return {
                "success": False,
                "error": "RAG repository actions require an explicit absolute project root; do not use MCP process cwd",
            }
        root = services_module._client_root(explicit_root)
    else:
        root = services_module._client_root(root)
    effective_workspace = workspace.strip() or root
    if action in {"index", "search", "ingest_document", "ingest_diagram"} and (
        not workspace.strip() or services_module.is_rooted_path(workspace.strip())
    ):
        effective_workspace = services_module.canonical_workspace_id(root)
    if action == "index":
        return services_module._compact(services_module.CLIENT.post("/api/rag/index", {
            "root": root,
            "workspace": effective_workspace,
            "delivery": "auto",
            "latency_budget_ms": 30_000,
        }, timeout=services_module._timeout("long")))
    if action == "search":
        capability_status = getattr(services_module.FEATURES, "capability_status", None)
        capabilities = capability_status() if callable(capability_status) else {}
        reranking = capabilities.get("reranking", {}) if isinstance(capabilities, dict) else {}
        use_reranker = isinstance(reranking, dict) and reranking.get("available") is True
        return services_module._compact(services_module.CLIENT.post("/api/rag/search", {
            "root": root, "query": query, "workspace": effective_workspace,
            "top_k": max(1, min(top_k, 12)), "use_reranker": use_reranker,
        }))
    if action == "list":
        return services_module._compact(services_module.CLIENT.get("/api/rag/workspaces"))
    if action == "docset_index":
        return services_module._compact(services_module.CLIENT.post("/api/rag/docset/index", {
            "name": workspace or query or "default", "root": root,
        }, timeout=services_module._timeout("long")))
    if action == "docset_search":
        return services_module._compact(services_module.CLIENT.post("/api/rag/docset/search", {
            "name": workspace or "default", "query": query, "top_k": max(1, min(top_k, 12)),
        }))
    if action == "ingest_document":
        if not isinstance(content, str) or not content.strip():
            return services_module._compact({
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "content is required for ingest_document",
            }, "status")
        return services_module._compact(services_module.CLIENT.post("/api/rag/ingest_document", {
            "root": root, "workspace": effective_workspace,
            "content": content,
            "title": title,
            "metadata": metadata if isinstance(metadata, dict) else None,
        }, timeout=services_module._timeout("quick")), "status")
    if action == "ingest_diagram":
        if not isinstance(image_path, str) or not image_path.strip():
            return services_module._compact({
                "success": False,
                "terminal": True,
                "retryable": False,
                "error": "image_path is required for ingest_diagram",
            }, "status")
        return services_module._compact(services_module.CLIENT.post("/api/rag/ingest_diagram", {
            "root": root, "workspace": effective_workspace,
            "image_path": image_path,
            "caption": caption,
            "metadata": metadata if isinstance(metadata, dict) else None,
        }, timeout=services_module._timeout("quick")), "status")
    return services_module._invalid_action("local_ai_rag", action, tuple(services_module.RagAction.__args__), "Use RAG only when cheaper Local AI Hub evidence is insufficient.")
