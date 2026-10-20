"""Canonical dashboard input choices and small browser presentation contracts."""
from __future__ import annotations

from html import escape
from typing import Any

from .agent_identity import AgentScope
from .agent_memory import MemoryKind


_FEATURES = ("status", "repo", "tasks", "rag", "commands", "coord", "artifacts",
             "code_intelligence", "preprocessing", "subagents", "agent_os", "dashboard", "work_orchestrator")
_BOOLEAN_SETTINGS = frozenset({"debug_traces.enabled", "preprocessing.enabled",
    "code_intelligence.enabled", "code_intelligence.serena_enabled", "monitoring.dashboard_enabled",
    *(f"features.{name}" for name in _FEATURES)})
_PROFILES = frozenset({"auto", "cpu", "integrated", "low", "balanced", "high", "max"})


def dashboard_settings_patch(requested: Any) -> dict[str, Any]:
    if not isinstance(requested, dict):
        raise ValueError("settings must be an object")
    patch: dict[str, Any] = {}
    for dotted, value in requested.items():
        if not isinstance(dotted, str):
            raise ValueError("setting names must be strings")
        if dotted == "hardware.profile":
            valid = type(value) is str and value in _PROFILES
        else:
            valid = dotted in _BOOLEAN_SETTINGS and type(value) is bool
        if not valid:
            raise ValueError(f"unsupported or invalid setting: {dotted[:120]}")
        table, name = dotted.split(".", 1)
        patch.setdefault(table, {})[name] = value
    return patch


def memory_scope_options() -> str:
    return '<option value="">All scopes</option>' + "".join(
        f'<option value="{escape(scope.value, quote=True)}">{escape(scope.value.title())}</option>'
        for scope in AgentScope
    )


def memory_kind_options() -> str:
    return '<option value="">All kinds</option>' + "".join(
        f'<option value="{escape(kind.value, quote=True)}">{escape(kind.value.replace("_", " ").title())}</option>'
        for kind in MemoryKind
    )


RESIDENT_INVENTORY_JS = r"""// BEGIN resident inventory contract
function residentInventoryState(s){
  if(s.snapshot_stale===true||s.loaded_model_inventory_stale===true)return {state:'stale',details:[],names:[]};
  if(s.loaded_models_available===false||s.model_inventory_available===false)return {state:'unknown',details:[],names:[]};
  const hasDetails=Object.prototype.hasOwnProperty.call(s,'loaded_model_details');
  const hasNames=Object.prototype.hasOwnProperty.call(s,'loaded_models');
  const details=hasDetails?s.loaded_model_details:[];
  const names=hasNames?s.loaded_models:[];
  if((hasDetails&&(!Array.isArray(details)||details.some(x=>!x||typeof x.name!=='string'||!x.name)))||
     (hasNames&&(!Array.isArray(names)||names.some(x=>typeof x!=='string'||!x))))return {state:'unknown',details:[],names:[]};
  if(details.length||names.length)return {state:'loaded',details,names:details.length?details.map(x=>x.name):names};
  return {state:hasDetails||hasNames?'none':'unknown',details:[],names:[]};
}
// END resident inventory contract

let residentInventorySnapshot=null,residentInventoryAt=0,residentInventoryInFlight=false,residentRenderSnapshot=null;
function residentInventoryFor(s){
  residentRenderSnapshot=s;
  const current=residentInventoryState(s);
  if(current.state==='loaded'||current.state==='none'){
    residentInventorySnapshot=s;residentInventoryAt=Date.now();return current;
  }
  if(current.state==='unknown'&&residentInventorySnapshot){
    return residentInventoryState({...residentInventorySnapshot,loaded_model_inventory_stale:Date.now()-residentInventoryAt>30000});
  }
  return current;
}
async function loadResidentInventory(){
  if(residentInventoryInFlight||document.visibilityState==='hidden')return;
  residentInventoryInFlight=true;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),5000);
  try{
    const response=await apiFetch('/api/status?scope=process',{cache:'no-store',signal:controller.signal});
    const data=await response.json();
    if(!response.ok||data.success===false)throw new Error('Resident inventory unavailable');
    const inventory=residentInventoryState(data);
    if(inventory.state==='unknown'||inventory.state==='stale')throw new Error('Resident inventory unverified');
    residentInventorySnapshot=data;residentInventoryAt=Date.now();
    if(residentRenderSnapshot)render(residentRenderSnapshot);
  }catch{
    residentInventorySnapshot=null;residentInventoryAt=0;
    if(residentRenderSnapshot)render(residentRenderSnapshot);
  }finally{clearTimeout(timer);residentInventoryInFlight=false;}
}
document.getElementById('residentInventoryRefresh')?.addEventListener('click',()=>loadResidentInventory());
"""


WORKSPACE_INVENTORY_JS = r"""
function workspaceInventoryState(workspace){
  const row=workspace&&typeof workspace==='object'?workspace:{};
  const root=typeof row.root==='string'?row.root:typeof row.repository_root==='string'?row.repository_root:'';
  const availability=typeof row.root_available==='boolean'?(row.root_available?'available':'missing'):root?'unverified':'unknown';
  const raw=row.last_verified_at??row.verified_at;
  const timestamp=typeof raw==='number'&&Number.isFinite(raw)&&raw>0?(raw<1e12?raw*1000:raw):null;
  return {root,availability,verifiedAt:timestamp,
    reason:availability==='missing'?'Root reported missing; ownership and recoverability still require review':
      availability==='available'?'Availability reported by the server':
      root?'Root availability has not been verified':'Root not supplied; root availability has not been verified'};
}
"""
