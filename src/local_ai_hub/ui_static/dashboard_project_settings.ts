// @ts-nocheck
async function loadProjectSettings(root){
  const body=$('modalProjectSettingsBody');
  if(!body)return;
  try{
    const d=await fetchDashboardJson('/api/project/config?root='+encodeURIComponent(root));
    if(!d||!d.success){
      body.innerHTML='<div class="tiny muted">Default repository settings active (no project overrides).</div>';
      return;
    }
    const s=d.settings||{};
    const hasExcludes=(s.exclude_paths||[]).length>0;
    const hasForce=(s.force_include_paths||[]).length>0;
    const hasExts=(s.custom_extensions||[]).length>0;
    const hasSkip=(s.skip_phases||[]).length>0;
    const hasCmds=Object.keys(s.commands||{}).length>0;
    const sources=(d.sources||[]).join(', ');

    let html=`<div class="kv" style="padding:0">
      <div>Config Source</div><div><b>${esc(d.config_exists?'.local-ai.toml (project active)':(d.sources||[]).join(', ')||'defaults')}</b></div>
      <div>Custom Extensions</div><div>${hasExts?s.custom_extensions.map(x=>`<span class="chip">${esc(x)}</span>`).join(' '):'<span class="tiny muted">defaults</span>'}</div>
      <div>Excluded Paths</div><div>${hasExcludes?s.exclude_paths.map(x=>`<span class="chip bad-t">${esc(x)}</span>`).join(' '):'<span class="tiny muted">none</span>'}</div>
      <div>Force Included</div><div>${hasForce?s.force_include_paths.map(x=>`<span class="chip ok">${esc(x)}</span>`).join(' '):'<span class="tiny muted">none</span>'}</div>
      <div>Skipped Phases</div><div>${hasSkip?s.skip_phases.map(x=>`<span class="chip warn-t">${esc(x)}</span>`).join(' '):'<span class="tiny muted">none (all 13 phases enabled)</span>'}</div>
      <div>Defined Commands</div><div>${hasCmds?Object.entries(s.commands).map(([k,v])=>`<code>${esc(k)}</code>: <code>${esc(Array.isArray(v)?v.join(' '):String(v))}</code>`).join('<br>'):'<span class="tiny muted">none</span>'}</div>
      <div>Max File Size</div><div>${s.max_file_size_bytes?n(s.max_file_size_bytes)+' bytes':'<span class="tiny muted">default (512 KB)</span>'}</div>
    </div>`;
    body.innerHTML=html;
  }catch(e){
    body.innerHTML='<div class="tiny muted">Settings: using default repository configuration.</div>';
  }
}

function openRegisterProjectModal(){
  if($('modalTitle'))$('modalTitle').textContent='Register Project for Preprocessing';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitRegisterProject(event)">
        <div class="form-group">
          <label for="regProjRoot">Repository Root Path *</label>
          <input type="text" id="regProjRoot" required placeholder="C:/Projects/my-app or /home/user/repo" autofocus>
          <span class="form-hint">Full path to the repository folder.</span>
        </div>
        <div style="margin-top:6px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="regProjForce">
            <span>Perform initial force re-scan for all files</span>
          </label>
          <div class="tiny muted" style="margin-left:22px;margin-top:3px">If unchecked, utilizes incremental fast sync and cached hashes.</div>
        </div>
        <div id="regProjStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">+ Register Project</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('regProjRoot')?.focus(),50);
}

