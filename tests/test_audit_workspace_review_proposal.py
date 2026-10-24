from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest


def _review_sources():
    from local_ai_hub.dashboard import DASHBOARD_HTML
    from local_ai_hub.dashboard_contracts import WORKSPACE_INVENTORY_JS

    handler = re.search(
        r"\$\('ragWorkspaceReviewBtn'\)\?\.addEventListener\('click',\(\)=>\{(.*?)\n\}\);",
        DASHBOARD_HTML,
        re.S,
    )
    assert handler, "workspace review button must keep an executable review action"
    identity = re.search(r"function ragWorkspaceIdentity\(workspace\)\{[^\n]*\}", DASHBOARD_HTML)
    assert identity, "workspace identity must remain sourced from the current inventory contract"
    proposal = re.search(
        r"// BEGIN workspace review proposal\n(.*?)// END workspace review proposal",
        DASHBOARD_HTML,
        re.S,
    )
    return DASHBOARD_HTML, WORKSPACE_INVENTORY_JS, identity.group(0), proposal.group(1) if proposal else "", handler.group(1)


def _run_review(rows):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; browser verification remains separate")
    _html, state_js, identity_js, proposal_js, handler_body = _review_sources()
    harness = r"""
let reviewHandler=null,sideEffects=0,unsafeWrites=0;
const els={ragWorkspaceReview:{open:false},ragWorkspaceReviewOutput:{textContent:''}};
Object.defineProperty(els.ragWorkspaceReviewOutput,'innerHTML',{set:()=>{unsafeWrites++}});
const $=id=>id==='ragWorkspaceReviewBtn'?{addEventListener:(_name,fn)=>{reviewHandler=fn}}:(els[id]||null);
const esc=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const humanLabel=value=>String(value||'unknown');
const n=value=>String(value);
const fetchDashboardJson=()=>{sideEffects++;throw new Error('review must be a local display only')};
const apiFetch=()=>{sideEffects++;throw new Error('review must not call APIs')};
const deleteWorkspace=()=>{sideEffects++;throw new Error('cleanup must never execute')};
"""
    setup = (
        "const ragWorkspaces=" + json.dumps(rows) + ";\n"
        + state_js
        + "\n"
        + identity_js
        + "\n"
        + proposal_js
        + "\nconst original=JSON.stringify(ragWorkspaces);\n"
        + "$('ragWorkspaceReviewBtn')?.addEventListener('click',()=>{"
        + handler_body
        + "\n});\nreviewHandler();\n"
        + "process.stdout.write(JSON.stringify({text:els.ragWorkspaceReviewOutput.textContent,open:els.ragWorkspaceReview.open,sideEffects,unsafeWrites,unchanged:original===JSON.stringify(ragWorkspaces)}));\n"
    )
    env = os.environ.copy()
    env["TZ"] = "UTC"
    result = subprocess.run([node, "-e", harness + setup], text=True, capture_output=True, timeout=10, check=True, env=env)
    return json.loads(result.stdout)


def test_review_proposal_uses_only_recorded_workspace_metadata_and_fails_closed():
    # This is the current APP.rag.list_workspaces() shape: named workspace plus
    # counts. It does not provide physical root, availability, last use, or a
    # verification timestamp, so none may be inferred from workspace identity.
    current_shape = [{"workspace": "docset:manual", "chunks": 12, "files": 3}]
    result = _run_review(current_shape)

    assert result["open"] is True
    assert "docset:manual" in result["text"]
    assert re.search(r"root\s*:?\s*(unknown|not provided|not supplied)", result["text"], re.I)
    assert re.search(r"availability\s*:?\s*(unknown|not verified)", result["text"], re.I)
    assert re.search(r"last use\s*:?\s*(unknown|not provided)", result["text"], re.I)
    assert re.search(r"last verification\s*:?\s*(unknown|not provided)", result["text"], re.I)
    assert re.search(r"no (automatic )?cleanup (candidate|proposed|action)", result["text"], re.I)
    assert result["sideEffects"] == 0
    assert result["unsafeWrites"] == 0
    assert result["unchanged"] is True


def test_only_missing_or_unverified_roots_offer_review_gated_cleanup_proposal():
    workspaces = [
        {"workspace": "docset:active", "root": "C:/work/active", "root_available": True,
         "last_verified_at": 1_735_787_045, "status": "ready", "chunks": 4, "files": 2},
        {"workspace": "docset:active-missing", "root": "C:/work/active-missing", "root_available": False,
         "status": "active", "chunks": 1, "files": 1},
        {"workspace": "docset:missing", "root": "C:/work/missing", "root_available": False,
         "last_verified_at": 1_735_787_045, "status": "indexed", "chunks": 2, "files": 1},
        {"workspace": "docset:unverified", "root": "C:/work/unverified", "status": "indexed", "chunks": 1, "files": 1},
        {"workspace": "docset:script-check", "root": "C:/work/<script>alert(1)</script>", "root_available": False,
         "status": "indexed", "chunks": 1, "files": 1},
    ]
    result = _run_review(workspaces)
    blocks = {block.splitlines()[0].lower(): block.lower() for block in result["text"].split("\n\n") if block.strip()}

    active = blocks["c:/work/active"]
    assert "availability: available" in active
    assert "last use: not provided" in active
    assert "last verification:" in active and "2025" in active
    assert re.search(r"\d{1,2}:\d{2}(:\d{2})?.*(utc|gmt)", active, re.I)
    assert "4 chunks" in active and "2 files" in active
    assert "no automatic cleanup candidate" in active

    active_missing = blocks["c:/work/active-missing"]
    assert "availability: missing" in active_missing
    assert "no automatic cleanup candidate" in active_missing

    for root in ("c:/work/missing", "c:/work/unverified"):
        block = blocks[root]
        assert "operator review only" in block
        assert "ownership check is required" in block
        assert "recoverable backup" in block and "restore identity" in block
        assert "explicit operator approval" in block
    assert "<script>alert(1)</script>" in result["text"]
    assert result["unsafeWrites"] == 0
    assert result["sideEffects"] == 0
    assert result["unchanged"] is True
