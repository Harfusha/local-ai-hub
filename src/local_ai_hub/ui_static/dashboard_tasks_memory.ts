// @ts-nocheck
function renderTaskModal(t){
  const st=String(t.status||'planned').toLowerCase();
  const terminal=st==='completed'||st==='failed';
  const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
  const goal=t.contract?.goal||'No goal specified';
  const criteria=t.contract?.acceptance_criteria||[];
  activeTaskInspectorState={taskId:String(t.task_id||''),criteria:[...criteria],status:st};
  trajectoryTaskId=activeTaskInspectorState.taskId;trajectoryAfterSeq=0;trajectorySnapshotSeq=null;trajectoryHasMore=false;trajectoryGaps=[];trajectoryEvents=[];trajectoryLoading=false;trajectoryPageError='';trajectoryGeneration++;
  const chk=t.checkpoint||{};
  const paths=chk.affected_paths||[];
  const evs=chk.evidence_ids||[];
  const risk=t.contract?.risk_profile||'normal';
  const created=t.created_at?new Date(t.created_at*1000).toLocaleString():'—';
  const updated=t.updated_at?new Date(t.updated_at*1000).toLocaleString():'—';

  let criteriaHtml='';
  if(criteria.length){
    criteriaHtml='<div class="modal-checklist">'+criteria.map((c,i)=>`
      <div class="modal-checklist-item task-criterion-row" data-criterion-index="${i}">
        <span class="badge-status badge-waiting" style="font-size:9px">#${i+1}</span>
        <span class="item-text"><b>${esc(c)}</b></span>
        <span class="task-criterion-state is-unavailable" role="status">Checking…</span>
      </div>
    `).join('')+'</div>';
  } else {
    criteriaHtml='<div class="muted tiny">No acceptance criteria defined for this task.</div>';
  }

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">DURABLE AGENT TASK</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <span class="mono">${esc(t.task_id)}</span>
            <button class="copy-btn" onclick="copyText(${escJs(t.task_id)},this)">Copy ID</button>
          </h2>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <span class="badge-status ${cls}">${esc(st.toUpperCase())}</span>
          <span class="chip">${esc(t.contract?.scope||'task')}</span>
          <span class="chip ${risk==='high'?'bad-t':risk==='medium'?'warn-t':'ok'}">${esc(risk)} risk</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Created: ${created} · Updated: ${updated} · Actor: <b>${esc(t.actor||'system')}</b></div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Goal &amp; Objective</span></div>
        <div class="modal-card-body">
          <div style="font-size:13px;font-weight:500;line-height:1.4">${esc(goal)}</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head">
          <span>Acceptance Criteria <span class="tiny" style="margin-left:5px">(${criteria.length})</span></span>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end">
            <span id="taskCriteriaSummary" class="task-criteria-summary" aria-live="polite">Checking receipts…</span>
            <button class="action-btn-sm" id="taskCriteriaRefresh" onclick="checkTaskCompletionGate(${escJs(t.task_id)},${escJs(st)})">Refresh status</button>
          </div>
        </div>
        <div class="modal-card-body">
          ${criteriaHtml}
          <div id="taskGateResult" class="task-gate-result" role="status" aria-live="polite">Checking verification receipts…</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Current Checkpoint &amp; Progress</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Current Phase</div><div><b>${esc(chk.phase||'planned')}</b></div>
            <div>Next Action</div><div class="mono tiny">${esc(chk.next_action||'none')}</div>
            <div>Affected Paths</div><div>${paths.length?paths.map(p=>`<span class="chip mono">${esc(p)}</span>`).join(' '):'<span class="muted">none</span>'}</div>
            <div>Evidence IDs</div><div>${evs.length?evs.map(e=>`<span class="chip">${esc(e)}</span>`).join(' '):'<span class="muted">none</span>'}</div>
          </div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Task Event Trajectory</span></div>
        <div class="modal-card-body">
          <div id="trajEventStatus" class="tiny muted">Loading task events…</div>
          <div id="trajEventGaps" class="tiny warn-t" style="margin-top:5px"></div>
          <div id="trajEventList" style="margin-top:6px"></div>
          <button id="trajEventPager" class="btn" data-load-traj-more hidden style="margin-top:8px">${trajectoryPageError?'Retry page':'Load next events'}</button>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Task Lifecycle &amp; Controls</span></div>
        <div class="modal-card-body">
          ${terminal?`
          <div class="task-terminal-state ${st==='completed'?'is-completed':'is-failed'}" role="status">
            <strong>${st==='completed'?'Completed':'Failed'}</strong>
            <span>This task is in a terminal state. Lifecycle controls are unavailable.</span>
          </div>
          `:`
          <div class="modal-actions-bar">
            <button class="btn ok" onclick="completeTaskAction(${escJs(t.task_id)})">✓ Complete Task</button>
            <button class="btn bad" onclick="showFailTaskInput()">✗ Mark Failed</button>
            <div style="display:flex;align-items:center;gap:6px;margin-left:auto">
              <label class="tiny muted" for="taskTransStatus">Status:</label>
              <select id="taskTransStatus" style="background:#282e22;color:var(--fg);border:1px solid #505d44;border-radius:5px;padding:4px 8px;font-size:11px">
                <option value="active" ${st==='active'?'selected':''}>active</option>
                <option value="verifying" ${st==='verifying'?'selected':''}>verifying</option>
                <option value="blocked" ${st==='blocked'?'selected':''}>blocked</option>
                <option value="planned" ${st==='planned'?'selected':''}>planned</option>
              </select>
              <button class="btn" onclick="transitionTaskAction(${escJs(t.task_id)})">Apply</button>
            </div>
          </div>
          <div id="failTaskBox" style="display:none;margin-top:10px;padding:8px;background:#181216;border:1px solid #7f1d1d;border-radius:6px">
            <label for="failTaskReason" style="font-size:11px;font-weight:600;display:block;margin-bottom:4px;color:#fca5a5">Failure Reason *</label>
            <div style="display:flex;gap:6px">
              <input type="text" id="failTaskReason" placeholder="Why did this task fail?" style="flex:1;background:#141811;border:1px solid #2d3f56;color:var(--fg);padding:4px 8px;border-radius:4px;font-size:11px">
              <button class="btn bad" onclick="submitFailTask(${escJs(t.task_id)})">Confirm Fail</button>
              <button class="btn" onclick="$('failTaskBox').style.display='none'">Cancel</button>
            </div>
          </div>
          <div id="taskActionStatus" class="tiny" style="margin-top:8px"></div>
          `}
        </div>
      </div>

      <details class="raw-json"><summary>Raw Task JSON</summary><pre>${esc(JSON.stringify(t,null,2))}</pre></details>
    </div>
  `;
  const trajectoryPager=$('trajEventPager');
  if(trajectoryPager)trajectoryPager.onclick=()=>loadTaskTrajectory(trajectoryTaskId);
  void loadTaskTrajectory(trajectoryTaskId);
  checkTaskCompletionGate(t.task_id,st);
}

async function checkTaskCompletionGate(taskId,status=''){
  const out=$('taskGateResult');
  if(!out)return;
  const taskState=activeTaskInspectorState;
  if(!taskState||taskState.taskId!==String(taskId))return;
  const summary=$('taskCriteriaSummary');
  const refresh=$('taskCriteriaRefresh');
  if(refresh){refresh.disabled=true;refresh.textContent='Checking…';}
  if(summary){summary.textContent='Checking receipts…';summary.className='task-criteria-summary';}
  out.className='task-gate-result';
  out.textContent='Checking verification receipts…';
  try{
    const res=await post('/api/agent-state/verification',{action:'completion',task_id:taskId});
    if(activeTaskInspectorState!==taskState)return;
    if(!res||!res.completion)throw new Error(res?.error||'Completion status was not returned.');
    const c=res.completion;
    const satisfied=new Set(Array.isArray(c.satisfied_criteria)?c.satisfied_criteria.map(String):[]);
    const unsatisfied=new Set(Array.isArray(c.unsatisfied_criteria)?c.unsatisfied_criteria.map(String):[]);
    const stale=new Set(Array.isArray(c.stale_criteria)?c.stale_criteria.map(String):[]);
    const receiptByCriterion=new Map((Array.isArray(c.receipts)?c.receipts:[]).filter(r=>r&&typeof r==='object'&&r.criterion!==undefined).map(r=>[String(r.criterion),r]));
    const rows=Array.from(document.querySelectorAll('.task-criterion-row'));
    const total=rows.length;
    let passedCount=0,failedCount=0,staleCount=0,pendingCount=0,unavailableCount=0;
    rows.forEach(row=>{
      const criterion=taskState.criteria[Number(row.dataset.criterionIndex)];
      const key=criterion===undefined?'':String(criterion);
      const ok=criterion!==undefined&&satisfied.has(key);
      const expired=!ok&&stale.has(key);
      const failed=!ok&&!expired&&receiptByCriterion.get(key)?.passed===false;
      const pending=!ok&&!expired&&!failed&&criterion!==undefined&&unsatisfied.has(key);
      const unavailable=!ok&&!expired&&!failed&&!pending;
      if(ok)passedCount++;
      if(expired)staleCount++;
      if(failed)failedCount++;
      if(pending)pendingCount++;
      if(unavailable)unavailableCount++;
      const state=row.querySelector('.task-criterion-state');
      if(!state)return;
      state.className='task-criterion-state '+(ok?'is-verified':(expired?'is-stale':(failed?'is-failed':(pending?'is-pending':'is-unavailable'))));
      state.textContent=ok?'✓ Verified':(expired?'Receipt expired':(failed?'✗ Failed':(pending?'! Pending':'Status unavailable')));
      state.title=ok?'A valid verification receipt exists.':(expired?'The verification receipt has expired.':(failed?'The latest verification receipt failed.':(pending?'No valid verification receipt exists yet.':'Verification status could not be determined.')));
    });
    const detailCounts=[failedCount?`${failedCount} failed`:'',staleCount?`${staleCount} expired`:'',pendingCount?`${pendingCount} pending`:'',unavailableCount?`${unavailableCount} unavailable`:'' ].filter(Boolean);
    if(summary){
      summary.textContent=total?`${passedCount}/${total} verified${detailCounts.length?' · '+detailCounts.join(' · '):''}`:'No criteria';
      summary.className='task-criteria-summary '+(failedCount?'is-failed':(total&&passedCount===total?'is-verified':(pendingCount||staleCount?'is-pending':'')));
    }
    status=String(status||taskState.status||'').toLowerCase();
    if(!total){
      out.className='task-gate-result';
      out.textContent='No acceptance criteria are defined for this task.';
    }else if(status==='completed'&&(c.complete!==true||passedCount<total)){
      out.className='task-gate-result is-warning';
      if(passedCount<total){
        out.innerHTML=`<b>Completed status needs review.</b> ${passedCount} of ${total} criteria are verified${detailCounts.length?'; '+detailCounts.join(', '):''}.`;
      }else{
        out.innerHTML=`<b>Completed status needs review.</b> All ${total} criteria are verified, but the completion gate reports incomplete.`;
      }
    }else if(status==='completed'){
      out.className='task-gate-result is-ok';
      out.innerHTML=`<b>Task completed.</b> All ${total} acceptance criteria have valid receipts.`;
    }else if(status==='failed'){
      out.className='task-gate-result is-failed';
      out.innerHTML=`<b>Task failed.</b> ${passedCount} of ${total} criteria have valid receipts.`;
    }else if(c.complete===true&&passedCount===total){
      out.className='task-gate-result is-ok';
      out.innerHTML=`<b>Completion gate passed.</b> All ${total} criteria have valid receipts.`;
    }else if(passedCount===total&&c.complete!==true){
      out.className='task-gate-result is-warning';
      out.innerHTML=`<b>Completion gate needs review.</b> All ${total} criteria are verified, but the gate reports incomplete.`;
    }else{
      out.className='task-gate-result is-warning';
      out.innerHTML=`<b>Completion gate pending.</b> ${passedCount} of ${total} criteria verified${detailCounts.length?'; '+detailCounts.join(', '):''}.`;
    }
  }catch(e){
    if(activeTaskInspectorState!==taskState)return;
    const rows=Array.from(document.querySelectorAll('.task-criterion-row'));
    rows.forEach(row=>{
      const state=row.querySelector('.task-criterion-state');
      if(state){state.className='task-criterion-state is-unavailable';state.textContent='Status unavailable';}
    });
    if(summary){summary.textContent='Status unavailable';summary.className='task-criteria-summary';}
    out.className='task-gate-result is-warning';
    out.textContent='Could not load verification receipts. Refresh status to try again.';
  }finally{
    if(refresh){refresh.disabled=false;refresh.textContent='Refresh status';}
  }
}

function showFailTaskInput(){
  const b=$('failTaskBox');
  if(b){b.style.display='block';$('failTaskReason')?.focus()}
}

async function submitFailTask(taskId){
  const reason=$('failTaskReason')?.value?.trim();
  if(!reason)return;
  const statusEl=$('taskActionStatus');
  if(statusEl)statusEl.textContent='Failing task…';
  try{
    const res=await post('/api/agent-state/tasks',{action:'fail',task_id:taskId,reason:reason});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="bad-t">Task marked as failed.</span>';
      await loadAgentOsView();
      if(res.task)renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Could not mark the task as failed.')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

async function completeTaskAction(taskId){
  const statusEl=$('taskActionStatus');
  if(statusEl)statusEl.textContent='Checking criteria receipts and completing task…';
  try{
    const res=await post('/api/agent-state/tasks',{action:'complete',task_id:taskId,reason:'Completed via dashboard inspector'});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="ok">✓ Task marked completed.</span>';
      await loadAgentOsView();
      if(res.task)renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Could not complete the task.')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

async function transitionTaskAction(taskId){
  const sel=$('taskTransStatus');
  if(!sel)return;
  const target=sel.value;
  const statusEl=$('taskActionStatus');
  if(statusEl)statusEl.textContent='Transitioning to '+target+'…';
  try{
    const res=await post('/api/agent-state/tasks',{action:'transition',task_id:taskId,status:target,reason:'Transitioned via dashboard inspector'});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="ok">✓ Transitioned to '+esc(target)+'.</span>';
      await loadAgentOsView();
      if(res.task)renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Transition failed')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openCreateTaskModal(){
  if($('modalTitle'))$('modalTitle').textContent='Create Durable Agent Task';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitCreateTask(event)">
        <div class="form-group">
          <label for="newTaskRoot">Repository Root *</label>
          <input type="text" id="newTaskRoot" list="worktreeRoots" required placeholder="Select or enter repository root" value="${esc($('agentOsRoot')?.value?.trim()||$('agentOsRepoSelect')?.value?.trim()||'')}">
          <span class="form-hint">The repository this task belongs to.</span>
        </div>
        <div class="form-group">
          <label for="newTaskGoal">Task Goal *</label>
          <textarea id="newTaskGoal" rows="3" required placeholder="Describe the goal and expected outcome..." autofocus></textarea>
          <span class="form-hint">What should be done?</span>
        </div>
        <div class="form-group">
          <label for="newTaskCriteria">Acceptance Criteria</label>
          <textarea id="newTaskCriteria" rows="3" placeholder="Criterion 1&#10;Criterion 2&#10;Criterion 3"></textarea>
          <span class="form-hint">One criterion per line, or comma-separated.</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="form-group">
            <label for="newTaskScope">Scope</label>
            <select id="newTaskScope">
              <option value="task" selected>Task</option>
              <option value="session">Session</option>
              <option value="repository">Repository</option>
              <option value="system">System</option>
            </select>
          </div>
          <div class="form-group">
            <label for="newTaskRisk">Risk Profile</label>
            <select id="newTaskRisk">
              <option value="low">Low Risk</option>
              <option value="normal" selected>Normal</option>
              <option value="high">High Risk</option>
            </select>
          </div>
        </div>
        <div id="createTaskStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">Create Task</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('newTaskGoal')?.focus(),50);
}

async function submitCreateTask(e){
  e.preventDefault();
  const goal=$('newTaskGoal')?.value?.trim();
  if(!goal)return;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Creating…');
  const root=$('newTaskRoot')?.value?.trim()||$('agentOsRoot')?.value?.trim()||$('agentOsRepoSelect')?.value?.trim();
  const rawCrit=$('newTaskCriteria')?.value||'';
  const criteria=rawCrit.split(/[\n,]/).map(s=>s.trim()).filter(Boolean);
  const scope=$('newTaskScope')?.value||'task';
  const risk=$('newTaskRisk')?.value||'normal';
  const statusEl=$('createTaskStatus');
  if(statusEl)statusEl.textContent='Creating task…';

  try{
    const payload={
      action:'create',
      contract:{goal,acceptance_criteria:criteria,scope,risk_profile:risk}
    };
    if(root)payload.root=root;
    const res=await post('/api/agent-state/tasks',payload);
    if(res.success&&res.task){
      await loadAgentOsView();
      renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Creation failed')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }finally{
    if(typeof setButtonLoading==='function')setButtonLoading(btn, false);
  }
}

function renderMemoryModal(m){
  const key=m.key||'—';
  const scope=m.scope||'task';
  const kind=m.kind||'fact';
  const conf=m.confidence!==undefined?Math.round(m.confidence*100):100;
  const source=m.source||'agent';
  const created=m.created_at?new Date(m.created_at*1000).toLocaleString():'—';
  const updated=m.updated_at?new Date(m.updated_at*1000).toLocaleString():'—';

  let valStr='';
  if(typeof m.value==='object'){
    try{valStr=JSON.stringify(m.value,null,2)}catch{valStr=String(m.value)}
  }else{
    valStr=String(m.value??'');
  }

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">AGENT MEMORY ENTRY</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <strong>${esc(key)}</strong>
            <button class="copy-btn" onclick="copyText(${escJs(key)},this)">Copy Key</button>
          </h2>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <span class="chip ok">${esc(scope)}</span>
          <span class="chip">${esc(kind)}</span>
          <span class="chip ${conf>=80?'ok':'warn-t'}">${conf}% confidence</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Source: <b>${esc(source)}</b> · Recorded: ${created} · Updated: ${updated}</div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head">
          <span>Memory Value</span>
          <button class="copy-btn" onclick="copyText(${escJs(valStr)},this)">Copy Value</button>
        </div>
        <div class="modal-card-body">
          <pre class="code-box" style="margin:0">${esc(valStr)}</pre>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Actions</span></div>
        <div class="modal-card-body">
          <div class="modal-actions-bar" id="memActionRow">
            <button class="btn bad" onclick="$('confirmDelMemBox').style.display='flex';$('memActionRow').style.display='none'">🗑 Delete Memory</button>
          </div>
          <div id="confirmDelMemBox" style="display:none;align-items:center;gap:8px;padding:6px 10px;background:#1a1015;border:1px solid #7f1d1d;border-radius:4px">
            <span class="tiny" style="color:#fca5a5">Delete memory <b>${esc(m.key)}</b> (${esc(m.scope)})?</span>
            <button class="btn bad" onclick="deleteMemoryAction(${escJs(m.key)},${escJs(m.scope)})">Confirm Delete</button>
            <button class="btn" onclick="$('confirmDelMemBox').style.display='none';$('memActionRow').style.display='flex'">Cancel</button>
          </div>
          <div id="memoryActionStatus" class="tiny" style="margin-top:8px"></div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Memory JSON</summary><pre>${esc(JSON.stringify(m,null,2))}</pre></details>
    </div>
  `;
}

