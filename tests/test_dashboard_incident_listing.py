"""Dashboard incident listing executes the shipped request/scoping helpers."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.http_server import Handler, RequestBodyError
from local_ai_hub.process_utils import hidden_run_kwargs


def _incident_probe(steps: list[dict[str, str]]) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute dashboard incident requests")
    source = DASHBOARD_HTML
    # Execute the shipped request scoping, HTTP error handling and view loader.
    runtime = source[source.index("function scopeAgentOsRequest("):
                     source.index("function setFrontendVisionCaptureState(")]
    runtime += source[source.index("async function fetchDashboardJson("):
                      source.index("async function post(")]
    runtime += source[source.index("let agentOsTasks=[]"):
                      source.index("function switchAgentOsSubtab(")]
    script = r"""
const elements = {
  agentOsRoot:{value:''}, agentOsRepoSelect:{value:''},
  agentOsCreateTaskBtn:{}, agentOsRecordMemBtn:{},
  agentOsRecordIncBtn:{}, agentOsCleanup:{}
};
const $=id=>elements[id];
const requests=[],views=[];
let incidentError='';
const nativeFetch=async(path,options={})=>{
  const url=new URL(path,'http://127.0.0.1');
  const method=String(options.method||'GET').toUpperCase();
  const body=options.body?JSON.parse(options.body):null;
  requests.push({path:url.pathname,root:url.searchParams.get('root'),method,body});
  const root=url.searchParams.get('root')||'all';
  let data;
  if(url.pathname.endsWith('/tasks'))data={success:true,tasks:[]};
  else if(url.pathname.endsWith('/memory'))data={success:true,records:[]};
  else if(method!=='GET')data={success:false,error:'query is required'};
  else if(incidentError)data={success:false,error:incidentError};
  else data={success:true,incidents:root==='empty'?[]:[{incident_id:'incident-'+root}]};
  return {ok:data.success,status:data.success?200:400,json:async()=>data};
};
function renderAgentOsView(){
  views.push(JSON.parse(JSON.stringify({incidents:agentOsIncidents,errors:agentOsLoadErrors,
    createDisabled:elements.agentOsCreateTaskBtn.disabled})));
}
""" + runtime + "\nconst steps=" + json.dumps(steps) + r""";
(async()=>{
  for(const step of steps){
    elements.agentOsRoot.value=step.root||'';
    elements.agentOsRepoSelect.value=step.repo||'';
    incidentError=step.error||'';
    await loadAgentOsView();
  }
  console.log(JSON.stringify({requests,views}));
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        [node], input=script, text=True, encoding="utf-8", capture_output=True,
        check=True, timeout=20, **hidden_run_kwargs(),
    )
    return json.loads(result.stdout)


def test_incidents_switch_repository_custom_root_and_global_without_search_query():
    repo = "C:/repo with spaces/#one"
    custom = "C:/another/repository"
    result = _incident_probe([
        {"repo": repo},
        {"repo": repo, "root": custom},
        {},
    ])
    requests = [r for r in result["requests"] if r["path"].endswith("/incidents")]
    assert requests == [
        {"path": "/api/agent-state/incidents", "root": root, "method": "GET", "body": None}
        for root in (repo, custom, None)
    ]
    assert [view["incidents"] for view in result["views"]] == [
        [{"incident_id": "incident-" + root}] for root in (repo, custom, "all")
    ]
    assert all(view["errors"] == {} for view in result["views"])
    assert [view["createDisabled"] for view in result["views"]] == [False, False, True]


@pytest.mark.parametrize("all_value", ["", "all", "__all__"])
def test_incidents_all_repositories_does_not_add_a_root_or_post(all_value):
    result = _incident_probe([{"repo": all_value}])
    request = next(r for r in result["requests"] if r["path"].endswith("/incidents"))
    assert request == {
        "path": "/api/agent-state/incidents", "root": None, "method": "GET", "body": None,
    }
    assert result["views"][0]["errors"] == {}


def test_incident_loading_clears_stale_rows_for_empty_and_failed_repository():
    result = _incident_probe([
        {"root": "C:/populated"},
        {"root": "empty"},
        {"root": "C:/unavailable", "error": "Incident store unavailable"},
    ])
    assert result["views"][0]["incidents"]
    assert result["views"][1]["incidents"] == []
    assert result["views"][1]["errors"] == {}
    assert result["views"][2]["incidents"] == []
    assert result["views"][2]["errors"] == {"incidents": "Incident store unavailable"}


@pytest.mark.parametrize("query", [None, "", "   ", "\x00"])
def test_incident_search_still_requires_a_real_query(query):
    payload = {"action": "find", "root": "C:/repository", "limit": 100}
    if query is not None:
        payload["query"] = query
    with pytest.raises(RequestBodyError, match="query is required"):
        Handler._validate_payload("/api/agent-state/incidents", payload)


def test_incident_search_accepts_an_explicit_nonempty_query():
    Handler._validate_payload("/api/agent-state/incidents", {
        "action": "find", "root": "C:/repository", "query": "timeout", "limit": 100,
    })


def test_record_incident_form_sends_canonical_operation_class():
    node = shutil.which("node")
    assert node, "Node.js is required to execute the incident form"
    start = DASHBOARD_HTML.index("async function submitRecordIncident(")
    runtime = DASHBOARD_HTML[start:DASHBOARD_HTML.index("function openCleanupModal(", start)]
    script = r"""
const fields={newIncClass:{value:'indexing'},newIncMsg:{value:'Index unavailable'},
  newIncCause:{value:'Missing file'},newIncFix:{value:'Check the file first'},recordIncStatus:{}};
const $=id=>fields[id],esc=String;
let recorded;
async function post(path,payload){recorded={path,payload};return {success:true,incident:{}}}
async function loadAgentOsView(){}
function renderIncidentModal(){}
""" + runtime + r"""
(async()=>{await submitRecordIncident({preventDefault(){}});console.log(JSON.stringify(recorded))})()
.catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run([node], input=script, text=True, encoding="utf-8",
        capture_output=True, check=True, timeout=5, **hidden_run_kwargs())
    recorded = json.loads(result.stdout)
    assert recorded["path"] == "/api/agent-state/incidents"
    payload = recorded["payload"]
    assert payload == {"action": "record", "operation_class": "indexing",
        "message": "Index unavailable", "root_cause": "Missing file",
        "verified_fix": "Check the file first"}
    Handler._validate_payload(recorded["path"], dict(payload, root="C:/repository"))


@pytest.mark.parametrize(("status", "expected"), [
    ("unresolved", "UNRESOLVED"),
    ("resolved", "RESOLVED WITH FIX"),
    ("ignored", "IGNORED"),
])
def test_incident_detail_renders_saved_status_without_reference_errors(status, expected):
    node = shutil.which("node")
    assert node, "Node.js is required to execute the incident detail"
    start = DASHBOARD_HTML.index("function renderIncidentModal(")
    runtime = DASHBOARD_HTML[start:DASHBOARD_HTML.index("function openRecordIncidentModal(", start)]
    incident = {"incident_id": "inc_fixture", "operation_class": "indexing",
        "error_class": "CommandExecutionError", "status": status,
        "ignored": status == "ignored", "verified_fix": "Check the file first"}
    script = "const body={innerHTML:''},$=()=>body,esc=String,escJs=JSON.stringify;\n"
    script += runtime + "\nrenderIncidentModal(" + json.dumps(incident) + ");console.log(body.innerHTML);"
    result = subprocess.run([node], input=script, text=True, encoding="utf-8",
        capture_output=True, timeout=5, **hidden_run_kwargs())
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert "inc_fixture" in result.stdout
    assert "Check the file first" in result.stdout
