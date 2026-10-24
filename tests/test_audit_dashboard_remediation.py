from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def dashboard_server(tmp_path, monkeypatch):
    from local_ai_hub.app import LocalAIApp
    import local_ai_hub.http_server as module
    config = tmp_path / "config.toml"
    config.write_text('[server]\nstate_dir=' + json.dumps(str(tmp_path / "state")) +
        '\n[security]\napi_token="audit-dashboard-test-token"\napi_token_permissions=["read","write"]\nallowed_roots=[' + json.dumps(str(tmp_path)) +
        ']\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    app = LocalAIApp(str(config))
    monkeypatch.setattr(module, "APP", app)
    server = module.LocalAIHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", config
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    app.close()


@pytest.mark.parametrize("value", [0, 1, [], {}])
def test_dashboard_boolean_settings_reject_non_booleans(dashboard_server, value):
    endpoint, config = dashboard_server
    request = urllib.request.Request(endpoint + "/api/config/update", method="POST",
        data=json.dumps({"settings": {"debug_traces.enabled": value}}).encode(),
        headers={"Content-Type": "application/json", "X-LocalAI-Token": "audit-dashboard-test-token"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (OSError, __import__("http.client").client.HTTPException):
        status = 0
    assert status == 400
    assert not config.with_name("config.runtime.toml").exists()


def test_dashboard_memory_options_match_the_canonical_enums():
    from local_ai_hub.agent_identity import AgentScope
    from local_ai_hub.agent_memory import MemoryKind
    from local_ai_hub.dashboard import DASHBOARD_HTML
    class Options(HTMLParser):
        current = ""
        values = {}
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "select":
                self.current = attributes.get("id", "")
                self.values[self.current] = set()
            if tag == "option" and self.current:
                self.values[self.current].add(attributes.get("value", ""))
        def handle_endtag(self, tag):
            if tag == "select":
                self.current = ""
    parser = Options()
    parser.feed(DASHBOARD_HTML)
    assert parser.values["agentOsMemScope"] == {"", *(scope.value for scope in AgentScope)}
    assert parser.values["agentOsMemKind"] == {"", *(kind.value for kind in MemoryKind)}


def test_dashboard_distinguishes_missing_empty_loaded_and_stale_inventory():
    from local_ai_hub.dashboard import DASHBOARD_HTML
    match = re.search(r"// BEGIN resident inventory contract\n(.*?)// END resident inventory contract", DASHBOARD_HTML, re.S)
    assert match, "resident inventory must have an explicit missing/empty/stale contract"
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; browser behavior still requires candidate verification")
    script = match[1] + '''
const values=[{}, {loaded_models:[]}, {loaded_models:['test']},
{loaded_model_details:[{name:'test',context_length:8192}]},
{loaded_models:[],snapshot_stale:true}].map(residentInventoryState);
process.stdout.write(JSON.stringify(values));
'''
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=10, check=True)
    states = json.loads(result.stdout)
    assert [item["state"] for item in states] == ["unknown", "none", "loaded", "loaded", "stale"]


def test_dashboard_discloses_metadata_only_raster_indexing():
    from local_ai_hub.dashboard import DASHBOARD_HTML
    assert 'id="diagramIndexingNotice"' in DASHBOARD_HTML
    assert "Raster diagrams are indexed as metadata only" in DASHBOARD_HTML


def test_diagram_metadata_notice_opens_opt_in_vision_dialog_without_side_effects():
    from local_ai_hub.dashboard import DASHBOARD_HTML

    assert 'id="diagramVisionReviewOpen"' in DASHBOARD_HTML
    assert 'id="visionReviewTitle"' in DASHBOARD_HTML
    assert 'id="diagramVisionReviewNotice"' in DASHBOARD_HTML
    assert re.search(
        r"if\(\$\('diagramVisionReviewOpen'\)\)[^\n]*openDiagramVisionReview",
        DASHBOARD_HTML,
    )
    assert "function openDiagramVisionReview()" in DASHBOARD_HTML
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; browser behavior still requires candidate verification")

    start = DASHBOARD_HTML.index("function setFrontendVisionCaptureState")
    end = DASHBOARD_HTML.index("function captureFrontendVisionTab", start)
    modal_logic = DASHBOARD_HTML[start:end]
    binding = re.search(
        r"if\(\$\('diagramVisionReviewOpen'\)\)[^\n]*",
        DASHBOARD_HTML,
    )[0]
    harness = r"""
let sideEffects=0;
const makeElement=()=>({value:'',textContent:'',innerHTML:'',className:'',style:{},dataset:{},
  attrs:{},setAttribute(k,v){this.attrs[k]=v},getAttribute(k){return this.attrs[k]||null},
  classList:{values:new Set(),add(v){this.values.add(v)},remove(v){this.values.delete(v)},contains(v){return this.values.has(v)}}});
const ids=['visionReviewModal','visionPrompt','visionFindingId','visionScreenshot','visionReviewResult',
  'visionReviewStatus','visionCaptureError','visionCaptureState','visionReviewTitle',
  'diagramVisionReviewNotice','visionReviewClose','diagramVisionReviewOpen'];
const els=Object.fromEntries(ids.map(id=>[id,makeElement()]));
const $=id=>els[id]||null;
const window={frontendVisionCapture:{old:true},addEventListener(){sideEffects++},
  postMessage(){sideEffects++},dispatchEvent(){sideEffects++}};
const apiFetch=()=>{sideEffects++;throw new Error('unexpected fetch')};
const post=()=>{sideEffects++;throw new Error('unexpected POST')};
const captureFrontendVisionTab=()=>{sideEffects++;throw new Error('unexpected capture')};
"""
    script = harness + modal_logic + binding + r"""
els.diagramVisionReviewOpen.onclick();
const opened={
  isOpen:els.visionReviewModal.classList.contains('open'),
  title:els.visionReviewTitle.textContent,
  ariaLabel:els.visionReviewModal.getAttribute('aria-label'),
  prompt:els.visionPrompt.value,
  notice:els.diagramVisionReviewNotice.textContent,
  sideEffects,
  capture:window.frontendVisionCapture
};
closeFrontendVisionReviewModal();
openFrontendVisionReviewModal();
const normal={
  isOpen:els.visionReviewModal.classList.contains('open'),
  title:els.visionReviewTitle.textContent,
  ariaLabel:els.visionReviewModal.getAttribute('aria-label'),
  prompt:els.visionPrompt.value,
  notice:els.diagramVisionReviewNotice.textContent,
  sideEffects
};
process.stdout.write(JSON.stringify({opened,normal}));
"""
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=10, check=True)
    observed = json.loads(result.stdout)
    opened = observed["opened"]
    assert opened["isOpen"] is True
    assert "diagram" in opened["title"].lower()
    assert "diagram" in opened["ariaLabel"].lower()
    assert "diagram" in opened["prompt"].lower()
    assert re.search(r"installed model", opened["notice"], re.I)
    assert re.search(r"download", opened["notice"], re.I)
    assert re.search(r"index", opened["notice"], re.I)
    assert opened["sideEffects"] == 0
    assert opened["capture"] == {}

    normal = observed["normal"]
    assert normal == {
        "isOpen": True,
        "title": "Frontend vision review",
        "ariaLabel": "Frontend vision review",
        "prompt": "",
        "notice": "",
        "sideEffects": 0,
    }


def test_resident_inventory_refresh_uses_its_own_last_render_snapshot():
    from local_ai_hub.dashboard_contracts import RESIDENT_INVENTORY_JS
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    script = '''const document={visibilityState:'visible',getElementById:()=>null};
let renders=0;
const apiFetch=async()=>({ok:true,json:async()=>({success:true,loaded_models:['fixture']})});
function render(s){renders++;residentInventoryFor(s);}
''' + RESIDENT_INVENTORY_JS + '''
residentInventoryFor({});
loadResidentInventory().then(()=>process.stdout.write(JSON.stringify({renders,state:residentInventoryFor({}).state})));
'''
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout) == {"renders": 1, "state": "loaded"}


