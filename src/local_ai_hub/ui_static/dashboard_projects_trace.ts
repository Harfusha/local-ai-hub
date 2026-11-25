// @ts-nocheck
function refreshProjectList(){renderProjects(last?.preprocessing?.projects||[])}
$('projectSearch').oninput=e=>{projectQuery=e.target.value;refreshProjectList()};
$('projectFilter').onchange=e=>{projectFilter=e.target.value;refreshProjectList()};
$('projectSort').onchange=e=>{projectSort=e.target.value;refreshProjectList()};
$('projectGroupWorktrees')?.addEventListener('change',refreshProjectList);

const PHASES = [
  {id:'inventory', name:'Discovery', icon:'📁', desc:'File inventory & change discovery'},
  {id:'hash', name:'Content Hash', icon:'⚡', desc:'SHA256 content hashing & cache linking'},
  {id:'code_index', name:'AST Symbols', icon:'🌲', desc:'Symbol & callgraph extraction'},
  {id:'deterministic', name:'Declarative Facts', icon:'📋', desc:'Routes, models & configs'},
  {id:'serena', name:'Serena', icon:'S', desc:'Semantic/LSP project index'},

  {id:'lexical', name:'Full-Text Search', icon:'🔍', desc:'FTS5 lexical keyword index'},
  {id:'rag', name:'Vector RAG', icon:'🧠', desc:'768-dim CPU code embeddings'},
  {id:'files', name:'Semantic Cards', icon:'📄', desc:'cached semantic context cards'},
  {id:'serena_optional', name:'Optional Serena', icon:'S', desc:'Optional semantic index checks'},
  {id:'modules', name:'Module Graph', icon:'📦', desc:'Module topology synthesis'},
  {id:'project', name:'Architecture', icon:'🏗️', desc:'Project-level graph'},
  {id:'hot_queries', name:'Intent Pre-warm', icon:'🔥', desc:'Top query pre-warming'},
  {id:'file_card_enrichment', name:'Card Enrichment', icon:'✨', desc:'Model based file card enrichment'},
  {id:'diagnostics', name:'Diagnostics', icon:'🩺', desc:'Project diagnostic checks'},
  {id:'complete', name:'Ready', icon:'✅', desc:'Fully indexed & synchronized'}
];

function renderStepper(currIdx, isComplete, status) {
  return `<div class="pipeline-stepper" title="Pipeline: ${isComplete ? 'All '+PHASES.length+' phases complete' : 'Phase ' + currIdx + ' active'}">` +
    PHASES.map((p, i) => {
      const stepNum = i + 1;
      let cls = 'pipe-pend', sym = stepNum;
      if (isComplete || stepNum < currIdx) { cls = 'pipe-done'; sym = '✓'; }
      else if (stepNum === currIdx) { cls = (status === 'error') ? 'pipe-pend bad-t' : 'pipe-curr'; sym = p.icon; }
      return `<span class="pipe-step ${cls}" title="${stepNum}. ${p.name}: ${p.desc}">${sym}</span>`;
    }).join('') + `</div>`;
}

let projectQuery='',projectFilter='all',projectSort='priority';
function projectIdentity(project){
  return String(project?.git_common_dir||project?.canonical_root||project?.root||project?.project||'').replace(/\\/g,'/').replace(/\/+$/,'');
}
function projectState(x){
  if(x.status==='error'||x.last_error)return 'error';
  if(x.paused||x.status==='paused')return 'paused';
  if(x.waiting||x.status==='waiting')return 'waiting';
  if(x.status==='running')return 'running';
  if(x.phase==='complete'||x.status==='complete')return 'ready';
  return 'queued';
}

function groupedProjects(items){
  const list=Array.isArray(items)?items:[];
  if(!$('projectGroupWorktrees')?.checked)return list.map(x=>({...x,repository_identity:x.root||x.project||'',variants:[x]}));
  const groups=new Map();
  list.forEach(item=>{
    const identity=projectIdentity(item)||String(item.project||'unknown');
    const group=groups.get(identity)||[];group.push(item);groups.set(identity,group);
  });
  const rank={error:0,running:1,waiting:2,queued:3,paused:4,ready:5};
  return [...groups.entries()].map(([identity,variants])=>{
    const ordered=[...variants].sort((a,b)=>(rank[projectState(a)]??9)-(rank[projectState(b)]??9));
    return {...ordered[0],canonical_root:ordered[0].root||identity,repository_identity:ordered[0].root||identity,variants};
  });
}

