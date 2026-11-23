// @ts-nocheck
function renderRouteStatModal(x){
  const route=x.route||'route';
  const task=x.task_type||'task';
  const comp=x.complexity||'standard';
  const calls=Number(x.calls||0);
  const fails=Number(x.failures||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">EXECUTION ROUTE</div>
          <h2 style="margin:2px 0 0;font-size:16px">➔ <span class="mono">${esc(route)}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${esc(comp)} complexity</span>
          <span class="chip">${esc(task)}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Route Dispatch Stats</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Assigned Task Type</div><div><b>${esc(task)}</b></div>
            <div>Complexity Tier</div><div><b>${esc(comp)}</b></div>
            <div>Total Executions</div><div><b>${n(calls)}</b></div>
            <div>Average Runtime</div><div><b>${ms(x.avg_ms)}</b></div>
            <div>Failures</div><div class="${fails?'bad-t':'ok'}"><b>${n(fails)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderBlockedReasonModal(x){
  const r=x.reason||'Blocked';
  const count=Number(x.count||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">COMMAND SECURITY POLICY REJECTION</div>
          <h2 style="margin:2px 0 0;font-size:16px"><span class="bad-t">Blocked:</span> ${esc(humanLabel(r))}</h2>
        </div>
        <span class="badge-status badge-error">${n(count)} REJECTIONS</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Rejection Details</span></div>
        <div class="modal-card-body">
          <div style="font-size:12px;line-height:1.5">
            Commands matching this rule were blocked by Local AI Hub's sandbox policy broker to protect system integrity.
          </div>
          <div class="kv" style="padding:0;margin-top:8px">
            <div>Policy Reason</div><div class="mono tiny bad-t">${esc(r)}</div>
            <div>Total Blocked Count</div><div><b>${n(count)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderSchedulerJobModal(j){
  const jid=n(j.job_id);
  const state=j.state||'queued';
  const model=j.model||'—';

  const source=j.source||'api';
  const reason=j.wait_reason||'ready';
  const traceId=j.trace_id;
  const isErr=state==='failed'||state==='error';
  const isLive=state==='running'||state==='processing';
  const stateCls=isErr?'badge-error':(isLive?'badge-running':'badge-waiting');

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">JOB SCHEDULER INFLIGHT ITEM</div>
          <h2 style="margin:2px 0 0;font-size:16px">Job <b>#${jid}</b> <span class="badge-status ${stateCls}">${esc(state.toUpperCase())}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${esc(model)}</span>
          <span class="chip">${esc(source)}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Execution &amp; Queue Timing</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Job ID</div><div><b>#${jid}</b></div>
            <div>Status</div><div><span class="badge-status ${stateCls}">${esc(state)}</span></div>
            <div>Assigned Model</div><div class="mono tiny"><b>${esc(model)}</b></div>

            <div>Origin / Source</div><div>${esc(source)}</div>
            <div>Queue Wait Time</div><div><b>${ms(j.wait_ms)}</b></div>
            <div>Service Execution Time</div><div><b>${ms(j.service_ms)}</b></div>
            <div>Wait / Scheduling Reason</div><div class="warn-t"><b>${esc(reason)}</b></div>
          </div>
        </div>
      </div>
      ${traceId?`
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#101a26;border:1px solid #1e354d;border-radius:6px">
          <span>Linked Trace: <b class="mono">${esc(traceId)}</b></span>
          <button class="btn ok" onclick="openTrace(${escJs(traceId)})">↗ Open Full Trace</button>
        </div>
      `:''}
      <details class="raw-json"><summary>Raw Job Details</summary><pre>${esc(JSON.stringify(j,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderHttpRequestModal(r){
  const rid=r.request_id||'—';
  const agent=r.agent||'unknown';

  const action=r.action||'—';
  const status=r.status_code!==undefined?n(r.status_code):'—';
  const isErr=r.success===false||(r.status_code&&r.status_code>=400);
  const dur=r.duration_ms!==undefined?ms(r.duration_ms):(r.age_ms!==undefined?age(r.age_ms):'—');
  const dt=r.created_at?new Date(r.created_at*1000).toLocaleString():'—';

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">HTTP WORK REQUEST</div>
          <h2 style="margin:2px 0 0;font-size:16px"><span class="mono">${esc(action)}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ${isErr?'bad-t':'ok'}">${status}</span>
          <span class="chip">${dur}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Request Profile</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Request ID</div><div class="mono tiny"><b>${esc(rid)}</b></div>
            <div>Action / Endpoint</div><div class="mono tiny">${esc(action)}</div>
            <div>Calling Agent</div><div><b>${esc(agent)}</b></div>

            <div>Duration / In-flight Age</div><div><b>${dur}</b></div>
            <div>Status Code</div><div class="${isErr?'bad-t':'ok'}"><b>${status}</b></div>
            <div>Timestamp</div><div>${dt}</div>
          </div>
        </div>
      </div>
      <details class="raw-json"><summary>Raw Request Details</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

if($('modalClose'))$('modalClose').onclick=()=>{if($('modalBg'))$('modalBg').classList.remove('open');activeTraceId='';activeTraceData=null;traceDetailPoller?.stop();traceDetailPoller=null;tracePollAbortController?.abort();tracePollAbortController=null};
if($('modalBg'))$('modalBg').onclick=e=>{if(e.target===$('modalBg'))$('modalClose')?.click()};

document.addEventListener('change',e=>{const select=e.target.closest?.('[data-trace-view-select]');if(select)setTraceView(select.value)});
document.addEventListener('click',e=>{
  const closeBtn=e.target.closest?.('button');
  if(closeBtn && (closeBtn.getAttribute('onclick')?.includes('modalClose') || closeBtn.dataset.modalClose!==undefined || (closeBtn.textContent?.trim()==='Cancel' && closeBtn.closest('#modalBody')))){
    $('modalClose')?.click();
    return;
  }
  const copyFinal=e.target.closest?.('[data-trace-copy-final]');if(copyFinal){copyTraceFinalResponse(copyFinal);return}
  const copyTrace=e.target.closest?.('[data-trace-copy]');if(copyTrace){copyTraceContent(copyTrace.dataset.traceCopy,copyTrace);return}
  const expandAll=e.target.closest?.('[data-trace-expand-all]');if(expandAll){setTraceDetailsOpen(true);return}
  const collapseAll=e.target.closest?.('[data-trace-collapse-all]');if(collapseAll){setTraceDetailsOpen(false);return}
  const eventPage=e.target.closest?.('[data-trace-event-page]');if(eventPage){loadTraceEventPage(eventPage.dataset.traceEventPage);return}
  const tab=e.target.closest?.('[data-trace-view]');if(tab){setTraceView(tab.dataset.traceView);return}
  const pageTrace=e.target.closest?.('[data-trace-page-id]');if(pageTrace){openTrace(pageTrace.dataset.tracePageId);return}
  const back=e.target.closest?.('[data-trace-back]');if(back){switchTab('work');return}
  const toggle=e.target.closest?.('[data-trace-toggle]');if(toggle){toggleTraceStep(toggle);return}
  const projectDetails=e.target.closest?.('[data-project-details]');
  if(projectDetails){
    const row=projectDetails.closest('[data-detail]'),entry=row?dataStore.get(row.dataset.detail):null;
    const project=entry?.data??entry;
    if(project)openModal(project,'','project');
    return;
  }
  if(e.target.closest('button, a, input, select, textarea, .action-btn-sm, [data-project-action], [data-export-root]'))return;
  const trace=e.target.closest?.('[data-trace-id]');if(trace){openTrace(trace.dataset.traceId);return}
  const tr=e.target.closest?.('[data-detail]');
  if(tr){
    let entry=dataStore.get(tr.dataset.detail);
    let obj=null, type=tr.dataset.type||'';
    if(entry){
      obj=(entry.data!==undefined&&entry.type!==undefined)?entry.data:entry;
      type=entry.type||type||inferEntityType(obj);
    }
    if(!obj && tr.dataset.id){
      const eid=tr.dataset.id;
      if(type==='task') obj=agentOsTasks.find(x=>x.task_id===eid);
      else if(type==='memory') obj=agentOsMemories.find(x=>((x.scope||'task')+':'+x.key)===eid||x.key===eid);
      else if(type==='incident') obj=agentOsIncidents.find(x=>x.incident_id===eid);
      else if(type==='project') obj=(last?.preprocessing?.projects||[]).find(x=>x.root===eid);
    }
    if(obj){
      openModal(obj,'',type);
    }
  }
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if($('visionReviewModal')?.classList.contains('open'))closeFrontendVisionReviewModal();
    else if($('modalBg')?.classList.contains('open'))$('modalClose')?.click();
    else if($('controlMenu'))$('controlMenu').open=false;
    return;
  }
  const tab=e.target.closest?.('[data-trace-view]');
  if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();moveTraceTab(tab,e.key);
});

function switchTab(tabId){
  if(!tabId||!$(tabId))return;
  const changed=document.querySelector('.page.active')?.id!==tabId;
  if($('controlMenu'))$('controlMenu').open=false;
  document.querySelectorAll('.tabbtn').forEach(x=>{const active=x.dataset.tab===tabId;x.classList.toggle('active',active);x.setAttribute('aria-current',active?'page':'false');});
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===tabId));
  try{localStorage.setItem('activeTab',tabId)}catch{}
  if(location.hash.replace('#','')!==tabId)history.replaceState(null,'','#'+tabId);
  if(tabId==='config')loadConfigView();
  if(tabId==='agentos'){loadAgentOsView();loadEndpointStatsView();}
  if(tabId==='coordination')loadCoordinationView();
  if(tabId==='performance'){loadRagWorkspaces();loadActiveLeases();loadResidentInventory();}
  if(tabId==='commands')loadWorktrees();
  if(tabId==='reliability')loadLogsTail();
  if(tabId==='work')renderRecentRequestHistory();
  if(['work','reliability','traceInspector'].includes(tabId))pollTraces();else tracesPollAbortController?.abort();
  if(changed){window.scrollTo({top:0,left:0,behavior:'instant'});$(tabId).querySelector('.page-heading h1')?.focus({preventScroll:true});}
}

document.querySelectorAll('.tabbtn').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
window.addEventListener('hashchange',()=>switchTab(location.hash.replace('#','')));
$('pauseEvents').onclick=e=>{paused=!paused;e.target.textContent=paused?'Resume live events':'Pause live events'};
async function fetchDashboardJson(path,options={}){
  const response=await apiFetch(path,options);
  let data;
  try{data=await response.json()}catch{throw new Error(`Invalid server response (HTTP ${response.status})`)}
  if(!response.ok||data?.success===false)throw new Error(String(data?.error||data?.message||`HTTP ${response.status}`));
  return data;
}
async function post(path,payload,requestOptions={}){const r=await apiFetch(path,{...requestOptions,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});return await r.json()}

const ACTIVITY_MODES=['active','gaming','maintenance','preprocessing'];
let activityModeStatusPolls=0;
let activityModeTransitionNotice=null;
const activityModeLabels={active:'Active',gaming:'GAMING / PAUSED',maintenance:'Maintenance',preprocessing:'Preprocessing'};
function renderActivityMode(mode){
  const badge=$('activityModeBadge');if(!badge)return;
  const valid=ACTIVITY_MODES.includes(String(mode||''));
  const value=valid?String(mode):'unknown';
  badge.dataset.mode=value;badge.className=`pill ${value==='active'?'ok':value==='unknown'?'warn-t':''}`;
  badge.textContent=`Mode: ${valid?activityModeLabels[value]:'Unknown'}`;
  document.querySelectorAll('[data-activity-mode]').forEach(button=>button.setAttribute('aria-pressed',String(valid&&button.dataset.activityMode===value)));
}
function activityModeFailure(response,data){
  if(response?.status===401)return 'Request rejected (HTTP 401).';
  if(response?.status===400)return `Invalid mode: ${data?.error||'server rejected request'}`;
  if(response&&!response.ok)return `Mode request failed (HTTP ${response.status}).`;
  return data?.error||'Mode request failed.';
}
function projectActivityModeTransition(confirmed,data){
  const failures=[];
  if(confirmed==='preprocessing'&&data.preprocessing_start?.success!==true)failures.push('preprocessing start incomplete');
  if(confirmed==='gaming'){
    const unload=data.runtime_unload;
    if(!unload||unload.state!=='pending'&&unload.success!==true)failures.push('VRAM unload incomplete');
    const acceleratorRelease=data.accelerator_release;
    if(!acceleratorRelease||acceleratorRelease.success!==true)failures.push('accelerator release incomplete');
    if(unload?.state==='pending')failures.push('VRAM unload pending');
  }
  if(data.job_cancellation&&data.job_cancellation.success!==true)failures.push('job cancellation incomplete');
  const persisted=`Mode persisted as ${activityModeLabels[confirmed]}.`;
  return {
    modePersisted:true,
    partial:failures.length>0,
    failures,
    status:failures.length?`${persisted} Mode transition incomplete: ${failures.join('; ')}.`:`Mode set to ${activityModeLabels[confirmed]}.`,
  };
}
async function refreshActivityMode(){
  const status=$('activityModeStatus');
  try{
    const response=await apiFetch('/api/mode',{cache:'no-store',timeoutMs:5000});
    const data=await response.json().catch(()=>null);
    if(!response.ok||!data||data.success!==true){renderActivityMode('unknown');if(status)status.textContent=`Mode unavailable: ${activityModeFailure(response,data)}`;return false;}
    if(!ACTIVITY_MODES.includes(data.mode)){renderActivityMode('unknown');if(status)status.textContent='Mode unavailable: invalid mode returned by server.';return false;}
    renderActivityMode(data.mode);
    if(activityModeTransitionNotice&&activityModeTransitionNotice.mode!==data.mode)activityModeTransitionNotice=null;
    const notice=activityModeTransitionNotice?.mode===data.mode?activityModeTransitionNotice:null;
    if(notice&&data.mode==='gaming'&&data.runtime_unload?.state!=='pending'){
      const unloadState=data.runtime_unload?.success===true?'complete':'incomplete';
      notice.text=notice.text.replace(/VRAM unload (?:pending|incomplete)/,`VRAM unload ${unloadState}`);
    }
    if(status){const unload=data.runtime_unload;status.textContent=data.mode==='preprocessing'&&data.preprocessing_ready!==true?'Preprocessing not ready. Select Preprocessing to retry.':notice?.text??(data.mode==='gaming'&&unload?(unload.success===true?'Gaming mode active. VRAM unload complete.':unload.state==='pending'?'Gaming mode active. VRAM unload in progress.':'Gaming mode active. VRAM unload incomplete.'):'Mode loaded.');}
    if(data.mode==='gaming'&&data.runtime_unload?.state==='pending'&&activityModeStatusPolls<8){activityModeStatusPolls++;setTimeout(refreshActivityMode,1500);}else if(data.runtime_unload?.state!=='pending'){activityModeStatusPolls=0;}
    return true;
  }catch(_){renderActivityMode('unknown');if(status)status.textContent='Mode unavailable: Hub offline or unreachable.';return false;}
}
async function applyActivityMode(mode){
  const buttons=Array.from(document.querySelectorAll('[data-activity-mode]')),status=$('activityModeStatus');
  mode=String(mode||'');
  if(!ACTIVITY_MODES.includes(mode)){if(status)status.textContent='Invalid mode selected.';return false;}
  activityModeTransitionNotice=null;
  buttons.forEach(button=>button.disabled=true);if(status)status.textContent='Updating mode…';
  try{
    const response=await apiFetch('/api/admin/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode}),timeoutMs:5000});
    const data=await response.json().catch(()=>null);
    if(!response.ok||!data||data.success!==true){if(status)status.textContent=activityModeFailure(response,data);return false;}
    const confirmed=data.mode;
    if(!ACTIVITY_MODES.includes(confirmed)||confirmed!==mode){if(status)status.textContent='Mode update rejected: invalid mode returned by server.';return false;}
    renderActivityMode(confirmed);
    const transition=projectActivityModeTransition(confirmed,data);
    if(transition.partial)activityModeTransitionNotice={mode:confirmed,text:transition.status};
    if(status)status.textContent=transition.status;
    if(confirmed==='gaming'&&data.runtime_unload?.state==='pending'){activityModeStatusPolls=0;setTimeout(refreshActivityMode,800);}
    return true;
  }catch(_){if(status)status.textContent='Mode update failed: Hub offline or unreachable.';return false;}
  finally{buttons.forEach(button=>button.disabled=false);}
}

function setConfigFormReady(ready){
  document.querySelectorAll('#config input,#config select').forEach(control=>{control.disabled=!ready});
  for(const id of ['cfgSave','cfgReset'])if($(id))$(id).disabled=!ready;
}
let configViewLoad=null;
async function loadConfigView(){
  if(configViewLoad)return configViewLoad;
  setConfigFormReady(false);
  $('cfgStatus').textContent='Loading configuration…';
  configViewLoad=(async()=>{
  try{
    const r=await apiFetch('/api/config',{cache:'no-store'}),d=await r.json();
    if(r.ok===false||!d.success){$('cfgStatus').textContent=d.error||'Configuration unavailable. Reload to retry.';return}
    const c=d.config||{},feat=c.features||{};
    $('cfgProfile').value=c.hardware?.profile||'auto';
    $('cfgPreprocess').checked=c.preprocessing?.enabled!==false&&feat.preprocessing!==false;
    $('cfgIntel').checked=c.code_intelligence?.enabled!==false&&feat.code_intelligence!==false;
    $('cfgSerena').checked=!!c.code_intelligence?.serena_enabled;

    if($('cfgFeatStatus'))$('cfgFeatStatus').checked=feat.status!==false;
    if($('cfgFeatRepo'))$('cfgFeatRepo').checked=feat.repo!==false;
    if($('cfgFeatTasks'))$('cfgFeatTasks').checked=feat.tasks!==false;
    if($('cfgFeatRag'))$('cfgFeatRag').checked=feat.rag!==false;
    if($('cfgFeatCommands'))$('cfgFeatCommands').checked=feat.commands!==false;
    if($('cfgFeatCoord'))$('cfgFeatCoord').checked=feat.coord!==false;
    if($('cfgFeatArtifacts'))$('cfgFeatArtifacts').checked=feat.artifacts!==false;
    if($('cfgFeatSubagents'))$('cfgFeatSubagents').checked=feat.subagents!==false;
    if($('cfgFeatAgentOs'))$('cfgFeatAgentOs').checked=feat.agent_os!==false;
    if($('cfgFeatDashboard'))$('cfgFeatDashboard').checked=feat.dashboard!==false;
    $('cfgPath').textContent=(d.config_path||'')+(d.runtime_override_path?' · overrides '+d.runtime_override_path:'');
    $('cfgPreview').textContent=JSON.stringify(c,null,2);
    $('cfgStatus').textContent='';
    setConfigFormReady(true);
  }catch(e){$('cfgStatus').textContent='Configuration unavailable: '+String(e)}
  })();
  try{await configViewLoad}finally{configViewLoad=null}
}
$('cfgReload').onclick=loadConfigView;
$('cfgSave').onclick=async()=>{
  const settings={
    'hardware.profile':$('cfgProfile').value,
    'preprocessing.enabled':$('cfgPreprocess').checked,
    'code_intelligence.enabled':$('cfgIntel').checked,
    'code_intelligence.serena_enabled':$('cfgSerena').checked,

    'features.status':$('cfgFeatStatus')?$('cfgFeatStatus').checked:true,
    'features.repo':$('cfgFeatRepo')?$('cfgFeatRepo').checked:true,
    'features.tasks':$('cfgFeatTasks')?$('cfgFeatTasks').checked:true,
    'features.rag':$('cfgFeatRag')?$('cfgFeatRag').checked:true,
    'features.commands':$('cfgFeatCommands')?$('cfgFeatCommands').checked:true,
    'features.coord':$('cfgFeatCoord')?$('cfgFeatCoord').checked:true,
    'features.artifacts':$('cfgFeatArtifacts')?$('cfgFeatArtifacts').checked:true,
    'features.code_intelligence':$('cfgIntel').checked,
    'features.preprocessing':$('cfgPreprocess').checked,
    'features.subagents':$('cfgFeatSubagents')?$('cfgFeatSubagents').checked:true,
    'features.agent_os':$('cfgFeatAgentOs')?$('cfgFeatAgentOs').checked:true,
    'features.dashboard':$('cfgFeatDashboard')?$('cfgFeatDashboard').checked:true
  };
  const r=await post('/api/config/update',{action:'update',settings});
  $('cfgStatus').textContent=r.success?'saved · restart hub to apply':('error: '+(r.error||'failed'));
  if(r.success)loadConfigView();
};
if($('cfgReset'))$('cfgReset').onclick=async()=>{
  if($('modalTitle'))$('modalTitle').textContent='Reset dashboard overrides';
  if($('modalLive'))$('modalLive').textContent='Confirmation required';
  if($('modalBody'))$('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Scope and impact</span></div><div class="modal-card-body"><p><b>Scope:</b> Dashboard-managed configuration override sidecar only.</p><p style="margin-bottom:0"><b>Impact:</b> Removes override values. Base configuration and project data stay unchanged; restart applies result.</p></div></div><div class="modal-actions-bar" style="justify-content:flex-end"><button class="btn" onclick="$('modalClose')?.click()">Cancel</button><button class="btn warn" id="confirmConfigReset">Reset overrides</button></div></div>`;
  if($('modalBg'))$('modalBg').classList.add('open');
  const confirmBtn=$('confirmConfigReset');
  if(confirmBtn)confirmBtn.onclick=async()=>{const r=await post('/api/config/update',{action:'reset'});if($('cfgStatus'))$('cfgStatus').textContent=r.success?'overrides reset · restart hub to apply':('error: '+(r.error||'failed'));if(r.success)loadConfigView();$('modalClose')?.click();};
};

let logLines=['Click Refresh to load logs.'];
async function loadLogsTail(){
  try{
    const lines=$('logLinesSelect')?.value||'250';
    const r=await apiFetch('/api/logs/tail?lines='+lines,{cache:'no-store'}),d=await r.json();
    logLines=d.success?(d.lines||[]):[JSON.stringify(d,null,2)];
    renderFilteredLogs();
  }catch(e){$('logTail').textContent=String(e)}
}
function renderFilteredLogs(){
  const q=String($('logFilterInput')?.value||'').trim().toLowerCase();
  const filtered=q?logLines.filter(l=>l.toLowerCase().includes(q)):logLines;
  $('logTail').textContent=filtered.length?filtered.join('\n'):'No log lines matching filter.';
}
$('loadLogs').onclick=loadLogsTail;
$('logFilterInput')?.addEventListener('input',renderFilteredLogs);
$('logLinesSelect')?.addEventListener('change',loadLogsTail);
$('copyLogsBtn')?.addEventListener('click',()=>{
  navigator.clipboard.writeText($('logTail').textContent||'');
  $('copyLogsBtn').textContent='Copied!';
  setTimeout(()=>{$('copyLogsBtn').textContent='Copy'},1500);
});

let preprocessActionInFlight=false;
async function setPreprocessing(action){
  if(preprocessActionInFlight)return;
  preprocessActionInFlight=true;
  const buttons=[$('prepToggle'),$('prepAllToggle')].filter(Boolean);
  buttons.forEach(b=>b.disabled=true);
  try{
    const result=await post('/api/preprocess',{action});
    if(result?.success){last={...last,preprocessing:result};render(last)}
    await pollStatus();
  }catch(e){alert('Preprocessing action failed: '+(e.message||e));await pollStatus()}
  finally{buttons.forEach(b=>b.disabled=false);preprocessActionInFlight=false}
}
function togglePreprocessing(){return setPreprocessing(last?.preprocessing?.paused?'resume':'pause')}
$('prepToggle').onclick=togglePreprocessing;
$('prepAllToggle').onclick=togglePreprocessing;
document.querySelectorAll('[data-activity-mode]').forEach(button=>button.onclick=()=>applyActivityMode(button.dataset.activityMode));
refreshActivityMode();
setInterval(()=>{if(document.visibilityState!=='hidden')refreshActivityMode()},30000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='hidden')refreshActivityMode()});

