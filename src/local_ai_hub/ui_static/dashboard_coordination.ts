// @ts-nocheck
// ── Coordination, Project Board & Resource Semaphores ────────────────────────
let cachedBoardItems = [];
let cachedPlanItems = [];
let cachedPlanBoard = null;
let cachedSemaphores = {};
let coordinationLoadErrors={},coordinationLoadGeneration=0;
function coordinationUnavailable(key){return `<div class="diag-banner bad" role="status">Coordination unavailable: ${esc(coordinationLoadErrors[key])}. Refresh to retry.</div>`}

function renderCoordPlanFilter(plans,preferredPlanId){
  const select=$('coordBoardPlan');
  const invalid=(Array.isArray(plans)?plans:[]).filter(plan=>plan?.invalid);
  const warning=$('coordPlanWarnings');
  if(warning)warning.textContent=invalid.length?`${invalid.length} invalid plan file(s) were skipped: ${invalid.map(plan=>plan.rel_path||'unknown file').join(', ')}. Fix the files before editing those plans.`:'';
  if(!select)return;
  const previous=typeof preferredPlanId==='string'&&preferredPlanId?preferredPlanId:select.value;
  const valid=(Array.isArray(plans)?plans:[]).filter(plan=>plan&&!plan.invalid&&plan.id);
  const invalidOptions=invalid.map(plan=>`<option disabled>${esc(plan.rel_path||'Invalid plan')}</option>`).join('');
  select.innerHTML='<option value="">All plans</option>'+valid.map(plan=>`<option value="${esc(plan.id)}">${esc(plan.title||plan.id)} · ${esc(plan.lifecycle||'draft')}</option>`).join('')+invalidOptions;
  select.value=valid.some(plan=>plan.id===previous)?previous:'';
  const edit=$('coordEditPlanBtn');
  if(edit)edit.disabled=!select.value;
}