let projectKnowledgeGeneration=0;
function resetProjectKnowledge(){
  projectKnowledgeGeneration++;
  const output=$('projectKnowledgeResults'),status=$('projectKnowledgeStatus'),button=$('projectKnowledgeSearch');
  if(output)output.replaceChildren();
  if(status)status.textContent='Choose a checkout and enter a query.';
  if(button)button.disabled=false;
}
function updateProjectKnowledgeRoots(items){
  const select=$('projectKnowledgeRoot');if(!select)return;
  const selected=select.value,roots=[...new Set((Array.isArray(items)?items:[]).map(item=>String(item?.root||'')).filter(Boolean))].sort();
  const previous=Array.from(select.options).slice(1).map(option=>option.value);
  if(previous.length===roots.length&&previous.every((root,index)=>root===roots[index]))return;
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Choose registered checkout';
  select.replaceChildren(placeholder);
  roots.forEach(root=>{const option=document.createElement('option');option.value=root;option.textContent=root;select.appendChild(option)});
  if(roots.includes(selected))select.value=selected;else if(selected)resetProjectKnowledge();
}
function renderProjectKnowledgeResults(result){
  const output=$('projectKnowledgeResults'),status=$('projectKnowledgeStatus');if(!output||!status)return;
  output.replaceChildren();
  const records=Array.isArray(result?.records)?result.records:[];
  const matches=Number(result?.match_count??records.length);
  status.textContent=records.length+' shown · '+matches+' matched or linked · '+(result?.complete===true?'inventory complete':'inventory partial')+(result?.truncated?' · result limit reached':'');
  if(!records.length){const note=document.createElement('p');note.textContent='No matching declarations in the scanned inventory.';output.appendChild(note);return}
  for(const item of records){
    const record=item?.record||{},payload=record.payload||{};
    const card=document.createElement('section');card.className='section';
    const title=document.createElement('h3');title.textContent=String(payload.title||record.id||'Knowledge record');card.appendChild(title);
    const meta=document.createElement('p');meta.className='tiny muted';meta.textContent=[record.kind,payload.layer,item.freshness,item.dependency_status,item.authority].filter(Boolean).join(' · ');card.appendChild(meta);
    const statement=document.createElement('p');statement.textContent=String(payload.statement||'');card.appendChild(statement);
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Sources, revision and declared relationships';details.appendChild(summary);
    const pre=document.createElement('pre');pre.className='human-pre';
    pre.textContent=JSON.stringify({record_id:record.id,revision:item.revision,evidence:record.evidence||[],source_statuses:item.evidence_statuses||[],source_checks_complete:item.source_checks_complete,source_assertion:item.source_assertion,verification_targets:item.verification_targets,verification_target_checks_complete:item.verification_target_checks_complete,relations:record.relations||[],flow:payload.flow},null,2);
    details.appendChild(pre);card.appendChild(details);
    const editor=document.createElement('details'),editorTitle=document.createElement('summary');editorTitle.textContent='Edit declaration';editor.appendChild(editorTitle);
    const input=document.createElement('textarea');input.rows=8;input.setAttribute('aria-label','Knowledge record JSON');input.value=JSON.stringify(record,null,2);editor.appendChild(input);
    const preview=document.createElement('button');preview.type='button';preview.className='btn';preview.textContent='Preview edit';editor.appendChild(preview);
    const review=document.createElement('pre');review.className='human-pre';editor.appendChild(review);
    preview.addEventListener('click',async()=>{
      try{
        const proposed=JSON.parse(input.value);
        if(proposed.id!==record.id||proposed.kind!==record.kind||proposed.project_id!==record.project_id)throw new Error('Record identity cannot change in this editor');
        await previewKnowledgeWrite(editor,review,preview,{action:'preview_edit',record:proposed,expected_revision:item.revision},'save_edit');
      }catch(error){review.textContent=String(error?.message||error)}
    });
    if(record.kind!=='review')card.appendChild(editor);
    output.appendChild(card);
  }
}
async function previewKnowledgeWrite(container,review,trigger,payload,saveAction){
  const root=String($('projectKnowledgeRoot')?.value||''),generation=projectKnowledgeGeneration;
  if(!root)return;
  trigger.disabled=true;
  container.querySelector('[data-knowledge-apply]')?.remove();
  review.textContent='Validating current revision…';
  try{
    const result=await post('/api/repo/knowledge/manage',{root,...payload});
    if(generation!==projectKnowledgeGeneration||$('projectKnowledgeRoot')?.value!==root)return;
    if(result?.success!==true)throw new Error(result?.error||'Preview failed');
    review.textContent=JSON.stringify({before:result.before,after:result.after},null,2);
    if(!result.writable_mode){review.textContent+='\nRead-only project: cannot save.';return}
    const save=document.createElement('button');save.type='button';save.className='btn primary';save.dataset.knowledgeApply='true';save.textContent='Save reviewed declaration to checkout';container.appendChild(save);
    const operationId=crypto.randomUUID();
    save.addEventListener('click',async()=>{
      if(generation!==projectKnowledgeGeneration||$('projectKnowledgeRoot')?.value!==root)return;
      save.disabled=true;trigger.disabled=true;
      try{
        const updated=await post('/api/repo/knowledge/manage',{root,...payload,action:saveAction,expected_revision:result.expected_revision,preview_digest:result.preview_digest,operation_id:operationId,apply:true});
        if(generation!==projectKnowledgeGeneration)return;
        if(updated?.success!==true)throw new Error(updated?.error||'Save failed');
        review.textContent='Saved to current checkout. Refresh before further edits. Review Git diff before commit.';
      }catch(error){review.textContent=String(error?.message||error)+' · Refresh and inspect current state before retry.'}
      finally{if(generation===projectKnowledgeGeneration)trigger.disabled=false}
    });
  }catch(error){if(generation===projectKnowledgeGeneration)review.textContent=String(error?.message||error)}
  finally{if(generation===projectKnowledgeGeneration)trigger.disabled=false}
}
$('projectKnowledgeAudit')?.addEventListener('click',async()=>{
  const root=String($('projectKnowledgeRoot')?.value||'');if(!root)return;
  const generation=++projectKnowledgeGeneration,output=$('projectKnowledgeResults'),status=$('projectKnowledgeStatus'),button=$('projectKnowledgeAudit');
  if(button)button.disabled=true;if(output)output.replaceChildren();if(status)status.textContent='Inspecting knowledge freshness and findings…';
  try{
    const result=await post('/api/repo/knowledge/manage',{root,action:'audit'});
    if(generation!==projectKnowledgeGeneration)return;
    if(result?.success!==true)throw new Error(result?.error||'Audit unavailable');
    const findings=Array.isArray(result.findings)?result.findings:[];
    if(status)status.textContent=findings.length+' candidates · '+(result.complete?'inventory complete':'partial inventory; cannot approve absent findings');
    for(const finding of findings){
      const card=document.createElement('section');card.className='section';
      const title=document.createElement('h3');title.textContent=String(finding.type||'Quality candidate');card.appendChild(title);
      const meta=document.createElement('p');meta.textContent=[finding.id,finding.record_id||finding.claim_key,finding.freshness,finding.review_disposition].filter(Boolean).join(' · ');card.appendChild(meta);
      const old=document.createElement('p');old.textContent=String(finding.review_note||'');card.appendChild(old);
      const choice=document.createElement('select');choice.setAttribute('aria-label','Finding disposition');
      for(const value of ['confirmed_issue','expected','acceptable','false_positive','deferred']){const option=document.createElement('option');option.value=value;option.textContent=value;choice.appendChild(option)}card.appendChild(choice);
      const note=document.createElement('textarea');note.rows=2;note.maxLength=2000;note.placeholder='Review note';note.setAttribute('aria-label','Finding review note');card.appendChild(note);
      const preview=document.createElement('button');preview.type='button';preview.className='btn';preview.textContent='Preview review';card.appendChild(preview);
      const remediation=document.createElement('button');remediation.type='button';remediation.className='btn';remediation.textContent='Preview corrective task';card.appendChild(remediation);
      const review=document.createElement('pre');review.className='human-pre';card.appendChild(review);
      preview.addEventListener('click',()=>previewKnowledgeWrite(card,review,preview,{action:'preview_review',finding_id:finding.id,subject_digest:finding.subject_digest,decision:choice.value,note:note.value},'save_review'));
      remediation.addEventListener('click',async()=>{
        remediation.disabled=true;
        card.querySelector('[data-knowledge-create-task]')?.remove();
        try{
          const request={root,action:'preview_remediation',finding_id:finding.id,subject_digest:finding.subject_digest};
          const result=await post('/api/repo/knowledge/manage',request);
          if(generation!==projectKnowledgeGeneration)return;
          if(result?.success!==true)throw new Error(result?.error||'Remediation unavailable');
          review.textContent=JSON.stringify(result.contract,null,2);
          const create=document.createElement('button');create.type='button';create.className='btn primary';create.dataset.knowledgeCreateTask='true';create.textContent='Create reviewed Agent OS task';card.appendChild(create);
          const taskId='task_'+crypto.randomUUID().replace(/-/g,'').slice(0,20);
          create.addEventListener('click',async()=>{
            if(generation!==projectKnowledgeGeneration||$('projectKnowledgeRoot')?.value!==root)return;
            create.disabled=true;remediation.disabled=true;
            try{
              const current=await post('/api/repo/knowledge/manage',request);
              if(generation!==projectKnowledgeGeneration||$('projectKnowledgeRoot')?.value!==root)return;
              if(current?.success!==true||JSON.stringify(current.contract)!==JSON.stringify(result.contract))throw new Error('Finding changed; refresh and preview again');
              const created=await post('/api/agent-state/tasks',{action:'create',root,task_id:taskId,contract:current.contract});
              if(generation!==projectKnowledgeGeneration)return;
              if(created?.success!==true||!created.task)throw new Error(created?.error||'Task creation not confirmed');
              review.textContent='Created Agent OS task '+String(created.task.task_id||taskId)+'. It is not executed or completed.';
            }catch(error){
              if(generation===projectKnowledgeGeneration)review.textContent=String(error?.message||error)+' · Inspect Agent OS for task '+taskId+' before retry.';
            }finally{if(generation===projectKnowledgeGeneration)remediation.disabled=false}
          });
        }catch(error){if(generation===projectKnowledgeGeneration)review.textContent=String(error?.message||error)}
        finally{if(generation===projectKnowledgeGeneration)remediation.disabled=false}
      });
      output?.appendChild(card);
    }
  }catch(error){if(generation===projectKnowledgeGeneration&&status)status.textContent=String(error?.message||error)}
  finally{if(button)button.disabled=false}
});
$('projectKnowledgeSync')?.addEventListener('click',async()=>{
  const root=String($('projectKnowledgeRoot')?.value||'');if(!root)return;
  const generation=++projectKnowledgeGeneration,output=$('projectKnowledgeResults'),status=$('projectKnowledgeStatus'),button=$('projectKnowledgeSync');
  if(button)button.disabled=true;if(output)output.replaceChildren();if(status)status.textContent='Reading local Git status…';
  try{
    const result=await post('/api/repo/knowledge/manage',{root,action:'sync_status'});
    if(generation!==projectKnowledgeGeneration)return;
    if(result?.success!==true)throw new Error(result?.error||'Git status unavailable');
    if(status)status.textContent='Shared paths: '+String(result.state)+' · remote not verified';
    const details=document.createElement('pre');details.className='human-pre';details.textContent=JSON.stringify(result,null,2);output?.appendChild(details);
  }catch(error){if(generation===projectKnowledgeGeneration&&status)status.textContent=String(error?.message||error)}
  finally{if(button)button.disabled=false}
});
$('projectKnowledgeHandoffs')?.addEventListener('click',async()=>{
  const root=String($('projectKnowledgeRoot')?.value||'');if(!root)return;
  const generation=++projectKnowledgeGeneration,output=$('projectKnowledgeResults'),status=$('projectKnowledgeStatus'),button=$('projectKnowledgeHandoffs');
  const current=()=>generation===projectKnowledgeGeneration&&$('projectKnowledgeRoot')?.value===root;
  if(button)button.disabled=true;if(output)output.replaceChildren();if(status)status.textContent='Reading shared handoffs…';
  try{
    const result=await post('/api/repo/knowledge/manage',{root,action:'handoff_list',limit:32});
    if(!current())return;
    if(result?.success!==true)throw new Error(result?.error||'Handoffs unavailable');
    const items=Array.isArray(result.handoffs)?result.handoffs:[];
    if(status)status.textContent=items.length+' historical handoffs · '+(result.complete?'inventory complete':'inventory partial');
    for(const item of items){
      const card=document.createElement('section');card.className='section';
      const title=document.createElement('h3');title.textContent=String(item.goal||item.id);card.appendChild(title);
      const meta=document.createElement('p');meta.className='tiny muted';meta.textContent=String(item.historical_status)+' · requires current revalidation';card.appendChild(meta);
      const preview=document.createElement('button');preview.type='button';preview.className='btn';preview.textContent='Preview new task';card.appendChild(preview);
      const details=document.createElement('pre');details.className='human-pre';card.appendChild(details);
      preview.addEventListener('click',async()=>{
        preview.disabled=true;card.querySelector('[data-handoff-create]')?.remove();
        try{
          const request={root,action:'preview_handoff_resume',handoff_id:item.id,expected_revision:item.revision};
          const candidate=await post('/api/repo/knowledge/manage',request);
          if(!current())return;
          if(candidate?.success!==true)throw new Error(candidate?.error||'Handoff preview unavailable');
          details.textContent=JSON.stringify({contract:candidate.contract,historical_verification:candidate.historical_verification,requires_revalidation:true},null,2);
          const create=document.createElement('button');create.type='button';create.className='btn primary';create.dataset.handoffCreate='true';create.textContent='Create reviewed new task';card.appendChild(create);
          const taskId='task_'+crypto.randomUUID().replace(/-/g,'').slice(0,20);
          create.addEventListener('click',async()=>{
            if(!current())return;
            create.disabled=true;preview.disabled=true;
            try{
              const checked=await post('/api/repo/knowledge/manage',request);
              if(!current())return;
              if(checked?.success!==true||checked.preview_digest!==candidate.preview_digest||JSON.stringify(checked.contract)!==JSON.stringify(candidate.contract))throw new Error('Handoff changed; refresh before resuming');
              const created=await post('/api/agent-state/tasks',{action:'create',root,task_id:taskId,contract:checked.contract});
              if(!current())return;
              if(created?.success!==true||!created.task)throw new Error(created?.error||'Task creation not confirmed');
              details.textContent='Created planned Agent OS task '+String(created.task.task_id||taskId)+'. Historical results are not current verification.';
            }catch(error){
              if(current())details.textContent=String(error?.message||error)+' · Inspect Agent OS for task '+taskId+' before retry.';
            }finally{if(current())preview.disabled=false}
          });
        }catch(error){if(current())details.textContent=String(error?.message||error)}
        finally{if(current())preview.disabled=false}
      });
      output?.appendChild(card);
    }
  }catch(error){if(current()&&status)status.textContent=String(error?.message||error)}
  finally{if(button)button.disabled=false}
});
$('projectKnowledgeRoot')?.addEventListener('change',resetProjectKnowledge);
$('projectKnowledgeForm')?.addEventListener('submit',async event=>{
  event.preventDefault();
  const root=String($('projectKnowledgeRoot')?.value||''),query=String($('projectKnowledgeQuery')?.value||'').trim();
  if(!root||!query)return;
  const generation=++projectKnowledgeGeneration,button=$('projectKnowledgeSearch'),status=$('projectKnowledgeStatus'),output=$('projectKnowledgeResults');
  if(button)button.disabled=true;
  if(status)status.textContent='Reading repository declarations…';
  if(output)output.replaceChildren();
  try{
    const result=await post('/api/repo/knowledge/query',{root,query,limit:8});
    if(generation!==projectKnowledgeGeneration||$('projectKnowledgeRoot')?.value!==root)return;
    if(result?.success!==true)throw new Error(result?.error||'Knowledge query failed');
    renderProjectKnowledgeResults(result);
  }catch(error){
    if(generation===projectKnowledgeGeneration&&status)status.textContent='Knowledge unavailable: '+String(error?.message||error);
  }finally{
    if(generation===projectKnowledgeGeneration&&button)button.disabled=false;
  }
});
function renderProjects(items){
  updateProjectKnowledgeRoots(items);
  const status=preprocessingSummary(last?.preprocessing||{},last?.dependency_status||{},last?.features||{});
  if(!status.available){
    if($('projectSummary'))$('projectSummary').textContent='Project inventory unavailable';
    if($('prepOverview'))$('prepOverview').innerHTML='<div class="prep-summary-card"><span>Project status unavailable</span></div>';
    rows('projectsBody',[],()=>'',5,'Project status unavailable. Refresh status to retry.');
    return;
  }
  const entries=Array.isArray(items)?items:[],source=groupedProjects(entries),query=projectQuery.trim().toLowerCase();
  const inspected=activeProjectInspectorRoot&&$('modalBg')?.classList.contains('open')?entries.find(item=>item.root===activeProjectInspectorRoot):null;
  if(inspected){
    activeProjectInspectorData={...activeProjectInspectorData,...inspected};
    const current=activeProjectInspectorData,liveOverall=preprocessingProgress(current),liveState=projectState(current);
    const liveCounts=preprocessingCounts(current),liveBadge={running:['badge-running','Running'],waiting:['badge-waiting','Waiting'],paused:['badge-paused','Paused'],error:['badge-error','Error'],ready:['badge-complete','Ready']}[liveState]||['badge-waiting','Queued'];
    if($('projectLiveBadge')){ $('projectLiveBadge').className=`badge-status ${liveBadge[0]}`;$('projectLiveBadge').textContent=liveBadge[1]; }
    if($('projectLivePhase'))$('projectLivePhase').textContent=inspected.phase||'Unavailable';
    if($('projectLiveProgress'))$('projectLiveProgress').textContent=inspected.phase_progress_measured!==false&&typeof inspected.phase_progress_pct==='number'?`${inspected.phase_progress_pct}%`:'Unavailable';
    if($('projectLiveActivity'))$('projectLiveActivity').textContent=inspected.active_detail||inspected.waiting_reason||'Unavailable';
    if($('projectLiveOverall'))$('projectLiveOverall').textContent=liveOverall===null?'Overall estimate unavailable':`${liveOverall}% estimated overall`;
    if($('projectLiveBar'))$('projectLiveBar').style.width=`${liveOverall??0}%`;
    if($('projectLiveStepper'))$('projectLiveStepper').innerHTML=renderStepper(inspected.phase_index||1,liveState==='ready',liveState);
    if($('projectPhaseList'))$('projectPhaseList').innerHTML=projectPhaseListHtml(current);
    if($('projectPhaseLabel'))$('projectPhaseLabel').textContent=inspected.phase||'Unavailable';
    if($('projectPhaseDetail'))$('projectPhaseDetail').textContent=inspected.active_detail||inspected.waiting_reason||'Unavailable';
    for(const [id,pair] of [['projectLiveHash',liveCounts.hash],['projectLiveCode',liveCounts.code],['projectLiveRag',liveCounts.rag],['projectLiveCards',liveCounts.cards]])if($(id))$(id).textContent=preprocessingCountText(pair);
    if($('projectLiveBreakdownPhase'))$('projectLiveBreakdownPhase').textContent=inspected.active_detail||inspected.phase||'Unavailable';
    if($('projectLiveRate'))$('projectLiveRate').textContent=`${inspected.speed_str||'Unavailable'} · ${inspected.phase==='rag'?'Estimate unavailable':inspected.eta_str||'Unavailable'}`;
  }
  const overview=$('prepOverview');
  if(overview){const count=state=>entries.filter(entry=>projectState(entry)===state).length;overview.innerHTML=[['Running',count('running')],['Waiting / queued',count('waiting')+count('queued')],['Paused / errors',count('paused')+count('error')],['Ready',count('ready')]].map(([label,value])=>`<div class="prep-summary-card"><b>${n(value)}</b><span>${label}</span></div>`).join('');}
  const rank={error:0,running:1,waiting:2,queued:3,paused:4,ready:5};
  const visible=source.filter(x=>{
    const state=projectState(x),haystack=[x.project,x.root,x.repository_identity,x.active_detail,x.phase,...(x.variants||[]).map(v=>v.root)].join(' ').toLowerCase();
    return (!query||haystack.includes(query))&&(projectFilter==='all'||state===projectFilter);
  });
  visible.sort((a,b)=>{
    if(projectSort==='name')return String(a.project||'').localeCompare(String(b.project||''));
    if(projectSort==='progress')return Number(b.overall_progress_pct||0)-Number(a.overall_progress_pct||0)||String(a.project||'').localeCompare(String(b.project||''));
    if(projectSort==='recent')return Number(b.updated_at||b.last_complete_at||0)-Number(a.updated_at||a.last_complete_at||0)||String(a.project||'').localeCompare(String(b.project||''));
    return (rank[projectState(a)]??9)-(rank[projectState(b)]??9)||String(a.project||'').localeCompare(String(b.project||''));
  });
  const summary=$('projectSummary');
  if(summary)summary.textContent=`${visible.length} of ${source.length} repository identities · ${entries.length} project entries`;
  rows('projectsBody',visible,x=>{
    const state=projectState(x),counts=preprocessingCounts(x),overall=preprocessingProgress(x),phasePct=Math.max(0,Math.min(100,Number(x.phase_progress_pct||0))),isComplete=state==='ready',isWorktree=x.is_worktree===true;
    const badge={running:['badge-running','Running','<span class="pulse-dot"></span>'],waiting:['badge-waiting','Waiting',''],paused:['badge-paused','Paused',''],error:['badge-error','Error',''],ready:['badge-complete','Ready','✓ ']}[state]||['badge-waiting','Queued',''];
    const activityText=isComplete?'Indexing complete · last reported snapshot':x.active_detail||(state==='paused'?(x.global_paused?'Globally paused':'Project paused'):state==='waiting'?'Waiting for preprocessing slot':state==='error'?(x.last_error_short||'Pipeline error'):'Processing queue');
    const activityCls=isComplete?'ok':state==='error'?'bad-t':state==='paused'?'warn-t':state==='waiting'?'muted':'';
    const progressAge=Number(x.progress_age_seconds),progressHint=Number.isFinite(progressAge)?(progressAge<5?'live checkpoint':`${durSec(progressAge)} since last checkpoint`):'';
    const phaseIndex=PHASES.findIndex(ph=>ph.id===x.phase),currentStep=phaseIndex>=0?phaseIndex+1:(Number(x.phase_index)||1);
    const phaseObj=(phaseIndex>=0?PHASES[phaseIndex]:null)||(isComplete?PHASES[PHASES.length-1]:{name:x.phase||'Inventory',icon:'⚙️'});
    const phaseTitle=(isComplete||x.phase==='complete')?`${PHASES.length}/${PHASES.length} Ready`:`${currentStep}/${PHASES.length} ${phaseObj.icon} ${phaseObj.name}`;
    const phaseDetailText=isComplete?'100% complete':(x.phase_progress_measured!==false&&typeof x.phase_progress_pct==='number'&&Number.isFinite(x.phase_progress_pct)?`${phasePct}% in current phase`:'Phase progress unavailable');
    const remainingText=x.phase==='hash'&&counts.hash.remaining!==null?`${n(counts.hash.remaining)} files left to hash`:'';
    const variants=x.variants||[x],variantLabel=variants.length>1?`<span class="chip" title="${esc(variants.map(v=>v.root).join('\n'))}">${variants.length} entries · showing ${esc(x.root||'selected entry')}</span>`:'';
    const actions=`<div class="project-actions"><button class="action-btn-sm" data-project-details title="Open project details">Details</button><button class="action-btn-sm" data-project-action="${state==='paused'?'resume':'pause'}" data-project-root="${esc(x.root)}" title="${state==='paused'?'Resume project preprocessing':'Pause project'}">${state==='paused'?'▶ Resume':'⏸ Pause'}</button><button class="action-btn-sm" data-project-action="refresh" data-project-root="${esc(x.root)}" title="Re-scan selected project entry">Refresh</button><button class="action-btn-sm danger" data-project-action="delete" data-project-root="${esc(x.root)}" data-project-name="${esc(x.project)}" title="Unregister selected project entry">Unregister</button></div>`;
    return clickableRow(x,`<td><span class="prep-kicker">Repository entry</span><div class="project-name"><b>${esc(x.project)}</b>${isWorktree?'<span class="chip" style="font-size:9px;color:var(--accent2);border-color:#584578">worktree</span>':''}${variantLabel}</div><div class="tiny muted mono project-root" title="${esc(x.root||'')}">${esc(x.root||'—')}</div></td><td><span class="prep-kicker">Current activity</span><span class="badge-status ${badge[0]}">${badge[2]}${badge[1]}</span><div class="tiny ${activityCls} project-activity" title="${esc(x.active_detail||activityText)}">${esc(activityText)}</div><div class="tiny muted">${esc(progressHint)}</div></td><td><span class="prep-kicker">Pipeline · estimated overall</span><div class="project-progress-line"><b>${phaseTitle}</b><span class="prep-progress-value">${overall===null?'—':overall+'%'}</span></div><div class="bar project-progress" role="progressbar" aria-label="Estimated overall progress" ${overall===null?'':`aria-valuenow="${overall}"`} aria-valuemin="0" aria-valuemax="100"><i style="width:${overall??0}%;background:${state==='error'?'var(--bad)':isComplete?'var(--ok)':'var(--accent)'}"></i></div><div class="tiny muted">${esc(phaseDetailText)}</div><div class="tiny muted">${esc(remainingText)}</div><div class="tiny muted">${esc(x.speed_str||'')} ${x.eta_str&&x.phase!=='rag'?'· Phase ETA: '+esc(x.eta_str):''}</div></td><td><span class="prep-kicker">Inventory coverage</span><div class="project-index"><span>Hashed ${preprocessingCountText(counts.hash)}</span><span>RAG ${preprocessingCountText(counts.rag)}</span><span>Cards ${preprocessingCountText(counts.cards)}</span></div></td><td><span class="prep-kicker">Actions for this entry</span>${actions}</td>`,'project',x.root);
  },5,query||projectFilter!=='all'?'No projects match the current filters.':'No projects registered. Register a repository to begin.');
}
async function projectAction(root, action) {
  const btn = arguments[2];
  if(btn) if(typeof setButtonLoading==='function')setButtonLoading(btn, true, '…');
  try { const result=await post('/api/preprocess', { root, action }); if(!result.success)throw new Error(result.error||'Project action failed'); await pollStatus(); } catch(e) { alert('Action error: ' + e); } finally { if(btn) if(typeof setButtonLoading==='function')setButtonLoading(btn, false); }
}
$('regProjectBtn').onclick = openRegisterProjectModal;
$('cleanMissingBtn').onclick = openCleanMissingModal;
async function deleteProjectDialog(root, name) {
  openDeleteProjectModal(root, name);
}

