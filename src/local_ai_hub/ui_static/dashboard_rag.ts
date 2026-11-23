// @ts-nocheck
// ── Models, RAG & Leases ──────────────────────────────────────────────────────
let ragWorkspaces=[],ragWorkspaceLoadError='';
function ragWorkspaceIdentity(workspace){return String(workspace?.root||workspace?.repository_root||workspace?.workspace||workspace?.id||workspace||'unknown');}
// BEGIN workspace review proposal
function formatRagWorkspaceReviewProposal(w){
  const state=workspaceInventoryState(w),identity=ragWorkspaceIdentity(w);
  const root=state.root||'Not provided';
  const availability=state.availability||'unknown';
  const verified=state.verifiedAt&&Number.isFinite(state.verifiedAt)?new Date(state.verifiedAt).toLocaleString(undefined,{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short'}):'Not provided';
  const status=String(w?.status||w?.state||'status unreported');
  const statusLower=status.toLowerCase();
  const activeOrAvailable=statusLower==='active'||statusLower==='available'||availability==='available';
  const reviewOnly=!activeOrAvailable&&(availability==='missing'||availability==='unverified');
  const chunks=Number(w?.chunks??w?.document_count??w?.count??0);
  const files=Number(w?.files||0);
  const contents=[Number.isFinite(chunks)&&chunks>0?chunks+' chunks':'',Number.isFinite(files)&&files>0?files+' files':''].filter(Boolean).join(' · ')||'Not provided';
  const proposal=reviewOnly
    ?'Operator review only. No cleanup is performed. Before any deletion, an ownership check is required; create a recoverable backup and verify its restore identity, then obtain explicit operator approval.'
    :activeOrAvailable
      ?'No automatic cleanup candidate: this workspace is active or reported available.'
      :'No automatic cleanup action proposed: identity or root availability is unknown.';
  return `${identity}\nRoot: ${root}\nAvailability: ${availability}\nLast use: Not provided\nLast verification: ${verified}\nIndex status: ${status}\nContents: ${contents}\n${proposal}`;
}
// END workspace review proposal
function renderRagWorkspaces(){
  const list=$('ragWorkspacesList');if(!list)return;
  if(ragWorkspaceLoadError){if($('ragWorkspaceSummary'))$('ragWorkspaceSummary').textContent='Repository indexes unavailable';list.innerHTML=`<div class="diag-banner bad" role="status">Repository indexes unavailable: ${esc(ragWorkspaceLoadError)}</div>`;return}
  const query=String($('ragWorkspaceSearch')?.value||'').trim().toLowerCase(),filter=$('ragWorkspaceStateFilter')?.value||'';
  const visible=ragWorkspaces.filter(w=>{
    const identity=ragWorkspaceIdentity(w),state=workspaceInventoryState(w);
    return (!filter||state.availability===filter)&&(!query||[identity,state.root,w?.status,w?.state,w?.model].filter(Boolean).join(' ').toLowerCase().includes(query));
  });
  const summary=$('ragWorkspaceSummary');if(summary)summary.textContent=visible.length+' of '+ragWorkspaces.length+' workspaces · availability is separate from index status';
  list.innerHTML=visible.length?'<div class="table-wrap"><table><thead><tr><th>Workspace identity</th><th>Root availability</th><th>Last verification</th><th>Index status</th><th>Contents</th></tr></thead><tbody>'+visible.map(w=>{
    const identity=ragWorkspaceIdentity(w),state=workspaceInventoryState(w),chunks=Number(w?.chunks??w?.document_count??w?.count??0);
    const indexState=String(w?.status||w?.state||'status unreported'),contents=[chunks&&n(chunks)+' chunks',w?.files&&n(w.files)+' files',w?.embedding_model].filter(Boolean).join(' · ')||'Content counts not provided';
    const verified=state.verifiedAt?new Date(state.verifiedAt).toLocaleString():'Not provided';
    return '<tr><td><b>'+esc(identity.split(/[\\/]/).filter(Boolean).pop()||identity)+'</b><div class="tiny muted mono">'+esc(state.root||identity)+'</div></td><td>'+esc(humanLabel(state.availability))+'<div class="tiny muted">'+esc(state.reason)+'</div></td><td class="tiny">'+esc(verified)+'</td><td>'+esc(humanLabel(indexState))+'</td><td class="tiny">'+esc(contents)+'</td></tr>';
  }).join('')+'</tbody></table></div>':'<span class="muted">No RAG workspace matches current filters.</span>';
}
async function loadRagWorkspaces(){
  try{
    const d=await fetchDashboardJson('/api/rag/workspaces',{cache:'no-store'});
    ragWorkspaceLoadError='';
    ragWorkspaces=d.workspaces||[];
    renderRagWorkspaces();
  }catch(e){ragWorkspaces=[];ragWorkspaceLoadError=String(e.message||e);renderRagWorkspaces()}
}
$('ragWorkspaceSearch')?.addEventListener('input',renderRagWorkspaces);
$('ragWorkspaceStateFilter')?.addEventListener('change',renderRagWorkspaces);
$('ragWorkspaceReviewBtn')?.addEventListener('click',()=>{
  const review=$('ragWorkspaceReview'),output=$('ragWorkspaceReviewOutput');if(!review||!output)return;
  output.textContent=ragWorkspaces.map(formatRagWorkspaceReviewProposal).join('\n\n');
  review.open=true;
});

async function loadActiveLeases(){
  try{
    const d=await fetchDashboardJson('/api/leases',{cache:'no-store'});
    const leases=d.leases||[];
    rows('activeLeasesBody',leases,l=>{
      const id=esc(l.lease_id||'—');
      const paths=Array.isArray(l.paths)?l.paths.map(p=>`<span class="chip mono">${esc(p)}</span>`).join(' '):esc(l.path||'');
      const purp=esc(l.purpose||'agent edit');
      const exp=l.expires_in_seconds?durSec(l.expires_in_seconds):'—';
      const action=`<button class="action-btn-sm danger" data-release-lease="${id}">Release</button>`;
      return clickableRow(l,`<td><strong>${id}</strong></td><td>${paths}</td><td class="tiny">${purp}</td><td class="tiny ok">${exp}</td><td>${action}</td>`,'lease',l.lease_id);
    },5);
  }catch(e){if($('activeLeasesBody'))$('activeLeasesBody').innerHTML=`<tr><td colspan="5" class="empty warn-t">Leases unavailable: ${esc(e.message||e)}</td></tr>`}
}
document.addEventListener('click',async e=>{
  const btn=e.target.closest?.('[data-release-lease]');
  if(!btn)return;
  const leaseId=btn.dataset.releaseLease;
  try{
    const result=await post('/api/leases/release',{lease_id:leaseId});
    if(result.success===false)throw new Error(result.error||'Release failed');
    await loadActiveLeases();
  }catch(err){alert('Release lease error: '+err)}
});