async function deleteMemoryAction(key,scope){
  const statusEl=$('memoryActionStatus');
  if(statusEl)statusEl.textContent='Deleting memory…';
  try{
    const res=await post('/api/agent-state/memory',{action:'delete',key:key,scope:scope});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="ok">✓ Memory deleted.</span>';
      await loadAgentOsView();
      setTimeout(()=>$('modalClose')?.click(),700);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to delete')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openRecordMemoryModal(){
  if($('modalTitle'))$('modalTitle').textContent='Record Agent Memory';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitRecordMemory(event)">
        <div class="form-group">
          <label for="newMemKey">Memory Key *</label>
          <input type="text" id="newMemKey" required placeholder="e.g. auth_service_port or prefer_relative_imports" autofocus>
          <span class="form-hint">A unique name for this memory in the selected scope.</span>
        </div>
        <div class="form-group">
          <label for="newMemVal">Memory Value *</label>
          <textarea id="newMemVal" rows="4" required placeholder="Text value or JSON object..."></textarea>
          <span class="form-hint">Task memory stays local to its task. Publish repository knowledge through Projects → Knowledge.</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="form-group">
            <label for="newMemScope">Scope</label>
            <select id="newMemScope">
              __MEMORY_CREATE_SCOPE_OPTIONS__
            </select>
          </div>
          <div class="form-group">
            <label for="newMemKind">Kind</label>
            <select id="newMemKind">
              __MEMORY_CREATE_KIND_OPTIONS__
            </select>
          </div>
        </div>
        <div class="form-group">
          <label for="newMemTaskId">Task ID (required for Task scope)</label>
          <input id="newMemTaskId" placeholder="task_…">
          <span class="form-hint">Use a task from the selected repository. Other scopes do not use this field.</span>
        </div>
        <div id="recordMemStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">Record Memory</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('newMemKey')?.focus(),50);
}