function openControlConfirmation(action){
  const details={
    purge_cache:{title:'Purge expired cache',scope:'Cache entries older than 7 days in configured state directory.',impact:'Expired cached responses removed. Project source and indexes remain intact.'},
    purge_stats:{title:'Purge all statistics',scope:'All recorded telemetry, token savings metrics, latency rollups, endpoint counters and live traces.',impact:'All accumulated metrics reset to zero across all repositories. Current projects and plans are unaffected.'},
  }[action];
  if(!details)return;
  if($('modalTitle'))$('modalTitle').textContent=details.title;
  if($('modalLive'))$('modalLive').textContent='Confirmation required';
  if($('modalBody'))$('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Scope and impact</span></div><div class="modal-card-body"><p><b>Scope:</b> ${esc(details.scope)}</p><p style="margin-bottom:0"><b>Impact:</b> ${esc(details.impact)}</p></div></div><div class="modal-actions-bar" style="justify-content:flex-end"><button class="btn" onclick="$('modalClose')?.click()">Cancel</button><button class="btn warn" id="confirmControlAction">${esc(details.title)}</button></div></div>`;
  if($('modalBg'))$('modalBg').classList.add('open');
  const confirmBtn=$('confirmControlAction');
  if(confirmBtn)confirmBtn.onclick=async()=>{
    if(typeof setButtonLoading==='function')setButtonLoading(confirmBtn, true, 'Purging…');
    try{
      if(action==='purge_cache'){
        await post('/api/maintenance/purge_cache',{days:7});
      }else if(action==='purge_stats'){
        await post('/api/telemetry/endpoint-stats/reset',{root:'',purge_telemetry:true});
        if(typeof loadOverview==='function')loadOverview();
        if(typeof loadTelemetry==='function')loadTelemetry();
        if(typeof render==='function'&&last)render(last);
      }
      $('modalClose')?.click();
    }catch(error){
      if($('modalLive'))$('modalLive').textContent='Action failed: '+String(error?.message||error);
    }finally{
      if(typeof setButtonLoading==='function')setButtonLoading(confirmBtn, false);
    }
  };
}
$('optDbBtn').onclick=async()=>{try{const r=await post('/api/maintenance/optimize_db',{});openModal(r,'Database Optimization & WAL Checkpoint Results','db_opt')}catch(e){openModal({error:String(e)},'Error')}};
$('purgeCacheBtn').onclick=()=>openControlConfirmation('purge_cache');
if($('purgeStatsBtn'))$('purgeStatsBtn').onclick=()=>openControlConfirmation('purge_stats');
if($('purgeDebugTracesBtn'))$('purgeDebugTracesBtn').onclick=async()=>{
  if(!window.confirm('Purge every retained detailed trace, including active trace records? This cannot be undone.'))return;
  const button=$('purgeDebugTracesBtn');if(button)button.disabled=true;
  try{const result=await post('/api/debug-traces/purge',{confirm:true});if(!result?.success)throw new Error(result?.error||'Trace purge failed');activeTraceId='';activeTraceData=null;traceEvents=[];traceSeq=0;$('tracePageBody')?.replaceChildren();const status=$('detailedTelemetryStatus');if(status)status.textContent=`Purged ${result.deleted_sessions} traces and ${result.deleted_events} events.`;await pollTraces();}
  catch(error){const status=$('detailedTelemetryStatus');if(status)status.textContent=String(error?.message||'Trace purge failed').slice(0,240);}
  finally{if(button)button.disabled=false;}
};
$('doctorBtn').onclick=openDoctorModal;

function ensureHttpTailTable(){
  const performance=$('performance');if(!performance||$('httpTail'))return;
  performance.insertAdjacentHTML('beforeend','<section class="section"><h2>HTTP tail latency <span class="tiny">per action · excludes policy rejections</span></h2><div class="table-wrap"><table><thead><tr><th>Action</th><th>Calls</th><th>p50</th><th>p95</th><th>p99</th><th>Fails</th></tr></thead><tbody id="httpTail"></tbody></table></div></section>');
}
function setupWorkLayout(){
  const work=$('work');if(!work||work.dataset.refined)return;work.dataset.refined='1';work.classList.add('work-page');
  const sections=[...work.children].filter(x=>x.classList.contains('section'));sections.forEach((x,i)=>x.classList.add('work-panel','work-panel-'+(i+1)));
  const headers=[['State','Work item','Model / source','Timing','Reason'],['Request','Agent','Action','Age'],['Time','Request ID','Project','Agent','Action / context','Result','Trace availability','Duration'],['State','Kind','Project','Action / context','Agent','Model','Created','Updated / duration','Links']];
  sections.forEach((section,index)=>{const row=section.querySelector('thead tr');if(row&&headers[index])row.innerHTML=headers[index].map(x=>`<th>${x}</th>`).join('')});
  work.insertAdjacentHTML('afterbegin','<section class="section work-summary"><div class="work-summary-head"><div><div class="work-kicker">Requests</div><h2>Live work</h2></div><span class="tiny">Click any row to inspect its trace</span></div><div class="work-kpis"><div><span>Queued</span><strong id="workQueued">—</strong></div><div><span>Running</span><strong id="workRunning">—</strong></div><div><span>Active API</span><strong id="workActive">—</strong></div><div><span>Retained traces</span><strong id="workRetained">—</strong></div></div><div class="work-filter"><input id="workSearch" type="search" placeholder="Search project, agent, action, model…" autocomplete="off"><select id="workState" aria-label="Work state"><option value="">All states</option><option value="running">Running</option><option value="queued">Queued</option><option value="failed">Failed</option><option value="completed">Completed</option></select><button class="btn" id="workReset">Reset</button><span class="work-filter-summary" id="workFilterSummary"></span></div></section>');
  $('workSearch').oninput=()=>last&&render(last);$('workState').onchange=()=>last&&render(last);$('workReset').onclick=()=>{$('workSearch').value='';$('workState').value='';if(last)render(last)};
  if($('requestHistoryReset')&&!$('requestHistorySort'))$('requestHistoryReset').insertAdjacentHTML('beforebegin','<select id="requestHistorySort" aria-label="Sort recent API requests"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="duration-desc">Longest duration</option><option value="status">Status</option><option value="endpoint">Endpoint A–Z</option></select>');
  if($('traceKind')&&!$('traceTableSearch'))$('traceKind').insertAdjacentHTML('beforebegin','<input id="traceTableSearch" type="search" aria-label="Search agent traces" placeholder="Search request, action, trace ID…" style="width:220px"><select id="traceTableState" aria-label="Filter traces by state"><option value="">All states</option><option value="running">Running</option><option value="queued">Queued</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="interrupted">Interrupted</option></select><select id="traceTableSort" aria-label="Sort agent traces"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="action">Action A–Z</option><option value="duration">Longest run</option><option value="state">State</option></select><button class="btn" id="traceTableReset">Reset</button>');
  $('requestHistorySearch')?.addEventListener('input',()=>last&&render(last));
  ['requestHistoryAction','requestHistoryStatus','requestHistoryPeriod','requestHistorySort'].forEach(id=>$(id)?.addEventListener('change',()=>last&&render(last)));
  $('requestHistoryReset')?.addEventListener('click',()=>{['requestHistorySearch','requestHistoryAction','requestHistoryStatus','requestHistoryPeriod'].forEach(id=>{const control=$(id);if(control)control.value=''});if($('requestHistorySort'))$('requestHistorySort').value='newest';if(last)render(last)});
  $('traceTableSearch')?.addEventListener('input',()=>renderTraceList(lastTraces));
  ['traceTableState','traceTableSort'].forEach(id=>$(id)?.addEventListener('change',()=>renderTraceList(lastTraces)));
  $('traceTableReset')?.addEventListener('click',()=>{if($('traceTableSearch'))$('traceTableSearch').value='';if($('traceTableState'))$('traceTableState').value='';if($('traceTableSort'))$('traceTableSort').value='newest';if($('traceKind'))$('traceKind').value='';renderTraceList(lastTraces)});
}
function workVisible(items){const query=String($('workSearch')?.value||'').trim().toLowerCase(),state=String($('workState')?.value||'').toLowerCase();return (items||[]).filter(item=>{const itemState=String(item.state||item.status||'').toLowerCase(),hay=Object.values(item||{}).join(' ').toLowerCase();return (!query||hay.includes(query))&&(!state||(state==='completed'?['completed','complete','succeeded','success','done'].includes(itemState):itemState===state||(state==='running'&&itemState==='processing')))});}
function filterRecentRequests(items,allItems){
  const all=allItems||items||[],selected=String($('requestHistoryAction')?.value||''),counts=new Map();
  all.forEach(item=>{const action=String(item.action||'');if(action)counts.set(action,(counts.get(action)||0)+1)});
  const actionSelect=$('requestHistoryAction');
  if(actionSelect){actionSelect.innerHTML='<option value="">All endpoints ('+all.length+')</option>'+[...counts].sort((a,b)=>a[0].localeCompare(b[0])).map(([action,count])=>`<option value="${esc(action)}">${esc(action)} (${count})</option>`).join('');actionSelect.value=counts.has(selected)?selected:''}
  const query=String($('requestHistorySearch')?.value||'').trim().toLowerCase(),action=String(actionSelect?.value||''),status=String($('requestHistoryStatus')?.value||''),period=Number($('requestHistoryPeriod')?.value||0),after=period?Date.now()/1000-period:0;
  const visible=(items||[]).filter(item=>{
    const code=Number(item.status_code||0),hay=[item.request_id,item.action,item.project,item.agent,item.error_type,code,traceProjectLabel(item),traceContextLabel(requestTrace(item))].filter(Boolean).join(' ').toLowerCase();
    const matchesStatus=!status||(status==='failed'?(item.success===false||code>=400):Math.floor(code/100)===Number(status[0]));
    return (!query||hay.includes(query))&&(!action||String(item.action||'')===action)&&matchesStatus&&(!after||Number(item.created_at||0)>=after);
  });
  const sort=String($('requestHistorySort')?.value||'newest');
  visible.sort((a,b)=>{const time=Number(a.created_at||0)-Number(b.created_at||0);if(sort==='oldest')return time;if(sort==='duration-desc')return Number(b.duration_ms||0)-Number(a.duration_ms||0);if(sort==='status')return Number(b.status_code||0)-Number(a.status_code||0);if(sort==='endpoint')return String(a.action||'').localeCompare(String(b.action||''))||-time;return -time});
  const summary=$('requestHistorySummary');if(summary)summary.textContent=`${visible.length} of ${all.length} loaded · ${counts.size} endpoints`;
  return visible;
}
function workState(state){const value=String(state||'queued'),cls=value==='failed'||value==='error'?'bad':(value==='running'||value==='processing'?'live':'');return `<span class="work-state ${cls}">${esc(value)}</span>`}
function workSchedulerRow(job){const inner=`<td>${workState(job.state)}</td><td><strong>#${n(job.job_id)}</strong></td><td><strong>${esc(job.model||'—')}</strong><div class="tiny">${esc(job.source||'—')}</div></td><td><span class="timing-label">wait</span> ${ms(job.wait_ms)}<div><span class="timing-label">run</span> ${ms(job.service_ms)}</div></td><td>${esc(job.wait_reason||'ready')}</td>`;return schedulerRow(job,inner,5)}
function workActiveRequestRow(request){const inner=`<td><strong>${esc(request.request_id||'—')}</strong></td><td>${esc(request.agent||'—')}</td><td>${esc(request.action||'—')}</td><td>${age(request.age_ms)}</td>`;return requestRow(request,inner,4)}
function requestTrace(request){return lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''))}
function traceContextLabel(trace){
  if(!trace)return '';
  const source=trace.source&&trace.source!==trace.action?trace.source:'',summary=trace.summary||trace.description||trace.operation||trace.action_detail||'',requestId=trace.request_id?`req ${String(trace.request_id).slice(-8)}`:'',jobId=trace.async_job_id?`job ${String(trace.async_job_id).slice(-8)}`:'';
  return [...new Set([trace.request_summary,summary,source,trace.kind?humanLabel(trace.kind):'',trace.model?`model ${trace.model}`:'',requestId,jobId].filter(Boolean))].join(' · ');
}

