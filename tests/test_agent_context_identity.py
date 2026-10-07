from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from local_ai_hub import agent_context
from local_ai_hub.agent_context import CompiledContext, ContextElement


GOLDEN_IDS = {
    "unicode": "10c3dfaf54e2",
    "nested": "f0d34fa4ec15",
    "map": "037874f080a9",
    "unicode_request": "9c8811665fe8",
}


def _context(provenance: dict) -> CompiledContext:
    element = ContextElement(
        element_id="id:雪",
        source_kind="preload",
        content="Résumé — 雪",
        estimated_tokens=19,
        reason="nested identity ✓",
        confidence=0.75,
        freshness=12.5,
        provenance=provenance,
    )
    return CompiledContext(
        elements=[element],
        estimated_tokens=19,
        token_budget=100,
        phase="review",
        repo_revision="rev-雪",
    )


def _legacy_etag(context: CompiledContext) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(context.phase.encode("utf-8"))
    digest.update(context.repo_revision.encode("utf-8"))
    digest.update(getattr(context, "request_identity_digest", "").encode("ascii", errors="ignore"))
    for element in context.elements:
        element_data = element.to_dict(compact=False)
        element_data.pop("freshness", None)
        serialized = json.dumps(
            element_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest.update(serialized.encode("utf-8", errors="replace"))
    return digest.hexdigest()[:12]


def test_context_identity_has_golden_id_for_unicode() -> None:
    context = _context({"origin": "café-雪", "symbol": "🙂"})

    assert [item.element_id for item in context.elements] == ["id:雪"]
    assert context.etag() == _legacy_etag(context) == GOLDEN_IDS["unicode"]


def test_context_identity_has_golden_id_for_nested_values() -> None:
    context = _context({
        "origin": "café",
        "payload": {
            "items": [{"label": "x", "rank": 2}, {"rank": 1, "label": "雪"}],
            "enabled": True,
        },
    })

    assert [item.element_id for item in context.elements] == ["id:雪"]
    assert context.etag() == _legacy_etag(context) == GOLDEN_IDS["nested"]


def test_context_identity_golden_is_independent_of_nested_map_order() -> None:
    first = _context({
        "source": "unit",
        "details": {"right": 2, "left": 1, "deep": {"z": "雪", "a": "é"}},
    })
    reordered = _context({
        "details": {"deep": {"a": "é", "z": "雪"}, "left": 1, "right": 2},
        "source": "unit",
    })

    assert [item.element_id for item in first.elements] == ["id:雪"]
    assert [item.element_id for item in reordered.elements] == ["id:雪"]
    assert first.etag() == _legacy_etag(first) == reordered.etag() == _legacy_etag(reordered) == GOLDEN_IDS["map"]

def test_context_identity_keeps_request_digest_in_legacy_prefix() -> None:
    context = _context({"origin": "café-雪", "symbol": "🙂"})
    object.__setattr__(context, "request_identity_digest", "req-雪")

    assert context.etag() == _legacy_etag(context) == GOLDEN_IDS["unicode_request"]


def test_context_identity_streams_full_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context({"origin": "café-雪", "symbol": "🙂"})
    context = replace(
        context,
        elements=[replace(context.elements[0], content="x" * 1024)],
    )
    original_to_dict = ContextElement.to_dict
    calls = 0

    def track_full_dict(element: ContextElement, compact: bool = False):
        nonlocal calls
        assert compact is False
        calls += 1
        return original_to_dict(element, compact=compact)

    def reject_dumps(*args, **kwargs):
        pytest.fail("etag must stream JSONEncoder chunks instead of materializing json.dumps output")

    monkeypatch.setattr(ContextElement, "to_dict", track_full_dict)
    monkeypatch.setattr(agent_context.json, "dumps", reject_dumps)

    assert len(context.etag()) == 12
    assert calls == 1
