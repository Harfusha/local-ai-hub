// @ts-nocheck
// ── Git Worktrees Manager ──────────────────────────────────────────────────
async function loadWorktrees(){
  if($('pruneWorktreesBtn'))$('pruneWorktreesBtn').disabled=true;
  const root=$('worktreeRoot')?.value?.trim();
  if(!root){
    if($('worktreeSummary'))$('worktreeSummary').textContent='Choose a repository root';
    if($('worktreesTable'))$('worktreesTable').innerHTML='<tr><td colspan="5" class="empty">Choose or enter a repository root, then refresh.</td></tr>';
    return;
  }
  try{
    const d=await fetchDashboardJson('/api/coord/worktrees?root='+encodeURIComponent(root),{cache:'no-store'});
    if($('worktreeRoot')?.value?.trim()!==root)return;
    if($('pruneWorktreesBtn'))$('pruneWorktreesBtn').disabled=false;
    const wts=d.worktrees||[];
    if($('worktreeSummary'))$('worktreeSummary').textContent=`${wts.length} registered · ${wts.filter(w=>w.prunable).length} prunable · ${wts.filter(w=>w.locked).length} locked`;
    rows('worktreesTable',wts,w=>{
      const dir=esc(w.worktree||'—');
      const br=esc(String(w.branch||'—').replace('refs/heads/',''));
      const head=esc(String(w.head||'—').slice(0,8));
      const isLocked=!!w.locked;
      const isPrunable=!!w.prunable;
      let statusBadge='<span class="chip">registered</span>';
      if(isLocked) statusBadge='<span class="chip warn-t">locked</span>';
      else if(isPrunable) statusBadge='<span class="chip bad-t">prunable</span>';
      const act=`<button class="action-btn-sm danger" data-release-worktree="${dir}">Remove</button>`;
      return `<tr><td class="mono tiny">${dir}</td><td><span class="chip">${br}</span></td><td class="mono tiny">${head}</td><td>${statusBadge}</td><td>${act}</td></tr>`;
    },5);
  }catch(e){
    if($('worktreeSummary'))$('worktreeSummary').textContent='Worktrees unavailable';
    if($('worktreesTable'))$('worktreesTable').innerHTML=`<tr><td colspan="5" class="empty warn-t">${esc(e.message||e)}. Check the repository root and refresh.</td></tr>`;
  }
}

$('refreshWorktreesBtn')?.addEventListener('click',loadWorktrees);
$('worktreeRoot')?.addEventListener('input',()=>{
  if($('pruneWorktreesBtn'))$('pruneWorktreesBtn').disabled=true;
  if($('worktreeSummary'))$('worktreeSummary').textContent='Refresh for the selected repository';
  if($('worktreesTable'))$('worktreesTable').innerHTML='<tr><td colspan="5" class="empty">Repository selection changed. Refresh to load its worktrees.</td></tr>';
});
$('worktreeRoot')?.addEventListener('keydown',event=>{if(event.key==='Enter')loadWorktrees()});
$('pruneWorktreesBtn')?.addEventListener('click',async()=>{
  if(!confirm('Prune stale Git worktrees?'))return;
  const root=$('worktreeRoot')?.value?.trim();if(!root)return;
  try{
    const result=await post('/api/coord/worktree_prune',{root});
    if(result.success===false)throw new Error(result.error||'Prune failed');
    await loadWorktrees();
  }catch(err){alert('Prune worktrees error: '+err)}
});

document.addEventListener('click',async e=>{
  const btn=e.target.closest?.('[data-release-worktree]');
  if(!btn)return;
  const wtPath=btn.dataset.releaseWorktree;
  if(!wtPath)return;
  if(!confirm(`Remove worktree ${wtPath}?`))return;
  const root=$('worktreeRoot')?.value?.trim();if(!root)return;
  try{
    const result=await post('/api/coord/worktree_release',{root,worktree_path:wtPath});
    if(result.success===false)throw new Error(result.error||'Remove failed');
    await loadWorktrees();
  }catch(err){alert('Remove worktree error: '+err)}
});