function requestTraceAvailability(request){
  if(request.trace_available===false)return {label:'No trace recorded',className:'muted',trace:null};
  const trace=requestTrace(request);
  if(trace)return {label:'Trace available',className:'ok',trace};
  return {label:'Trace status unverified',className:'muted',trace:null};
}
function requestOutcome(request={},trace=null){
  const code=Number(request.status_code)||0,state=String(trace?.state||'').trim().toLowerCase();
  const pendingStates=['outcome_unknown','interrupted','cancelled','canceled','timed_out','preempted','partial','needs_agent','blocked','planned','ready','source_ready','active','in_progress','running','queued','pending','waiting'];
  const traceFailed=state==='failed'||state==='error',failed=request.success===false||code>=400||traceFailed;
  const pending=!failed&&pendingStates.includes(state);
  const label=pending?humanLabel(state):failed?'Failed':request.success===true?'Succeeded':code?'HTTP result':'Result unreported';
  return {failed,pending,label:label+(code?' · HTTP '+code:''),className:failed?'bad-t':pending?'warn-t':request.success===true?'ok':'muted'};
}
function workRecentRequestRow(request){const trace=requestTrace(request),availability=requestTraceAvailability(request),outcome=requestOutcome(request,trace),context=trace?traceContextLabel(trace):(request.error_type||''),requestId=String(request.request_id||'—'),project=traceProjectLabel(request.project||request.workspace||request.root||trace?.project)||'—',inner=`<td>${request.created_at?new Date(request.created_at*1000).toLocaleString():'—'}</td><td><strong>${esc(requestId.slice(-12))}</strong><div class="tiny">${trace?'Trace linked · '+esc(String(trace.trace_id||'').slice(-8)):'Request-only record'}</div></td><td><strong>${esc(project)}</strong></td><td>${esc(request.agent||'—')}</td><td><strong>${esc(request.action||'—')}</strong><div class="tiny">${esc(context)}</div></td><td><span class="${outcome.className}">${esc(outcome.label)}</span>${request.error_type?`<div class="tiny">${esc(request.error_type)}</div>`:''}</td><td><span class="${availability.className}">${esc(availability.label)}</span></td><td>${ms(request.duration_ms)}</td>`;return requestRow(request,inner,8)}

function renderRecentRequestHistory(snapshot=last){
  if(!snapshot)return;
  const recentRequests=snapshot.observability?.recent_http||[],visibleRecent=filterRecentRequests(workVisible(recentRequests),recentRequests);
  rows('recentReq',visibleRecent,x=>workRecentRequestRow(x),8,'No requests match the current filters.');
}
function updateTraceSummaries(items){
  const changed=JSON.stringify(items)!==JSON.stringify(lastTraces),recentRequests=last?.observability?.recent_http||[];
  if(!changed)return {changed:false};
  const requestIds=new Set(recentRequests.map(request=>String(request.request_id||'')).filter(Boolean));
  const priorLinks=new Map(lastTraces.filter(trace=>requestIds.has(String(trace.request_id||''))).map(trace=>[String(trace.request_id),String(trace.trace_id||'')]));
  const nextLinks=new Map(items.filter(trace=>requestIds.has(String(trace.request_id||''))).map(trace=>[String(trace.request_id),String(trace.trace_id||'')]));
  const linksChanged=[...requestIds].some(id=>priorLinks.get(id)!==nextLinks.get(id));
  lastTraces=items;renderTraceList(lastTraces);
  if(linksChanged&&document.querySelector('.page.active')?.id==='work')renderRecentRequestHistory(last);
  return {changed:true};
}

