// @ts-nocheck
// ── Agent OS ──────────────────────────────────────────────────────────────────
let agentOsTasks=[], agentOsMemories=[], agentOsIncidents=[],agentOsLoadErrors={};
let agentOsTaskOffset=0,agentOsTaskTotal=null,agentOsActiveTasksTotal=null;
let agentOsTaskLoadGeneration=0,agentOsTaskPageLoading=false;
let agentOsHasMore=false,agentOsQueryTruncated=false,agentOsCountScope=null;
const agentOsTaskPageSize=100;
function setAgentOsScopeReady(ready){
  ['agentOsCreateTaskBtn','agentOsRecordMemBtn','agentOsCleanup'].forEach(id=>{if($(id))$(id).disabled=!ready});
}
async function loadAgentOsView({appendTasks=false}={}){
  if(appendTasks&&(agentOsTaskPageLoading||!agentOsHasMore||agentOsQueryTruncated))return;
  const loadGeneration=++agentOsTaskLoadGeneration;
  const repoVal=$('agentOsRepoSelect')?.value?.trim()||'';
  const rootVal=$('agentOsRoot')?.value?.trim()||'';
  const selectedRoot=rootVal||repoVal||'';
  const isAll=!selectedRoot||selectedRoot.toLowerCase()==='all'||selectedRoot==='__all__';
  setAgentOsScopeReady(!isAll&&Boolean(selectedRoot));
  if(!appendTasks){
    agentOsTaskOffset=0;
    agentOsTasks=[];
    agentOsTaskPageLoading=false;
    agentOsHasMore=false;
    agentOsQueryTruncated=false;
    agentOsCountScope=null;
  } else {
    agentOsTaskPageLoading=true;
  }
  if($('agentOsTasksMore'))$('agentOsTasksMore').disabled=true;
  const requestOffset=agentOsTaskOffset;
  const promises=[
    fetchDashboardJson(`/api/agent-state/tasks?limit=${agentOsTaskPageSize}&offset=${requestOffset}&include_stale=true`,{cache:'no-store',unscoped:isAll})
  ];
  if(!appendTasks){
    const rootQuery=selectedRoot?`?root=${encodeURIComponent(selectedRoot)}`:'';
    promises.push(fetchDashboardJson(`/api/agent-state/memory${rootQuery}`,{cache:'no-store',unscoped:isAll}));
    promises.push(isAll?Promise.resolve({incidents:[]}):fetchDashboardJson(
      `/api/agent-state/incidents?root=${encodeURIComponent(selectedRoot)}`,{cache:'no-store'}));
  }
  const results=await Promise.allSettled(promises);
  if(loadGeneration!==agentOsTaskLoadGeneration||($('agentOsRoot')?.value?.trim()||'')!==rootVal){
    if(loadGeneration===agentOsTaskLoadGeneration)agentOsTaskPageLoading=false;
    return;
  }

  agentOsLoadErrors={};
  if(results[0].status==='rejected'){
    agentOsLoadErrors.tasks=String(results[0].reason?.message||results[0].reason);
  }
  if(!appendTasks&&results[1]?.status==='rejected'){
    agentOsLoadErrors.memory=String(results[1].reason?.message||results[1].reason);
  }
  if(!appendTasks&&results[2]?.status==='rejected'){
    agentOsLoadErrors.incidents=String(results[2].reason?.message||results[2].reason);
  }

  if(results[0].status==='fulfilled'){
    const taskPage=results[0].value||{};
    const pageTasks=taskPage.tasks||[];
    agentOsTasks=appendTasks?[...agentOsTasks,...pageTasks]:pageTasks;
    agentOsTaskOffset=Number(taskPage.next_offset??(requestOffset+pageTasks.length));
    agentOsTaskTotal=Number.isSafeInteger(taskPage.total_count)&&taskPage.total_count>=0?taskPage.total_count:null;
    agentOsActiveTasksTotal=Number.isSafeInteger(taskPage.active_count)&&taskPage.active_count>=0?taskPage.active_count:null;
    agentOsHasMore=Boolean(taskPage.has_more??(agentOsTaskTotal!==null&&agentOsTaskOffset<agentOsTaskTotal));
    agentOsQueryTruncated=Boolean(taskPage.query_truncated);
    agentOsCountScope=taskPage.count_scope||null;
  }else if(!appendTasks){
    agentOsTaskTotal=null;
    agentOsActiveTasksTotal=null;
    agentOsHasMore=false;
    agentOsQueryTruncated=false;
    agentOsCountScope=null;
  }
  if(!appendTasks){
    agentOsMemories=results[1]?.status==='fulfilled'?(results[1].value.records||[]):[];
    agentOsIncidents=results[2]?.status==='fulfilled'?(results[2].value.incidents||[]):[];
  }
  agentOsTaskPageLoading=false;
  renderAgentOsView();
}
$('agentOsTasksMore')?.addEventListener('click',()=>loadAgentOsView({appendTasks:true}));

