// @ts-nocheck
// ── Compare models Benchmark ───────────────────────────────────────────
$('arenaRunBtn')?.addEventListener('click',async()=>{
  const prompt=$('arenaPromptInput')?.value?.trim()||'Write a Python function with LRU cache to solve knapsack problem.';
  const btn=$('arenaRunBtn');
  btn.disabled=true;btn.textContent='Benchmarking…';
  if($('arenaFastStats'))$('arenaFastStats').textContent='Running Fast Tier (auto)...';
  if($('arenaSmartStats'))$('arenaSmartStats').textContent='Running Smart Tier (high)...';
  if($('arenaFastOutput'))$('arenaFastOutput').textContent='';
  if($('arenaSmartOutput'))$('arenaSmartOutput').textContent='';

  const runTier=async(complexity,labelEl,statsEl,outEl)=>{
    const t0=performance.now();
    try{
      const res=await post('/api/delegate',{task:prompt,complexity});
      if(res.success===false)throw new Error(res.error||'Inference failed');
      const lat=Math.round(performance.now()-t0);
      const model=res.route?.model||res.model||'Model not reported';
      const gen=res.eval_count||res.tokens_generated||0;
      const tps=res.eval_duration?Math.round((gen/(res.eval_duration/1e9))*10)/10:(lat>0&&gen>0?Math.round((gen/(lat/1000))*10)/10:'—');
      if(labelEl)labelEl.textContent=`${complexity==='auto'?'Fast Tier':'Smart Tier'} (${model})`;
      if(statsEl)statsEl.innerHTML=`<span class="chip ok">⚡ ${lat}ms</span> <span class="chip">Tokens: ${gen}</span> <span class="chip">${res.eval_duration?'Generation speed':'End-to-end rate'}: ${tps} t/s</span>`;
      if(outEl)outEl.textContent=res.response||res.content||JSON.stringify(res,null,2);
    }catch(err){
      if(statsEl)statsEl.innerHTML=`<span class="chip bad-t">Error</span>`;
      if(outEl)outEl.textContent='Benchmark failed: '+(err.message||err);
    }
  };

  try{
    await Promise.allSettled([
      runTier('auto',$('arenaFastLabel'),$('arenaFastStats'),$('arenaFastOutput')),
      runTier('high',$('arenaSmartLabel'),$('arenaSmartStats'),$('arenaSmartOutput'))
    ]);
  }finally{
    btn.disabled=false;btn.textContent='Run comparison';
  }
});