function render(s){
  last=s;
  syncDetailedTelemetryToggle(resolveDetailedTelemetryState(Boolean(s.debug_traces?.enabled)));
  const receivedAt=Date.now();
  lastOverviewReceivedAt=receivedAt;
  const q=s.scheduler||{},o=s.observability||{},p=s.preprocessing||{},bg=s.background_gpu||{},h=s.headless||{},r=s.runtime_stats||{},ss=q.stats||{},rp=s.runtime_profile||{},cmd=r.commands||{};
  ensureHttpTailTable();setupWorkLayout();
  renderOverviewHealth(s,receivedAt);

  (function renderFeaturePills(){
    const feat=s.features||{};
    const mods=[
      {k:'status',label:'Status',tool:'local_ai_status',tab:'overview'},
      {k:'repo',label:'Repo',tool:'local_ai_repo',tab:'projects'},
      {k:'tasks',label:'Tasks',tool:'local_ai_task',tab:'performance'},
      {k:'rag',label:'RAG',tool:'local_ai_rag',tab:'performance'},
      {k:'coord',label:'Coord',tool:'local_ai_coord',tab:'work'},
      {k:'artifacts',label:'Artifacts',tool:'local_ai_artifact',tab:'overview'},
      {k:'code_intelligence',label:'Code intel',tool:'AST / Serena / Graph',tab:'projects'},
      {k:'preprocessing',label:'Preprocessing',tool:'Background workers',tab:'projects'},
      {k:'subagents',label:'Subagents',tool:'Ollama workers',tab:'performance'},
      {k:'agent_os',label:'Agent OS',tool:'Durable memory/receipts',tab:'agentos'},
      {k:'dashboard',label:'Dashboard',tool:'Web UI',tab:'config'},
    ];
    const pills=$('featurePills');
    if(pills){
      const disabledMods=mods.filter(m=>feat[m.k]===false);
      const enabledCount=mods.filter(m=>feat[m.k]===true).length,unknownCount=mods.filter(m=>feat[m.k]==null).length;
      pills.innerHTML=mods.map(m=>{
        const off=feat[m.k]===false,unknown=feat[m.k]==null;
        if(unknown)return `<button class="chip" data-goto-tab="${m.tab}">${esc(m.label)} · unreported</button>`;
        return `<button class="chip" data-goto-tab="${m.tab}" style="cursor:pointer;${off?'border-color:#7f1d1d;color:#f87171;background:#450a0a33':'border-color:#065f46;color:#34d399;background:#064e3b22'}" title="${m.k}: ${off?'disabled':'enabled'} · tool: ${m.tool}"><b>${m.label}</b> ${off?'<span class="tiny bad-t">✗ off</span>':'<span class="tiny ok">✓ on</span>'}</button>`;
      }).join('');
      pills.querySelectorAll('[data-goto-tab]').forEach(btn=>btn.onclick=()=>switchTab(btn.dataset.gotoTab));
      const txt=$('featStatusText');
      if(txt){
        if(unknownCount){txt.textContent=unknownCount+' module states unreported';txt.title='';}
        else if(disabledMods.length){txt.innerHTML=`<span class="warn-t">${disabledMods.length} module${disabledMods.length>1?'s':''} disabled</span>`;txt.title=disabledMods.map(m=>m.k).join(', ');}
        else{txt.innerHTML='<span class="ok">All 12 modules enabled</span>';txt.title='';}
      }
      const sumEl=$('featSummary');
      if(sumEl){
        sumEl.style.cursor='pointer';
        sumEl.onclick=()=>switchTab('config');
        if(unknownCount){sumEl.textContent=enabledCount+'/'+mods.length+' modules enabled · '+unknownCount+' unreported';sumEl.className='pill tiny warn-t';}
        else if(disabledMods.length){sumEl.textContent=enabledCount+'/'+mods.length+' modules enabled';sumEl.className='pill tiny warn-t';}
        else{sumEl.textContent='12/12 modules enabled ✓';sumEl.className='pill tiny ok';}
      }
    }
    document.querySelectorAll('.tabbtn[data-feature]').forEach(b=>{
      const f=b.dataset.feature;
      const off=feat[f]===false;
      b.classList.toggle('tab-disabled',off);
      let badge=b.querySelector('.tab-badge');
      if(off){if(!badge){badge=document.createElement('span');badge.className='tab-badge bad-t';badge.textContent='(off)';b.appendChild(badge);}}
      else if(badge){badge.remove();}
    });
    if($('cmdDisabledBanner'))$('cmdDisabledBanner').style.display=feat.commands===false?'flex':'none';
    if($('agentOsDisabledBanner'))$('agentOsDisabledBanner').style.display=feat.agent_os===false?'flex':'none';
    if(feat.tasks===false){
      if($('fgQueue'))$('fgQueue').innerHTML='<span class="muted">local LLM tasks disabled</span>';
      if($('bgQueue'))$('bgQueue').innerHTML='<span class="muted">tasks feature disabled (features.tasks=false)</span>';
    }
    if(feat.preprocessing===false){
      if($('prep'))$('prep').innerHTML='<span class="muted">disabled</span>';
      if($('prepSub'))$('prepSub').textContent='features.preprocessing = false';
    }
    if(feat.agent_os===false){
      if($('agentStateVal'))$('agentStateVal').innerHTML='<span class="muted">disabled</span>';
      if($('agentStateSub'))$('agentStateSub').textContent='features.agent_os = false';
    }
  })();

  const capabilityProfile=$('localCapabilityProfile'),capabilityStates=$('localCapabilityStates');
  if(capabilityProfile){
    const profile=String(s.hardware_profile||s.hardware?.profile||'unknown');
    capabilityProfile.textContent=`Effective profile: ${profile}. This is a configuration ceiling; provider readiness and model quality are not inferred here.`;
  }
  if(capabilityStates){
    const capabilities=s.capabilities&&typeof s.capabilities==='object'?s.capabilities:{};
    const labels={search_summaries:'Search summaries',semantic_analysis:'Semantic analysis',repository_review:'Repository review',cross_file_design:'Cross-file design',vision:'Vision',code_generation:'Code generation',automation:'Browser automation',bounded_local_work:'Bounded local work'};
    capabilityStates.innerHTML=Object.entries(labels).map(([key,label])=>{
      const item=capabilities[key];
      if(!item)return `<div class="tiny muted">${esc(label)} · state unreported</div>`;
      const state=String(item.state||'unknown'),reason=item.reason?String(item.reason):'';
      const enabled=state==='enabled_by_operator',blocked=state==='profile_blocked'||state==='feature_disabled';
      const stateClass=enabled?'warn-t':blocked?'muted':'muted';
      const detail=[item.feature_gate?`features.${item.feature_gate}`:'',reason,`provider ${item.provider_readiness||'unknown'}`].filter(Boolean).join(' · ');
      return `<div class="tiny ${stateClass}"><b>${esc(label)}</b> · ${esc(state)}${detail?` · ${esc(detail)}`:''}</div>`;
    }).join('');
  }

  if($('worktreeRoots'))$('worktreeRoots').innerHTML=[...new Set((p.projects||[]).map(project=>project.root).filter(Boolean))].sort().map(root=>`<option value="${esc(root)}"></option>`).join('');
  const repoSelect=$('agentOsRepoSelect');
  if(repoSelect){
    const currentVal=repoSelect.value;
    const projectRoots=(p.projects||[]).map(x=>x.root).filter(Boolean);
    const uniqueRoots=[...new Set(projectRoots)].sort();
    const rootsKey=uniqueRoots.join('|');
    if(repoSelect.dataset.renderedRoots!==rootsKey){
      let optHtml='<option value="">All repositories</option>';
      uniqueRoots.forEach(root=>{
        const proj=(p.projects||[]).find(x=>x.root===root);
        const name=(proj&&proj.project)?`${proj.project} (${root})`:root;
        optHtml+=`<option value="${esc(root)}">${esc(name)}</option>`;
      });
      repoSelect.innerHTML=optHtml;
      repoSelect.dataset.renderedRoots=rootsKey;
      if(currentVal)repoSelect.value=currentVal;
    }
  }

  const statusBadge=dashboardHealthBadge(s);
  $('health').innerHTML=`<span class="${statusBadge.className}">${s.hub_online==null?'hub ?':s.hub_online?'hub ✓':'hub ✗'} / ${s.ollama_online==null?'ollama ?':s.ollama_online?'ollama ✓':'ollama ✗'} / ${esc(h.state||'n/a')}${statusBadge.degradedLabel}</span>`;
  $('uptime').textContent='uptime '+durSec(s.uptime_seconds)+' · supervisor restarts '+n(h.restarts);

  const ep=(rp.execution||{}).models||(s.model_execution||{}).models||[];
  const httpTail=o.http_tail_latency||{};
  rows('httpTail',httpTail.by_action||[],x=>clickableRow(x,`<td>${esc(x.action)}</td><td>${n(x.events)}</td><td>${ms(x.p50_duration_ms)}</td><td>${ms(x.p95_duration_ms)}</td><td>${ms(x.p99_duration_ms)}</td><td>${n(x.failures)}</td>`,'http_tail'),6);

  $('fgQueue').textContent=n(q.foreground_queued)+' queued / '+n(q.foreground_inflight)+' running';
  $('bgQueue').textContent='background '+n(q.background_queued)+' queued / '+n(q.inflight_background)+' running · '+(q.background_allowed?'idle work allowed':'yielding');

  const http=o.http||{},cohorts=o.cohorts||{},agentHttp=cohorts.agent_http||{},inference=cohorts.inference||{},policy=cohorts.policy_rejection||{},compatibility=cohorts.compatibility||{},domains=o.cache_domains||{},generation=domains.generation||{},repository=domains.repository||{},commandCache=domains.command||{},cacheDecisions=o.cache_decisions||{},generationHits=Number(generation.hits||0),generationEvents=Number(generation.events||0),netDelta=Number(o.net_cloud_token_delta_est??0),savedTokens=Math.max(0,netDelta),tokenOverhead=Math.max(0,Number(o.cloud_token_overhead_est||0)),grossSaved=Math.max(0,Number(o.gross_cloud_tokens_avoided_est||0)),protocolTokens=Math.max(0,Number(o.agent_protocol_tokens_est||0)),toolCallTokens=Math.max(0,Number(o.agent_tool_request_tokens_est||0)),toolReadTokens=Math.max(0,Number(o.agent_tool_response_tokens_est||0)),schemaTokens=Math.max(0,Number(o.tool_schema_tokens_exposure_est||0)),schemaDelta=Number(o.net_after_schema_token_delta_est??0),localComputeSaved=Math.max(0,Number(o.local_compute_tokens_avoided_est||0)),savedUsd=o.estimated_savings_usd,inputSavedUsd=o.estimated_input_savings_usd,outputSavedUsd=o.estimated_output_savings_usd,inputRate=o.cloud_input_token_cost_usd_per_million,outputRate=o.cloud_output_token_cost_usd_per_million;
  $('handledRequests').textContent=n(agentHttp.events);
  $('handledRequestsSub').textContent=n(agentHttp.failures)+' operational failures · '+n(policy.events)+' policy rejections · '+n(compatibility.events)+' compatibility 404s';
  $('tokensSaved').textContent=n(netDelta);
  $('tokensSavedSub').textContent='baseline '+n(grossSaved)+' − protocol '+n(protocolTokens)+' (call '+n(toolCallTokens)+' + read '+n(toolReadTokens)+')'+(tokenOverhead?' · overhead '+n(tokenOverhead):'')+' · schema-adjusted '+n(schemaDelta)+' (catalog ≈'+n(schemaTokens)+')';
  $('dollarsSaved').textContent=o.estimated_savings_pricing_mode==='incomplete'||savedUsd==null?'Unknown':'≈ $'+Number(savedUsd).toFixed(2);
  $('dollarsSavedSub').textContent=o.estimated_savings_pricing_mode==='incomplete'?'Known channel subtotals: input '+formatChannelSavings(inputSavedUsd,inputRate)+' · output '+formatChannelSavings(outputSavedUsd,outputRate)+' · historical channel costs unknown':o.estimated_savings_pricing_mode==='input_output'?'input '+formatChannelSavings(inputSavedUsd,inputRate)+' · output '+formatChannelSavings(outputSavedUsd,outputRate):'Cost unavailable';
  const qHitRate=(Number(o.preprocessed_query_hit_rate??0)*100).toFixed(1),ingReuse=(Number(p.ingestion_reuse_rate??0)*100).toFixed(1);
  $('cache').textContent=generationEvents>0?((generationHits/generationEvents)*100).toFixed(1)+'%':'No samples';
  const reuse=o.cache_reuse_breakdown||{};
  const reuseDetail=n(reuse.semantic_hits)+' semantic · '+n(reuse.single_flight_waiters)+' single-flight';
  const semanticMissLabels={semantic_cache_disabled:'semantic cache disabled',query_too_short:'query too short',numpy_unavailable:'NumPy unavailable',query_embedding_unavailable:'query embedding unavailable',no_candidates:'no candidates in scope',invalid_query_vector:'invalid query vector',below_threshold:'below similarity threshold',invalid_candidates:'invalid candidate vectors',invalid_candidate_value:'invalid cached value',invalid_scope:'invalid semantic scope',context_ineligible:'context not eligible',cache_disabled:'cache disabled',reason_unavailable:'reason unavailable'};
  const semanticMissDetails=Object.entries(cacheDecisions).filter(([key])=>key.startsWith('semantic_miss_')).map(([key,count])=>{const reason=key.slice('semantic_miss_'.length);return Number(count)>0?n(count)+' '+(semanticMissLabels[reason]||reason.replaceAll('_',' ')):''}).filter(Boolean);
  const missDetail=[['new_exact_key','exact misses'],['semantic_not_reused','semantic misses'],['cache_disabled','cache disabled']].map(([key,label])=>Number(cacheDecisions[key]||0)>0?n(cacheDecisions[key])+' '+label:'').filter(Boolean).concat(semanticMissDetails).join(', ')||'no misses recorded';
  const generationDetail=generationEvents>0?n(generationHits)+'/'+n(generationEvents)+' generation hits · '+reuseDetail+' · '+missDetail:'No generation calls · '+missDetail;
  $('cacheSub').textContent=generationDetail+' · '+n(repository.hits)+' repository ('+qHitRate+'% index hit) · '+n(commandCache.hits)+' command hits · '+n(localComputeSaved)+' local tokens avoided';
  $('latency').textContent=ms(agentHttp.p50_duration_ms)+' / '+ms(agentHttp.p95_duration_ms)+' / '+ms(agentHttp.p99_duration_ms);
  $('queueWait').textContent='local inference p95 '+ms(inference.p95_duration_ms)+' · avg queue wait '+ms(o.avg_queue_wait_ms);
  $('reliabilityValue').innerHTML=`<span class="${agentHttp.failures?'warn-t':'ok'}">${n(agentHttp.failures)} failures</span>`;
  $('reliabilitySub').textContent=telemetryPeriod(o)+' · retained samples · '+n(policy.events)+' policy rejections · '+n(inference.fallback_count)+' fallbacks · '+n(inference.degraded_count)+' degraded · '+n(inference.retry_count)+' retries';

  renderTelemetryMetrics(o);

  // Plot selected-period aggregates observed at each distinct status refresh.
  const curP95=Number(agentHttp.p95_duration_ms||0);
  const curWait=Number(o.avg_queue_wait_ms||0);
  const curRps=Number(agentHttp.events||0);
  recordTelemetrySnapshot(o);

  drawSpark('latencySpark', latencySparkData, '#efb76f', 'rgba(56,189,248,0.12)');
  drawSpark('throughputSpark', throughputSparkData, '#34d399', 'rgba(52,211,153,0.12)');
  drawDualChart('liveChartCanvas', liveChartLatency, liveChartQueue);
  const liveChartEmpty=$('liveChartEmpty');
  const hasLiveChartSamples=liveChartLatency.length>0,liveChartCanvas=$('liveChartCanvas'),liveChartSummary=$('liveChartSummary');
  if(liveChartEmpty)liveChartEmpty.style.display=hasLiveChartSamples?'none':'block';
  const liveChartLabel=hasLiveChartSamples?`${telemetryPeriod(o)} aggregate snapshots. Period p95 latency ${ms(curP95)}. Period average queue wait ${ms(curWait)}. ${liveChartLatency.length} status snapshots.`:'No available telemetry samples for the selected period.';
  if(liveChartCanvas)liveChartCanvas.setAttribute('aria-label',liveChartLabel);
  if(liveChartSummary)liveChartSummary.textContent=liveChartLabel;
  if($('performanceMetricsScope'))$('performanceMetricsScope').textContent=telemetryPeriod(o)+' · retained samples · model, cache, agent, route and HTTP statistics below';

  const agState=s.agent_state||{};
  if($('agentStateVal')){
    if(agState.enabled&&s.features?.agent_os!==false){
      const act=agState.active_tasks_count||0,mem=agState.memory_records_count;
      $('agentStateVal').innerHTML='<span>Enabled</span>';
      $('agentStateSub').textContent='Hub-wide · '+n(act)+' active task'+(act===1?'':'s')+(mem!==undefined?' · '+n(mem)+' memories':'');
    }else{
      $('agentStateVal').textContent=agState.enabled===false||s.features?.agent_os===false?'Disabled':'Unavailable';
      $('agentStateSub').textContent=agState.enabled===false||s.features?.agent_os===false?'Agent OS is disabled':'Hub-wide Agent OS inventory unavailable';
    }
  }
  if($('agentStateCard'))$('agentStateCard').onclick=()=>switchTab('agentos');

  const inventory=residentInventoryFor(s),loadedModels=inventory.details;
  const loadedVal=$('loadedModelVal'),loadedSub=$('loadedModelSub');
  if(loadedVal&&loadedSub){
    if(loadedModels.length>0){
      const primary=loadedModels[0];
      const others=loadedModels.length>1?` (+${loadedModels.length-1} more)`:'';
      loadedVal.textContent=primary.name+others;
      const ctxStr=primary.context_length?`${n(primary.context_length)} ctx`:'Dynamic ctx';
      const vramStr=primary.vram_bytes?`${formatBytes(primary.vram_bytes)} VRAM`:(primary.size_bytes?formatBytes(primary.size_bytes):'');
      const paramStr=primary.parameter_size||primary.quantization||'';
      loadedSub.textContent=[ctxStr,paramStr,vramStr].filter(Boolean).join(' · ');
    }else if(inventory.state==='loaded'&&inventory.names.length>0){
      loadedVal.textContent=inventory.names.join(', ');
      loadedSub.textContent='Resident in memory';
    }else{
      loadedVal.textContent=inventory.state==='none'?'None resident':inventory.state==='stale'?'Stale inventory':'Unknown';
      loadedSub.textContent=inventory.state==='none'?'Models load on demand':inventory.state==='stale'?'Refresh Models & RAG to verify':'Resident inventory not included in this snapshot';
    }
  }
  if($('loadedModelCard'))$('loadedModelCard').onclick=()=>switchTab('performance');

  $('prep').textContent=(p.paused?'paused':(p.processing_projects?'active':'idle'))+' · '+n(p.steps)+' steps';
  const prepStatus=preprocessingSummary(p,s.dependency_status||{},s.features||{});
  $('prepSub').textContent=prepStatus.text+(prepStatus.available?' · card reuse '+ingReuse+'% · query hit '+qHitRate+'%':'');
  if(!prepStatus.available)$('prep').textContent='Unavailable';

  const allJobs=[...(q.inflight_jobs||[]),...(q.pending_jobs||[])];
  if($('currentSummary'))$('currentSummary').textContent=n(q.foreground_queued)+' queued · '+n(q.foreground_inflight)+' running';
  rows('overviewJobs',allJobs.slice(0,12),j=>schedulerRow(j,`<td>${esc(j.state)}</td><td>${esc(j.agent||'—')}</td><td>${esc(j.source)}</td><td>${esc(j.model)}</td><td>${ms(j.wait_ms)}</td><td>${ms(j.service_ms)}</td><td>${esc(j.wait_reason)}</td>`),7);

  const hs=o.hotspots||[];
  if($('hotspots'))$('hotspots').innerHTML=hs.length?hs.map((x,i)=>`<div>${esc(x.type||'signal')}</div><div><span class="chip">${esc(x.signal||'')}</span> ${esc(x.value??x.value_ms??x.count??'')}</div>`).join(''):'<div>Status</div><div class="muted">No hotspot reported in available telemetry</div>';

  const recentRequests=o.recent_http||[],visibleJobs=workVisible(allJobs),visibleActive=workVisible(o.active_requests||[]),visibleRecent=filterRecentRequests(workVisible(recentRequests),recentRequests);
  if($('queueSummary'))$('queueSummary').textContent=n(q.foreground_queued)+' fg + '+n(q.background_queued)+' bg queued · '+n(q.foreground_inflight)+' fg + '+n(q.inflight_background)+' bg running · GPU admission: '+esc(q.gpu_admission_state||'unknown');
  if($('workQueued'))$('workQueued').textContent=n((q.foreground_queued||0)+(q.background_queued||0));
  if($('workRunning'))$('workRunning').textContent=n((q.foreground_inflight||0)+(q.inflight_background||0));
  if($('workActive'))$('workActive').textContent=n((o.active_requests||[]).length);
  if($('workRetained'))$('workRetained').textContent=n(lastTraces.length);
  if($('workFilterSummary'))$('workFilterSummary').textContent=`showing ${visibleJobs.length+visibleActive.length+visibleRecent.length} live/history items`;

  rows('jobs',visibleJobs,j=>workSchedulerRow(j),5);
  rows('activeReq',visibleActive,x=>workActiveRequestRow(x),4);
  renderRecentRequestHistory(s);
  renderTraceList(lastTraces);

  const diagBar=$('prepDiagnosticBar');
  if(diagBar){
    const projs=p.projects||[], isGlobPaused=!!p.paused, isEnabled=p.enabled!==false&&s.features?.preprocessing!==false;
    const hasErr=projs.some(x=>String(x.status||'').toLowerCase()==='error');
    const allDone=projs.length>0&&projs.every(x=>projectState(x)==='ready');
    const bgYield=p.scheduler_background_allowed===false;
    diagBar.style.display='flex';
    if(!prepStatus.available){
      diagBar.className='diag-banner warn';
      diagBar.textContent='Project status is unavailable. This does not mean that no projects are registered. Refresh status to retry.';
    }else if(!isEnabled){
      diagBar.className='diag-banner bad';
      diagBar.innerHTML=`<span><b>Project indexing is turned off.</b> Enable it in Settings to prepare repository indexes.</span>`;
    }else if(isGlobPaused){
      diagBar.className='diag-banner warn';
      diagBar.innerHTML=`<span style="flex:1"><b>Indexing is paused.</b> Background indexing and file synchronization are stopped.</span><button class="btn ok" onclick="setPreprocessing('resume')" style="padding:3px 8px;font-size:11px">Resume indexing</button>`;
    }else if(!projs.length){
      diagBar.className='diag-banner info';
      diagBar.innerHTML=`<span style="flex:1"><b>No repositories connected yet.</b> Add a repository to prepare its search index.</span><button class="btn ok" onclick="$('regProjectBtn').click()" style="padding:3px 8px;font-size:11px">+ Register Project</button>`;
    }else if(hasErr){
      const errProjs=projs.filter(x=>String(x.status||'').toLowerCase()==='error').map(x=>x.project||x.root).join(', ');
      diagBar.className='diag-banner bad';
      diagBar.innerHTML=`<span style="flex:1"><b>Some repositories could not be indexed:</b> ${esc(errProjs)}. Check status column below for error details.</span><button class="btn" onclick="pollStatus()" style="padding:3px 8px;font-size:11px">Refresh status</button>`;
    }else if(allDone){
      diagBar.className='diag-banner ok';
      diagBar.innerHTML=`<span><b>All ${projs.length} registered project entries report complete indexing progress</b>. This snapshot does not verify synchronization with later file changes.</span>`;
    }else if(bgYield){
      diagBar.className='diag-banner warn';
      diagBar.innerHTML=`<span><b>Indexing is waiting for active requests.</b> It will resume automatically when the model queue is free.</span>`;
    }else{
      const runningNames=projs.filter(x=>x.status==='running').map(x=>x.project).join(', ');
      diagBar.className='diag-banner info';
      diagBar.innerHTML=runningNames?`<span><b>Indexing:</b> ${esc(runningNames)}</span>`:'<span>Preprocessing is enabled. No project reports active processing in this snapshot.</span>';
    }
  }

  const prepPaused=!!p.paused;
  $('prepState').textContent=n((p.projects||[]).length)+' registered project entries · global '+(p.enabled===false?'disabled':prepPaused?'paused':'enabled');
  if(!prepStatus.available)$('prepState').textContent='Project inventory unavailable';
  $('prepAllToggle').disabled=!prepStatus.available;
  $('cleanMissingBtn').disabled=!prepStatus.available;
  $('prepToggle').textContent=prepPaused?'Resume preprocessing':'Pause preprocessing';
  $('prepAllToggle').textContent=prepPaused?'Resume all projects':'Pause all projects';
  renderProjects(p.projects||[]);

  rows('loadedModelsBody',loadedModels,m=>{
    const ctx=m.context_length?`${n(m.context_length)} tokens`:'<span class="muted">Dynamic</span>';
    const params=esc(m.parameter_size||'—');
    const quant=m.quantization?`<span class="chip">${esc(m.quantization)}</span>`:'<span class="muted">—</span>';
    const memStr=`${formatBytes(m.vram_bytes||0)} VRAM / ${formatBytes(m.size_bytes||0)} total`;
    const offload=`${Math.round((m.gpu_fraction||0)*100)}% GPU / ${Math.round((m.cpu_offload_fraction||0)*100)}% CPU`;
    const statusChip=m.expires_at?`<span class="chip ok">expires ${new Date(m.expires_at).toLocaleTimeString()}</span>`:'<span class="chip">Resident</span>';
    return `<tr><td><strong>${esc(m.name)}</strong></td><td>${ctx}</td><td>${params}</td><td>${quant}</td><td class="mono tiny">${memStr}</td><td class="tiny">${offload}</td><td>${statusChip}</td></tr>`;
  },7,inventory.state==='none'?'No models currently resident in VRAM/memory.':inventory.state==='loaded'?'Resident names are available; detailed memory inventory is unavailable.':'Resident inventory unknown or stale; refresh Models & RAG to verify.');

  rows('executionProfiles',ep,x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${esc(x.tier)}</td><td>${n(x.num_ctx)}</td><td>${n(x.max_ctx)}</td><td>${n(x.parallel_limit)}</td><td>${x.think?'on':'role-gated/off'}</td><td>${n(x.prompt_budget_tokens)}</td>`,'execution_profile'),7);
  rows('models',o.by_model||[],x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${ms(x.avg_load_ms)}</td><td>${n(x.failures)}</td>`,'model_stat'),5);
  rows('cacheLayers',o.cache_layers||[],x=>clickableRow(x,`<td>${esc(x.layer)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.context_tokens_avoided_est)}</td>`,'cache_layer'),4);
  rows('agents',o.by_agent||[],x=>clickableRow(x,`<td>${esc(x.agent)}</td><td>${n(x.requests)}</td><td>${n(x.local_inference_calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`,'agent_stat'),5);
  rows('routes',o.execution_routes||[],x=>clickableRow(x,`<td>${esc(x.route)}</td><td>${esc(x.task_type)}</td><td>${esc(x.complexity)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`,'route_stat'),6);

  $('commandState').textContent=n(cmd.active_count)+' running';
  rows('activeCommands',cmd.active||[],x=>clickableRow(x,`<td>${esc(x.command)}</td><td>${esc(x.cwd)}</td><td>${esc(x.class)}</td><td>${age(x.age_ms)}</td><td>${durSec(x.timeout_seconds)}</td>`,'command'),5);
  $('commandStats').innerHTML=`<div>Executed</div><div>${n(cmd.executed)}</div><div>Cache hits / misses</div><div>${n(cmd.hits)} / ${n(cmd.misses)}</div><div>Coalesced waiters</div><div>${n(cmd.coalesced_waiters)}</div><div>Policy blocked</div><div>${n(cmd.blocked)}</div>`;
  rows('blockedReasons',Object.entries(cmd.blocked_by_reason||{}),x=>clickableRow({reason:x[0],count:x[1]},`<td>${esc(x[0])}</td><td>${n(x[1])}</td>`,'blocked_reason'),2);

  renderReliabilitySummary(s);
  rows('errors',o.recent_errors||[],x=>clickableRow(x,`<td>${esc(x.component)}</td><td>${esc(x.operation)}</td><td>${esc(String(x.safe_message||'Diagnostic unavailable').slice(0,96))}</td><td>${n(x.count)}</td><td>${n(x.recovered_count)}</td><td>${x.last_seen?new Date(x.last_seen*1000).toLocaleTimeString():'—'}</td>`,'error'),6);
  $('runtimeCounters').innerHTML=`<div>Scheduler submitted</div><div>${n(ss.submitted)}</div><div>Completed / failed</div><div>${n(ss.completed)} / ${n(ss.failed)}</div><div>Model switches</div><div>${n(ss.model_switches)}</div><div>Queue rejections</div><div>${n(ss.queue_rejections)}</div><div>Caller timeouts</div><div>${n(ss.caller_timeouts)}</div><div>Background yields</div><div>${n(ss.background_yields)}</div><div>Supervisor restarts</div><div>${n(h.restarts)}</div>`;

  if($('hubHealthCard'))$('hubHealthCard').onclick=()=>switchTab('reliability');
  rows('sessionRows',o.sessions||[],x=>{
    const st=x.status||'unknown',stBadge=st==='active'?`<span class="badge ok">Active (PID ${n(x.pid)})</span>`:st==='clean_stop'?`<span class="badge" style="background:#343b2d;color:#abb2a5;border:1px solid #4c5840">Clean stop</span>`:st==='crashed'?`<span class="badge bad" title="No clean shutdown recorded; the termination cause is unknown">Unclean exit</span>`:'<span class="badge">Status unknown</span>',hitPct=((Number(x.cache_hit_rate||0))*100).toFixed(1),started=x.started_at?new Date(x.started_at*1000).toLocaleString():'—';
    return clickableRow(x,`<td>${started}</td><td>${durSec(x.duration_seconds)}</td><td>${stBadge}</td><td>${n(x.events)}</td><td>${hitPct}% <span class="tiny muted">(${n(x.cache_hits)})</span></td><td>${n(x.tokens_saved)}</td><td><code>${esc(x.version||'—')}</code></td>`,'session');
  },7);

  renderBundles(s);
}