def test_dashboard_trace_polling_requires_a_relevant_visible_panel():
    from local_ai_hub.dashboard import DASHBOARD_HTML
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    source = DASHBOARD_HTML[DASHBOARD_HTML.index("function tracePollingNeeded"):DASHBOARD_HTML.index("async function probeHealth")]
    harness = """
let active='overview',requests=0,renders=0,tracesPollInFlight=false;
let tracesPollAbortController=null,lastTraces=[],refresh;
const document={visibilityState:'visible',querySelector:()=>({id:active})};
const $=id=>id==='traceRefresh'?{addEventListener:(_event,cb)=>{refresh=cb}}:null;
const apiFetch=async()=>{requests++;return {json:async()=>({success:true,items:[{trace_id:'real-fixture'}]})}};
const renderTraceList=()=>{renders++};
"""
    script = harness + source + """
(async()=>{
  await pollTraces();
  active='performance';await pollTraces();
  active='work';await pollTraces();
  document.visibilityState='hidden';await pollTraces();
  document.visibilityState='visible';await refresh({type:'click'});
  process.stdout.write(JSON.stringify({requests,renders,inFlight:tracesPollInFlight}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, timeout=10, check=True)
    assert json.loads(result.stdout) == {"requests": 2, "renders": 1, "inFlight": False}


def test_workspace_inventory_exposes_verification_limits_and_review_only_action():
    from local_ai_hub.dashboard import DASHBOARD_HTML
    assert 'id="ragWorkspaceStateFilter"' in DASHBOARD_HTML
    assert 'id="ragWorkspaceReviewBtn"' in DASHBOARD_HTML
    assert "Root availability has not been verified" in DASHBOARD_HTML
    assert "This review only lists indexes" in DASHBOARD_HTML
    assert "keep a recoverable copy" in DASHBOARD_HTML
