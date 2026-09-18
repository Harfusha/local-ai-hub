from __future__ import annotations

from local_ai_hub.frontend_review import build_coder_context


def test_coder_context_keeps_findings_relevant_dom_and_artifact_refs() -> None:
    packet = build_coder_context(
        {
            "summary": "CTA hidden",
            "findings": [
                {
                    "finding_id": "f-1",
                    "element_ids": ["el-42"],
                    "severity": "high",
                    "category": "layout",
                    "observed": "display is none",
                    "hypothesized": "state gate hides CTA",
                    "uncertainty": ["hydration not captured"],
                    "evidence": ["display:none"],
                }
            ],
            "unknowns": ["hydration state"],
        },
        {
            "prompt": "Fix mobile checkout",
            "screenshot": {"artifact_id": "img-1", "mime_type": "image/png"},
            "dom": {
                "artifact_id": "dom-1",
                "html": "<main><button>Save</button></main>",
                "elements": [
                    {"element_id": "root", "ancestor_ids": []},
                    {"element_id": "parent", "ancestor_ids": ["root"]},
                    {"element_id": "el-42", "ancestor_ids": ["root", "parent"]},
                    {"element_id": "other", "ancestor_ids": ["root"]},
                ],
            },
            "accessibility": {"el-42": {"role": "button", "name": "Save"}},
            "computed_styles": {"el-42": {"display": "none"}},
            "runtime": {"errors": ["hydration mismatch"]},
            "viewport": {"width": 390, "height": 844},
        },
        repo_context={"files": ["src/Checkout.tsx"], "symbols": ["Checkout"]},
    )

    assert packet["success"] is True
    assert packet["artifact_refs"] == {
        "screenshot": "img-1",
        "dom": "dom-1",
    }
    assert packet["dom"]["html"].startswith("<main>")
    assert {item["element_id"] for item in packet["dom"]["elements"]} == {
        "root",
        "parent",
        "el-42",
    }
    assert packet["accessibility"]["el-42"]["role"] == "button"
    assert packet["computed_styles"]["el-42"]["display"] == "none"
    assert packet["runtime"]["errors"] == ["hydration mismatch"]
    assert packet["repo"]["files"] == ["src/Checkout.tsx"]


def test_coder_context_keeps_console_and_network_artifact_refs() -> None:
    packet = build_coder_context(
        {"findings": []},
        {
            "runtime": {
                "console_artifact_id": "console-1",
                "network_artifact_id": "network-1",
                "errors": ["hydration mismatch"],
            }
        },
    )

    assert packet["success"] is True
    assert packet["artifact_refs"]["runtime"] == {
        "console_artifact_id": "console-1",
        "network_artifact_id": "network-1",
    }


def test_coder_context_returns_terminal_result_for_truncated_dom() -> None:
    packet = build_coder_context(
        {"findings": []},
        {
            "dom": {
                "artifact_id": "dom-1",
                "html": "partial",
                "truncated": True,
                "original_chars": 20_000,
                "limit_chars": 12_000,
            }
        },
    )

    assert packet["success"] is False
    assert packet["terminal"] is True
    assert packet["error"]["code"] == "frontend_dom_context_truncated"
