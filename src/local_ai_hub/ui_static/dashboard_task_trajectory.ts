// @ts-nocheck
function renderTaskTrajectory(){
  const list=$('trajEventList'),status=$('trajEventStatus'),pager=$('trajEventPager'),gaps=$('trajEventGaps');
  if(!list||!status||!pager||!gaps)return;
  list.innerHTML=trajectoryEvents.length?trajectoryEvents.map(ev=>`<div class="kv" style="padding:5px 0"><div class="mono">#${esc(ev.seq)}</div><div><b>${esc(ev.event_type||'event')}</b> <span class="muted">${esc(ev.actor||'system')}</span></div></div>`).join(''):'<div class="tiny muted">No task events recorded.</div>';
  gaps.textContent=trajectoryGaps.length?`Missing retained events: ${trajectoryGaps.map(g=>`${g.from_seq??g.from??'?'}–${g.to_seq??g.to??'?'}`).join(', ')}`:'';
  status.textContent=trajectoryLoading?'Loading task events…':trajectoryPageError?`Could not load task events: ${trajectoryPageError}`:trajectoryHasMore?`Showing ${trajectoryEvents.length} events through sequence ${trajectorySnapshotSeq}.`:`${trajectoryEvents.length} events loaded${trajectorySnapshotSeq===null?'':` through sequence ${trajectorySnapshotSeq}`}.`;
  pager.textContent=trajectoryPageError?'Retry page':'Load next events';
  pager.disabled=trajectoryLoading||!trajectoryHasMore;
  pager.hidden=!trajectoryHasMore&&!trajectoryLoading;
}

async function loadTaskTrajectory(taskId=trajectoryTaskId){
  taskId=String(taskId||'');
  if(!taskId||taskId!==trajectoryTaskId||trajectoryLoading)return;
  const generation=trajectoryGeneration;
  trajectoryLoading=true;trajectoryPageError='';renderTaskTrajectory();
  const isCurrent=()=>generation===trajectoryGeneration&&taskId===trajectoryTaskId&&activeTaskInspectorState?.taskId===taskId;
  try{
    const query=new URLSearchParams({stream_id:taskId,after_seq:String(trajectoryAfterSeq),limit:'100'});
    if(trajectorySnapshotSeq!==null)query.set('through_seq',String(trajectorySnapshotSeq));
    let r=await apiFetch('/api/agent-state/events?'+query.toString(),{cache:'no-store'}),d=await r.json();
    if(!isCurrent())return;
    if((r.ok||r.status===413)&&trajectorySnapshotSeq===null&&Number.isFinite(Number(d.last_seq)))trajectorySnapshotSeq=Math.max(0,Math.floor(Number(d.last_seq)));
    if(r.status===413&&trajectorySnapshotSeq!==null){
      query.set('through_seq',String(trajectorySnapshotSeq));
      r=await apiFetch('/api/agent-state/events?'+query.toString(),{cache:'no-store'});d=await r.json();
      if(!isCurrent())return;
    }
    if(!r.ok)throw new Error(`task event page failed (HTTP ${r.status})`);
    const evs=Array.isArray(d.events)?d.events:[];
    if(trajectorySnapshotSeq===null&&Number.isFinite(Number(d.last_seq)))trajectorySnapshotSeq=Math.max(0,Math.floor(Number(d.last_seq)));
    if(trajectorySnapshotSeq===null)trajectorySnapshotSeq=evs.reduce((max,ev)=>Math.max(max,Number(ev.seq)||0),0);
    const boundedEvents=evs.filter(ev=>Number(ev.seq||0)<=trajectorySnapshotSeq);
    const seen=new Set(trajectoryEvents.map(ev=>Number(ev.seq||0)));
    trajectoryEvents.push(...boundedEvents.filter(ev=>!seen.has(Number(ev.seq||0))));
    const previousAfterSeq=trajectoryAfterSeq;
    trajectoryAfterSeq=Number(d.next_seq||trajectoryAfterSeq);
    trajectoryHasMore=Boolean(d.has_more)&&Number(trajectoryAfterSeq)<trajectorySnapshotSeq;
    if(trajectoryAfterSeq<=previousAfterSeq)trajectoryHasMore=false;
    if(Array.isArray(d.gap_ranges))trajectoryGaps.push(...d.gap_ranges);
    trajectoryPageError='';
  }catch(error){
    if(isCurrent()){trajectoryPageError=String(error.message||error);trajectoryHasMore=true}
  }finally{
    if(isCurrent()){trajectoryLoading=false;renderTaskTrajectory()}
  }
}

