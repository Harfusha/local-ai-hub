// @ts-nocheck
// ── Trajectory & Step Inspector ───────────────────────────────────────────
let cachedTrajTasks=[];

async function loadTrajectories(){
  try{
    const repoVal=$('agentOsRepoSelect')?.value?.trim()||'';
    const rootVal=$('agentOsRoot')?.value?.trim()||'';
    const selectedRoot=rootVal||repoVal||'';
    const isAll=!selectedRoot||selectedRoot.toLowerCase()==='all'||selectedRoot==='__all__';
    const d=await fetchDashboardJson('/api/agent-state/tasks?limit=100',{cache:'no-store',unscoped:isAll});
    cachedTrajTasks=d.tasks||[];
    renderTrajectories();
  }catch(e){
    if($('trajSummary'))$('trajSummary').textContent='Run history unavailable';
    if($('trajTableBody'))$('trajTableBody').innerHTML=`<tr><td colspan="6" class="empty warn-t">${esc(e.message||e)}. Refresh to retry.</td></tr>`;
  }
}

function renderTrajectories(){
  const q=String($('trajSearch')?.value||'').trim().toLowerCase();
  const list=cachedTrajTasks.filter(t=>{
    if(!q)return true;
    const hay=[t.task_id,t.contract?.goal,t.status,t.owner].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(q);
  });
  if($('trajSummary'))$('trajSummary').textContent=`${list.length} trajectories · click to inspect steps`;
  rows('trajTableBody',list,t=>{
    const tid=esc(t.task_id||'—');
    const goal=esc(t.contract?.goal||'—');
    const st=String(t.status||'planned').toLowerCase();
    const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
    const stepsCount=n(t.checkpoint?.affected_paths?.length)+' paths / '+n(Object.keys(t.verification_receipts||{}).length)+' receipts';
    const tokensUsed=t.checkpoint?.state_data?.tokens_used!=null?n(t.checkpoint.state_data.tokens_used):'Unreported';
    const act=`<button class="action-btn-sm" data-view-traj="${tid}">Inspect</button>`;
    return `<tr class="click" data-view-traj="${tid}"><td><strong>${tid}</strong></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${stepsCount}</span></td><td class="tiny mono">${tokensUsed}</td><td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td>${act}</td></tr>`;
  },6);
}

$('trajSearch')?.addEventListener('input',renderTrajectories);
$('trajRefreshBtn')?.addEventListener('click',loadTrajectories);