async function submitRegisterProject(e){
  e.preventDefault();
  const root=$('regProjRoot')?.value?.trim();
  if(!root)return;
  const btn = e?.submitter || e?.target?.querySelector?.('button[type="submit"]');
  if(typeof setButtonLoading==='function')setButtonLoading(btn, true, 'Registering…');
  const force=$('regProjForce')?.checked||false;
  const statusEl=$('regProjStatus');
  if(statusEl)statusEl.textContent='Registering project…';

  try{
    const r=await post('/api/preprocess',{root,action:force?'refresh':'register'});
    if(r.success){
      $('modalClose')?.click();
      await pollStatus();
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(r.error||'Failed')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }finally{
    if(typeof setButtonLoading==='function')setButtonLoading(btn, false);
  }
}

function openDeleteProjectModal(root,name){
  if($('modalTitle'))$('modalTitle').textContent='Unregister Project';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <div style="font-size:13px">
        Unregister project <b>${esc(name)}</b>?
        <div class="tiny mono muted" style="margin-top:2px">${esc(root)}</div>
      </div>

      <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">
        <label class="modal-radio-option">
          <input type="radio" name="deleteOption" id="delOpt1" value="unregister" checked>
          <div>
            <div style="font-weight:600;font-size:12px">Option 1: Unregister Only (Recommended)</div>
            <div class="tiny muted" style="margin-top:2px">Stops background syncing and removes from dashboard. Preserves content caches so re-registering is instant.</div>
          </div>
        </label>

        <label class="modal-radio-option" style="border-color:#7f1d1d">
          <input type="radio" name="deleteOption" id="delOpt2" value="purge">
          <div>
            <div style="font-weight:600;font-size:12px;color:var(--bad)">Option 2: Purge All Index Data</div>
            <div class="tiny muted" style="margin-top:2px">Permanently deletes all AST symbols, RAG embeddings and cache entries for this workspace.</div>
          </div>
        </label>
      </div>

      <div id="delProjStatus" class="tiny"></div>

      <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
        <button class="btn" onclick="$('modalClose')?.click()">Cancel</button>
        <button class="btn bad" id="confirmDeleteProjectBtn" onclick="confirmDeleteProject(${escJs(root)})">Confirm Unregister / Purge</button>
      </div>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  const confirmBtn=$('confirmDeleteProjectBtn');
  if(confirmBtn)confirmBtn.onclick=()=>confirmDeleteProject(root);
}

async function confirmDeleteProject(root){
  const purge=$('delOpt2')?.checked||false;
  const confirmBtn=$('confirmDeleteProjectBtn');
  if(typeof setButtonLoading==='function')setButtonLoading(confirmBtn, true, 'Processing…');
  const statusEl=$('delProjStatus');
  if(statusEl)statusEl.textContent='Processing…';
  try{
    const r=await post('/api/preprocess',{root,action:'unregister',purge_data:purge});
    if(r && r.success===false){
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(r.error||'Failed to unregister')}</span>`;
      return;
    }
    $('modalClose')?.click();
    await pollStatus();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }finally{
    if(typeof setButtonLoading==='function')setButtonLoading(confirmBtn, false);
  }
}

function openCleanMissingModal(){
  if($('modalTitle'))$('modalTitle').textContent='Prune Missing Worktrees';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Clean Missing Worktree Directories</span></div>
        <div class="modal-card-body" style="font-size:12px;line-height:1.4">
          Scan registered projects and remove worktree directories that have been deleted from disk.
          Deduplicated content caches remain preserved for reuse.
        </div>
      </div>
      <div id="cleanMissingStatus" class="tiny"></div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Cancel</button>
        <button class="btn warn" id="confirmCleanMissingBtn" onclick="confirmCleanMissing()">🧹 Prune Missing Projects</button>
      </div>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
}

async function confirmCleanMissing(){
  const statusEl=$('cleanMissingStatus');
  const confirmBtn=$('confirmCleanMissingBtn');
  if(typeof setButtonLoading==='function')setButtonLoading(confirmBtn, true, 'Pruning…');
  if(statusEl)statusEl.textContent='Scanning and cleaning…';
  try{
    const r=await post('/api/preprocess',{action:'cleanup_deleted'},{timeoutMs:120000});
    $('modalClose')?.click();
    await pollStatus();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }finally{
    if(typeof setButtonLoading==='function')setButtonLoading(confirmBtn, false);
  }
}

function renderDoctorModal(d){
  const checks=d.checks||[];
  const okCount=checks.filter(c=>c.status==='OK').length;
  const allOk=okCount===checks.length;

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">SYSTEM DIAGNOSTICS &amp; HEALTH</div>
          <h2 style="margin:2px 0 0;font-size:16px">Local AI Hub Doctor</h2>
        </div>
        <div>
          <span class="badge-status ${allOk?'badge-complete':'badge-error'}">${allOk?'✓ ALL CHECKS HEALTHY':(checks.length-okCount)+' ISSUES DETECTED'}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="doc-check-grid">
        ${checks.map(c=>{
          const isOk=c.status==='OK';
          const isWarn=c.status==='WARN'||c.status==='OFF';
          const badgeClass=isOk?'badge-complete':(isWarn?'badge-paused':'badge-error');
          const icon=isOk?'✅':(isWarn?'⚠️':'❌');
          return `
            <div class="doc-check-card" style="border-color:${isOk?'#166534':(isWarn?'#854d0e':'#991b1b')}">
              <span class="doc-check-icon">${icon}</span>
              <div style="flex:1">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                  <span class="doc-check-title">${esc(c.component)}</span>
                  <span class="badge-status ${badgeClass}" style="font-size:9px">${esc(c.status)}</span>
                </div>
                <div class="doc-check-detail">${esc(c.detail||'')}</div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="openDoctorModal()">↻ Re-run Doctor</button>
        <button class="btn" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

async function openDoctorModal(){
  openModal({},'Local AI Hub Doctor Health Diagnostics','doctor');
  if($('modalBody'))$('modalBody').innerHTML='<div class="modal-body-wrap"><div class="tiny muted">Running comprehensive health diagnostics across Hub, Ollama, GPU, databases and preprocessor…</div></div>';
  try{
    const r=await post('/api/doctor',{});
    renderDoctorModal(r);
  }catch(e){
    if($('modalBody'))$('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="bad-t">Doctor failed: ${esc(e.message||e)}</div></div>`;
  }
}

function renderActiveLeaseModal(l){
  const paths=Array.isArray(l.paths)?l.paths:[l.path||''];
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">MULTI-AGENT COORDINATION LEASE</div>
          <h2 style="margin:2px 0 0;font-size:16px;font-family:monospace">${esc(l.lease_id||'—')}</h2>
        </div>
        <span class="badge-status badge-complete">ACTIVE</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Lease Details</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">

            <div>Purpose</div><div>${esc(l.purpose||'agent edits')}</div>
            <div>Time Remaining</div><div class="ok"><b>${l.expires_in_seconds?durSec(l.expires_in_seconds):'—'}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-card">
        <div class="modal-card-head"><span>Protected Paths (${paths.length})</span></div>
        <div class="modal-card-body">
          ${paths.map(p=>`<div class="mono tiny" style="padding:3px 0"><span class="chip mono">${esc(p)}</span></div>`).join('')}
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn bad" onclick="releaseLeaseAction(${escJs(l.lease_id)})">Release Lease</button>
      </div>
    </div>
  `;
}

async function releaseLeaseAction(leaseId){
  try{
    await post('/api/leases/release',{lease_id:leaseId});
    $('modalClose')?.click();
    await loadActiveLeases();
  }catch(e){
    alert('Release error: '+e);
  }
}

function renderActiveCommandModal(cmd){
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">RUNNING SAFE COMMAND</div>
          <h2 style="margin:2px 0 0;font-size:15px;font-family:monospace">${esc(cmd.command||'—')}</h2>
        </div>
        <span class="badge-status badge-running"><span class="pulse-dot"></span> RUNNING</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Execution Parameters</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Working Directory</div><div class="mono tiny">${esc(cmd.cwd||'—')}</div>

            <div>Policy Classification</div><div><span class="chip ok">${esc(cmd.class||'safe')}</span></div>
            <div>Age / Running For</div><div>${age(cmd.age_ms)}</div>
            <div>Timeout</div><div>${durSec(cmd.timeout_seconds)}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

