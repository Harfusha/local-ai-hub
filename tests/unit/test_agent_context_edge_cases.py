from __future__ import annotations

import math
from typing import Any

import pytest

from local_ai_hub.agent_context import (
    CompiledContext,
    ContextCompiler,
    ContextElement,
    ContextRequest,
    KnowledgeLink,
    _estimate_tokens,
)


def test_context_element_post_init_validation() -> None:
    # Empty / null-byte element_id gets generated fallback
    el = ContextElement(
        element_id="  \x00  ",
        source_kind=" \x00test_kind ",
        content="hello\x00world",
        estimated_tokens=-5,
        reason="some \x00reason",
        confidence=float("nan"),
        freshness=-100.0,
        provenance=None,  # type: ignore
    )
    assert el.element_id.startswith("el_")
    assert el.source_kind == "test_kind"
    assert el.content == "helloworld"
    assert el.estimated_tokens >= 1
    assert el.reason == "some reason"
    assert el.confidence == 1.0  # NaN replaced with 1.0
    assert el.freshness == 0.0  # negative clamped to 0.0
    assert el.provenance == {}  # None replaced with empty dict


def test_context_element_confidence_clamping() -> None:
    el_high = ContextElement(
        element_id="el-1",
        source_kind="fact",
        content="content",
        estimated_tokens=5,
        reason="reason",
        confidence=2.5,
    )
    assert el_high.confidence == 1.0

    el_low = ContextElement(
        element_id="el-2",
        source_kind="fact",
        content="content",
        estimated_tokens=5,
        reason="reason",
        confidence=-0.5,
    )
    assert el_low.confidence == 0.0


def test_context_request_budget_validation() -> None:
    req = ContextRequest(task_id="task-\x001", token_budget=-10)
    assert req.task_id == "task-1"
    assert req.token_budget == 4000

    req_nan = ContextRequest(task_id="task-2", token_budget=float("nan"))  # type: ignore
    assert req_nan.token_budget == 4000


def test_compiled_context_inspection_helpers() -> None:
    el1 = ContextElement(
        element_id="el-1",
        source_kind="fact",
        content="content 1",
        estimated_tokens=5,
        reason="r1",
    )
    el2 = ContextElement(
        element_id="el-2",
        source_kind="receipt",
        content="content 2",
        estimated_tokens=10,
        reason="r2",
    )
    ctx = CompiledContext(
        elements=[el1, el2],
        estimated_tokens=15,
        token_budget=100,
        truncated=True,
        stale=False,
    )
    assert ctx.has_elements() is True
    assert ctx.element_count() == 2
    assert ctx.element_ids() == ("el-1", "el-2")
    assert ctx.element_kinds() == ("fact", "receipt")
    assert ctx.get_elements_by_kind("FACT") == [el1]
    assert ctx.get_elements_by_kind("receipt") == [el2]
    assert ctx.get_elements_by_kind("missing") == []
    assert ctx.is_truncated() is True
    assert ctx.is_stale() is False

    empty_ctx = CompiledContext(
        elements=[],
        estimated_tokens=0,
        token_budget=100,
    )
    assert empty_ctx.has_elements() is False
    assert empty_ctx.element_count() == 0
    assert empty_ctx.element_ids() == ()
    assert empty_ctx.element_kinds() == ()
    assert empty_ctx.get_elements_by_kind("fact") == []


def test_knowledge_link_post_init_sanitization() -> None:
    link = KnowledgeLink(
        link_id=" link-\x001 ",
        source_id=" \x00src ",
        target_id=" tgt\x00 ",
        relationship=" rel ",
        path=" path/\x00a.py ",
        revision=" rev-\x001 ",
        valid=1,  # type: ignore
        created_at=float("nan"),
    )
    assert link.link_id == "link-1"
    assert link.source_id == "src"
    assert link.target_id == "tgt"
    assert link.relationship == "rel"
    assert link.path == "path/a.py"
    assert link.revision == "rev-1"
    assert link.valid is True
    assert link.created_at == 0.0


def test_estimate_tokens_defensive() -> None:
    assert _estimate_tokens(None) >= 1  # type: ignore
    assert _estimate_tokens("   ") >= 1
    assert _estimate_tokens("word " * 10) >= 2