function renderReliabilitySummary(snapshot){
  const o=snapshot?.observability||{},agent=o.cohorts?.agent_http||{},sessions=o.sessions||[],health=dashboardHealth(snapshot||{});
  const available=o.enabled!==false&&o.data_available===true&&o.stale!==true;
  const failures=Math.max(0,Number(agent.failures)||0),unclean=sessions.filter(x=>x.status==='crashed').length;
  const headline=$('reliabilityHeadline'),trend=$('reliabilityTrend'),action=$('reliabilityAction');
  if(headline)headline.innerHTML=`<div>Current runtime</div><div class="${health.level==='healthy'?'ok':'warn-t'}"><b>${esc(health.label)}</b> · ${esc(health.reason)}</div><div>Recorded request failures · ${telemetryPeriod(o)}</div><div>${available?n(failures):'Unavailable'} <span class="tiny muted">retained samples</span></div><div>Supervisor restarts · supervisor lifetime</div><div>${n(snapshot?.headless?.restarts)}</div><div>Unclean exits · retained 30-day sessions</div><div>${available?n(unclean):'Unavailable'}</div>`;
  if(trend)trend.textContent='Historical failures and unclean exits describe past events, not active incidents. Session history retains at most 100 entries; absence of a clean shutdown does not establish a crash cause.';
  if(action){action.textContent='Open failed request history';action.onclick=()=>{
    for(const id of ['workSearch','workState','requestHistorySearch','requestHistoryAction','requestHistoryPeriod'])if($(id))$(id).value='';
    if($('requestHistoryStatus'))$('requestHistoryStatus').value='failed';
    switchTab('work');if(last)render(last);
  };}
}