function switchAgentOsSubtab(tabKey){
  const subtabs=['tasks','memory','incidents','trajectories'];
  if(!subtabs.includes(tabKey))return;
  subtabs.forEach(t=>{
    const btn=$('subtab'+t.charAt(0).toUpperCase()+t.slice(1));
    const sec=$('agentOs'+t.charAt(0).toUpperCase()+t.slice(1)+'Sec');
    if(btn)btn.classList.toggle('active',t===tabKey);
    if(sec)sec.style.display=t===tabKey?'block':'none';
  });
  if(tabKey==='trajectories'){
    loadTrajectories();
  }
}
document.querySelectorAll('.subtab-btn[data-agentos-tab]').forEach(btn=>{
  btn.addEventListener('click',()=>switchAgentOsSubtab(btn.dataset.agentosTab));
});


function renderAgentOsView(){
  const query=String($('agentOsSearch')?.value||'').trim().toLowerCase();
  const statusFilter=String($('agentOsTaskStatus')?.value||'').trim().toLowerCase();
  const filteredTasks=agentOsTasks.filter(t=>{
    const st=String(t.status||'').toLowerCase();
    if(statusFilter&&st!==statusFilter)return false;
    if(!query)return true;
    const hay=[t.task_id,t.contract?.goal,t.checkpoint?.phase,t.checkpoint?.next_action,t.repo_root].join(' ').toLowerCase();
    return hay.includes(query);
  });

  const memQuery=String($('agentOsMemSearch')?.value||'').trim().toLowerCase();
  const memScope=String($('agentOsMemScope')?.value||'').trim().toLowerCase();
  const memKind=String($('agentOsMemKind')?.value||'').trim().toLowerCase();
  const filteredMem=agentOsMemories.filter(m=>{
    if(memScope&&String(m.scope||'').toLowerCase()!==memScope)return false;
    if(memKind&&String(m.kind||'').toLowerCase()!==memKind)return false;
    if(!memQuery)return true;
    const hay=[m.key,typeof m.value==='object'?JSON.stringify(m.value):String(m.value||''),m.source].join(' ').toLowerCase();
    return hay.includes(memQuery);
  });

  const incQuery=String($('agentOsIncSearch')?.value||'').trim().toLowerCase();
  const incFilter=String($('agentOsIncFilter')?.value||'').trim();
  const filteredInc=agentOsIncidents.filter(i=>{
    const incidentStatus=String(i.status||(i.verified_fix?'resolved':'unresolved'));
    if(incFilter!==''&&incidentStatus!==incFilter)return false;
    if(!incQuery)return true;
    const hay=[i.incident_id,i.error_class,i.redacted_message,i.root_cause,i.verified_fix,incidentStatus].join(' ').toLowerCase();
    return hay.includes(incQuery);
  });

  const taskTotalLabel=agentOsTaskTotal===null?'Task total unavailable':(agentOsCountScope==='repository'?`${agentOsTaskTotal} total tasks in this repository`:`${agentOsTaskTotal} total tasks`);
  const activeTaskLabel=agentOsActiveTasksTotal===null?'Active count unavailable':`${agentOsActiveTasksTotal} active`;
  const truncatedLabel=agentOsQueryTruncated?' · Task list incomplete':'';
  if($('agentOsSummary'))$('agentOsSummary').textContent=`${filteredTasks.length} shown · ${agentOsTasks.length} loaded · ${taskTotalLabel}${truncatedLabel} · ${filteredMem.length} memories · ${filteredInc.length} incidents`;
  if($('agentOsState')){
    $('agentOsState').textContent=`${activeTaskLabel} · ${taskTotalLabel} · ${agentOsMemories.length} memories`;
  }
  const more=$('agentOsTasksMore');
  if(more){
    more.hidden=Boolean(agentOsQueryTruncated||!agentOsHasMore||(agentOsTaskTotal!==null&&agentOsTaskOffset>=agentOsTaskTotal));
    more.disabled=more.hidden||agentOsTaskPageLoading;
    const remaining=agentOsTaskTotal!==null?Math.max(0,agentOsTaskTotal-agentOsTaskOffset):agentOsTaskPageSize;
    more.textContent=(!agentOsHasMore&&agentOsTaskTotal===null)?'Task pagination unavailable':agentOsTaskPageLoading?'Loading next tasks…':`Load next ${Math.min(agentOsTaskPageSize,remaining)} tasks`;
  }

  rows('agentOsTasksBody',filteredTasks,t=>{
    const st=String(t.status||'planned').toLowerCase();
    const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
    const goal=esc(t.contract?.goal||'—');
    const chk=t.checkpoint?`${esc(t.checkpoint.phase||'')} ➔ ${esc(t.checkpoint.next_action||'')}`:'—';
    const crit=(t.contract?.acceptance_criteria||[]).length?(t.contract.acceptance_criteria.length+' criteria'):'—';
    const dt=t.updated_at?new Date(t.updated_at*1000).toLocaleTimeString():'—';
    const repoLabel=t.repo_root?(t.repo_root.split(/[\\/]/).filter(Boolean).pop()||t.repo_root):(t.context?.repository_id||'—');
    return clickableRow(t,`<td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td><strong>${esc(t.task_id)}</strong></td><td title="${esc(t.repo_root||'')}"><span class="chip" style="max-width:140px;overflow:hidden;text-overflow:ellipsis">${esc(repoLabel)}</span></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${esc(t.contract?.scope||'task')}</span></td><td class="tiny">${chk}</td><td class="tiny">${esc(crit)}</td><td class="tiny">${dt}</td>`,'task',t.task_id);
  },8,'No Agent OS tasks found.');

  rows('agentOsMemoryBody',filteredMem,m=>clickableRow(m,formatAgentOsMemoryCells(m),'memory',(m.scope||'task')+':'+m.key),7,agentOsMemories.length?'No memories match the current filters.':'No memories recorded.');

  rows('agentOsIncBody',filteredInc,i=>{
    const id=esc(i.incident_id||'—');
    const status=String(i.status||(i.verified_fix?'resolved':'unresolved'));
    const statusChip=status==='ignored'?'<span class="chip">ignored</span>':status==='resolved'?'<span class="chip ok">resolved</span>':'<span class="chip warn-t">unresolved</span>';
    const op=esc(i.operation_class||i.outcome?.tool_name||'agent');
    const ec=esc(i.error_class||'Error');
    let msg=esc(i.redacted_message||'');
    if(msg.length>45)msg=msg.slice(0,42)+'...';
    const cause=esc(i.root_cause||'—');
    const fix=esc(i.verified_fix||'—');
    return clickableRow(i,`<td><strong>${id}</strong></td><td>${statusChip}</td><td>${n(i.attempts||1)}</td><td><span class="chip">${op}</span></td><td><span class="chip bad-t">${ec}</span></td><td class="tiny" title="${esc(i.redacted_message||'')}">${msg}</td><td class="tiny">${cause}</td><td class="tiny ok">${fix}</td>`,'incident',i.incident_id);
  },8);
  renderAgentOsLoadErrors();
}

