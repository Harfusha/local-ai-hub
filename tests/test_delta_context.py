from __future__ import annotations

from local_ai_hub.agent_context import ContextElement, CompiledContext
from local_ai_hub.projection import AgentProjector


def test_context_element_compact():
    el = ContextElement(
        element_id="el_1",
        source_kind="active_lease",
        content="Active lease on src/main.py",
        estimated_tokens=25,
        reason="file lock",
        confidence=0.9,
        freshness=1234567.8,
    )
    # Full to_dict
    full_dict = el.to_dict(compact=False)
    assert "confidence" in full_dict
    assert "freshness" in full_dict
    assert "estimated_tokens" in full_dict

    # Compact to_dict
    compact_dict = el.to_dict(compact=True)
    assert "confidence" not in compact_dict
    assert "freshness" not in compact_dict
    assert "estimated_tokens" not in compact_dict
    assert compact_dict["element_id"] == "el_1"
    assert compact_dict["content"] == "Active lease on src/main.py"
    assert compact_dict["reason"] == "file lock"


def test_compiled_context_etag_stability():
    el1 = ContextElement("id1", "kind1", "content 1", 10, "r1")
    el2 = ContextElement("id2", "kind2", "content 2", 20, "r2")
    ctx1 = CompiledContext([el1, el2], 30, 4000)
    ctx2 = CompiledContext([el1, el2], 30, 4000)

    # Same elements yield exact same etag
    assert ctx1.etag() == ctx2.etag()
    assert len(ctx1.etag()) == 12

    # Different content yields different etag
    el3 = ContextElement("id2", "kind2", "content different", 20, "r2")
    ctx3 = CompiledContext([el1, el3], 30, 4000)
    assert ctx1.etag() != ctx3.etag()


def test_context_projection_compacts_elements():
    projector = AgentProjector()
    raw = {
        "success": True,
        "context": {
            "elements": [
                {
                    "element_id": "e1",
                    "source_kind": "memory",
                    "content": "some text",
                    "confidence": 1.0,
                    "freshness": 5000.0,
                    "estimated_tokens": 15,
                }
            ],
            "value_density": 0.85,
            "packed_ratio": 0.5,
        }
    }
    projected = projector.project(raw, agent="agent", task_kind="context")
    elements = projected["context"]["elements"]
    assert len(elements) == 1
    # Metadata fields stripped by projector
    assert "confidence" not in elements[0]
    assert "freshness" not in elements[0]
    assert "value_density" not in projected["context"]
