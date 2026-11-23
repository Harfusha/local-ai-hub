// @ts-nocheck
function setFrontendVisionCaptureState(state,label){const el=$('visionCaptureState');if(!el)return;const normalized=['produced','empty','not_captured','redacted'].includes(String(state||''))?String(state):'not_captured';el.className=`trace-capture-state ${normalized.replace('_','-')}`;el.dataset.captureState=normalized;el.textContent=`Capture state · ${label||traceCaptureStateLabel(normalized)}`;}
function setFrontendVisionCaptureError(message){const el=$('visionCaptureError');if(!el)return;const text=String(message||'');el.textContent=text;el.style.display=text?'':'none';}
function openFrontendVisionReviewModal(prefill={}){const modal=$('visionReviewModal');if(!modal)return;window.frontendVisionCapture={};modal.setAttribute('aria-label','Frontend vision review');if($('visionReviewTitle'))$('visionReviewTitle').textContent='Frontend vision review';if($('diagramVisionReviewNotice')){$('diagramVisionReviewNotice').textContent='';$('diagramVisionReviewNotice').style.display='none';}modal.classList.add('open');if($('visionPrompt'))$('visionPrompt').value=String(prefill.prompt||'');if($('visionFindingId'))$('visionFindingId').value=String(prefill.findingId||'');if($('visionScreenshot'))$('visionScreenshot').value='';if($('visionReviewResult'))$('visionReviewResult').innerHTML='';if($('visionReviewStatus'))$('visionReviewStatus').textContent='';setFrontendVisionCaptureError('');setFrontendVisionCaptureState('not_captured','Not captured');}
function openDiagramVisionReview(){openFrontendVisionReviewModal({prompt:'Review this raster diagram for visible components, relationships, labels, and uncertainties. Do not guess unreadable details.'});const modal=$('visionReviewModal');if(!modal)return;modal.setAttribute('aria-label','Raster diagram vision review');if($('visionReviewTitle'))$('visionReviewTitle').textContent='Raster diagram vision review';if($('diagramVisionReviewNotice')){$('diagramVisionReviewNotice').textContent='Run uses the existing vision review and requires an available installed model; no model is downloaded automatically. This review does not change the metadata-only index.';$('diagramVisionReviewNotice').style.display='';}}
function closeFrontendVisionReviewModal(){const modal=$('visionReviewModal');if(modal)modal.classList.remove('open');}
function captureFrontendVisionTab(){
  const requestId=`vision-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
  setFrontendVisionCaptureError('');setFrontendVisionCaptureState('not_captured','Waiting for current-tab bridge…');
  window.postMessage({type:'LOCAL_AI_VISION_CAPTURE_REQUEST',request_id:requestId,prompt:String($('visionPrompt')?.value||'')},'*');
}
function consumeFrontendVisionCapture(result){
  const payload=result&&typeof result==='object'?result:{};
  if(payload.success!==true){setFrontendVisionCaptureState('not_captured','Capture failed');setFrontendVisionCaptureError(payload.error||payload.error_code||'Current-tab capture failed.');return;}
  window.frontendVisionCapture=payload;setFrontendVisionCaptureState('produced','Captured current tab');setFrontendVisionCaptureError('');
}
if(typeof window!=='undefined')window.addEventListener('message',event=>{if(event?.data?.type==='LOCAL_AI_VISION_CAPTURE_RESULT')consumeFrontendVisionCapture(event.data.result||event.data)});
function readFrontendVisionFile(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(new Error('Screenshot could not be read.'));reader.onload=()=>resolve(String(reader.result||''));reader.readAsDataURL(file);});}
function renderFrontendVisionReviewResult(result){const target=$('visionReviewResult');if(!target)return;const model={output:result,session:{model:result?.model||'',source:result?.source||'upload'},identity:{action:'/api/vision/review'},lifecycle:{state:result?.success===false?'failed':'completed'}};target.innerHTML=typeof renderVisionReviewPresentation==='function'?renderVisionReviewPresentation(model):`<pre>${esc(JSON.stringify(result||{},null,2))}</pre>`;}
async function submitFrontendVisionReview(){
  const prompt=String($('visionPrompt')?.value||'').trim(),file=$('visionScreenshot')?.files?.[0],capture=window.frontendVisionCapture||{};
  if(!prompt){setFrontendVisionCaptureError('Prompt is required.');return;}
  if(!file&&!capture.bundle_artifact_id&&!capture.screenshot_artifact_id){setFrontendVisionCaptureError('Provide a screenshot or capture the current tab.');return;}
  const submit=$('visionReviewSubmit');if(submit){submit.disabled=true;submit.textContent='Reviewing…';}
  try{
    const image=file?await readFrontendVisionFile(file):capture.screenshot;
    const result=await post('/api/vision/review',{prompt,source:file?'upload':'current_tab',image:image||'',bundle_artifact_id:capture.bundle_artifact_id||'',screenshot_artifact_id:capture.screenshot_artifact_id||'',dom_artifact_id:capture.dom_artifact_id||'',accessibility_artifact_id:capture.accessibility_artifact_id||''});
    if(result?.success===false){setFrontendVisionCaptureError(result.error?.message||result.error||result.error_code||'Vision review failed.');if(result.error_code==='permission_denied')setFrontendVisionCaptureState('not_captured','Permission denied');return;}
    if($('visionReviewStatus'))$('visionReviewStatus').textContent=`${result.model||'vision model'} · ${result.source||'local'}`;renderFrontendVisionReviewResult(result);
  }catch(error){setFrontendVisionCaptureError(String(error));}
  finally{if(submit){submit.disabled=false;submit.textContent='Run vision review';}}
}
if($('visionReviewClose'))$('visionReviewClose').onclick=closeFrontendVisionReviewModal;
if($('visionReviewOpen'))$('visionReviewOpen').onclick=()=>openFrontendVisionReviewModal();
if($('diagramVisionReviewOpen'))$('diagramVisionReviewOpen').onclick=openDiagramVisionReview;
if($('visionCaptureCurrentTab'))$('visionCaptureCurrentTab').onclick=captureFrontendVisionTab;
if($('visionReviewSubmit'))$('visionReviewSubmit').onclick=submitFrontendVisionReview;
const rows=(id,items,fn,cols,emptyText='No active items recorded')=>{const el=$(id);if(!el)return;el.innerHTML=(items&&items.length)?items.map(fn).join(''):`<tr><td colspan="${cols}" class="muted" style="text-align:center;padding:16px 10px;font-style:italic">${emptyText}</td></tr>`};
function copyText(text, btn){
  try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(String(text)).catch(()=>{});}}catch{}
  if(btn){
    const oldText=btn.textContent;
    btn.textContent='Copied!';
    setTimeout(()=>{btn.textContent=oldText},1500);
  }
}
function renderCodeIntelModal(d,title){
  if(d.code||d.tests||d.test_code){
    const code=d.code||d.tests||d.test_code;
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-card">
          <div class="modal-card-head">
            <span>${esc(title||'Generated Unit Tests')}</span>
            <button class="copy-btn" onclick="copyText(${esc(JSON.stringify(code))},this)">📋 Copy Code</button>
          </div>
          <div class="modal-card-body">
            <pre class="code-box" style="margin:0;max-height:450px">${esc(code)}</pre>
          </div>
        </div>
      </div>
    `;
    return;
  }
  if(d.callers||d.impact||d.affected_files){
    const callers=d.callers||[];
    const files=d.affected_files||d.files||[];
    const risk=d.risk||d.risk_score||'medium';
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-hero" style="border-radius:6px;border:1px solid #2d3e56">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <b>Refactoring Risk Assessment</b>
            <span class="badge-status ${risk==='high'?'badge-error':risk==='medium'?'badge-paused':'badge-complete'}">${esc(String(risk).toUpperCase())} RISK</span>
          </div>
        </div>
        <div class="modal-card">
          <div class="modal-card-head"><span>Direct Callers (${callers.length})</span></div>
          <div class="modal-card-body">
            ${callers.length?callers.map(c=>`<div style="padding:4px 0"><span class="chip"><b>${esc(c.name||c)}</b></span> <span class="tiny muted">${esc(c.file||'')}</span></div>`).join(''):'<div class="muted tiny">No direct callers detected.</div>'}
          </div>
        </div>
        <div class="modal-card">
          <div class="modal-card-head"><span>Impacted Files (${files.length})</span></div>
          <div class="modal-card-body">
            ${files.length?files.map(f=>`<div style="padding:4px 0" class="mono tiny">${esc(f)}</div>`).join(''):'<div class="muted tiny">No downstream files impacted.</div>'}
          </div>
        </div>
      </div>
    `;
    return;
  }
  if(d.imports||d.missing_imports){
    const imps=d.imports||d.missing_imports||[];
    const code=Array.isArray(imps)?imps.join('\n'):String(imps);
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-card">
          <div class="modal-card-head">
            <span>Resolved Missing Imports</span>
            <button class="copy-btn" onclick="copyText(${esc(JSON.stringify(code))},this)">📋 Copy Imports</button>
          </div>
          <div class="modal-card-body">
            <pre class="code-box" style="margin:0">${esc(code)}</pre>
          </div>
        </div>
      </div>
    `;
    return;
  }
  if(d.symbols||d.declarations||d.references||d.implementations){
    const items=d.symbols||d.declarations||d.references||d.implementations||[];
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-card">
          <div class="modal-card-head"><span>Results (${items.length})</span></div>
          <div class="modal-card-body">
            ${items.length?items.map(s=>`
              <div style="padding:6px 0;border-bottom:1px solid #1f2c3d">
                <div style="display:flex;justify-content:space-between">
                  <b>${esc(s.name||s.symbol||'symbol')}</b>
                  <span class="chip">${esc(s.kind||'reference')}</span>
                </div>
                <div class="tiny mono muted" style="margin-top:2px">${esc(s.path||s.file||'')}:${n(s.line||s.start_line||0)}</div>
                ${s.snippet?`<pre class="code-box" style="margin-top:4px;padding:6px">${esc(s.snippet)}</pre>`:''}
              </div>
            `).join(''):'<div class="muted tiny">No matching occurrences found.</div>'}
          </div>
        </div>
      </div>
    `;
    return;
  }
  renderHumanModal(d);
}

function renderDeadCodeModal(s){
  const name=s.name||'Symbol';
  const kind=s.kind||'symbol';
  const path=s.path||'';
  const line=s.line||0;
  const cont=s.container||'—';
  const reason=s.reason||'No callers found across repository AST callgraph';
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">CODEBASE OPTIMIZATION · UNUSED SYMBOL</div>
          <h2 style="margin:2px 0 0;font-size:16px"><b>${esc(name)}</b> <span class="chip">${esc(kind)}</span></h2>
        </div>
        <span class="badge-status badge-waiting">CANDIDATE</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Location &amp; Reason</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>File Path</div><div class="mono tiny">${esc(path)}:${n(line)}</div>
            <div>Container / Parent</div><div>${esc(cont)}</div>
            <div>Analysis Finding</div><div class="warn-t"><b>${esc(reason)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderAuditVulnModal(v){
  const pkg=v.package||'Package';
  const sev=v.severity||'MEDIUM';
  const inst=v.installed_version||'—';
  const fixed=v.fixed_version||'—';
  const adv=v.advisory||'Security advisory';
  const manifest=v.manifest_path||'—';
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">DEPENDENCY VULNERABILITY ADVISORY</div>
          <h2 style="margin:2px 0 0;font-size:16px">🛡️ <b>${esc(pkg)}</b></h2>
        </div>
        <span class="badge-status ${sev==='HIGH'||sev==='CRITICAL'?'badge-error':'badge-waiting'}">${esc(sev)} SEVERITY</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Advisory Information</span></div>
        <div class="modal-card-body">
          <div style="font-size:12px;margin-bottom:8px">${esc(adv)}</div>
          <div class="kv" style="padding:0">
            <div>Package</div><div><b>${esc(pkg)}</b></div>
            <div>Installed Version</div><div class="bad-t"><b>${esc(inst)}</b></div>
            <div>Fixed Version</div><div class="ok"><b>${esc(fixed)}</b></div>
            <div>Manifest Path</div><div class="mono tiny">${esc(manifest)}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderArchEdgeModal(e){
  const fromName=e.from?.split(/[\\/]/).pop()||e.from;
  const toName=e.to?.split(/[\\/]/).pop()||e.to;
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">ARCHITECTURE DEPENDENCY LINK</div>
          <h2 style="margin:2px 0 0;font-size:16px"><b>${esc(fromName)}</b> ➔ <b>${esc(toName)}</b></h2>
        </div>
        <span class="chip ok">${esc(e.type||'dependency')}</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Connection Information</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Source Project</div><div class="mono tiny">${esc(e.from)}</div>
            <div>Target Dependency</div><div class="mono tiny">${esc(e.to)}</div>
            <div>Relationship Kind</div><div><b>${esc(e.type)}</b></div>
            <div>Context / Evidence</div><div>${esc(e.label||'Direct dependency / import linkage')}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function inferEntityType(obj){
  if(!obj||typeof obj!=='object')return 'raw';
  if(obj.task_id)return 'task';
  if(obj.key&&(obj.value!==undefined||obj.scope||obj.kind))return 'memory';
  if(obj.incident_id||(obj.error_class&&obj.root_cause))return 'incident';
  if(obj.stream_id||obj.event_type||obj.stage)return 'event';
  if(obj.project&&obj.root)return 'project';
  if(obj.lease_id)return 'lease';
  if(obj.command&&obj.cwd)return 'command';
  if(obj.component&&(obj.operation||obj.count!==undefined))return 'error';
  if(obj.session_id)return 'session';
  if(obj.checks&&Array.isArray(obj.checks))return 'doctor';
  if(obj.code||obj.tests||obj.test_code||obj.missing_imports||obj.callers)return 'code_intel';
  if(obj.databases_optimized!==undefined)return 'db_opt';
  if(obj.purged_entries!==undefined)return 'cache_purge';
  if(obj.tier&&obj.num_ctx!==undefined)return 'execution_profile';
  if(obj.layer&&obj.context_tokens_avoided_est!==undefined)return 'cache_layer';
  if(obj.local_inference_calls!==undefined)return 'agent_stat';
  if(obj.route&&obj.task_type&&obj.complexity)return 'route_stat';
  if(obj.action&&obj.p50_duration_ms!==undefined)return 'http_tail';
  if(obj.avg_load_ms!==undefined&&obj.model)return 'model_stat';
  if(obj.fixed_version||obj.advisory||(obj.package&&obj.severity))return 'audit_vulnerability';
  if(obj.container!==undefined&&obj.reason&&obj.path)return 'dead_code';
  if(obj.reason&&obj.count!==undefined)return 'blocked_reason';
  if(obj.from&&obj.to&&obj.type)return 'arch_edge';
  if(obj.job_id!==undefined&&(obj.wait_ms!==undefined||obj.service_ms!==undefined||obj.wait_reason!==undefined))return 'scheduler_job';
  if(obj.request_id&&obj.agent&&(obj.action||obj.status_code!==undefined||obj.duration_ms!==undefined||obj.age_ms!==undefined))return 'http_request';
  return 'generic';
}
const dataStore=new Map(); let seq=0;
function clickableRow(obj,html,type='',idAttr=''){
  const id='d'+(++seq);
  const resolvedType=type||inferEntityType(obj);
  dataStore.set(id,{data:obj,type:resolvedType});
  if(dataStore.size>5000){
    const oldest=dataStore.keys().next().value;
    dataStore.delete(oldest);
  }
  const entityId=idAttr||obj?.task_id||obj?.incident_id||(obj?.key?((obj.scope||'task')+':'+obj.key):'')||obj?.root||obj?.lease_id||obj?.command||'';
  return `<tr class="click" data-detail="${id}" data-type="${esc(resolvedType)}" ${entityId?`data-id="${esc(entityId)}"`:''}>${html}</tr>`;
}

let traceDetailPoller=null,tracePollAbortController=null,activeTraceId='',traceSeq=0,traceEvents=[],traceOpenSteps=new Set(),traceView='timeline',activeTraceData=null,traceOptionalDetailsOpen=false,tracePollGeneration=0,traceEventTotal=0,traceFullPayloadInFlightId='';
const traceEventBufferLimit=200;
function traceAppendEvents(current,incoming,eventsTotal=0){const existing=Array.isArray(current)?current:[],seen=new Set(existing.map(event=>event&&Number.isFinite(event.seq)?event.seq:null).filter(seq=>seq!==null)),fresh=(Array.isArray(incoming)?incoming:[]).filter(event=>{const seq=event&&Number.isFinite(event.seq);if(!seq)return true;if(seen.has(event.seq))return false;seen.add(event.seq);return true}),merged=existing.concat(fresh);return {events:merged.slice(-traceEventBufferLimit),eventsTotal:Math.max(Number(eventsTotal)||0,merged.length)};}