function schedulerRow(job,html,cols){const linked=lastTraces.find(x=>String(x.scheduler_job_id||'')===String(job.job_id||''));const id=linked?.trace_id||job.trace_id;if(id)return `<tr class="click" data-trace-id="${esc(id)}">${html}</tr>`;return clickableRow(job,html,'scheduler_job');}
function requestRow(request,html,cols){const linked=lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''));if(linked)return `<tr class="click" data-trace-id="${esc(linked.trace_id)}">${html}</tr>`;return clickableRow(request,html,'http_request');}

function renderTraceList(items){
  const base=workVisible(items||[]),kind=String($('traceKind')?.value||''),matching=base.filter(x=>!kind||x.kind===kind);
  const tableQuery=String($('traceTableSearch')?.value||'').trim().toLowerCase(),tableState=String($('traceTableState')?.value||''),tableSort=String($('traceTableSort')?.value||'newest');
  const tableVisible=matching.filter(x=>{const state=traceStatus(x),hay=[x.trace_id,x.request_id,x.action,x.source,x.kind,x.project,x.agent,x.model,x.error_type,x.error,traceProjectLabel(x),traceContextLabel(x)].filter(Boolean).join(' ').toLowerCase();return (!tableQuery||hay.includes(tableQuery))&&(!tableState||state===tableState)});
  tableVisible.sort((a,b)=>{const time=Number(a.updated_at||a.created_at||0)-Number(b.updated_at||b.created_at||0);if(tableSort==='oldest')return -time;if(tableSort==='action')return String(a.action||'').localeCompare(String(b.action||''))||-time;if(tableSort==='duration'){const ad=Number(a.updated_at||a.created_at||0)-Number(a.created_at||0),bd=Number(b.updated_at||b.created_at||0)-Number(b.created_at||0);return bd-ad||-time}if(tableSort==='state')return String(traceStatus(a)).localeCompare(String(traceStatus(b)))||-time;return -time});
  const historyQuery=String($('traceHistorySearch')?.value||'').trim().toLowerCase(),historyState=$('traceHistoryState')?.value||'useful';
  const sidebarVisible=matching.filter(x=>{const state=traceStatus(x),hay=[x.trace_id,x.request_id,x.action,x.source,x.kind,x.agent,x.model,x.error,traceContextLabel(x)].filter(Boolean).join(' ').toLowerCase();return (!historyQuery||hay.includes(historyQuery))&&(historyState==='useful'?(state!=='interrupted'&&state!=='failed'):(!historyState||state===historyState))});
  $('traceSummary').textContent=`${tableVisible.length} shown · ${n(items?.length||0)} retained · metadata only · bounded retention`;
  if($('workRetained'))$('workRetained').textContent=n(items?.length||0);
  rows('traces',tableVisible,x=>{const state=traceStatus(x),cls='trace-'+state,links=[x.async_job_id&&('job '+String(x.async_job_id).slice(0,10)),x.scheduler_job_id&&('sched '+String(x.scheduler_job_id).slice(0,10))].filter(Boolean).join(' · '),activity=x.updated_at&&x.created_at?durSec(Math.max(0,Number(x.updated_at)-Number(x.created_at))):'—',context=traceContextLabel({...x,kind:'',model:''}),project=traceProjectLabel(x)||'—';return `<tr class="click" data-trace-id="${esc(x.trace_id)}"><td class="${cls}">${esc(humanLabel(state))}</td><td>${esc(humanLabel(x.kind||'trace'))}</td><td><strong>${esc(project)}</strong></td><td><strong>${esc(x.action||'—')}</strong><div class="tiny">${esc(context||'No request details')}</div></td><td>${esc(x.agent||'—')}</td><td>${esc(x.model||'—')}</td><td>${x.created_at?new Date(x.created_at*1000).toLocaleTimeString():'—'}</td><td>${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'}<div class="tiny">${esc(activity)} total</div></td><td class="tiny">${esc(links||'open trace')}</td></tr>`},9);
  $('traceSideSummary').textContent=`${sidebarVisible.length} trace${sidebarVisible.length===1?'':'s'} · click to inspect`;
  $('traceSidebarList').innerHTML=sidebarVisible.length?sidebarVisible.map(x=>{const state=traceStatus(x),label=state==='interrupted'?'Interrupted':state,cls=state==='interrupted'?'interrupted':(state==='failed'||state==='error'?'failed':(x.terminal||state==='completed'||state==='succeeded'?'done':'')),kindLabel=x.kind==='api_request'?'API request':humanLabel(x.kind||'trace'),context=traceContextLabel({...x,kind:'',model:''}),project=traceProjectLabel(x),projectMeta=[project,context].filter(Boolean).join(' · ')||x.agent||'unknown context';return `<button class="trace-side-item ${String(x.trace_id)===activeTraceId?'active':''}" data-trace-page-id="${esc(x.trace_id)}"><span class="trace-side-top"><span class="trace-side-state ${cls}"></span><span class="trace-side-action">${esc(x.action||x.kind||'Trace')}</span><span class="tiny spacer">${esc(label)}</span></span><span class="trace-side-meta">${esc(projectMeta)}</span><span class="trace-side-meta">${esc(kindLabel)} · ${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'}</span></button>`}).join(''):'<div class="empty-human">No retained traces</div>';
}
function tracePollingNeeded(){return ['work','reliability','traceInspector'].includes(document.querySelector('.page.active')?.id);}
async function pollTraces(isCurrent=()=>document.visibilityState!=='hidden'){
  if(!isCurrent()||tracesPollInFlight)return false;
  if(!tracePollingNeeded())return false;
  tracesPollInFlight=true;
  const controller=typeof AbortController==='function'?new AbortController():null;
  tracesPollAbortController=controller;
  try{
    const kind=$('traceKind')?.value||'',suffix=kind?'&kind='+encodeURIComponent(kind):'',opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
    const r=await apiFetch('/api/debug-traces?limit=200'+suffix,opts);if(!isCurrent()||!tracePollingNeeded())return false;
    const d=await r.json();if(!isCurrent()||!tracePollingNeeded()||!d.success)return false;
    const items=Array.isArray(d.items)?d.items:[];
    return updateTraceSummaries(items);
  }catch(e){if(isCurrent()&&!controller?.signal.aborted)console.warn('trace refresh failed',e);return false}
  finally{tracesPollInFlight=false;if(tracesPollAbortController===controller)tracesPollAbortController=null}
}
$('traceRefresh')?.addEventListener('click',()=>pollTraces());$('traceKind')?.addEventListener('change',()=>renderTraceList(lastTraces));
$('traceHistorySearch')?.addEventListener('input',()=>renderTraceList(lastTraces));$('traceHistoryState')?.addEventListener('change',()=>renderTraceList(lastTraces));