async function loadCoordinationView(preferredPlanId){
    const generation=++coordinationLoadGeneration;
    const root=String($('coordBoardRoot')?.value||'').trim();
    const planSelect=$('coordBoardPlan');
    let plansResult={success:false,error:root?'Plan list unavailable':'Choose a repository or worktree root.'};
    if(root){
      try{plansResult=await fetchDashboardJson('/api/coord/plan_list',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root})})}
      catch(error){plansResult={success:false,error:String(error?.message||error)}}
    }
    if(generation!==coordinationLoadGeneration)return;
    cachedPlanItems=plansResult.success===true&&Array.isArray(plansResult.plans)?plansResult.plans:[];
    renderCoordPlanFilter(cachedPlanItems,preferredPlanId);
    try{if(root)localStorage.setItem('local-ai-hub.coordBoardRoot',root)}catch{}
    const planId=String(planSelect?.value||'').trim();
    const boardRequest=root&&plansResult.success===true
      ?fetchDashboardJson('/api/coord/plan_board_view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root,plan_id:planId})})
      :Promise.resolve({success:false,error:plansResult.error||'Choose a repository or worktree root.'});
    const [boardRes, semRes] = await Promise.allSettled([
      boardRequest,
      fetchDashboardJson('/api/coord/semaphore_status', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    ]);
    if(generation!==coordinationLoadGeneration)return;
    coordinationLoadErrors={};
    for(const [key,result] of [['board',boardRes],['semaphores',semRes]]){
      if(result.status==='fulfilled'&&result.value?.success===true)continue;
      const error=result.status==='rejected'?result.reason:result.value?.error||'Invalid server response';
      coordinationLoadErrors[key]=String(error?.message||error);
    }
    if(!root)coordinationLoadErrors.board='Choose a repository or worktree root. The global legacy board is not used.';
    if(plansResult.success!==true)coordinationLoadErrors.board=String(plansResult.error||'Could not load repository plans');
    cachedPlanBoard=coordinationLoadErrors.board?null:boardRes.value;
    cachedBoardItems=coordinationLoadErrors.board?[]:Object.entries(cachedPlanBoard?.columns||{}).flatMap(([status,items])=>
      (Array.isArray(items)?items:[]).map(item=>({...item,item_id:item.task_id,status}))
    );
    cachedSemaphores=coordinationLoadErrors.semaphores?{}:(semRes.value.semaphores||{});
    if(!Array.isArray(cachedBoardItems)||cachedBoardItems.some(item=>!item||typeof item!=='object')){cachedBoardItems=[];coordinationLoadErrors.board='Invalid board data'}
    if(!cachedSemaphores||typeof cachedSemaphores!=='object'||Array.isArray(cachedSemaphores)||Object.values(cachedSemaphores).some(item=>!item||typeof item!=='object')){cachedSemaphores={};coordinationLoadErrors.semaphores='Invalid semaphore data'}
    renderKanbanBoard();
    renderSemaphoresTable();
    renderPlanProgressView();
    updateCoordOverviewCards();
}

let kanbanCompact = true;
const expandedCardIds = new Set();

function toggleKanbanCompact(){
  kanbanCompact = !kanbanCompact;
  const btn = $('coordCompactBtn');
  if(btn) btn.textContent = kanbanCompact ? '▤ Compact (On)' : '▤ Compact (Off)';
  renderKanbanBoard();
}

function toggleCardCompact(taskId){
  if(expandedCardIds.has(taskId)) expandedCardIds.delete(taskId);
  else expandedCardIds.add(taskId);
  renderKanbanBoard();
}

function renderKanbanBoard(){
  const query = String($('coordBoardSearch')?.value || '').trim().toLowerCase();
  const container = $('kanbanBoardContainer');
  if(!container) return;
  if(coordinationLoadErrors.board){if($('coordBoardSummaryText'))$('coordBoardSummaryText').textContent='Board unavailable';container.innerHTML=coordinationUnavailable('board');return}

  const labels={planned:'Planned',ready:'Ready',in_progress:'In Progress',blocked:'Blocked',source_ready:'Source Ready',done:'Done'};
  const icons={planned:'📋',ready:'🟦',in_progress:'⚡',blocked:'⛔',source_ready:'📦',done:'✅'};
  const cols=Object.keys(cachedPlanBoard?.columns||{}).map(key=>({key,label:labels[key]||key.replaceAll('_',' '),icon:icons[key]||'•'}));

  const filtered = cachedBoardItems.filter(item => {
    if(!query) return true;
    const text = [item.task_id,item.title,item.description,item.status,item.plan_title,item.accountable_role,item.next_action,item.blocker].join(' ').toLowerCase();
    return text.includes(query);
  });

  const counts = {};
  cols.forEach(c => counts[c.key] = 0);
  filtered.forEach(item => {
    const st = String(item.status || 'planned').toLowerCase();
    counts[st] = (counts[st] || 0) + 1;
  });

  if($('coordBoardSummaryText'))$('coordBoardSummaryText').textContent=`${cachedPlanBoard?.project_root||''} · ${planIdLabel()} · ${filtered.length} tasks · ${counts.in_progress||0} active · ${counts.blocked||0} blocked`;

  container.innerHTML = cols.map(c => {
    const colItems = filtered.filter(item => String(item.status || 'planned').toLowerCase() === c.key);
    const cardsHtml = colItems.length ? colItems.map(item => {
      const accountable=item.accountable_role||'';
      const moveable=['planned','ready','in_progress','blocked'];
      const moveOptions=moveable.map(status=>`<option value="${status}" ${status===c.key?'selected':''}>${esc(labels[status]||status)}</option>`).join('');
      const statusControl=moveable.includes(c.key)
        ?`<select class="action-btn-sm" aria-label="Move task status" style="font-size:11px;padding:2px 6px;height:26px" onchange="updateCardStatus(this.dataset.planId,this.dataset.taskId,this.value)" data-plan-id="${esc(item.plan_id)}" data-task-id="${esc(item.task_id)}">${moveOptions}</select>`
        :`<span class="chip ${item.verified===true?'ok':'warn-t'}" title="${item.verified===true?'Verification confirmed':'File status is a declaration; verification is pending'}">${esc(labels[c.key]||c.key)} · ${item.verified===true?'Verified':'Unverified'}</span>`;

      const isCompact = typeof kanbanCompact !== 'undefined' ? kanbanCompact : true;
      const isExpanded = typeof expandedCardIds !== 'undefined' && expandedCardIds.has(item.task_id);
      const hasCollapsible = Boolean(item.description || item.next_action || item.blocker);

      return `
        <div class="kanban-card ${isCompact ? 'compact' : ''} ${isExpanded ? 'expanded' : ''}" data-item-id="${esc(item.task_id)}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:6px">
            <button type="button" class="kanban-card-title" style="border:0;background:none;color:inherit;text-align:left;cursor:pointer;padding:0" onclick="editPlanTask(this.dataset.planId,this.dataset.taskId)" data-plan-id="${esc(item.plan_id)}" data-task-id="${esc(item.task_id)}">${esc(item.title||item.task_id)}</button>
            <div style="display:flex;align-items:center;gap:4px">
              <span class="chip mono" style="font-size:10px">${esc(item.task_id)}</span>
              ${isCompact && hasCollapsible ? `<button type="button" class="kanban-card-toggle" data-task-id="${esc(item.task_id)}" onclick="toggleCardCompact(this.dataset.taskId)" title="${isExpanded ? 'Collapse card' : 'Expand card'}">${isExpanded ? '▲' : '▼'}</button>` : ''}
            </div>
          </div>
          <div class="kanban-card-meta">
            <span class="chip" title="Plan">📁 ${esc(item.plan_title||item.plan_id)}</span>
            ${accountable?`<span class="chip" title="Accountable role">👤 ${esc(accountable)}</span>`:''}
            ${item.work_phase?`<span class="chip">${esc(String(item.work_phase).replaceAll('_',' '))}</span>`:''}
          </div>
          ${hasCollapsible ? `
          <div class="kanban-card-collapsible">
            ${item.description?`<p class="tiny muted" style="margin:2px 0">${esc(item.description)}</p>`:''}
            ${item.next_action?`<p class="tiny" style="margin:2px 0"><b>Next:</b> ${esc(item.next_action)}</p>`:''}
            ${item.blocker?`<p class="tiny bad-t" style="margin:2px 0"><b>Blocked:</b> ${esc(item.blocker)}</p>`:''}
          </div>
          ` : ''}
          <div class="kanban-card-actions">
            ${statusControl}
            <button class="action-btn-sm danger" style="padding:2px 7px;font-size:11px" onclick="deletePlanTask(this.dataset.planId,this.dataset.taskId)" data-plan-id="${esc(item.plan_id)}" data-task-id="${esc(item.task_id)}">Delete</button>
          </div>
        </div>
      `;
    }).join('') : '<div class="empty tiny" style="padding:24px 8px">No cards</div>';

    return `
      <div class="kanban-col col-${c.key}">
        <div class="kanban-col-head">
          <span>${c.icon} ${c.label}</span>
          <span class="chip">${counts[c.key] || 0}</span>
        </div>
        <div class="kanban-cards">
          ${cardsHtml}
        </div>
      </div>
    `;
  }).join('');
}

function planIdLabel(){const selected=$('coordBoardPlan')?.value||'';return selected?(cachedPlanItems.find(plan=>plan.id===selected)?.title||selected):'All plans'}

function renderSemaphoresTable(){
  const body = $('coordSemaphoresBody');
  if(!body) return;
  if(coordinationLoadErrors.semaphores){if($('coordSemSummary'))$('coordSemSummary').textContent='Semaphores unavailable';body.innerHTML=`<tr><td colspan="6">${coordinationUnavailable('semaphores')}</td></tr>`;return}
  const list = Object.values(cachedSemaphores);
  if($('coordSemSummary')) $('coordSemSummary').textContent = `${list.length} registered semaphores`;
  if(!list.length){
    body.innerHTML = '<tr><td colspan="6" class="empty">No semaphores configured yet. Use "+ Acquire Semaphore" to create one.</td></tr>';
    return;
  }
  body.innerHTML = list.map(s => {
    const active = s.active_count || (s.active_holders || []).length || 0;
    const cap = s.capacity || 1;
    const ratio = `${active} / ${cap}`;
    const badge = active >= cap ? '<span class="chip bad-t">Full (Locked)</span>' : (active > 0 ? '<span class="chip warn-t">Partially Held</span>' : '<span class="chip ok">Available</span>');
    const holdersHtml = (s.active_holders || []).map(h => {
      const exp = Math.max(0, Math.round((h.expires_at || 0) - (Date.now() / 1000)));
      return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0"><span class="chip mono">${esc(h.owner || 'agent')} (${exp}s)</span> <button class="action-btn-sm danger" style="padding:1px 5px;font-size:10px" onclick="releaseSemaphore(this.dataset.name, this.dataset.leaseId)" data-name="${esc(s.name)}" data-lease-id="${esc(h.lease_id)}">Release</button></div>`;
    }).join('') || '<span class="muted tiny">None</span>';
    const qLen = s.queue_length || 0;
    const qBadge = qLen > 0 ? `<span class="chip warn-t">${qLen} waiting</span>` : '<span class="muted tiny">0</span>';
    const act = `<button class="action-btn-sm" onclick="quickAcquireSem(this.dataset.name, ${cap})" data-name="${esc(s.name)}">+ Acquire</button>`;
    return `<tr><td><strong>${esc(s.name)}</strong></td><td>${cap}</td><td>${badge} <span class="tiny mono">(${ratio})</span></td><td>${holdersHtml}</td><td>${qBadge}</td><td>${act}</td></tr>`;
  }).join('');
}

function renderPlanProgressView(){
  const grid = $('coordPlanProgressGrid');
  if(!grid) return;
  if(coordinationLoadErrors.board){if($('coordPlanProgressSummary'))$('coordPlanProgressSummary').textContent='Plan progress unavailable';grid.innerHTML=coordinationUnavailable('board');return}
  if($('coordPlanProgressSummary'))$('coordPlanProgressSummary').textContent='Progress by plan in the selected repository/worktree';
  const planMap = Object.create(null);
  cachedBoardItems.forEach(item => {
    const key = String(item.plan_id || '');
    if(!key) return;
    if(!planMap[key]) planMap[key] = {title: String(item.plan_title || key), total: 0, done: 0, verified_done: 0, in_progress: 0, blocked: 0, planned: 0, ready: 0, source_ready: 0};
    planMap[key].total++;
    const st = String(item.work_status || item.status || 'planned').toLowerCase();
    if(Object.prototype.hasOwnProperty.call(planMap[key], st) && st !== 'total') planMap[key][st]++;
    else planMap[key].planned++;
    if(st === 'done' && item.verified === true) planMap[key].verified_done++;
  });

  const keys = Object.keys(planMap);
  if(!keys.length){
    grid.innerHTML = '<div class="empty" style="grid-column:1/-1">No tasks in the selected plan. Choose another plan or add a task.</div>';
    return;
  }

  grid.innerHTML = keys.map(k => {
    const data = planMap[k];
    const pct = data.total > 0 ? Math.round((data.verified_done / data.total) * 100) : 0;
    return `
      <div class="milestone-card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <strong style="font-size:14px">▤ ${esc(data.title)} <span class="muted tiny mono">${esc(k)}</span></strong>
          <span class="chip ${pct === 100 ? 'ok' : (pct > 0 ? 'warn-t' : '')}">${pct}% verified complete</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
        <div class="tiny" style="display:flex;gap:8px;flex-wrap:wrap">
          <span class="chip ok">✅ ${data.verified_done} verified done</span>
          ${data.done > data.verified_done ? `<span class="chip warn-t">${data.done - data.verified_done} awaiting verification</span>` : ''}
          <span class="chip">⚡ ${data.in_progress} In Progress</span>
          <span class="chip">📋 ${data.planned} Planned</span>
          ${data.ready ? `<span class="chip">◉ ${data.ready} Ready</span>` : ''}
          ${data.source_ready ? `<span class="chip">⇧ ${data.source_ready} Source Ready</span>` : ''}
          ${data.blocked ? `<span class="chip bad-t">⛔ ${data.blocked} Blocked</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function updateCoordOverviewCards(){
  if($('overviewBoardCount')){
    const inProg = cachedBoardItems.filter(i => String(i.status || '').toLowerCase() === 'in_progress').length;
    $('overviewBoardCount').textContent = coordinationLoadErrors.board?'—':`${inProg} / ${cachedBoardItems.length}`;
  }
  if($('overviewBoardSub')){
    const blocked = cachedBoardItems.filter(i => String(i.status || '').toLowerCase() === 'blocked').length;
    $('overviewBoardSub').textContent = coordinationLoadErrors.board?'Board unavailable':`${cachedBoardItems.length} items${blocked ? ` · ${blocked} blocked` : ' · healthy'}`;
  }
  if($('overviewSemCount')){
    const sems = Object.values(cachedSemaphores);
    const held = sems.filter(s => (s.active_count || 0) > 0).length;
    $('overviewSemCount').textContent = coordinationLoadErrors.semaphores?'—':`${held} / ${sems.length}`;
  }
  if($('overviewSemSub')){
    $('overviewSemSub').textContent = coordinationLoadErrors.semaphores?'Semaphores unavailable':`${Object.keys(cachedSemaphores).length} semaphores configured`;
  }
}

function coordOperationId(prefix){
  const randomId=globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomId}`;
}

async function updateCardStatus(planId, taskId, newStatus){
  const root=String($('coordBoardRoot')?.value||'').trim();
  const item=cachedBoardItems.find(entry=>entry.plan_id===planId&&entry.task_id===taskId);
  if(!root||!item)return;
  try{
    const res=await post('/api/coord/plan_task_edit',{
      root,plan_id:planId,task_id:taskId,expected_revision:item.plan_file_revision,
      task_data:{work_status:newStatus},owner:'dashboard',idempotency_key:coordOperationId(`status-${taskId}`)
    });
    if(res.success===false)throw new Error(res.error||'Failed to update plan task');
    await loadCoordinationView();
  }catch(e){
    alert('Failed to update plan task: '+(e.message||e));
  }
}

async function deletePlanTask(planId,taskId){
  const root=String($('coordBoardRoot')?.value||'').trim();
  const item=cachedBoardItems.find(entry=>entry.plan_id===planId&&entry.task_id===taskId);
  if(!root||!item||!confirm(`Delete task "${taskId}" from plan "${item.plan_title||planId}"?`))return;
  try{
    const res=await post('/api/coord/plan_task_delete',{
      root,plan_id:planId,task_id:taskId,expected_revision:item.plan_file_revision,
      owner:'dashboard',idempotency_key:coordOperationId(`delete-${taskId}`)
    });
    if(res.success===false)throw new Error(res.error||'Failed to delete plan task');
    await loadCoordinationView();
  }catch(e){
    alert('Failed to delete plan task: '+(e.message||e));
  }
}

async function releaseSemaphore(name, leaseId){
  if(!confirm(`Release semaphore "${name}" (lease ${leaseId})?`)) return;
  try{
    const res = await post('/api/coord/semaphore_release', {name, lease_id: leaseId});
    if(res.success === false) throw new Error(res.error || 'Failed to release');
    await loadCoordinationView();
  }catch(e){
    alert('Failed to release semaphore: ' + (e.message || e));
  }
}

async function quickAcquireSem(name, capacity){
  const owner = prompt('Enter holder/owner ID:', 'agent_' + Math.random().toString(36).slice(2, 7));
  if(!owner) return;
  try{
    const res = await post('/api/coord/semaphore_acquire', {name, owner, capacity, ttl_seconds: 300});
    if(res.acquired){
      alert(`Acquired lock! Lease ID: ${res.lease_id}`);
    }else{
      alert(`Could not acquire: ${res.reason || 'Capacity reached'}`);
    }
    await loadCoordinationView();
  }catch(e){
    alert('Acquire error: ' + (e.message || e));
  }
}

let activePlanTaskEdit=null;

function openCreatePlanModal(){
  const root=String($('coordBoardRoot')?.value||'').trim();
  if(!root){alert('Choose a repository or worktree root first.');return}
  if($('modalTitle'))$('modalTitle').textContent='Create Repository Plan';
  if($('modalLive'))$('modalLive').textContent='Saved directly to .local-ai-hub/plans in this repository.';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap"><form class="modal-form" onsubmit="submitCreatePlan(event)">
      <div class="form-group"><label for="newPlanTitle">Plan name *</label><input id="newPlanTitle" required maxlength="160" autofocus placeholder="e.g. Project planning and delivery"></div>
      <div class="form-group"><label for="newPlanId">Stable plan ID *</label><input id="newPlanId" required pattern="plan_[A-Za-z0-9][A-Za-z0-9_\\-]{0,79}" maxlength="85" placeholder="plan_project-planning"><span class="form-hint">Start with plan_, followed by letters, digits, underscores or hyphens. Keep this ID stable.</span></div>
      <div class="form-group"><label for="newPlanDescription">Description</label><textarea id="newPlanDescription" rows="4" maxlength="12000"></textarea></div>
      <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px"><button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button><button type="submit" class="btn ok">Create Plan</button></div>
    </form></div>`;
  const title=$('newPlanTitle'),id=$('newPlanId');
  title?.addEventListener('input',()=>{if(id&&!id.dataset.edited){const slug=title.value.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,80);id.value='plan_'+(slug||'new')}});
  id?.addEventListener('input',()=>{id.dataset.edited='true'});
  $('modalBg')?.classList.add('open');
}

async function submitCreatePlan(e){
  e.preventDefault();
  const root=String($('coordBoardRoot')?.value||'').trim();
  const plan_id=$('newPlanId')?.value?.trim();
  const title=$('newPlanTitle')?.value?.trim();
  const description=$('newPlanDescription')?.value||'';
  if(!root||!plan_id||!title)return;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Creating…');
  try{
    const res=await post('/api/coord/plan_create',{root,plan_id,title,description,lifecycle:'active',owner:'dashboard',idempotency_key:coordOperationId(`create-${plan_id}`)});
    if(res.success===false)throw new Error(res.error||'Could not create plan');
    $('modalClose')?.click();
    await loadCoordinationView(plan_id);
  }catch(error){alert('Create plan failed: '+(error.message||error))}
  finally{if(typeof setButtonLoading==='function')setButtonLoading(btn, false);}
}

function openEditPlanModal(){
  const planId=String($('coordBoardPlan')?.value||'');
  const plan=cachedPlanItems.find(item=>item.id===planId);
  if(!plan){alert('Select a plan first.');return}
  if($('modalTitle'))$('modalTitle').textContent='Edit Plan';
  if($('modalLive'))$('modalLive').textContent=`Plan file revision ${plan.file_revision||'unknown'}`;
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap"><form class="modal-form" onsubmit="submitPlanUpdate(event)">
      <div class="form-group"><label>Stable plan ID</label><input value="${esc(plan.id)}" disabled></div>
      <div class="form-group"><label for="editPlanTitle">Plan name *</label><input id="editPlanTitle" required maxlength="160" value="${esc(plan.title||'')}"></div>
      <div class="form-group"><label for="editPlanDescription">Description</label><textarea id="editPlanDescription" rows="5" maxlength="12000">${esc(plan.description||'')}</textarea></div>
      <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px"><button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button><button type="submit" class="btn ok">Save Plan</button></div>
    </form></div>`;
  $('modalBg')?.classList.add('open');
}

async function submitPlanUpdate(e){
  e.preventDefault();
  const planId=String($('coordBoardPlan')?.value||'');
  const plan=cachedPlanItems.find(item=>item.id===planId);
  const root=String($('coordBoardRoot')?.value||'').trim();
  if(!root||!plan)return;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Saving…');
  try{
    const res=await post('/api/coord/plan_update',{root,plan_id:planId,expected_revision:plan.file_revision,title:$('editPlanTitle')?.value?.trim(),description:$('editPlanDescription')?.value||'',owner:'dashboard',idempotency_key:coordOperationId(`update-${planId}`)});
    if(res.success===false)throw new Error(res.error||'Could not update plan');
    $('modalClose')?.click();
    await loadCoordinationView();
  }catch(error){alert('Update plan failed: '+(error.message||error))}
  finally{if(typeof setButtonLoading==='function')setButtonLoading(btn, false);}
}

function openAddCardModal(){
  const planId=String($('coordBoardPlan')?.value||'');
  const plan=cachedPlanItems.find(item=>item.id===planId);
  if(!String($('coordBoardRoot')?.value||'').trim()){alert('Choose a repository or worktree root first.');return}
  if(!plan){alert('Select one plan before adding a task.');return}
  if($('modalTitle'))$('modalTitle').textContent=`Add Task · ${plan.title||planId}`;
  if($('modalLive'))$('modalLive').textContent='Task will be saved to the selected plan file.';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap"><form class="modal-form" onsubmit="submitAddCard(event)">
      <div class="form-group"><label for="newCardTitle">Task title *</label><input id="newCardTitle" required maxlength="240" autofocus></div>
      <div class="form-group"><label for="newCardDescription">Description</label><textarea id="newCardDescription" rows="4" maxlength="12000"></textarea></div>
      <div class="form-group"><label for="newCardStatus">Work status</label><select id="newCardStatus"><option value="planned">Planned</option><option value="ready">Ready</option><option value="in_progress">In Progress</option><option value="blocked">Blocked</option></select></div>
      <div class="form-group"><label for="newCardOwner">Accountable role</label><input id="newCardOwner" maxlength="120" placeholder="e.g. integrator"></div>
      <div class="form-group"><label for="newCardNextAction">Next action</label><textarea id="newCardNextAction" rows="2" maxlength="2000"></textarea></div>
      <div class="form-group"><label for="newCardAcceptance">Acceptance criteria (one per line)</label><textarea id="newCardAcceptance" rows="4" maxlength="8000"></textarea></div>
      <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px"><button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button><button type="submit" class="btn ok">Create Task</button></div>
    </form></div>`;
  $('modalBg')?.classList.add('open');
}

async function submitAddCard(e){
  e.preventDefault();
  const root=String($('coordBoardRoot')?.value||'').trim();
  const planId=String($('coordBoardPlan')?.value||'');
  const plan=cachedPlanItems.find(item=>item.id===planId);
  const title=$('newCardTitle')?.value?.trim();
  if(!root||!plan||!title)return;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Creating…');
  const task_id=`task_${coordOperationId('dashboard').replace(/[^a-zA-Z0-9_-]/g,'_')}`;
  const task_data={title,description:$('newCardDescription')?.value||'',kind:'code',work_status:$('newCardStatus')?.value||'planned',depends_on:[],clarifications:[],acceptance_criteria:String($('newCardAcceptance')?.value||'').split(/\r?\n/).map(line=>line.trim()).filter(Boolean),next_action:$('newCardNextAction')?.value?.trim()||'',blocker:null,accountable_role:$('newCardOwner')?.value?.trim()||undefined};
  try{
    const res=await post('/api/coord/plan_task_edit',{root,plan_id:planId,task_id,task_data,expected_revision:plan.file_revision,owner:'dashboard',idempotency_key:coordOperationId(`create-${task_id}`)});
    if(res.success===false)throw new Error(res.error||'Could not create task');
    $('modalClose')?.click();
    await loadCoordinationView();
  }catch(error){alert('Create task failed: '+(error.message||error))}
  finally{if(typeof setButtonLoading==='function')setButtonLoading(btn, false);}
}

async function editPlanTask(planId,taskId){
  const root=String($('coordBoardRoot')?.value||'').trim();
  if(!root)return;
  try{
    const res=await post('/api/coord/plan_get',{root,plan_id:planId});
    if(res.success===false||!res.plan)throw new Error(res.error||'Could not load plan task');
    const task=res.plan.tasks?.[taskId];
    if(!task)throw new Error(`Task ${taskId} no longer exists`);
    activePlanTaskEdit={root,planId,taskId,revision:res.file_revision};
    const statusOptions=['planned','ready','in_progress','blocked'];
    const statusEditor=statusOptions.includes(task.work_status)
      ?`<div class="form-group"><label for="editTaskStatus">Work status</label><select id="editTaskStatus">${statusOptions.map(status=>`<option value="${status}" ${status===task.work_status?'selected':''}>${status.replaceAll('_',' ')}</option>`).join('')}</select></div>`
      :`<p class="tiny warn-t">${esc(task.work_status)} is saved in the plan and cannot be changed in this dialog.${['done','source_ready'].includes(task.work_status)?' Completion and delivery are not verified by this declaration.':''}</p>`;
    const clarifications=Array.isArray(task.clarifications)?task.clarifications:[];
    if($('modalTitle'))$('modalTitle').textContent=`Edit Task · ${taskId}`;
    if($('modalLive'))$('modalLive').textContent=`Plan ${res.plan.title||planId} · file revision ${res.file_revision}`;
    if($('modalBody'))$('modalBody').innerHTML=`
      <div class="modal-body-wrap"><form class="modal-form" onsubmit="submitPlanTaskEdit(event)">
        <div class="form-group"><label for="editTaskTitle">Title *</label><input id="editTaskTitle" required maxlength="240" value="${esc(task.title||'')}"></div>
        <div class="form-group"><label for="editTaskDescription">Description</label><textarea id="editTaskDescription" rows="4" maxlength="12000">${esc(task.description||'')}</textarea></div>
        ${statusEditor}
        <div class="form-group"><label for="editTaskOwner">Accountable role</label><input id="editTaskOwner" maxlength="120" value="${esc(task.accountable_role||'')}"></div>
        <div class="form-group"><label for="editTaskNextAction">Next action</label><textarea id="editTaskNextAction" rows="2" maxlength="2000">${esc(task.next_action||'')}</textarea></div>
        <div class="form-group"><label for="editTaskBlocker">Blocker</label><textarea id="editTaskBlocker" rows="2" maxlength="2000">${esc(typeof task.blocker==='string'?task.blocker:(task.blocker?.message||''))}</textarea></div>
        <div class="form-group"><label for="editTaskAcceptance">Acceptance criteria (one per line)</label><textarea id="editTaskAcceptance" rows="4" maxlength="8000">${esc((task.acceptance_criteria||[]).join('\n'))}</textarea></div>
        ${clarifications.length?`<details><summary>${clarifications.length} saved clarification(s)</summary><pre class="tiny">${esc(JSON.stringify(clarifications,null,2))}</pre></details>`:''}
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px"><button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button><button type="submit" class="btn ok">Save Task</button></div>
      </form></div>`;
    $('modalBg')?.classList.add('open');
  }catch(error){alert('Could not open task: '+(error.message||error))}
}

async function submitPlanTaskEdit(e){
  e.preventDefault();
  if(!activePlanTaskEdit)return;
  const edit=activePlanTaskEdit;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Saving…');
  const task_data={title:$('editTaskTitle')?.value?.trim(),description:$('editTaskDescription')?.value||'',accountable_role:$('editTaskOwner')?.value?.trim()||'',next_action:$('editTaskNextAction')?.value?.trim()||'',blocker:$('editTaskBlocker')?.value?.trim()||null,acceptance_criteria:String($('editTaskAcceptance')?.value||'').split(/\r?\n/).map(line=>line.trim()).filter(Boolean)};
  const status=$('editTaskStatus');
  if(status)task_data.work_status=status.value;
  try{
    const res=await post('/api/coord/plan_task_edit',{root:edit.root,plan_id:edit.planId,task_id:edit.taskId,expected_revision:edit.revision,task_data,owner:'dashboard',idempotency_key:coordOperationId(`update-${edit.taskId}`)});
    if(res.success===false)throw new Error(res.error||'Could not update task');
    activePlanTaskEdit=null;
    $('modalClose')?.click();
    await loadCoordinationView();
  }catch(error){alert('Save task failed: '+(error.message||error))}
  finally{if(typeof setButtonLoading==='function')setButtonLoading(btn, false);}
}

function openAcquireSemModal(){
  if($('modalTitle')) $('modalTitle').textContent = 'Acquire Resource Semaphore';
  if($('modalLive')) $('modalLive').textContent = '';
  if($('modalBody')) $('modalBody').innerHTML = `
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitAcquireSem(event)">
        <div class="form-group">
          <label for="newSemName">Semaphore Name *</label>
          <input type="text" id="newSemName" required placeholder="e.g. unity_editor, gpu_lock, git_writer" autofocus>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="form-group">
            <label for="newSemOwner">Holder / Owner ID *</label>
            <input type="text" id="newSemOwner" required placeholder="e.g. agent_1, session_123" value="agent_${Math.random().toString(36).slice(2,7)}">
          </div>
          <div class="form-group">
            <label for="newSemCapacity">Capacity (Slots)</label>
            <input type="number" id="newSemCapacity" min="1" max="100" value="1">
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="form-group">
            <label for="newSemTtl">TTL (Seconds)</label>
            <input type="number" id="newSemTtl" min="1" max="3600" value="300">
          </div>
          <div class="form-group">
            <label for="newSemTimeout">Wait Timeout (Seconds)</label>
            <input type="number" id="newSemTimeout" min="0" max="600" value="0">
          </div>
        </div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">Acquire / Create</button>
        </div>
      </form>
    </div>
  `;
  $('modalBg')?.classList.add('open');
}

async function submitAcquireSem(e){
  e.preventDefault();
  const name = $('newSemName')?.value?.trim();
  const owner = $('newSemOwner')?.value?.trim() || 'agent';
  const capacity = parseInt($('newSemCapacity')?.value || '1', 10);
  const ttl_seconds = parseFloat($('newSemTtl')?.value || '300');
  const timeout = parseFloat($('newSemTimeout')?.value || '0');
  if(!name) return;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Acquiring…');
  try{
    const res = await post('/api/coord/semaphore_acquire', {
      name, owner, capacity, ttl_seconds, timeout
    });
    $('modalClose')?.click();
    if(res.acquired){
      alert(`Acquired semaphore "${name}"! Lease ID: ${res.lease_id}`);
    }else{
      alert(`Could not acquire semaphore: ${res.reason || 'Capacity reached'}`);
    }
    await loadCoordinationView();
  }catch(err){
    alert('Acquire semaphore error: ' + (err.message || err));
  }finally{
    if(typeof setButtonLoading==='function')setButtonLoading(btn, false);
  }
}

async function generateSessionBriefing(){
  const agentId = $('coordBriefingAgentId')?.value?.trim() || 'primary_agent';
  const out = $('coordBriefingOutput');
  if(!out) return;
  out.textContent = 'Compiling session briefing...';
  try{
    const res = await post('/api/coord/session_briefing', {agent_id: agentId});
    if(res.success === false) throw new Error(res.error || 'Failed to compile briefing');
    const b = res.board_summary?.counts || res.board?.summary?.counts || {};
    const sems = Object.values(res.semaphores?.semaphores || {});
    const md = [
      `# Session Briefing for \`${agentId}\` (${new Date((res.timestamp || Date.now() / 1000) * 1000).toLocaleString()})`,
      '',
      `## Project Board Status`,
      `- Total items: **${b.total || 0}**`,
      `- In progress: **${b.in_progress || 0}**`,
      `- Planned: **${b.planned || 0}**`,
      `- Done: **${b.done || 0}**`,
      `- Blocked: **${b.blocked || 0}**`,
      '',
      `## Resource Semaphores`,
      sems.length ? sems.map(s => `- **${s.name}**: ${s.active_count || 0}/${s.capacity} held (${s.queue_length || 0} waiting)`).join('\n') : '- No active semaphores',
      '',
      `## Active Tasks`,
      (res.active_tasks || []).length ? res.active_tasks.map(t => `- **${t.task_id}**: ${t.goal || 'No goal stated'}`).join('\n') : '- No active tasks reported'
    ].join('\n');
    out.textContent = md;
  }catch(e){
    out.textContent = 'Briefing compilation error: ' + (e.message || e);
  }
}

function switchCoordSubtab(tabKey){
  const tabs = [
    ['board','Board'], ['semaphores','Semaphores'],
    ['plan-progress','PlanProgress'], ['briefing','Briefing']
  ];
  if(!tabs.some(([key]) => key === tabKey)) return;
  tabs.forEach(([key,name]) => {
    const btn = $('subtabCoord' + name);
    const sec = $('coord' + name + 'Sec');
    if(btn) btn.classList.toggle('active', key === tabKey);
    if(sec) sec.style.display = key === tabKey ? 'block' : 'none';
  });
}

document.querySelectorAll('.subtab-btn[data-coord-subtab]').forEach(btn => {
  btn.addEventListener('click', () => switchCoordSubtab(btn.dataset.coordSubtab));
});

$('coordRefreshBoardBtn')?.addEventListener('click', loadCoordinationView);
$('coordBoardRoot')?.addEventListener('change', loadCoordinationView);
$('coordBoardPlan')?.addEventListener('change', loadCoordinationView);
$('coordBoardSearch')?.addEventListener('input', renderKanbanBoard);
$('coordCompactBtn')?.addEventListener('click', toggleKanbanCompact);
$('coordNewPlanBtn')?.addEventListener('click', openCreatePlanModal);
$('coordEditPlanBtn')?.addEventListener('click', openEditPlanModal);
$('coordNewCardBtn')?.addEventListener('click', openAddCardModal);
$('coordRefreshSemBtn')?.addEventListener('click', loadCoordinationView);
$('coordAcquireSemBtn')?.addEventListener('click', openAcquireSemModal);
$('coordRefreshPlanProgressBtn')?.addEventListener('click', loadCoordinationView);
$('coordGenerateBriefingBtn')?.addEventListener('click', generateSessionBriefing);

if($('coordBoardRoot')&&!$('coordBoardRoot').value){
  try{$('coordBoardRoot').value=localStorage.getItem('local-ai-hub.coordBoardRoot')||''}catch{}
  if(!$('coordBoardRoot').value)$('coordBoardRoot').value=$('agentOsRoot')?.value?.trim()||$('agentOsRepoSelect')?.value?.trim()||'';
}

if($('coordBoardCard')) $('coordBoardCard').onclick = () => switchTab('coordination');
if($('coordSemCard')) $('coordSemCard').onclick = () => { switchTab('coordination'); switchCoordSubtab('semaphores'); };

// Quick keyboard tab shortcuts
window.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;
  if(e.key==='1')switchTab('overview');
  if(e.key==='2')switchTab('work');
  if(e.key==='3')switchTab('agentos');
  if(e.key==='4')switchTab('projects');
  if(e.key==='5')switchTab('coordination');
  if(e.key==='6')switchTab('commands');
  if(e.key==='8')switchTab('performance');
  if(e.key==='9')switchTab('reliability');
  if(e.key==='0')switchTab('config');
});

let initTab = 'overview';
try{initTab = location.hash.replace('#','') || localStorage.getItem('activeTab') || 'overview';}catch{initTab = location.hash.replace('#','') || 'overview';}
switchTab(initTab);
loadCoordinationView();