async function submitRecordMemory(e){
  e.preventDefault();
  const key=$('newMemKey')?.value?.trim();
  const rawVal=$('newMemVal')?.value?.trim();
  if(!key||rawVal===undefined)return;
  let val=rawVal;
  try{val=JSON.parse(rawVal)}catch{}
  const scope=$('newMemScope')?.value||'task';
  const kind=$('newMemKind')?.value||'fact';
  const statusEl=$('recordMemStatus');
  const taskId=$('newMemTaskId')?.value?.trim();
  if(scope==='task'&&!taskId){if(statusEl)statusEl.textContent='Task ID is required for Task scope.';return;}
  if(statusEl)statusEl.textContent='Saving memory…';

  try{
    const res=await post('/api/agent-state/memory',{
      action:'record',
      key:key,
      value:val,
      scope:scope,
      ...(scope==='task'?{task_id:taskId}:{}),
      kind:kind,
      confidence:1.0
    });
    if(res.success){
      await loadAgentOsView();
      renderMemoryModal(res.record||{key,value:val,scope,kind,confidence:1.0});
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to record')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }
}

function renderIncidentModal(i){
  const id=i.incident_id||'—';
  const errorClass=i.error_class||'Error';
  const op=i.operation_class||i.outcome?.tool_name||'agent';
  const msg=i.redacted_message||i.message||'—';
  const cause=i.root_cause||'—';
  const fix=i.verified_fix||'—';
  const status=String(i.status||(i.verified_fix?'resolved':'unresolved'));
  const isResolved=status==='resolved';
  const isIgnored=i.ignored===true||status==='ignored';
  if($('modalTitle'))$('modalTitle').textContent='Incident';

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">INCIDENT &amp; LESSON</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <span class="badge-status badge-error">${esc(errorClass)}</span>
            <span class="mono tiny muted">#${esc(id)}</span>
          </h2>
        </div>
        <div>
            <span class="badge-status ${isIgnored?'badge-waiting':isResolved?'badge-complete':'badge-waiting'}">${isIgnored?'IGNORED':isResolved?'✓ RESOLVED WITH FIX':'UNRESOLVED'}</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Operation: <b>${esc(op)}</b></div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Failure Description</span></div>
        <div class="modal-card-body">
          <div style="font-family:ui-monospace,monospace;font-size:11px;color:#fca5a5">${esc(msg)}</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Identified Root Cause</span></div>
        <div class="modal-card-body">
          <div style="font-size:12px">${esc(cause)}</div>
        </div>
      </div>

      <div class="modal-card" style="border-color:${isResolved?'var(--ok)':'#4c5840'}">
        <div class="modal-card-head" style="background:${isResolved?'#0c2e1f':'#131d2b'}">
          <span class="${isResolved?'ok':''}">Verified Prevention Rule / Fix</span>
          ${fix!=='—'?`<button class="copy-btn" onclick="copyText(${escJs(fix)},this)">Copy Fix</button>`:''}
        </div>
        <div class="modal-card-body">
          <div style="font-size:12px;font-weight:500;color:${isResolved?'#86efac':'var(--fg)'}">${esc(fix)}</div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Incident JSON</summary><pre>${esc(JSON.stringify(i,null,2))}</pre></details>
    </div>
  `;
}

function openCleanupModal(){
  if($('modalTitle'))$('modalTitle').textContent='Cleanup Stale Agent OS State';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Agent OS Maintenance</span></div>
        <div class="modal-card-body" style="font-size:12px;line-height:1.5">
          <p>Running bounded state cleanup will prune:</p>
          <ul style="margin:6px 0;padding-left:20px;color:var(--muted)">
            <li>Expired SSE live events older than the retention threshold.</li>
            <li>Completed and abandoned task checkpoints beyond compaction limit.</li>
            <li>Expired memory entries outside active TTL.</li>
          </ul>
          <p style="margin-bottom:0">Active tasks, verified anti-patterns and non-expired memories will <b>not</b> be touched.</p>
        </div>
      </div>
      <div id="cleanupStatus" class="tiny"></div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Cancel</button>
        <button class="btn warn" onclick="executeCleanupAction()">🧹 Execute Cleanup</button>
      </div>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
}

async function executeCleanupAction(){
  const statusEl=$('cleanupStatus');
  if(statusEl)statusEl.textContent='Running state cleanup…';
  try{
    const res=await post('/api/agent-state/cleanup',{});
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="diag-banner ok">
          <span style="font-size:16px">✅</span>
          <div>
            <b>Agent OS State Cleanup Completed</b>
            <div class="tiny" style="margin-top:8px">${renderAny(res)}</div>
          </div>
        </div>
        <div class="modal-actions-bar" style="justify-content:flex-end">
          <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
        </div>
      </div>
    `;
    await loadAgentOsView();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function renderLiveStreamModal(ev){
  const seq=ev.seq!==undefined?ev.seq:(ev.event_id||'—');
  const kind=ev.kind||ev.event_type||'event';
  const actor=ev.actor||ev.agent||'system';
  const timestamp=ev.timestamp||ev.created_at||0;
  const dt=timestamp?new Date(timestamp*1000).toLocaleString():'—';
  const streamId=ev.stream_id||'—';
  const p=ev.payload||ev;
  let taskId=p.task_id||(p.task&&p.task.task_id)||ev.task_id||'';

  let payloadStr='';
  try{payloadStr=JSON.stringify(p,null,2)}catch{payloadStr=String(p)}

  const dur=ev.duration_ms!==undefined?` · Duration: <b>${ms(ev.duration_ms)}</b>`:'';
  const status=ev.success!==undefined?` · Status: <span class="${ev.success?'ok':'bad-t'}"><b>${ev.success?'SUCCESS':'FAILURE'}</b></span>`:'';
  const action=ev.action?` · Action: <span class="mono"><b>${esc(ev.action)}</b></span>`:'';
  const stage=ev.stage?` · Stage: <span class="chip">${esc(ev.stage)}</span>`:'';
  const model=ev.model?` · Model: <span class="chip ok">${esc(ev.model)}</span>`:'';

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">LIVE EVENT INSPECTOR</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <span class="mono">Seq #${esc(seq)}</span>
            <span class="chip">${esc(kind)}</span>
          </h2>
        </div>
        <div class="tiny muted">
          Stream: <span class="mono">${esc(streamId)}</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Actor: <b>${esc(actor)}</b> · Time: ${dt}${action}${stage}${model}${dur}${status}</div>
    </div>
    <div class="modal-body-wrap">
      ${taskId?`
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#101a26;border:1px solid #1e354d;border-radius:6px">
          <span>Related Task: <b class="mono">${esc(taskId)}</b></span>
          <button class="btn ok" onclick="openTaskById(${escJs(taskId)})">↗ Open Task Inspector</button>
        </div>
      `:''}

      <div class="modal-card">
        <div class="modal-card-head">
          <span>Event Payload</span>
          <button class="copy-btn" onclick="copyText(${escJs(payloadStr)},this)">Copy Payload</button>
        </div>
        <div class="modal-card-body">
          <pre class="code-box" style="margin:0">${esc(payloadStr)}</pre>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Event Object</summary><pre>${esc(JSON.stringify(ev,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

async function openTaskById(taskId){
  try{
    const res=await post('/api/agent-state/tasks',{action:'get',task_id:taskId});
    if(res.success&&res.task){
      renderTaskModal(res.task);
    }else{
      alert('Task not found: '+taskId);
    }
  }catch(e){
    alert('Error loading task: '+e.message);
  }
}

function preprocessingProgress(p){
  const value=p.overall_progress_pct;
  return typeof value==='number'&&Number.isFinite(value)?Math.max(0,Math.min(100,value)):null;
}
function preprocessingCounts(p){
  const count=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
  const total=p.phase==='inventory'?null:count(p.files);
  const pair=value=>{const done=count(value);return {done,total,remaining:done!==null&&total!==null?Math.max(0,total-done):null};};
  return {hash:pair(p.hashed_files),code:pair(p.code_index_files),rag:pair(p.rag_files),cards:pair(p.file_cards)};
}
function preprocessingCountText(pair){
  if(pair.done===null)return 'Unavailable';
  if(pair.total===null)return `${n(pair.done)} files · total pending`;
  return `${n(pair.done)} / ${n(pair.total)} inventoried files`;
}
async function loadProjectDetails(project,generation){
  try{
    const result=await fetchDashboardJson('/api/preprocess/status?root='+encodeURIComponent(project.root));
    if(generation!==projectInspectorGeneration||!$('modalBg')?.classList.contains('open'))return;
    const detail=Array.isArray(result?.projects)?result.projects.find(item=>item.root===project.root):null;
    if(detail){activeProjectInspectorData={...activeProjectInspectorData,...detail};renderProjectModal(activeProjectInspectorData);}
    else if($('projectDetailStatus'))$('projectDetailStatus').textContent='Detailed status unavailable';
  }catch(e){
    if(generation===projectInspectorGeneration&&$('projectDetailStatus'))$('projectDetailStatus').textContent='Detailed status unavailable';
  }
}
function projectPhaseListHtml(p){
  const phaseCounts={hash:p.hashed_files,code_index:p.code_index_files,deterministic:p.deterministic_files,lexical:p.lexical_files,rag:p.rag_files,files:p.file_cards};
  return PHASES.map((step,index)=>{
    const current=step.id===p.phase,count=phaseCounts[step.id];
    const coverage=typeof count==='number'&&typeof p.files==='number'?`${n(count)} / ${n(p.files)} inventoried files`:'';
    const value=current?(p.phase_progress_measured!==false&&typeof p.phase_progress_pct==='number'?`${p.phase_progress_pct}% · ${p.active_detail||'In progress'}`:(p.active_detail||'Progress unavailable')):(coverage||'No per-phase history available');
    return `<div>${index+1}. ${esc(step.name)}</div><div>${esc(value)}</div>`;
  }).join('');
}
function renderProjectModal(p){
  const state=projectState(p);
  const isComplete=state==='ready';
  const overall=preprocessingProgress(p);
  const counts=preprocessingCounts(p);
  const astSymbols=typeof p.ast_symbols==='number'?p.ast_symbols:typeof p.symbols_count==='number'?p.symbols_count:null;
  const badge={
    running:['badge-running','Running'],
    waiting:['badge-waiting','Waiting'],
    paused:['badge-paused','Paused'],
    error:['badge-error','Error'],
    ready:['badge-complete','Ready']
  }[state]||['badge-waiting','Queued'];

  const stepperHtml=renderStepper(p.phase_index||1,isComplete,state);

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">PREPROCESSED REPOSITORY WORKSPACE</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <b>${esc(p.project)}</b>
            <button class="copy-btn" onclick="copyText(${escJs(p.root)},this)">Copy Path</button>
          </h2>
          <div class="tiny mono muted" style="margin-top:3px">${esc(p.root)}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span id="projectLiveBadge" class="badge-status ${badge[0]}">${badge[1]}</span>
          <span class="chip" id="projectLiveOverall">${overall===null?'Overall estimate unavailable':`${overall}% estimated overall`}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Current work and cache</span></div>
        <div class="modal-card-body"><div class="kv" style="padding:0">
          <div>Phase progress</div><div id="projectLiveProgress">${p.phase_progress_measured===false?'Unavailable':typeof p.phase_progress_pct==='number'?esc(p.phase_progress_pct)+'%':'Unavailable'}</div>
          <div>Current phase</div><div id="projectLivePhase">${esc(p.phase||'Unavailable')}</div>
          <div>Current activity</div><div id="projectLiveActivity">${esc(p.active_detail||p.waiting_reason||'Unavailable')}</div>
          <div>Files changed in last inventory</div><div>${typeof p.stats?.changed_files==='number'?n(p.stats.changed_files):'Unavailable'}</div>
          <div>Major change detected</div><div>${typeof p.stats?.major_change==='boolean'?(p.stats.major_change?'Yes':'No'):'Unavailable'}</div>
          <div>Incremental watcher</div><div>${typeof p.stats?.incremental_watcher==='boolean'?(p.stats.incremental_watcher?'Used':'Not used'):'Unavailable'}</div>
          <div>Cards awaiting enrichment</div><div>${typeof p.pending_stub_cards==='number'?n(p.pending_stub_cards):'Unavailable'}</div>
          <div>External indexes</div><div>${p.external_indexes?esc(JSON.stringify(p.external_indexes)):'Unavailable'}</div>
          <div>Last error</div><div>${esc(Object.hasOwn(p,'last_error')?(p.last_error||'None reported'):'Unavailable')}</div>
        </div><div id="projectDetailStatus" class="tiny muted">${p.stats?'Full project status':'Loading detailed status…'}</div></div>
      </div>
      <div class="modal-card">
        <div class="modal-card-head"><span>Pipeline phase order</span></div>
        <div class="modal-card-body">
          <div id="projectLiveStepper">${stepperHtml}</div>
          <div class="tiny muted">Earlier phases may have been skipped or reused; the stepper shows order, not evidence that each phase ran.</div>
          <div class="kv" id="projectPhaseList" style="padding:10px 0">${projectPhaseListHtml(p)}</div>
          <div class="bar" style="margin-top:10px"><i id="projectLiveBar" style="width:${overall??0}%;background:${state==='error'?'var(--bad)':isComplete?'var(--ok)':'var(--accent)'}"></i></div>
          <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px">
            <span class="tiny muted">Phase: <b id="projectPhaseLabel">${esc(p.phase||'Inventory')}</b></span>
            <span class="tiny muted" id="projectPhaseDetail">${esc(p.active_detail||(isComplete?'All phases synchronized':'Processing pipeline'))}</span>
          </div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Index Breakdown &amp; Diagnostics</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Inventoried files</div><div><b>${counts.hash.total===null?'Unavailable':n(counts.hash.total)}</b></div>
            <div>Content hashed</div><div><b id="projectLiveHash">${preprocessingCountText(counts.hash)}</b></div>
            <div>Code index coverage</div><div><b id="projectLiveCode">${preprocessingCountText(counts.code)}</b> <span class="muted">(demand indexed)</span></div>
            <div>AST Code Symbols</div><div><b>${astSymbols===null?'Unavailable':n(astSymbols)}</b>${astSymbols===null?'':' declarations indexed'}</div>
            <div>RAG files</div><div><b id="projectLiveRag">${preprocessingCountText(counts.rag)}</b></div>
            <div>Semantic context cards</div><div><b id="projectLiveCards">${preprocessingCountText(counts.cards)}</b></div>
            <div>Current phase</div><div id="projectLiveBreakdownPhase">${esc(p.active_detail||p.phase||'Unavailable')}</div>
            <div>Rate / phase estimate</div><div id="projectLiveRate">${esc(p.speed_str||'Unavailable')} · ${esc(p.phase==='rag'?'Estimate unavailable':p.eta_str||'Unavailable')}</div>
            <div>Last Activity Checkpoint</div><div>${p.updated_at?new Date(p.updated_at*1000).toLocaleString():typeof p.progress_age_seconds==='number'?`${durSec(p.progress_age_seconds)} ago`:'Unavailable'}</div>
          </div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span style="display:flex;align-items:center;gap:6px">⚙️ Project Settings &amp; Configuration (.local-ai.toml)</span></div>
        <div class="modal-card-body" id="modalProjectSettingsBody">
          <div class="tiny muted">Loading project settings…</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Workspace Controls</span></div>
        <div class="modal-card-body">
          <div class="modal-actions-bar">
            <button class="btn" onclick="projectAction(${escJs(p.root)},'${state==='paused'?'resume':'pause'}');$('modalClose')?.click()">${state==='paused'?'Resume indexing':'⏸ Pause Preprocessing'}</button>
            <button class="btn ok" onclick="projectAction(${escJs(p.root)},'refresh');$('modalClose')?.click()">↻ Force Re-scan</button>
            <button class="btn" onclick="exportBundle(${escJs(p.root)})">📦 Export Bundle</button>
            <button class="btn bad" style="margin-left:auto" onclick="deleteProjectDialog(${escJs(p.root)},${escJs(p.project)})">🗑 Unregister / Delete</button>
          </div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Project Metadata</summary><pre>${esc(JSON.stringify(p,null,2))}</pre></details>
    </div>
  `;
  loadProjectSettings(p.root);
}