function renderVersionBadge(running, installed){
  const el = $('versionBadge');
  const run = (running === null || running === undefined || running === '') ? 'unknown' : String(running);
  const inst = (installed === null || installed === undefined || installed === '') ? 'unknown' : String(installed);
  const text = `Running code ${run} · Installed package ${inst}`;
  const isMatch = Boolean(running && installed && running === installed);
  const cls = isMatch ? 'ok' : 'warn-t';
  if(el){
    el.textContent = text;
    el.className = 'pill ' + cls;
  }
  return {text: text, level: cls, match: isMatch};
}

async function probeHealth(){
  try{
    const r=await nativeFetch('/health',{cache:'no-store'});
    if(r.ok){
      const data=await r.json();
      if(!hasLiveStatus){$('conn').textContent='online';$('conn').className='pill ok'}
      renderVersionBadge(data.version, data.installed_version);
    }
  }catch(e){
    if(!hasLiveStatus){$('conn').textContent='offline';$('conn').className='pill bad-t'}
    renderVersionBadge(null, null);
  }
}
async function pollStatus(isCurrent=()=>document.visibilityState!=='hidden'){
  if(document.visibilityState==='hidden'||!isCurrent())return false;
  if(statusPollInFlight)return true;
  statusPollInFlight=true;
  const controller=typeof AbortController==='function'?new AbortController():null;
  statusPollAbortController=controller;
  const current=()=>document.visibilityState!=='hidden'&&isCurrent();
  try{
    const opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
    const r=await apiFetch('/api/live/status?light=1&scope='+sloScope,opts);
    if(!current())return false;
    if(!r.ok)throw new Error(`status request failed (HTTP ${r.status})`);
    const s=await r.json();
    if(!current())return false;
    if(s.snapshot_warming===true){
      lastDashboardStatusChanged=false;
      if(!hasLiveStatus){$('conn').textContent='warming';$('conn').className='pill warn-t'}
      return false;
    }
    const statusDegraded=s.snapshot_stale===true||s.degraded===true||s.success===false;
    const changed=shouldRefreshDashboardStatus(s);
    if(changed)render(s);
    hasLiveStatus=true;$('conn').textContent=s.snapshot_stale===true?'stale':statusDegraded?'degraded':'live';$('conn').className=statusDegraded?'pill warn-t':'pill ok';if(changed)$('updated').textContent='updated '+new Date().toLocaleTimeString();
    if(s.success===false){$('conn').textContent=s.snapshot_stale===true?'stale':'degraded';$('conn').className='pill warn-t';return false}
    if(changed||hardwareRefreshPending)try{
      const hardwareOpts={cache:'no-store'};if(controller)hardwareOpts.signal=controller.signal;
      const gr=await apiFetch('/api/hardware/system',hardwareOpts);
      if(!current())return false;
      if(gr.ok){
        const sys=await gr.json(), g=sys.gpu||{}, ram=sys.ram||{};
        const pct=value=>value==null||!Number.isFinite(Number(value))?null:Math.max(0,Math.min(100,Number(value)));
        const cpuUtil=pct(sys.cpu_utilization_pct), gpuUtil=pct(g.gpu_utilization_pct), ramPct=Number(ram.used_pct||0);
        const npus=Array.isArray(sys.npus)?sys.npus:[], ov=Array.isArray(sys.openvino_devices)?sys.openvino_devices:[], gpus=Array.isArray(sys.gpus)?sys.gpus:[];
        const igpuAvailable=Boolean(sys.igpu_available||g.integrated||gpus.some(x=>x.integrated)), igpuUtil=pct(sys.igpu_utilization_pct??(g.integrated?g.gpu_utilization_pct:null));
        const npuAvailable=Boolean(sys.npu_available||npus.length||ov.some(x=>x.kind==='npu')), npuUtil=pct(sys.npu_utilization_pct);
        const loads=[['CPU',cpuUtil]];
        if(g.available&&!g.integrated)loads.push(['GPU',gpuUtil]);
        if(igpuAvailable)loads.push(['iGPU',igpuUtil]);
        if(npuAvailable)loads.push(['NPU',npuUtil]);
        const knownLoads=loads.map(x=>x[1]).filter(x=>x!==null), peak=knownLoads.length?Math.max(...knownLoads):0;
        const barColor=peak>80?'var(--bad)':peak>50?'var(--warn)':'var(--ok)';
        const loadText=loads.map(([label,value])=>`${label} ${value===null?'—':`${Math.round(value)}%`}`).join(' · ');
        $('sysUtil').innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center"><span>${loadText}</span><span class="tiny muted">${sys.cpu_count||1} threads</span></div><div class="bar"><i style="width:${peak}%;background:${barColor}"></i></div>`;
        const vram=g.available?(g.vram_total_mb&&!g.integrated?` · VRAM ${Math.round(g.vram_used_mb||0)} / ${Math.round(g.vram_total_mb)} MB`:g.unified_memory_mb?` · Unified memory ${Math.round(g.unified_memory_mb)} MB`:g.integrated?' · shared-memory iGPU':''):'';
        const accel=npus.length?` · NPU ${npus[0].runtime_available?'ready':'detected'}`:(ov.some(x=>x.kind==='gpu')?' · OpenVINO GPU ready':'');
        $('sysSub').textContent=`RAM ${ram.used_gb||0} / ${ram.total_gb||0} GB (${ramPct}%)${vram}${accel}`;
        hardwareRefreshPending=false;
      }else{
        hardwareRefreshPending=true;
      }
    }catch{hardwareRefreshPending=true}
    return true;
  }catch(e){
    if(!current())return false;
    console.error('dashboard status refresh failed',e);if(last&&lastOverviewReceivedAt)renderOverviewHealth(last,lastOverviewReceivedAt);$('conn').textContent=hasLiveStatus?'stale':'offline';$('conn').className=hasLiveStatus?'pill warn-t':'pill bad-t';return false;
  }finally{statusPollInFlight=false;if(statusPollAbortController===controller)statusPollAbortController=null}
}
const statusPoller=createDashboardStatusPoller(isCurrent=>pollStatus(isCurrent));
document.addEventListener('visibilitychange',()=>{
  const visible=document.visibilityState!=='hidden';
  statusPoller.setVisible(visible);
  if(!visible&&statusPollAbortController)statusPollAbortController.abort();
});
statusPoller.start();
let liveEvents=[],eventsPollInFlight=false,tracesPollInFlight=false,eventsPollHasLoaded=false;
let eventsPollAbortController=null,tracesPollAbortController=null;
function eventSeverity(event){
  if(event?.success===false||Number(event?.status_code)>=400||/fail|error|crash|reject/i.test([event?.kind,event?.event_type,event?.status].join(' ')))return 'failure';
  if(/warn|retry|degrad|stale/i.test([event?.kind,event?.event_type,event?.status].join(' ')))return 'warning';
  if(event?.success===true)return 'success';
  return 'info';
}
function renderEvents(events=liveEvents){
  if(Array.isArray(events)&&events.length){liveEvents=[...events,...liveEvents].slice(0,300);}
  if(paused)return;
  const box=$('eventList');if(!box)return;
  const severity=String($('eventSeverity')?.value||''),source=String($('eventSource')?.value||'').trim().toLowerCase();
  const filtered=liveEvents.filter(event=>{const kind=eventSeverity(event),hay=[event.agent,event.kind,event.event_type,event.action,event.stage,event.model].filter(Boolean).join(' ').toLowerCase();return (!severity||kind===severity)&&(!source||hay.includes(source));}).slice(0,120);
  const summary=$('eventSummary');if(summary)summary.textContent=`${filtered.length} of ${liveEvents.length} retained events`;
  const html=filtered.map(e=>{const id='d'+(++seq),severity=eventSeverity(e),traceId=e.trace_id?String(e.trace_id):'',traceAttr=traceId?` data-trace-id="${esc(traceId)}"`:'';dataStore.set(id,{data:e,type:'event'});if(dataStore.size>5000){dataStore.delete(dataStore.keys().next().value);}const label=severity==='failure'?'FAIL':severity==='warning'?'WARN':severity==='success'?'OK':'INFO';return `<div class="event click"${traceAttr} data-detail="${id}" data-type="event"><span>${new Date((e.created_at||0)*1000).toLocaleTimeString()}</span><span>${esc(e.agent||e.kind||'')}</span><span>${esc(e.event_type||'')}</span><span>${esc(e.action||e.stage||'')}</span><span class="hide-sm">${esc(e.model||'')}</span><span>${e.duration_ms?ms(e.duration_ms):''}</span><span class="${severity==='failure'?'bad-t':severity==='warning'?'warn-t':severity==='success'?'ok':'muted'}">${label}</span></div>`}).join('');
  box.innerHTML=html||'<div class="empty">No events match current severity/source filters.</div>';
}
$('eventSeverity')?.addEventListener('change',()=>renderEvents([]));
$('eventSource')?.addEventListener('input',()=>renderEvents([]));
async function pollEvents(isCurrent=()=>document.visibilityState!=='hidden'){
  if(!isCurrent()||eventsPollInFlight)return false;
  eventsPollInFlight=true;
  const controller=typeof AbortController==='function'?new AbortController():null;
  eventsPollAbortController=controller;
  try{
    const previousCursor=cursor,opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
    const r=await apiFetch('/api/live?after='+cursor+'&limit='+(cursor?200:50),opts);if(!isCurrent())return false;
    const d=await r.json();if(!isCurrent()||!d.success)return false;
    const events=Array.isArray(d.events)?d.events:[];cursor=Number(d.cursor||cursor);
    const changed=!eventsPollHasLoaded||cursor!==previousCursor||events.length>0;eventsPollHasLoaded=true;
    if(changed)renderEvents(events);
    return {changed};
  }catch{return false}
  finally{eventsPollInFlight=false;if(eventsPollAbortController===controller)eventsPollAbortController=null}
}
const eventsPoller=createDashboardStatusPoller(pollEvents,{baseDelay:1000,maxDelay:30000});
const tracesPoller=createDashboardStatusPoller(pollTraces,{baseDelay:2000,maxDelay:30000});

if(!document.hidden)probeHealth();
eventsPoller.start();tracesPoller.start();
let isVisible=!document.hidden;
document.addEventListener('visibilitychange',()=>{
  isVisible=!document.hidden;
  if(!isVisible){eventsPollAbortController?.abort();tracesPollAbortController?.abort();tracePollAbortController?.abort();}
  eventsPoller.setVisible(isVisible);tracesPoller.setVisible(isVisible);traceDetailPoller?.setVisible(isVisible);
  if(isVisible)probeHealth();
});