async function viewTrajectory(taskId, afterSeq=0, append=false){
  if(!taskId)return;
  const task=cachedTrajTasks.find(t=>t.task_id===taskId);
  const panel=$('trajDetailPanel');
  const title=$('trajDetailTitle');
  const list=$('trajStepsList');
  if(!panel||!list||!title)return;
  panel.style.display='block';
  title.innerHTML=`Trajectory Inspection: <code>${esc(taskId)}</code> — <span class="muted">${esc(task?.contract?.goal||'')}</span>`;
  if(!append)list.innerHTML='<div class="tiny muted">Loading event stream & trajectory steps…</div>';
  else list.querySelector('.trajectory-load-more')?.remove();

  try{
    const params=new URLSearchParams({stream_id:taskId,limit:'100'});
    if(afterSeq>0)params.set('after_seq',String(afterSeq));
    const r=await apiFetch('/api/agent-state/events?'+params.toString(),{cache:'no-store',unscoped:true});
    const responseText=await r.text();
    const d=JSON.parse(responseText);
    const evs=Array.isArray(d.events)?d.events:[];
    const gapRanges=Array.isArray(d.gap_ranges)?d.gap_ranges.slice():[];
    const gapMetadataUnavailable=d.retention_gap_metadata_available===false||
      !Array.isArray(d.gap_ranges);
    if(!append)list.innerHTML='';
    if(gapMetadataUnavailable&&!gapRanges.length&&!list.querySelector('.trajectory-gap')){
      const gap=document.createElement('div');
      gap.className='trace-event trajectory-gap';
      gap.style.cssText='border-left:2px solid #f0ad4e;padding:8px;margin-bottom:8px;color:#f0ad4e';
      gap.textContent='Retention gap metadata unavailable; cannot verify history completeness.';
      list.appendChild(gap);
    }
    if(!evs.length&&!append){
      const cp=task?.checkpoint||{};
      const receipts=Object.entries(task?.verification_receipts||{});
      list.insertAdjacentHTML('beforeend',`<div class="trace-event" style="border-left:2px solid var(--accent);padding:8px;margin-bottom:8px">
        <div style="font-weight:600;font-size:12px;margin-bottom:4px">Phase: ${esc(cp.phase||'init')} ➔ Next: ${esc(cp.next_action||'—')}</div>
        <div class="tiny muted">Affected Paths: ${esc((cp.affected_paths||[]).join(', ')||'none')}</div>
        <div class="tiny muted">Evidence IDs: ${esc((cp.evidence_ids||[]).join(', ')||'none')}</div>
        ${receipts.length?`<div style="margin-top:6px;font-size:11px"><b>Receipts:</b> ${receipts.map(([k,v])=>`<span class="chip ok">${esc(k)}</span>`).join(' ')}</div>`:''}
      </div>`);
    }
    const skipQuotedString=(jsonText,start)=>{
      let escaped=false;
      for(let i=start+1;i<jsonText.length;i++){
        const ch=jsonText[i];
        if(escaped)escaped=false;
        else if(ch==='\\')escaped=true;
        else if(ch==='"')return i;
      }
      return jsonText.length;
    };
    const readRawInteger=(jsonText,key)=>{
      let depth=0;
      for(let i=0;i<jsonText.length;i++){
        if(jsonText[i]==='"'){
          const end=skipQuotedString(jsonText,i);
          if(depth===1){
            const name=JSON.parse(jsonText.slice(i,end+1));
            let valueIndex=end+1;
            while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
            if(name===key&&jsonText[valueIndex++]===':'){
              while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
              const number=/^-?\d+/.exec(jsonText.slice(valueIndex));
              if(!number)return null;
              const delimiter=jsonText[valueIndex+number[0].length];
              return delimiter&&/[.eE\d]/.test(delimiter)?null:number[0];
            }
          }
          i=end;
          continue;
        }
        if(jsonText[i]==='{'||jsonText[i]==='[')depth++;
        else if(jsonText[i]==='}'||jsonText[i]===']')depth--;
      }
      return null;
    };
    const readTopLevelArrayObjects=(jsonText,key)=>{
      let depth=0;
      for(let i=0;i<jsonText.length;i++){
        if(jsonText[i]==='"'){
          const end=skipQuotedString(jsonText,i);
          if(depth===1){
            const name=JSON.parse(jsonText.slice(i,end+1));
            let valueIndex=end+1;
            while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
            if(name===key&&jsonText[valueIndex++]===':'){
              while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
              if(jsonText[valueIndex]!=='[')return [];
              const items=[];
              for(let itemIndex=valueIndex+1;itemIndex<jsonText.length;){
                while(/[\s,]/.test(jsonText[itemIndex]||''))itemIndex++;
                if(jsonText[itemIndex]===']')return items;
                if(jsonText[itemIndex]!=='{')return [];
                const start=itemIndex;
                let objectDepth=0;
                for(;itemIndex<jsonText.length;itemIndex++){
                  if(jsonText[itemIndex]==='"'){
                    itemIndex=skipQuotedString(jsonText,itemIndex);
                    continue;
                  }
                  if(jsonText[itemIndex]==='{')objectDepth++;
                  else if(jsonText[itemIndex]==='}'&&--objectDepth===0){
                    items.push(jsonText.slice(start,itemIndex+1));
                    itemIndex++;
                    break;
                  }
                }
              }
              return [];
            }
          }
          i=end;
          continue;
        }
        if(jsonText[i]==='{'||jsonText[i]==='[')depth++;
        else if(jsonText[i]==='}'||jsonText[i]===']')depth--;
      }
      return [];
    };
    const readRawArrayIntegers=(jsonText,arrayKey,fieldKey)=>
      readTopLevelArrayObjects(jsonText,arrayKey).map(item=>readRawInteger(item,fieldKey));
    const exactEventSeqs=readRawArrayIntegers(responseText,'events','seq');
    const exactGapStarts=readRawArrayIntegers(responseText,'gap_ranges','from_seq');
    const exactGapEnds=readRawArrayIntegers(responseText,'gap_ranges','to_seq');
    const exactFirstRetainedSeq=readRawInteger(responseText,'first_retained_seq')??d.first_retained_seq;
    const timeline=[
      ...evs.map((ev,index)=>({type:'event',seq:exactEventSeqs[index]??ev.seq,ev})),
      ...gapRanges.map((range,index)=>({
        type:'gap',seq:exactGapStarts[index]??range.from_seq,
        fromSeq:exactGapStarts[index]??range.from_seq,
        toSeq:exactGapEnds[index]??range.to_seq,range,
      })),
    ];
    timeline.sort((left,right)=>{
      try{
        const a=BigInt(String(left.seq??0));
        const b=BigInt(String(right.seq??0));
        return a<b?-1:(a>b?1:0);
      }catch{
        return String(left.seq??0).localeCompare(String(right.seq??0),undefined,{numeric:true});
      }
    });
    timeline.forEach(item=>{
      if(item.type==='gap'){
        const gap=document.createElement('div');
        gap.className='trace-event trajectory-gap';
        gap.style.cssText='border-left:2px solid #f0ad4e;padding:8px;margin-bottom:8px;color:#f0ad4e';
        gap.textContent=`Event history gap: expired #${item.fromSeq}–#${item.toSeq}; first retained #${exactFirstRetainedSeq??'unknown'}.`;
        list.appendChild(gap);
        return;
      }
      const ev=item.ev;
      const kind=esc(ev.event_type||ev.kind||'event');
      const timestamp=ev.created_at??ev.timestamp;
      const time=timestamp?new Date(timestamp*1000).toLocaleTimeString():'';
      const payload=traceOutputValueMarkup(ev.payload, null, 5000);
      list.insertAdjacentHTML('beforeend',`<div class="trace-event" style="border-left:2px solid var(--accent);padding:8px;margin-bottom:8px;background:#141811;border-radius:4px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span class="chip"><b>${kind}</b></span>
          <span class="tiny muted">#${esc(item.seq||0)} · ${time}</span>
        </div>
        <div style="margin:0;font-size:11px;color:#dfe6d5;max-height:220px;overflow:auto">${payload}</div>
      </div>`);
    });
    const cursorToken=readRawInteger(responseText,'next_seq')??String(d.next_seq??afterSeq);
    let cursorAdvances=false;
    try{cursorAdvances=BigInt(cursorToken)>BigInt(String(afterSeq));}catch{}
    if(d.has_more&&cursorAdvances){
      const button=document.createElement('button');
      button.type='button';
      button.className='trajectory-load-more';
      button.style.cssText='margin:8px 0;padding:6px 10px';
      button.textContent='Load more events';
      button.onclick=()=>viewTrajectory(taskId,cursorToken,true);
      list.appendChild(button);
    }
  }catch(err){
    if(append){
      const error=document.createElement('div');
      error.className='bad-t';
      error.textContent=`Failed to load trajectory events: ${err.message||err}`;
      list.appendChild(error);
    }else{
      list.innerHTML=`<div class="bad-t">Failed to load trajectory events: ${esc(err.message||err)}</div>`;
    }
  }
}

document.addEventListener('click',e=>{
  const el=e.target.closest?.('[data-view-traj]');
  if(el){
    const tid=el.dataset.viewTraj;
    viewTrajectory(tid);
  }
});

