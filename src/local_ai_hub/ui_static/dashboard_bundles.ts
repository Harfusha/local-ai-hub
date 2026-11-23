// @ts-nocheck
// ── Bundles ────────────────────────────────────────────────────────────────────
function renderBundles(s){
  if(!preprocessingSummary(s?.preprocessing||{},s?.dependency_status||{},s?.features||{}).available){$('bundleExportTable').innerHTML='<tr><td colspan="4" class="empty warn-t">Project inventory unavailable. Export readiness cannot be verified.</td></tr>';return;}
  const projs=groupedProjects(s?.preprocessing?.projects||[]);
  $('bundleExportTable').innerHTML=projs.length?projs.map(p=>{
    const state=projectState(p),progress=Math.round(Number(p.overall_progress_pct||0)),ready=state==='ready';
    const contents=[Number(p.files||0)&&`${n(p.files)} files`,Number(p.rag_files||0)&&`${n(p.rag_files)} RAG`,Number(p.file_cards||0)&&`${n(p.file_cards)} cards`].filter(Boolean).join(' · ')||'Index summary unavailable';
    const variants=(p.variants||[]).length;
    return `<tr><td><b>${esc(p.project||'Unnamed repository')}</b><div class="tiny mono muted" title="${esc(p.repository_identity||p.root||'')}">${esc(p.repository_identity||p.root||'—')}</div>${variants>1?`<div class="tiny">${variants} project entries grouped</div>`:''}</td><td><span class="${ready?'ok':'warn-t'}">${ready?'Ready to export':'Partial index'}</span><div class="tiny">${progress}% · ${esc(state)}</div></td><td class="tiny">${esc(contents)}</td><td><button class="btn" data-export-root="${esc(p.root||'')}" title="Exports available index content; does not alter this repository">Export bundle</button></td></tr>`;
  }).join(''):`<tr><td colspan="4" class="muted">No registered repositories. Bundle export needs a preprocessed project.</td></tr>`;
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-project-action],[data-export-root]');
  if(!button)return;
  event.stopPropagation();
  if(button.dataset.exportRoot!==undefined){exportBundle(button.dataset.exportRoot);return}
  const root=button.dataset.projectRoot||'';
  if(button.dataset.projectAction==='delete')deleteProjectDialog(root,button.dataset.projectName||'');
  else projectAction(root,button.dataset.projectAction,button);
});
async function exportBundle(root){
  try{
  const r=await apiFetch('/api/bundle/export',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/zip'},body:JSON.stringify({root})});
  if(!r.ok){alert('Export failed: '+(await r.text()));return;}
  const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bundle.zip';a.click();URL.revokeObjectURL(url);
  }catch(error){alert('Export failed: '+String(error.message||error))}
}
let diagnosticsExportPassword='';
async function exportDiagnostics(){
  const button=$('diagnosticsExportBtn'),status=$('diagnosticsExportStatus');if(!button||button.disabled)return;
  button.disabled=true;if(status)status.textContent='Building large installation-wide support archive…';
  try{
    let fileHandle=null;
    if(typeof window.showSaveFilePicker==='function')fileHandle=await window.showSaveFilePicker({suggestedName:'local-ai-hub-support.zip'});
    const r=await apiFetch('/api/diagnostics/export',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/zip'},body:'{}'});
    if(!r.ok){
      const failure=await r.json().catch(()=>({}));
      throw new Error(failure.error_code==='detailed_diagnostics_disabled'
        ?'Enable detailed diagnostics in the dashboard before exporting.'
        :(typeof failure.error==='string'&&failure.error?failure.error:`HTTP ${r.status}`));
    }
    const password=r.headers.get('X-Local-AI-Export-Password');if(!password)throw new Error('Archive password was not returned; download cancelled.');
    if(fileHandle&&r.body){
      const writer=await fileHandle.createWritable(),reader=r.body.getReader(),total=Number(r.headers.get('Content-Length'))||0;let received=0;
      try{for(;;){const{done,value}=await reader.read();if(done)break;await writer.write(value);received+=value.byteLength;if(status)status.textContent=total?`Saving support archive: ${(received/1048576).toFixed(0)} / ${(total/1048576).toFixed(0)} MiB`:`Saving support archive: ${(received/1048576).toFixed(0)} MiB`; }await writer.close();}
      catch(error){await writer.abort().catch(()=>{});throw error;}
    }else{
      const total=Number(r.headers.get('Content-Length'))||0;if(total>512*1024*1024){await r.body?.cancel();throw new Error('This browser cannot save large archives as a stream. Open the dashboard in Chrome or Edge and retry.');}
      const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='local-ai-hub-support.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
    diagnosticsExportPassword=password;$('diagnosticsExportPassword').value=password;$('diagnosticsExportDialog').showModal();
    if(status)status.textContent='Encrypted support archive downloaded.';
  }catch(error){if(status)status.textContent='Export failed: '+String(error.message||error)}finally{button.disabled=false}
}
$('diagnosticsExportBtn')?.addEventListener('click',exportDiagnostics);
$('diagnosticsCopyPassword')?.addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(diagnosticsExportPassword);$('diagnosticsCopyPassword').textContent='Copied';}
  catch{$('diagnosticsExportPassword').focus();$('diagnosticsExportPassword').select();}
});
$('diagnosticsExportDialog')?.addEventListener('close',()=>{
  diagnosticsExportPassword='';$('diagnosticsExportPassword').value='';$('diagnosticsCopyPassword').textContent='Copy password';
});
$('diagnosticsClosePassword')?.addEventListener('click',()=>$('diagnosticsExportDialog').close());
$('bundleImport')?.addEventListener('click',async()=>{
  const file=$('bundleFile')?.files?.[0];const statusEl=$('bundleImportStatus');if(!file){if(statusEl)statusEl.textContent='Select a file first';return;}
  const button=$('bundleImport');if(button.disabled)return;button.disabled=true;
  if(statusEl)statusEl.textContent='Uploading…';
  const target=$('bundleTargetRoot')?.value?.trim()||'';const suffix=target?'?target_root='+encodeURIComponent(target):'';
  try{
    const r=await apiFetch('/api/bundle/import'+suffix,{method:'POST',headers:{'Content-Type':'application/zip'},body:await file.arrayBuffer()});
    const d=await r.json();
    if(statusEl)statusEl.textContent=d.success?'Import successful: '+String(d.root||''):'Error: '+String(d.error||'failed');
  }catch(e){if(statusEl)statusEl.textContent='Upload error: '+(e?.message||e)}finally{button.disabled=false}
});