// BEGIN memory provenance display
function formatAgentOsMemoryCells(m){
  const sc=esc(m?.scope||'task');
  const kd=esc(m?.kind||'fact');
  const k=esc(m?.key||'—');
  let rawValue='';
  try{rawValue=typeof m?.value==='object'?JSON.stringify(m.value):String(m?.value||'')}catch(_){rawValue='[unavailable]'}
  if(rawValue.length>55)rawValue=rawValue.slice(0,52)+'...';
  const v=esc(rawValue);
  const conf=m?.confidence!==undefined?Math.round(m.confidence*100)+'%':'—';
  const source=typeof m?.source==='string'&&m.source.trim()?m.source.trim():'Unknown source';
  const provenance=m?.provenance&&typeof m.provenance==='object'&&!Array.isArray(m.provenance)?m.provenance:{};
  const root=typeof provenance.root==='string'&&provenance.root.trim()?provenance.root.trim():'Unknown root';
  const repository=typeof provenance.repository_id==='string'&&provenance.repository_id.trim()?provenance.repository_id.trim():'Unknown repository';
  const stamp=typeof m?.created_at==='number'&&Number.isFinite(m.created_at)&&m.created_at>0?new Date(m.created_at*1000):null;
  const dt=stamp&&Number.isFinite(stamp.getTime())?stamp.toLocaleString(undefined,{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'}):'Unknown date/time';
  const sourceDetails=`<div>Source: ${esc(source)}</div><div>Root: ${esc(root)}</div><div>Repository: ${esc(repository)}</div>`;
  return `<td><span class="chip">${sc}</span></td><td><span class="chip">${kd}</span></td><td><strong>${k}</strong></td><td class="tiny mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${v}</td><td class="tiny">${conf}</td><td class="tiny">${sourceDetails}</td><td class="tiny">${esc(dt)}</td>`;
}
// END memory provenance display

function renderAgentOsLoadErrors(){
  const failed=Object.keys(agentOsLoadErrors);
  if(!failed.length)return;
  const isRepoPrompt=Object.values(agentOsLoadErrors).every(msg=>/Choose a repository|Select a repository/i.test(msg));
  if(isRepoPrompt){
    if($('agentOsState'))$('agentOsState').textContent='Select a repository';
    if($('agentOsSummary'))$('agentOsSummary').textContent='Choose a repository above, then refresh to view its records.';
    [['tasks','agentOsTasksBody',8],['memory','agentOsMemoryBody',7],['incidents','agentOsIncBody',8]].forEach(([key,id,columns])=>{
      if(agentOsLoadErrors[key]&&$(id))$(id).innerHTML=`<tr><td colspan="${columns}" class="empty">${esc(agentOsLoadErrors[key])}</td></tr>`;
    });
    return;
  }
  if(!Boolean($('agentOsTasksBody')?.children?.length)){
    if($('agentOsState'))$('agentOsState').textContent='Partially unavailable · '+failed.join(', ');
    if($('agentOsSummary'))$('agentOsSummary').textContent='Some data could not be loaded. Refresh to retry.';
  }
  [['tasks','agentOsTasksBody',8],['memory','agentOsMemoryBody',7],['incidents','agentOsIncBody',8]].forEach(([key,id,columns])=>{
    if(agentOsLoadErrors[key]&&$(id))$(id).innerHTML=`<tr><td colspan="${columns}" class="empty warn-t">${esc(agentOsLoadErrors[key])}</td></tr>`;
  });
}

$('agentOsRefresh')?.addEventListener('click',loadAgentOsView);
$('agentOsRepoSelect')?.addEventListener('change',()=>{
  const val=$('agentOsRepoSelect').value;
  if($('agentOsRoot'))$('agentOsRoot').value=val;
  loadAgentOsView();
});
$('agentOsRoot')?.addEventListener('change',()=>{
  const val=$('agentOsRoot').value.trim();
  if($('agentOsRepoSelect'))$('agentOsRepoSelect').value=val;
  loadAgentOsView();
});
$('agentOsRoot')?.addEventListener('keydown',event=>{if(event.key==='Enter')loadAgentOsView()});
$('agentOsCleanup')?.addEventListener('click',openCleanupModal);
$('agentOsSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsTaskStatus')?.addEventListener('change',renderAgentOsView);
$('agentOsMemSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsMemScope')?.addEventListener('change',renderAgentOsView);
$('agentOsMemKind')?.addEventListener('change',renderAgentOsView);
$('agentOsIncSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsIncFilter')?.addEventListener('change',renderAgentOsView);

// Create Task Modal
$('agentOsCreateTaskBtn')?.addEventListener('click',openCreateTaskModal);

// Record Memory Modal
$('agentOsRecordMemBtn')?.addEventListener('click',openRecordMemoryModal);

// Record Incident Modal

