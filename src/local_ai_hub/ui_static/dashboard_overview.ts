// @ts-nocheck
// @ts-nocheck
let cursor=0,paused=false,last=null,lastTraces=[],lastOverviewAnnouncement='',lastOverviewReceivedAt=0;
const latencySparkData=[], throughputSparkData=[], liveChartLatency=[], liveChartQueue=[];
let lastChartSnapshot=null,lastChartScope=null;

const traceStyles=document.createElement('style');
document.head.append(traceStyles);
traceStyles.textContent+='.trace-view-picker{display:flex;align-items:center;gap:8px;margin:8px 0;color:var(--muted);font-size:11px}.trace-view-picker select{max-width:100%;border:1px solid #414b37;border-radius:6px;background:#171b14;color:var(--fg);padding:7px 9px;font:inherit}.trace-view-picker select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}';
traceStyles.textContent+='.trace-main-head #tracePageTitle,.trace-main-head #tracePageLive{display:none}.trace-inspector-head{align-items:center}.trace-header-title{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.trace-header-title h1{margin:0;font-size:16px;overflow-wrap:anywhere}.trace-header-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:11px}.trace-header-time{font-variant-numeric:tabular-nums}.trace-primary{margin:10px 0 14px}.trace-primary-grid{display:grid;grid-template-columns:1fr;gap:10px}.trace-primary-card{min-width:0;border:1px solid #526144;border-radius:8px;background:#171b14;overflow:hidden}.trace-primary-card.input{border-color:#9b8756}.trace-primary-card.output{border-color:#397658}.trace-primary-card-head{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 11px;background:#20251c}.trace-primary-card-head h2{margin:0;font-size:12px}.trace-primary-card pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:12px;max-height:60vh;overflow:auto;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.trace-primary-empty{padding:12px;color:var(--muted);font-size:12px}.trace-metrics{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 0;color:var(--muted);font-size:11px}.trace-metrics span{border:1px solid #434f37;border-radius:999px;padding:4px 8px}.trace-optional-details{margin-top:12px}@media(max-width:700px){.trace-inspector-head{align-items:flex-start;flex-direction:column}.trace-primary-card pre{max-height:50vh}}';
document.head.insertAdjacentHTML('beforeend','<style>.vision-review-modal{width:min(980px,96vw)}.vision-review-modal .modal-body-wrap{padding:12px;overflow-y:auto}.vision-review-modal .modal-card-body{display:grid;gap:10px}.vision-review-modal textarea{width:100%;box-sizing:border-box;background:#171b14;color:var(--fg);border:1px solid #566349;border-radius:6px;padding:8px;font:inherit;resize:vertical}.vision-review-modal input[type=file]{color:var(--fg)}.vision-review-modal .modal-actions-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.trace-vision-provenance{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}.trace-vision-provenance span{border:1px solid #434f37;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px}.trace-vision-summary{border-color:#9b8756}.trace-vision-findings{display:grid;gap:8px}.trace-vision-finding{border:1px solid #526144;border-left:3px solid var(--accent);border-radius:7px;background:#171b14;padding:10px}.trace-vision-finding.blocker,.trace-vision-finding.high{border-left-color:var(--bad)}.trace-vision-finding-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.trace-vision-finding-head strong{overflow-wrap:anywhere}.trace-vision-finding .trace-chip{margin:0}.trace-vision-finding-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.trace-vision-evidence{margin-top:8px}.trace-vision-evidence img{max-width:100%;height:auto;border:1px solid #526144;border-radius:5px}.trace-vision-error{border-color:#784747;color:#ffb1b1}.trace-vision-empty{color:var(--muted);padding:8px 0}</style>');
 document.head.insertAdjacentHTML('beforeend','<style>.trace-inspector-context{display:flex;align-items:flex-end;gap:8px;flex-direction:column}.trace-project-label{border:1px solid #9b8756;border-radius:999px;padding:4px 8px;color:#c7dcff;font-size:10px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-search-presentation,.trace-model-presentation{border:1px solid #526144;border-radius:8px;background:#161a13;padding:12px}.trace-search-query{border:1px solid #2d4965;border-left:3px solid #5b8def;border-radius:6px;background:#111b26;padding:9px 10px;overflow-wrap:anywhere}.trace-search-query strong,.trace-search-answer strong{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}.trace-search-spec{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0;color:var(--muted);font-size:10px}.trace-search-spec span{border:1px solid #434f37;border-radius:999px;padding:3px 7px}.trace-search-results{margin-top:12px}.trace-search-results h3{margin:0 0 5px;font-size:11px}.trace-search-result-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;gap:9px;align-items:start;border-top:1px solid #414c35;padding:8px 0;min-width:0}.trace-search-rank{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#343e29;color:#c7dcff;font-size:10px}.trace-search-result-main{min-width:0;overflow-wrap:anywhere}.trace-search-result-main strong{display:block;overflow-wrap:anywhere}.trace-search-result-main>.tiny{display:block;margin-top:2px}.trace-search-snippet{color:#c9d5e2;font-size:11px;line-height:1.35;margin-top:4px;overflow-wrap:anywhere}.trace-search-score{color:var(--muted);font-size:10px;padding-top:3px}.trace-search-answer{border-top:1px solid #414c35;margin-top:8px;padding-top:9px;overflow-wrap:anywhere}.trace-model-presentation .trace-primary-card{min-height:0}.trace-model-presentation .trace-chat-message{border-top:0;padding:0}.trace-model-presentation .trace-chat-role{display:none}.trace-model-presentation .prompt-pre{max-height:260px}.trace-summary-card,.trace-code-card,.trace-list-card{border:1px solid #414c35;border-radius:6px;background:#171b14;padding:10px;margin-bottom:8px}.trace-summary-card h3,.trace-code-card h3,.trace-list-card h3{margin:0 0 6px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.trace-summary-value{overflow-wrap:anywhere}.trace-chip{display:inline-block;padding:2px 6px;border-radius:4px;background:#172535;border:1px solid #2d4965;font-size:11px;margin:2px}.trace-obj-field{margin-bottom:4px;overflow-wrap:anywhere}.trace-obj-key{color:var(--muted);font-size:11px;font-weight:600}.trace-obj-val{font-size:11px}.trace-primary-groups{display:grid;gap:8px;margin-top:10px}.trace-primary-group{border:1px solid #414c35;border-radius:6px;background:#171b14}.trace-primary-group>summary{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 10px;cursor:pointer;color:var(--fg);font-size:11px;font-weight:700;list-style:none}.trace-primary-group>summary::-webkit-details-marker{display:none}.trace-primary-group>summary::after{content:\"+\";color:var(--muted);font-size:15px;line-height:1}.trace-primary-group[open]>summary::after{content:\"−\"}.trace-primary-group-body{padding:0 10px 10px}.trace-primary-group .trace-primary-card{border:0;background:transparent;padding:0;margin:0}.trace-primary-group .trace-primary-card h3{display:none}.trace-primary-group .trace-primary-value{padding-top:2px}@media(max-width:700px){.trace-inspector-context{align-items:flex-end}.trace-project-label{max-width:150px}}</style>');

const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), escJs=v=>esc(JSON.stringify(v));
const n=v=>Number(v||0).toLocaleString(), ms=v=>{v=Number(v||0);return v>=1000?(v/1000).toFixed(v>=10000?1:2)+' s':v===0?'0 ms':v.toFixed(v<10?2:1)+' ms'}, durSec=s=>{s=Number(s||0);if(s<60)return Math.round(s)+'s';if(s<3600)return Math.floor(s/60)+'m '+Math.round(s%60)+'s';if(s<86400)return Math.floor(s/3600)+'h '+Math.floor((s%3600)/60)+'m';return Math.floor(s/86400)+'d '+Math.floor((s%86400)/3600)+'h'}, age=msv=>durSec(Number(msv||0)/1000), formatBytes=b=>{b=Number(b||0);if(b<=0)return '0 B';const u=['B','KB','MB','GB','TB'],i=Math.min(u.length-1,Math.floor(Math.log(b)/Math.log(1024)));return (b/Math.pow(1024,i)).toFixed(i>1?1:0)+' '+u[i];};
function setButtonLoading(btn, isLoading, loadingText){
  if(!btn) return;
  if(isLoading){
    if(!btn.dataset.origHtml) btn.dataset.origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.classList.add('is-loading');
    btn.innerHTML = `<span class="btn-spinner" aria-hidden="true"></span> ${esc(loadingText || btn.textContent.trim())}`;
  } else {
    btn.disabled = false;
    btn.classList.remove('is-loading');
    if(btn.dataset.origHtml){ btn.innerHTML = btn.dataset.origHtml; delete btn.dataset.origHtml; }
  }
}

function dashboardPreprocessingHealth(preprocessing={},dependencies={},features={}){
  const disabled=features.preprocessing===false||preprocessing.enabled===false;
  if(disabled)return {available:true,statsAvailable:true,errorCount:0,disabled:true};
  const unavailable=preprocessing.success===false||dependencies['preprocessing.status']?.degraded===true||!Array.isArray(preprocessing.projects);
  const statsAvailable=dependencies['preprocessing.stats']?.degraded!==true;
  if(unavailable)return {available:false,statsAvailable,errorCount:null};
  const errorCount=preprocessing.projects.filter(project=>String(project?.status||'').toLowerCase()==='error').length;
  return {available:true,statsAvailable,errorCount,disabled:false};
}

function isTelemetrySummaryDependency(name){
  return name==='telemetry.summary'||name.endsWith('.telemetry.summary');
}

function dashboardHealthBadge(status={}){
  const dependencyEntries=status.dependency_status&&typeof status.dependency_status==='object'&&!Array.isArray(status.dependency_status)?Object.entries(status.dependency_status):[];
  const failedDependencies=dependencyEntries.filter(([name,value])=>!name.startsWith('runtime_stats.')&&name!=='preprocessing.stats'&&!isTelemetrySummaryDependency(name)&&value?.degraded===true);
  const telemetrySummaryOnlyFailure=dependencyEntries.some(([name,value])=>isTelemetrySummaryDependency(name)&&value?.degraded===true)&&failedDependencies.length===0;
  const dependencies=failedDependencies.map(([,value])=>value);
  const degradedCount=dependencies.filter(item=>item&&item.degraded===true).length;
  const preprocessingDeps=status.dependency_status&&typeof status.dependency_status==='object'&&!Array.isArray(status.dependency_status)?status.dependency_status:{};
  const preprocessingAdvertised=Object.hasOwn(status,'preprocessing')||Object.hasOwn(preprocessingDeps,'preprocessing.status')||Object.hasOwn(preprocessingDeps,'preprocessing.stats');
  const preprocessing=preprocessingAdvertised?dashboardPreprocessingHealth(status.preprocessing||{},status.dependency_status||{},status.features||{}):{available:true,statsAvailable:true,errorCount:0,disabled:false};
  const preprocessingWarning=preprocessingAdvertised&&(!preprocessing.available||!preprocessing.statsAvailable||preprocessing.errorCount>0);
  const health=dashboardHealth(status);
  const degraded=health.level==='degraded'||(status.success===false&&!telemetrySummaryOnlyFailure);
  const ollamaState=status.ollama_status||((status.ollama_online==null)?'unknown':status.ollama_online?'online':'offline');
  const className=status.hub_online?(degraded||health.level==='attention'||ollamaState!=='online'||preprocessingWarning?'warn-t':'ok'):'bad-t';
  const degradedLabel=degradedCount?` / ${String(degradedCount)} degraded check${degradedCount===1?'':'s'}`:degraded?' / status degraded':'';
  const preprocessingLabel=!preprocessingAdvertised?'':preprocessing.disabled?' / preprocessing disabled':!preprocessing.available?' / preprocessing status unknown':(!preprocessing.statsAvailable?' / preprocessing stats unknown':'')+(preprocessing.errorCount?` / ${n(preprocessing.errorCount)} preprocessing project error${preprocessing.errorCount===1?'':'s'}`:'');
  return {className,degradedCount,degradedLabel:degradedLabel+preprocessingLabel};
}

function dashboardTelemetryState(observability={}){
  const observedCount=value=>Number.isSafeInteger(value)&&value>=0?value:null;
  const observedNumber=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
  const writer=observability.writer||{};
  const dropped=observedCount(writer.dropped),errors=observedCount(writer.writer_errors);
  const pending=observedCount(writer.pending);
  const accepted=Number.isSafeInteger(writer.accepted)&&writer.accepted>=0?writer.accepted:null;
  const written=Number.isSafeInteger(writer.written)&&writer.written>=0?writer.written:null;
  const requestFailures=observedCount(observability.cohorts?.agent_http?.failures);
  const requestEvents=observedCount(observability.cohorts?.agent_http?.events);
  const policyRejections=observedCount(observability.cohorts?.policy_rejection?.events);
  const latencyMetricsAvailable=requestEvents===0||requestEvents!==null&&['p50_duration_ms','p95_duration_ms','p99_duration_ms'].every(key=>observedNumber(observability.cohorts?.agent_http?.[key])!==null);
  const metricsAvailable=dropped!==null&&requestFailures!==null&&requestEvents!==null&&policyRejections!==null&&latencyMetricsAvailable;
  const activityObserved=writer.activity_observed===true;
  const accountingBalanced=writer.accounting_balanced===true;
  const summaryCacheStale=observability.summary_cache_stale===true;
  const detailIncomplete=observability.detail?.incomplete===true||observability.detail?.status==='incomplete';
  const available=observability.enabled!==false&&observability.data_available!==false&&observability.stale!==true&&
    (observability.data_available===true||Object.hasOwn(observability,'net_cloud_token_delta_est'));
  const complete=available&&metricsAvailable&&activityObserved&&accountingBalanced&&pending<=20&&dropped===0&&errors===0&&!summaryCacheStale&&!detailIncomplete&&!observability.accounting_boundary_incomplete;
  return {available,complete,metricsAvailable,requestFailures,requestEvents,policyRejections,dropped,errors,pending,accepted,written,activityObserved,accountingBalanced,summaryCacheStale,detailIncomplete};
}

function formatEstimatedUsd(value){
  const amount=Number(value);
  if(!Number.isFinite(amount))return 'Unavailable';
  const absolute=Math.abs(amount),digits=absolute>0&&absolute<0.01?4:2;
  return '≈ '+(amount<0?'−':'')+'$'+absolute.toFixed(digits);
}
function formatChannelSavings(value,rate){
  if(value==null||rate==null||!Number.isFinite(Number(value))||!Number.isFinite(Number(rate)))return 'unknown';
  return '$'+Number(value).toFixed(4)+' @ $'+Number(rate).toFixed(2)+' / 1M';
}

function renderTelemetryMetrics(observability={}){
  const state=dashboardTelemetryState(observability),period=observability.scope==='window'||sloScope==='window'?'Last 30 days':'Since restart';
  const observedCount=value=>Number.isSafeInteger(value)&&value>=0?value:null;
  const observedMetric=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  const metricText=value=>value===null?'unknown':n(value);
  const calls=observedCount(observability.tool_accounting_events);
  const status=$('efficiencyStatus'),breakdown=$('efficiencyBreakdown');
  if(status){
    const completeness=!state.available?'Telemetry unavailable. Metrics cannot be verified.':!state.activityObserved?'Writer activity was not observed; completeness is unknown.':!state.accountingBalanced?'Writer accounting is unavailable or unbalanced.':state.pending?'Telemetry writer has '+metricText(state.pending)+' pending record'+(state.pending===1?'':'s')+'.':state.summaryCacheStale?'Cached telemetry summary is stale.':!state.complete?'Incomplete telemetry. Estimates exclude missing records.':calls===null?'Accounted tool call count is unavailable.':calls===0?'No accounted tool calls yet.':'Estimated from '+metricText(calls)+' accounted tool calls.';
    status.textContent=period+' · '+completeness;
    status.classList.toggle('warn-t',!state.complete);
  }
  if(breakdown){
    const sources=Object.entries(observability.token_savings_breakdown||{}).map(([name,value])=>name+': '+metricText(observedMetric(value))).join('\n');
    breakdown.textContent='Period: '+period+'\nAccounted calls: '+metricText(calls)+'\nBaseline: '+metricText(observedMetric(observability.gross_cloud_tokens_avoided_est))+' tokens\nProtocol: '+metricText(observedMetric(observability.agent_protocol_tokens_est))+' tokens (call '+metricText(observedMetric(observability.agent_tool_request_tokens_est))+' + read '+metricText(observedMetric(observability.agent_tool_response_tokens_est))+')\nSchema-adjusted delta: '+metricText(observedMetric(observability.net_after_schema_token_delta_est))+' tokens\nSchema catalog exposure: '+metricText(observedMetric(observability.tool_schema_tokens_exposure_est))+' tokens\nLocal compute reuse: '+metricText(observedMetric(observability.local_compute_tokens_avoided_est))+' tokens\nWriter: '+metricText(state.accepted)+' accepted; '+metricText(state.written)+' written; '+metricText(state.dropped)+' records dropped; '+metricText(state.errors)+' caught error attempts; '+metricText(state.pending)+' pending; activity '+(state.activityObserved?'observed':'unobserved')+'; accounting '+(state.accountingBalanced?'balanced':'unknown/unbalanced')+(sources?'\nBaseline sources:\n'+sources:'\nNo baseline source recorded.');
  }
  if(breakdown){
    breakdown.textContent=breakdown.textContent.replace('Baseline sources:','Baseline sources (retained detail only):');
    if(observability.token_accounting_storage==='daily_rollups_and_boundary_events')breakdown.textContent+='\nAccounting: persistent daily totals plus retained partial-day records'+(observability.accounting_boundary_incomplete?'\nPartial boundary day has missing records; its lost savings are not reconstructed.':'');
  }
  if(!state.available){
    for(const id of ['handledRequests','tokensSaved','dollarsSaved','cache','latency','reliabilityValue'])if($(id))$(id).textContent='Unavailable';
    for(const id of ['handledRequestsSub','tokensSavedSub','dollarsSavedSub','cacheSub','queueWait','reliabilitySub'])if($(id))$(id).textContent='Telemetry unavailable · '+period;
    return;
  }
  const netDelta=observedMetric(observability.net_cloud_token_delta_est);
  const realisticDelta=observedMetric(observability.realistic_net_cloud_token_delta_est);
  if($('tokensSaved')){
    if(realisticDelta!==null && realisticDelta!==netDelta){
      $('tokensSaved').textContent=metricText(netDelta)+' .. '+(realisticDelta>0?'+':'')+metricText(realisticDelta);
    } else {
      $('tokensSaved').textContent=metricText(netDelta);
    }
  }
  if($('tokensSavedSub'))$('tokensSavedSub').textContent=period+' · '+(calls===null?'Accounted call count unavailable':calls?n(calls)+' accounted calls':'No accounted calls yet')+(realisticDelta!==null && realisticDelta!==netDelta?' · strict min to realistic':'')+(!state.complete?' · partial estimate':'');

  const pricingProfiles = observability.pricing_profiles || {
    'claude-5-sonnet': {id:'claude-5-sonnet',name:'Claude 5 Sonnet',input:2.50,output:12.50,cache_read:0.25,cache_write:3.125},
    'claude-5-haiku': {id:'claude-5-haiku',name:'Claude 5 Haiku',input:0.50,output:2.50,cache_read:0.05,cache_write:0.625},
    'claude-5-opus': {id:'claude-5-opus',name:'Claude 5 Opus',input:10.0,output:50.0,cache_read:1.00,cache_write:12.50},
    'gpt-6': {id:'gpt-6',name:'GPT-6',input:2.00,output:8.00,cache_read:0.80,cache_write:2.00},
    'gpt-6-mini': {id:'gpt-6-mini',name:'GPT-6 mini',input:0.10,output:0.40,cache_read:0.04,cache_write:0.10},
    'gemini-3-flash': {id:'gemini-3-flash',name:'Gemini 3 Flash',input:0.05,output:0.20,cache_read:0.0125,cache_write:0.05},
    'gemini-3-pro': {id:'gemini-3-pro',name:'Gemini 3 Pro',input:1.00,output:4.00,cache_read:0.20,cache_write:1.00},
    'claude-3-5-sonnet': {id:'claude-3-5-sonnet',name:'Claude 3.5 Sonnet',input:3.0,output:15.0,cache_read:0.30,cache_write:3.75},
    'claude-3-5-haiku': {id:'claude-3-5-haiku',name:'Claude 3.5 Haiku',input:0.80,output:4.0,cache_read:0.08,cache_write:1.0},
    'gpt-4o': {id:'gpt-4o',name:'GPT-4o',input:2.50,output:10.0,cache_read:1.25,cache_write:2.50},
    'gpt-4o-mini': {id:'gpt-4o-mini',name:'GPT-4o mini',input:0.15,output:0.60,cache_read:0.075,cache_write:0.15},
    'gemini-2-flash': {id:'gemini-2-flash',name:'Gemini 2.0 Flash',input:0.10,output:0.40,cache_read:0.025,cache_write:0.10},
    'custom': {id:'custom',name:'Custom Configured',input:Number(observability.cloud_input_token_cost_usd_per_million||3.0),output:Number(observability.cloud_output_token_cost_usd_per_million||3.0),cache_read:Number(observability.cloud_cache_read_token_cost_usd_per_million||0.25),cache_write:Number(observability.cloud_cache_write_token_cost_usd_per_million||3.125)}
  };
  const profileSel = typeof document !== 'undefined' ? $('pricingProfileSelect') : null;
  if(profileSel && (!profileSel.options || profileSel.options.length === 0)){
    let opts = '';
    for(const [pid, p] of Object.entries(pricingProfiles)){
      opts += '<option value="' + pid + '">' + p.name + '</option>';
    }
    profileSel.innerHTML = opts;
  const savedPid = (typeof localStorage!=='undefined' && typeof localStorage.getItem==='function' && localStorage.getItem('telemetryPricingProfile')) || observability.active_pricing_profile || 'claude-5-sonnet';
    if(pricingProfiles[savedPid]) profileSel.value = savedPid;
    profileSel.onchange = function(){
      if(typeof localStorage!=='undefined' && typeof localStorage.setItem==='function') localStorage.setItem('telemetryPricingProfile', profileSel.value);
      renderTelemetryMetrics(observability);
    };
  }
  const activePid = (profileSel && profileSel.value && pricingProfiles[profileSel.value]) ? profileSel.value : ((typeof localStorage!=='undefined' && typeof localStorage.getItem==='function' && localStorage.getItem('telemetryPricingProfile')) || observability.active_pricing_profile || 'claude-5-sonnet');
  const activeProfile = pricingProfiles[activePid] || pricingProfiles['claude-5-sonnet'] || pricingProfiles['claude-3-5-sonnet'];

  const pricedReq = Number(observability.agent_tool_request_tokens_est || 0);
  const pricedResp = Number(observability.agent_tool_response_tokens_est || 0);
  const grossIn = Number(observability.gross_input_cloud_tokens_avoided_est || 0);
  const grossOut = Number(observability.gross_output_cloud_tokens_avoided_est || 0);
  const avoidedTurns = Number(observability.realistic_savings_breakdown?.avoided_turns ?? (calls > 0 ? Math.round(calls * 0.3) : 0));
  const dynamicDepth = Number(observability.dynamic_depth_tokens || observability.realistic_savings_breakdown?.dynamic_depth_tokens || 25000);

  let minUsd = null;
  if(observability.estimated_savings_pricing_mode !== 'incomplete'){
    minUsd = ((grossIn - pricedResp) * activeProfile.input / 1000000) + ((grossOut - pricedReq) * activeProfile.output / 1000000);
  }
  const realOutUsd = (grossOut + avoidedTurns * 250 - pricedReq) * activeProfile.output / 1000000;
  const realCacheUsd = (avoidedTurns * dynamicDepth) * activeProfile.cache_read / 1000000;
  const realInUsd = (grossIn + avoidedTurns * 600 - pricedResp) * activeProfile.input / 1000000;
  const realisticUsd = (observability.estimated_savings_pricing_mode === 'incomplete') ? null : (realOutUsd + realCacheUsd + realInUsd);

  if($('dollarsSaved')){
    if(observability.estimated_savings_pricing_mode==='incomplete'||minUsd==null){
      $('dollarsSaved').textContent='Unknown';
    } else if(realisticUsd!=null && realisticUsd!==minUsd){
      $('dollarsSaved').textContent=formatEstimatedUsd(minUsd)+' .. '+formatEstimatedUsd(realisticUsd);
    } else {
      $('dollarsSaved').textContent=formatEstimatedUsd(minUsd);
    }
  }
  if($('dollarsSavedSub')){
    if(observability.estimated_savings_pricing_mode==='incomplete'){
      $('dollarsSavedSub').textContent='Known channel subtotals: input '+formatChannelSavings(observability.estimated_input_savings_usd,activeProfile.input)+' · output '+formatChannelSavings(observability.estimated_output_savings_usd,activeProfile.output)+' · historical channel costs unknown · '+period+(!state.complete?' · incomplete data':'');
    } else if(realisticUsd!=null && realisticUsd!==minUsd){
      $('dollarsSavedSub').textContent=activeProfile.name+' · Strict min to realistic';
    } else {
      $('dollarsSavedSub').textContent=activeProfile.name+' rates · '+period+(!state.complete?' · incomplete data':'');
    }
  }
  if(period==='Last 30 days'){
    for(const id of ['handledRequestsSub','cacheSub','queueWait'])if($(id))$(id).textContent='Retained samples · '+$(id).textContent;
  }
  if(breakdown){
    breakdown.textContent+='\nUSD input rate: '+(observability.cloud_input_token_cost_usd_per_million==null?'unknown':'$'+Number(observability.cloud_input_token_cost_usd_per_million).toFixed(2)+' / 1M')+'\nUSD output rate: '+(observability.cloud_output_token_cost_usd_per_million==null?'unknown':'$'+Number(observability.cloud_output_token_cost_usd_per_million).toFixed(2)+' / 1M');
    if(observability.cloud_cache_read_token_cost_usd_per_million!=null){
      breakdown.textContent+='\nUSD prompt cache read rate: $'+Number(observability.cloud_cache_read_token_cost_usd_per_million).toFixed(2)+' / 1M';
    }
    if(observability.call_categories){
      const cats=observability.call_categories;
      breakdown.textContent+='\nTool call categorization:\n'+
        '  • Discovery (repo/artifact/rag): '+metricText(cats.discovery?.events||0)+' calls, net '+metricText(cats.discovery?.net_delta||0)+' tokens\n'+
        '  • Agent OS (contracts/memory):  '+metricText(cats.agent_os?.events||0)+' calls, '+metricText(cats.agent_os?.protocol_tokens||0)+' protocol tokens (infrastructure)\n'+
        '  • Local Inference (task/work):   '+metricText(cats.local_inference?.events||0)+' calls, net '+metricText(cats.local_inference?.net_delta||0)+' tokens\n'+
        '  • System / Health:               '+metricText(cats.system?.events||0)+' calls\n';
    }
    if(observability.realistic_savings_breakdown){
      const b=observability.realistic_savings_breakdown;
      breakdown.textContent+='\nRealistic model breakdown ('+activeProfile.name+' prompt cache):\n'+
        '  Avoided turns: '+metricText(avoidedTurns)+'\n'+
        '  Dynamic history depth: ~'+metricText(dynamicDepth)+' tokens / turn\n'+
        '  Avoided output tokens: '+metricText(avoidedTurns * 250)+' (@ $'+Number(activeProfile.output).toFixed(2)+'/1M)\n'+
        '  Avoided cache read tokens: '+metricText(avoidedTurns * dynamicDepth)+' (@ $'+Number(activeProfile.cache_read).toFixed(2)+'/1M)\n'+
        '  Avoided slice context: '+metricText(avoidedTurns * 600)+' tokens\n'+
        '  Realistic net delta: '+metricText(b.realistic_net_token_delta_est)+' tokens (≈ '+formatEstimatedUsd(realisticUsd)+')';
      breakdown.textContent+='\nMulti-model comparison (Strict min .. Realistic):\n';
      for(const [pid, p] of Object.entries(pricingProfiles)){
        if(pid === 'custom') continue;
        const pMin = ((grossIn - pricedResp) * p.input / 1000000) + ((grossOut - pricedReq) * p.output / 1000000);
        const pReal = ((grossOut + avoidedTurns * 250 - pricedReq) * p.output / 1000000) + ((avoidedTurns * dynamicDepth) * p.cache_read / 1000000) + ((grossIn + avoidedTurns * 600 - pricedResp) * p.input / 1000000);
        breakdown.textContent+='  • '+p.name.padEnd(23)+': '+formatEstimatedUsd(pMin)+' .. '+formatEstimatedUsd(pReal)+'\n';
      }
    }
  }
}

function preprocessingSummary(preprocessing={},dependencies={},features={}){
  if(features.preprocessing===false||preprocessing.enabled===false)return {available:true,statsAvailable:true,disabled:true,text:'Preprocessing disabled'};
  const available=preprocessing.success!==false&&Array.isArray(preprocessing.projects)&&dependencies['preprocessing.status']?.degraded!==true;
  const count=value=>Math.max(0,Number(value)||0).toLocaleString();
  const projects=available?preprocessing.projects:[];
  const running=projects.filter(project=>String(project?.status||'').toLowerCase()==='running').length;
  const slots=Number.isFinite(Number(preprocessing.max_preprocessing_projects))&&preprocessing.max_preprocessing_projects!=null?count(preprocessing.max_preprocessing_projects):'unknown';
  const statsAvailable=dependencies['preprocessing.stats']?.degraded!==true;
  return {available,statsAvailable,disabled:false,text:available?count(projects.length)+' registered · '+count(running)+' currently running · '+(statsAvailable?slots:'unknown')+' concurrent slots':'Preprocessing status unknown'};
}

function telemetryPeriod(observability={}){return observability.scope==='window'?'Last 30 days':'Since restart';}

function recordTelemetrySnapshot(o={}){
  if(o===lastChartSnapshot)return;
  lastChartSnapshot=o;
  if(o.scope!==lastChartScope||o.data_available===false||o.stale===true){
    for(const points of [latencySparkData,throughputSparkData,liveChartLatency,liveChartQueue])points.length=0;
  }
  lastChartScope=o.scope;
  if(o.data_available===false||o.stale===true)return;
  const cohort=o.cohorts?.agent_http||{};
  const observedCount=value=>Number.isSafeInteger(value)&&value>=0?value:null;
  const observedNumber=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
  const events=observedCount(cohort.events);
  const latency=observedNumber(cohort.p95_duration_ms);
  const wait=observedNumber(o.avg_queue_wait_ms);
  for(const [points,value,limit] of [[latencySparkData,latency,25],[throughputSparkData,events,25],[liveChartLatency,latency,30],[liveChartQueue,wait,30]]){
    if(value===null)continue;
    points.push(value);if(points.length>limit)points.shift();
  }
}

function dashboardHealth(snapshot={}){
  const current=snapshot.current||snapshot.live||snapshot.headless||snapshot;
  const status=String(current.health||current.status||current.service_status||current.state||'').toLowerCase();
  const count=value=>Math.max(0,Number(value)||0);
  const openIssues=Math.max(count(current.open_incidents),count(current.active_errors),count(current.blocked_requests)),hubOnline=snapshot.hub_online??current.hub_online,ollamaOnline=snapshot.ollama_online??current.ollama_online,heartbeatStale=current.heartbeat_stale===true||snapshot.heartbeat_stale===true;
  const ollamaStatus=String(snapshot.ollama_status??current.ollama_status??(ollamaOnline==null?'unknown':ollamaOnline?'online':'offline')).toLowerCase();
  const terminalStatuses=['down','offline','unavailable','crashed','stopped'];
  const processLiveness=hubOnline===false||terminalStatuses.includes(status)?'offline':heartbeatStale||status==='stale'?'stale':hubOnline===true||['running','healthy','ok','online'].includes(status)?'live':'unknown';
  const signals=[];
  const failedChecks=Object.entries(snapshot.dependency_status||{}).filter(([name,value])=>!name.startsWith('runtime_stats.')&&!isTelemetrySummaryDependency(name)&&value?.degraded).map(([name])=>name);
  if(failedChecks.length)signals.push('unavailable checks: '+failedChecks.join(', '));
  const coreCheckNames=['headless','runtime.online','scheduler'];
  const coreCheckFailed=failedChecks.some(name=>coreCheckNames.includes(name));
  const functionalCoreCheckFailed=failedChecks.some(name=>coreCheckNames.some(coreName=>name===coreName||name.endsWith(`.${coreName}`)));
  const preprocessingDeps=snapshot.dependency_status||current.dependency_status||{};
  const features=snapshot.features||current.features||{};
  const preprocessingAdvertised=Object.hasOwn(snapshot,'preprocessing')||Object.hasOwn(current,'preprocessing')||Object.hasOwn(preprocessingDeps,'preprocessing.status')||Object.hasOwn(preprocessingDeps,'preprocessing.stats');
  let preprocessing={available:true,statsAvailable:true,errorCount:0,disabled:true};
  if(preprocessingAdvertised){
    preprocessing=dashboardPreprocessingHealth(snapshot.preprocessing||current.preprocessing||{},preprocessingDeps,features);
    if(!preprocessing.disabled){
      if(!preprocessing.available)signals.push('preprocessing project status is unknown');
      if(!preprocessing.statsAvailable)signals.push('preprocessing statistics are unavailable');
      if(preprocessing.errorCount)signals.push(`${preprocessing.errorCount} current preprocessing project${preprocessing.errorCount===1?'':'s'} report error`);
    }
  }
  const telemetry=snapshot.observability&&typeof snapshot.observability==='object'?dashboardTelemetryState(snapshot.observability):null;
  const telemetrySummaryFailed=Object.entries(snapshot.dependency_status||{}).some(([name,value])=>isTelemetrySummaryDependency(name)&&value?.degraded===true);
  if(!telemetry){
    if(!telemetrySummaryFailed&&snapshot.success!==true)signals.push('telemetry data is unavailable or stale');
  }else{
    if(!telemetry.available)signals.push('telemetry data is unavailable or stale');
    else if(!telemetry.activityObserved)signals.push('telemetry writer activity is unobserved');
    else if(!telemetry.accountingBalanced)signals.push('telemetry writer accounting is unbalanced');
    else if(telemetry.pending>20)signals.push(`telemetry writer has ${telemetry.pending} pending records`);
    else if(telemetry.summaryCacheStale)signals.push('telemetry summary is stale');
    else if(!telemetry.complete)signals.push('telemetry coverage is incomplete');
  }
  const dataCompleteness=!telemetry?'unknown':!telemetry.available?'unavailable':telemetry.complete?'complete':'incomplete';
  const functionalFailure=hubOnline===false||heartbeatStale||terminalStatuses.includes(status)||['degraded','stale'].includes(status)||current.degraded===true||functionalCoreCheckFailed||Boolean(!preprocessing.disabled&&preprocessing.errorCount>0);
  const functionalUncertainty=preprocessingAdvertised&&(!preprocessing.available||!preprocessing.statsAvailable);
  const functionalHealth=functionalFailure?'degraded':functionalUncertainty||ollamaStatus!=='online'||['attention','warning','warn','partial'].includes(status)?'attention':'healthy';
  const finish=health=>({...health,process_liveness:processLiveness,data_completeness:dataCompleteness,functional_health:functionalHealth,reason:`${health.reason} Process liveness: ${processLiveness}; data completeness: ${dataCompleteness}; functional health: ${functionalHealth}.`});
  const actionTab=openIssues||count(current.blocked_requests)?'work':'reliability';
  const actionLabel=actionTab==='work'?'Open queue and requests':'Open reliability details';
  if(hubOnline===false||heartbeatStale||['degraded','down','offline','unavailable','crashed','stopped','stale'].includes(status)||current.degraded===true||coreCheckFailed){
    const reason=hubOnline===false?'Hub is offline.':heartbeatStale||status==='stale'?'Runtime heartbeat is stale.':signals.length?`Current runtime is degraded: ${signals.join(', ')}.`:'Current runtime reports an unavailable service.';
    return finish({level:'degraded',label:'Degraded',reason,actionTab,actionLabel});
  }
  if(ollamaStatus==='unknown')signals.push('Ollama status is unknown');
  else if(ollamaStatus==='offline')signals.push('Ollama is offline');
  if(hubOnline==null&&!status)signals.push('Hub status is unknown');
  if(['attention','warning','warn','partial'].includes(status)||openIssues||signals.length){
    const reason=openIssues?`Current runtime has ${openIssues} open issue${openIssues===1?'':'s'}${signals.length?`; ${signals.join(', ')}`:''}.`:signals.length?`Current runtime needs attention: ${signals.join(', ')}.`:'Current runtime reports a warning state.';
    return finish({level:'attention',label:'Needs attention',reason,actionTab,actionLabel});
  }
  return finish({level:'healthy',label:'Healthy',reason:'Current runtime reports no active issue.',actionTab:'reliability',actionLabel:'Open reliability details'});
}

function dashboardFreshness(timestamp,now=Date.now(),staleAfterMs=120000){
  let value=typeof timestamp==='number'?timestamp:(typeof timestamp==='string'&&/^[-+]?\d+(?:\.\d+)?$/.test(timestamp.trim())?Number(timestamp):Date.parse(timestamp||''));
  if(!Number.isFinite(value))return {state:'unknown',label:'Timestamp unavailable',ageMs:null};
  if(value>0&&value<100000000000)value*=1000;
  const current=Number(now);
  if(!Number.isFinite(current))return {state:'unknown',label:'Clock unavailable',ageMs:null};
  const ageMs=Math.max(0,current-value),configuredThreshold=Number(staleAfterMs),threshold=Number.isFinite(configuredThreshold)?Math.max(0,configuredThreshold):60000;
  return {state:ageMs>threshold?'stale':'fresh',label:ageMs>threshold?'Stale':'Fresh',ageMs};
}

function renderOverviewHealth(snapshot={},receivedAt=Date.now(),now=Date.now()){
  const runtime=snapshot.headless||{};
  const current={...runtime,health:runtime.health||runtime.state||snapshot.health||snapshot.status||snapshot.service_status};
  let health=dashboardHealth(snapshot);
  const timestamp=snapshot.updated_at??snapshot.generated_at??snapshot.timestamp??runtime.updated_at;
  let freshness=dashboardFreshness(timestamp,now);
  if(snapshot.snapshot_stale===true){
    const cachedAge=Number(snapshot.status_age_ms);
    freshness={state:'stale',label:'Stale',ageMs:Number.isFinite(cachedAge)?cachedAge:freshness.ageMs};
  }
  if(freshness.state==='unknown'&&Number.isFinite(Number(receivedAt)))freshness=dashboardFreshness(receivedAt,now);
  if(freshness.state!=='fresh'||snapshot.snapshot_stale===true)health={...health,level:'attention',label:'Status stale',reason:'Live status is stale; current health cannot be verified.'};
  const level=$('overviewHealthLevel'),evidence=$('overviewHealthEvidence'),freshnessEl=$('overviewFreshness'),action=$('overviewHealthAction'),summary=$('overviewHealthSummary'),announcement=$('overviewAnnouncement');
  if(!level||!evidence||!freshnessEl||!action||!summary)return;
  const label=health.label;
  const target=health.actionTab||'reliability';
  const targetLabel=health.actionLabel||'Open reliability details';
  const stateText=current.health||current.status||current.service_status||'unreported';
  const activeRequests=Array.isArray(snapshot.observability?.active_requests)?snapshot.observability.active_requests.length:null;
  const activeRequestText=activeRequests===null?'unknown':`${activeRequests} active API request${activeRequests===1?'':'s'}`;
  const evidenceText=`${health.reason} Runtime state: ${stateText}. Active API requests: ${activeRequestText}.`;
  level.textContent=label;
  level.className='value primary-metric '+(health.level==='healthy'?'ok':health.level==='attention'?'warn-t':'bad-t');
  evidence.textContent=evidenceText;
  const history=$('overviewHistorySummary'),o=snapshot.observability||{};
  const historySummary=()=>{
    const state=dashboardTelemetryState(o);
    if(!state.available)return 'Historical telemetry unavailable · current runtime checks shown above.';
    const label=value=>value===null?'unknown':value.toLocaleString();
    return `Recorded history · ${telemetryPeriod(o)} · ${label(state.requestFailures)} request failures · ${label(state.policyRejections)} policy rejections · ${label(state.dropped)} telemetry queue drops · ${state.complete?'complete':'incomplete'} data.`;
  };
  if(history)history.textContent=historySummary();
  freshnessEl.textContent=freshness.ageMs===null?freshness.label:`${freshness.label} · updated ${age(freshness.ageMs)} ago`;
  freshnessEl.className='tiny '+(freshness.state==='stale'?'warn-t':'muted');
  summary.style.borderLeftColor=health.level==='healthy'?'var(--ok)':health.level==='attention'?'var(--warn)':'var(--bad)';
  action.textContent=targetLabel;
  action.onclick=()=>switchTab(target);
  const announcementText=`${label}. ${freshness.label}.`;
  if(announcement&&announcementText!==lastOverviewAnnouncement){announcement.textContent=announcementText;lastOverviewAnnouncement=announcementText;}
}

function redactDiagnostic(value){
  let text=String(value??'');
  text=text.replace(/\bBearer\s+[^\s,;]+/gi,'Bearer <redacted>');
  text=text.replace(/(^|\s)((?:--(?:api[-_]?key|token|secret|password)(?:=|\s+)))(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)/gi,'$1$2<redacted>');
  text=text.replace(/(^|\s)((?:[a-z0-9_.-]*?(?:api[_-]?key|token|secret|password|authorization))\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)/gi,'$1$2<redacted>');
  text=text.replace(/((?:["'](?:api[_-]?key|token|secret|password|authorization)["'])\s*:\s*)(?:\"[^\"]*\"|'[^']*'|[^,\s}]+)/gi,'$1\"<redacted>\"');
  text=text.replace(/\b[A-Za-z]:[\\/][^\s\"'<>|]*/g,'<path>');
  text=text.replace(/(?<![:\w])\/[^\s\"'<>|]+/g,'<path>');
  return text;
}

// Lightweight pure-canvas chart renderer
function drawSpark(canvasId, points, strokeColor, fillColor){
  const cv=$(canvasId);if(!cv)return;
  const ctx=cv.getContext('2d');if(!ctx)return;
  const w=cv.width,h=cv.height;
  ctx.clearRect(0,0,w,h);
  if(!points.length)return;
  const maxVal=Math.max(...points, 1);
  const minVal=Math.min(...points, 0);
  const range=maxVal-minVal||1;
  const step=w/(Math.max(points.length-1, 1));
  ctx.beginPath();
  points.forEach((val, i)=>{
    const x=i*step;
    const y=h - ((val - minVal) / range) * (h - 4) - 2;
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  });
  if(fillColor){
    ctx.lineTo((points.length-1)*step, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fillStyle=fillColor;
    ctx.fill();
    ctx.beginPath();
    points.forEach((val, i)=>{
      const x=i*step;
      const y=h - ((val - minVal) / range) * (h - 4) - 2;
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    });
  }
  ctx.strokeStyle=strokeColor;
  ctx.lineWidth=1.5;
  ctx.shadowColor=strokeColor;
  ctx.shadowBlur=3;
  ctx.stroke();
  ctx.shadowBlur=0;
}

function drawDualChart(canvasId, series1, series2){
  const cv=$(canvasId);if(!cv)return;
  const ctx=cv.getContext('2d');if(!ctx)return;
  const w=cv.width,h=cv.height;
  ctx.clearRect(0,0,w,h);
  // Grid lines
  ctx.strokeStyle='#141d2a';
  ctx.lineWidth=1;
  for(let y=25;y<h;y+=35){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  const allPts=[...series1, ...series2];
  if(!allPts.length)return;
  const maxVal=Math.max(...allPts, 10);
  const step=w/Math.max((series1.length||1)-1, 1);
  const renderLine=(pts, color, fill)=>{
    if(!pts.length)return;
    ctx.beginPath();
    pts.forEach((val, i)=>{
      const x=i*step;
      const y=h - (val / maxVal) * (h - 20) - 10;
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    });
    ctx.strokeStyle=color;
    ctx.lineWidth=2;
    ctx.stroke();
  };
  renderLine(series1, '#efb76f', 'rgba(56,189,248,0.1)');
  renderLine(series2, '#34d399', 'rgba(52,211,153,0.1)');
}

const tracePageStyles=document.createElement('style');
tracePageStyles.textContent='.trace-page{height:calc(100vh - 112px);min-height:560px;padding:12px!important}.trace-layout{display:grid;grid-template-columns:300px minmax(0,1fr);height:100%;min-height:0;gap:12px}.trace-sidebar,.trace-main{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-height:0;overflow:hidden}.trace-sidebar{display:flex;flex-direction:column}.trace-sidebar-head{padding:12px;border-bottom:1px solid var(--line);background:#20251c}.trace-sidebar-head strong{display:block;font-size:14px;margin:7px 0 3px}.trace-sidebar-list{overflow:auto;padding:6px}.trace-side-item{display:block;width:100%;text-align:left;background:transparent;color:var(--fg);border:1px solid transparent;border-radius:7px;padding:9px;margin:2px 0;cursor:pointer}.trace-side-item:hover{background:#2c3524;border-color:#526144}.trace-side-item.active{background:#343e29;border-color:var(--accent)}.trace-side-top{display:flex;align-items:center;gap:7px}.trace-side-state{width:7px;height:7px;border-radius:50%;background:var(--warn);flex:0 0 auto}.trace-side-state.done{background:var(--ok)}.trace-side-state.failed{background:var(--bad)}.trace-side-action{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-side-meta{display:block;color:var(--muted);font-size:10px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-main{overflow:auto;padding:18px}.trace-main-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}.trace-main-head h1{font-size:18px;margin:0;overflow-wrap:anywhere}.trace-main-head .spacer{margin-left:auto}.trace-select-empty{display:grid;place-items:center;min-height:420px;color:var(--muted);text-align:center;border:1px dashed #526144;border-radius:8px}.trace-main .human-shell{padding:0}.trace-main .human-section{margin:12px 0}.trace-main .trace-timeline{padding:12px}.trace-page .trace-raw-panel{max-width:none}@media(max-width:900px){.trace-page{height:auto;min-height:calc(100vh - 112px)}.trace-layout{grid-template-columns:1fr}.trace-sidebar{max-height:280px}.trace-main{min-height:620px}}';
document.head.append(tracePageStyles);

const workPageStyles=document.createElement('style');
workPageStyles.textContent='.work-page{display:grid!important;grid-template-columns:minmax(0,1.55fr) minmax(320px,.9fr);gap:12px;align-items:start}.work-page>.work-summary{grid-column:1/-1}.work-panel{min-width:0}.work-panel-1{grid-column:1;grid-row:2}.work-panel-2{grid-column:2;grid-row:2}.work-panel-3{grid-column:1;grid-row:3}.work-panel-4{grid-column:2;grid-row:3}.work-summary{padding:14px!important}.work-summary-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.work-kicker{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}.work-summary h2{margin:0}.work-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}.work-kpis>div{background:#171b14;border:1px solid #434f37;border-radius:7px;padding:9px 10px}.work-kpis span{display:block;color:var(--muted);font-size:10px}.work-kpis strong{display:block;font-size:18px;margin-top:3px}.work-panel h2{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.work-panel .table-wrap{max-height:390px;overflow:auto}.work-panel table{width:100%;table-layout:fixed}.work-panel th{position:sticky;top:0;z-index:1;background:#20251c}.work-panel td{vertical-align:top;overflow-wrap:anywhere}.work-panel-1 th:nth-child(1){width:13%}.work-panel-1 th:nth-child(2){width:20%}.work-panel-1 th:nth-child(3){width:24%}.work-panel-1 th:nth-child(4){width:17%}.work-panel-1 th:nth-child(5){width:26%}.work-panel-2 th:nth-child(1){width:27%}.work-panel-2 th:nth-child(2){width:30%}.work-panel-2 th:nth-child(3){width:27%}.work-panel-2 th:nth-child(4){width:16%}.work-panel-3 th:nth-child(1){width:12%}.work-panel-3 th:nth-child(2){width:14%}.work-panel-3 th:nth-child(3){width:9%}.work-panel-3 th:nth-child(4){width:14%}.work-panel-3 th:nth-child(5){width:31%}.work-panel-3 th:nth-child(6){width:10%}.work-panel-3 th:nth-child(7){width:10%}.work-panel-3 td{white-space:normal;overflow-wrap:anywhere;word-break:break-word}.work-panel-4 th:nth-child(1){width:13%}.work-panel-4 th:nth-child(2){width:22%}.work-panel-4 th:nth-child(3){width:22%}.work-panel-4 th:nth-child(4){width:18%}.work-panel-4 th:nth-child(5){width:15%}.work-panel-4 th:nth-child(6){width:10%}.work-state{display:inline-block;border:1px solid #3b4b5e;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px;white-space:nowrap}.work-state.live{border-color:#4f8edb;color:var(--accent)}.work-state.bad{border-color:#a64c4c;color:var(--bad)}.timing-label{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.04em}.work-panel-4 .tiny{line-height:1.35}@media(max-width:1050px){.work-page{grid-template-columns:1fr}.work-page>.work-summary,.work-panel-1,.work-panel-2,.work-panel-3,.work-panel-4{grid-column:1;grid-row:auto}.work-panel .table-wrap{max-height:320px}}@media(max-width:620px){.work-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.work-summary-head{display:block}.work-summary-head>.tiny{display:block;margin-top:6px}.work-panel table{table-layout:auto;min-width:650px}.work-panel .table-wrap{overflow:auto}}';
document.head.append(workPageStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-side-state.interrupted{background:var(--warn)}.trace-interrupted{color:var(--warn)}.work-page{display:none!important}.work-page.active{display:grid!important}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.work-page.active .work-panel-4{grid-column:1/-1!important;grid-row:3!important}.work-page.active .work-panel-4 .table-wrap{max-height:460px}.work-page.active .work-panel-3{grid-column:1/-1!important;grid-row:4!important}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.work-panel-3 th:nth-child(1){width:10%}.work-panel-3 th:nth-child(2){width:12%}.work-panel-3 th:nth-child(3){width:9%}.work-panel-3 th:nth-child(4){width:10%}.work-panel-3 th:nth-child(5){width:20%}.work-panel-3 th:nth-child(6){width:11%}.work-panel-3 th:nth-child(7){width:9%}.work-panel-3 th:nth-child(8){width:12%}.work-panel-3 th:nth-child(9){width:7%}.work-panel-3 td:nth-child(8),.work-panel-3 td:nth-child(9){white-space:nowrap;overflow-wrap:normal;word-break:normal}</style>');

const workFilterStyles=document.createElement('style');
workFilterStyles.textContent='.work-filter{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}.work-filter input,.work-filter select{background:#171b14;color:var(--fg);border:1px solid #566349;border-radius:6px;padding:7px 9px;font:inherit;font-size:11px}.work-filter input{flex:1;min-width:220px}.work-filter select{min-width:125px}.work-filter .btn{padding:6px 9px;font-size:11px}.work-filter-summary{color:var(--muted);font-size:10px}';
document.head.append(workFilterStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-sidebar-controls{display:flex;gap:6px;padding:8px 8px 2px}.trace-sidebar-controls input,.trace-sidebar-controls select{min-width:0;width:100%;background:#171b14;color:var(--fg);border:1px solid #566349;border-radius:6px;padding:6px 7px;font:inherit;font-size:10px}.trace-sidebar-controls select{width:116px;flex:0 0 116px}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-main,.trace-step-body,.trace-event,.human-section{min-width:0}.prompt-meta{display:flex;gap:5px;flex-wrap:wrap;padding:7px 8px;border-bottom:1px solid #343c2b}.prompt-chip{border:1px solid #566349;border-radius:999px;padding:2px 7px;color:var(--muted);font-size:9px}.prompt-chip strong{color:var(--fg)}.prompt-messages{display:grid;gap:6px;padding:7px}.prompt-card{border:1px solid #46543a;border-left:3px solid #5b8def;border-radius:6px;overflow:hidden}.prompt-card.role-system{border-left-color:#a78bfa}.prompt-card.role-user{border-left-color:#efb76f}.prompt-card.role-assistant{border-left-color:#4ade80}.prompt-card-head{display:flex;align-items:center;gap:7px;padding:6px 8px;background:#20251c;color:var(--fg);font-size:10px;font-weight:700}.prompt-card-head .tiny{margin-left:auto}.prompt-pre{margin:0;padding:7px 8px;background:#141811;color:#dfe6d5;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.3;font-size:11px;max-height:150px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}.prompt-context{margin:0 8px 8px;border:1px solid #4b5a3e;border-radius:5px;background:#1b2116}.prompt-context summary{cursor:pointer;padding:6px 8px;color:var(--muted);font-size:9px}.prompt-context .prompt-pre{max-height:180px;border-top:1px solid #414c35}.prompt-fallback{padding:8px}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-codex-timeline,.trace-codex-timeline *{min-width:0;max-width:100%;box-sizing:border-box}.trace-codex-timeline .trace-timeline-event,.trace-codex-timeline .trace-tool-card{overflow:hidden;overflow-wrap:anywhere;word-break:break-word}.trace-codex-timeline .trace-timeline-marker,.trace-codex-timeline h4,.trace-codex-timeline .trace-tool-field,.trace-codex-timeline .human-grid,.trace-codex-timeline .human-value{overflow-wrap:anywhere;word-break:break-word}.trace-codex-timeline pre{max-width:100%;white-space:pre-wrap;overflow:auto}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-primary{margin:0 0 14px}.trace-primary-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:8px}.trace-primary-head h2{margin:0;font-size:14px}.trace-primary-grid{display:grid;grid-template-columns:1fr;gap:10px}.trace-primary-card{min-width:0;border:1px solid #526144;border-radius:8px;overflow:hidden;background:#171b14}.trace-primary-card.input{border-color:#9b8756}.trace-primary-card.output{border-color:#397658}.trace-primary-card h3{margin:0;padding:9px 11px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;background:#20251c}.trace-primary-card.input h3{color:#a9c6ff}.trace-primary-card.output h3{color:#9be7b8}.trace-primary-value{min-width:0;padding:10px;overflow-wrap:anywhere}.trace-primary-value .human-grid{padding:0}.trace-primary-empty{color:var(--muted);font-size:11px}.trace-presentation-actions{display:flex;align-items:center;justify-content:flex-end;gap:5px;flex-wrap:wrap;margin:0 0 8px}.trace-presentation-actions .btn{padding:4px 7px;font-size:10px}.trace-capture-state{display:inline-flex;align-items:center;border:1px solid #566349;border-radius:999px;padding:3px 7px;font-size:10px;white-space:nowrap}.trace-capture-state.produced{border-color:#397658;color:#9be7b8}.trace-capture-state.empty{border-color:#8b6d31;color:#f4d58b}.trace-capture-state.not-captured{border-color:#536274;color:#aeb9c7}.trace-capture-state.redacted{border-color:#795a9b;color:#d9b8ff}.trace-optional-details{width:100%;box-sizing:border-box;border:1px solid #46543a;border-radius:8px;background:#161a13}.trace-optional-details>summary{cursor:pointer;padding:10px 12px;color:var(--fg);font-size:11px;font-weight:700}.trace-optional-details>summary::marker{color:var(--accent)}.trace-optional-details[open]>summary{border-bottom:1px solid #414c35}.trace-optional-body{padding:0 12px 12px;min-width:0;overflow-wrap:anywhere}.trace-optional-body .human-section:first-child{margin-top:12px}.trace-chat-columns{display:grid;grid-template-columns:1fr;gap:10px;align-items:start}.trace-chat-column{min-width:0}.trace-chat-input{border-color:#9b8756}.trace-chat-output{border-color:#397658}.trace-chat-message{border-top:1px solid #414c35;padding:9px 0}.trace-chat-message:first-child{border-top:0;padding-top:0}.trace-chat-role{color:var(--accent);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}.trace-chat-meta{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 8px}.trace-chat-meta span{border:1px solid #434f37;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px}.trace-tool-timeline{display:grid;gap:8px;margin-top:10px}.trace-tool-card{border:1px solid #526144;border-left:3px solid var(--accent);border-radius:6px;background:#0b131b;padding:9px}.trace-tool-card.error{border-left-color:var(--bad)}.trace-tool-card h4{margin:0 0 6px;font-size:11px}.trace-tool-card pre{max-height:220px;overflow:auto;margin:4px 0 0}.trace-tool-field{margin-top:7px}.trace-tool-field strong{color:var(--muted);font-size:10px;text-transform:uppercase}.trace-tool-field .human-pre{margin:4px 0 0}@media(max-width:700px){.trace-primary-grid,.trace-chat-columns{grid-template-columns:1fr}}</style>');

document.head.insertAdjacentHTML('beforeend','<style>.trace-presentation-field{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:6px 12px;align-items:start;padding:7px 0;min-width:0}.trace-presentation-field+ .trace-presentation-field{border-top:1px solid #414c35}.trace-presentation-field>strong{color:var(--muted);font-size:10px;line-height:1.4;overflow-wrap:anywhere}.trace-presentation-field>div,.trace-presentation-field>span,.trace-presentation-field>pre,.trace-presentation-field>details{min-width:0;overflow-wrap:anywhere}.trace-command-top{border:1px solid #46543a;border-radius:8px;background:#161a13;padding:10px;margin:0 0 14px}.trace-command-top>h3{margin:0 0 4px;font-size:12px;color:var(--fg)}@media(max-width:700px){.trace-presentation-field{grid-template-columns:1fr;gap:3px}.trace-command-top{padding:8px}}</style>');
const nativeFetch=window.fetch.bind(window);
function setupTraceInspector(){
  if($('traceInspector'))return;
  document.body.insertAdjacentHTML('beforeend','<div id="traceInspector" class="page trace-page"><div class="trace-layout"><aside class="trace-sidebar"><div class="trace-sidebar-head"><button class="btn" data-trace-back>← Queue & requests</button><strong>Agent trace history</strong><span class="tiny" id="traceSideSummary">Select a run to inspect</span></div><div id="traceSidebarList" class="trace-sidebar-list"></div></aside><main class="trace-main"><div class="trace-main-head"><div><h1 id="tracePageTitle">Select an agent trace</h1><span id="tracePageLive" class="tiny"></span></div><button class="btn spacer" data-trace-back>Back</button></div><div id="tracePageBody" class="trace-select-empty">Choose a trace from the left.</div></main></div></div>');
}
setupTraceInspector();
if($('traceSidebarList')&&!$('traceHistorySearch')){$('traceSidebarList').insertAdjacentHTML('beforebegin','<div class="trace-sidebar-controls"><input id="traceHistorySearch" type="search" placeholder="Search history…" autocomplete="off"><select id="traceHistoryState" aria-label="History state"><option value="useful">Live + completed</option><option value="">All history</option><option value="interrupted">Interrupted</option><option value="failed">Failed</option></select></div>')}

let statusPollInFlight=false,hasLiveStatus=false;
let sloScope=$('sloScope')?$('sloScope').value:'1h';
if($('sloScope')) $('sloScope').onchange=()=>{sloScope=$('sloScope').value;statusPoller.refresh()};
function syncDetailedTelemetryToggle(enabled){
  const button=$('detailedTelemetryToggle');if(!button)return;
  button.textContent=`Detailed telemetry: ${enabled?'On':'Off'}`;
  button.setAttribute('aria-pressed',String(Boolean(enabled)));
}
let detailedTelemetryOverride=null;
function resolveDetailedTelemetryState(reported){
  if(detailedTelemetryOverride===null||reported===detailedTelemetryOverride){
    detailedTelemetryOverride=null;
    return reported;
  }
  return detailedTelemetryOverride;
}
function confirmDetailedTelemetryEnable(){
  const dialog=$('detailedTelemetryConfirm');
  if(!dialog||typeof dialog.showModal!=='function')return Promise.resolve(false);
  return new Promise(resolve=>{
    const onClose=()=>resolve(dialog.returnValue==='enable');
    dialog.addEventListener('close',onClose,{once:true});
    dialog.returnValue='';
    try{dialog.showModal()}catch{dialog.removeEventListener('close',onClose);resolve(false)}
  });
}
if($('detailedTelemetryToggle'))$('detailedTelemetryToggle').onclick=async()=>{
  const button=$('detailedTelemetryToggle');
  const displayedState=button?.getAttribute('aria-pressed');
  const enabled=displayedState==='true'?false:displayedState==='false'?true:!Boolean(last?.debug_traces?.enabled);
  if(enabled&&!(await confirmDetailedTelemetryEnable())){const status=$('detailedTelemetryStatus');if(status)status.textContent='Detailed telemetry remains Off.';return;}
  if(button)button.disabled=true;
  const status=$('detailedTelemetryStatus');if(status)status.textContent='';
  let failureStage='';
  try{
    const result=await post('/api/config/update',{settings:{'telemetry.mode':enabled?'full':'minimal'}});
    failureStage=result?.failure_stage==='persistence'?'persistence':result?.failure_stage==='validation'?'validation':'';
    if(!result?.success)throw new Error(result?.error||'Unable to update telemetry');
    if(result.applied_live!==true){
      syncDetailedTelemetryToggle(Boolean(last?.debug_traces?.enabled));
      if(status)status.textContent=result.restart_required
        ?'Setting saved, but live telemetry could not be applied. Restart required.'
        :'Hub did not confirm live telemetry; current state unchanged.';
      return;
    }
    detailedTelemetryOverride=enabled;
    last={...last,debug_traces:{...(last?.debug_traces||{}),enabled}};
    syncDetailedTelemetryToggle(enabled);
    if(status)status.textContent=`Detailed telemetry ${enabled?'enabled':'disabled'}.`;
    if(activeTraceData)renderTraceDetail(activeTraceData);
  }catch(error){
    const message=typeof error?.message==='string'?error.message.trim().slice(0,240):'';
    const stageText=failureStage?` during ${failureStage}`:'';
    if(status)status.textContent=message?`Telemetry update failed${stageText}: ${message}`:'Could not confirm telemetry change. Check the displayed state before retrying.';
  }
  finally{if(button)button.disabled=false;statusPoller.refresh();}
};

function createDashboardStatusPoller(poll,options={}){
  const baseDelay=Math.max(1,Number(options.baseDelay)||5000);
  const maxDelay=Math.max(baseDelay,Number(options.maxDelay)||60000);
  const maxFailures=Math.max(1,Math.ceil(Math.log2(maxDelay/baseDelay))+1);
  const isVisible=options.isVisible||(()=>document.visibilityState!=='hidden');
  const setTimer=options.setTimer||((fn,delay)=>setTimeout(fn,delay));
  const clearTimer=options.clearTimer||((id)=>clearTimeout(id));
  const random=options.random||Math.random;
  let timer=null,started=false,running=false,pending=false,visible=true,generation=0,failures=0,unchangedSuccesses=0;
  const current=token=>started&&visible&&isVisible()&&generation===token;
  function clear(){if(timer!==null){clearTimer(timer);timer=null}}
  function schedule(delay){clear();if(started&&visible&&isVisible())timer=setTimer(()=>{timer=null;void run()},delay)}
  async function run(){
    if(!started||!visible||!isVisible())return;
    if(running){pending=true;return}
    running=true;
    const token=generation;
    let succeeded=false,unchanged=false;
    try{
      const outcome=await poll(()=>current(token));
      succeeded=outcome!==false&&!(outcome&&outcome.ok===false);
      unchanged=succeeded&&Boolean(outcome&&outcome.changed===false);
    }catch{}
    finally{
      running=false;
      if(current(token)){
        const refreshPending=pending;
        pending=false;
        if(succeeded){failures=0;unchangedSuccesses=unchanged?Math.min(unchangedSuccesses+1,maxFailures):0}
        else{failures=Math.min(failures+1,maxFailures);unchangedSuccesses=0}
        const backoff=succeeded?Math.min(maxDelay,baseDelay*2**unchangedSuccesses):Math.min(maxDelay,baseDelay*2**Math.max(0,failures-1));
        const sample=Math.min(0.999999,Math.max(0,Number(random())||0));
        schedule(refreshPending?0:Math.min(maxDelay,Math.round(backoff*(0.8+sample*0.4))));
      }else if(pending&&started&&visible&&isVisible()){
        pending=false;
        schedule(0);
      }
    }
  }
  return{
    start(){if(started)return;started=true;visible=isVisible();generation++;schedule(0)},
    refresh(){if(!started){started=true;visible=isVisible();generation++;schedule(0);return}if(!visible||!isVisible())return;if(running){pending=true;return}schedule(0)},
    setVisible(next){visible=Boolean(next)&&isVisible();generation++;if(visible)schedule(0);else{pending=false;clear()}},
    stop(){started=false;visible=false;pending=false;generation++;clear()}
  };
}

let lastDashboardStatusSnapshot=null;
let lastDashboardStatusChanged=false;
let hardwareRefreshPending=false;
function shouldRefreshDashboardStatus(status){
  const stableStatus={...(status||{})};delete stableStatus.status_age_ms;delete stableStatus.snapshot_cached;
  const snapshot=JSON.stringify(stableStatus);
  if(snapshot===lastDashboardStatusSnapshot)return false;
  lastDashboardStatusSnapshot=snapshot;
  return true;
}

function scopeAgentOsRequest(path,options={}){
  if(!String(path).startsWith('/api/agent-state/'))return {path,options};
  if(options?.unscoped)return {path,options};
  const root=$('agentOsRoot')?.value?.trim()||$('agentOsRepoSelect')?.value?.trim();
  if(!root)throw new Error('Choose a repository root in Agent OS first.');
  if(String(options.method||'GET').toUpperCase()==='GET'){
    if(!new URL(path,'http://localhost').searchParams.has('root')){
      path+=String(path).includes('?')?'&':'?';
      path+='root='+encodeURIComponent(root);
    }
  }else{
    const payload=options.body?JSON.parse(options.body):{};
    if(!payload.root)options={...options,body:JSON.stringify({...payload,root})};
  }
  return {path,options};
}
async function apiFetch(path,opts={}){
  const scoped=scopeAgentOsRequest(path,opts);path=scoped.path;opts=scoped.options;
  opts={...opts};
  const h=new Headers(opts.headers||{});
  h.set('X-LocalAI-Client','dashboard');opts.headers=h;
  const request=async requestOpts=>{
    const next={...requestOpts},parentSignal=next.signal;let controller=null,timer=null,timedOut=false,abortParent=null;
    const cleanup=()=>{if(timer!==null){clearTimeout(timer);timer=null}if(abortParent)parentSignal.removeEventListener('abort',abortParent)};
    const failure=error=>timedOut?new Error('Request timed out. Refresh this page to retry.'):error;
    if(typeof AbortController==='function'){
      controller=new AbortController();next.signal=controller.signal;
      if(parentSignal){abortParent=()=>controller.abort(parentSignal.reason);if(parentSignal.aborted)abortParent();else parentSignal.addEventListener('abort',abortParent,{once:true})}
      const requestedTimeout=Number(next.timeoutMs),timeoutMs=Number.isFinite(requestedTimeout)&&requestedTimeout>0?requestedTimeout:30000;
      timer=setTimeout(()=>{timedOut=true;controller.abort();cleanup()},Math.max(1000,timeoutMs));
    }
    delete next.timeoutMs;
    try{
      const response=await nativeFetch(path,next);let readable=false;
      for(const method of ['json','text','blob','arrayBuffer','formData']){
        if(typeof response[method]!=='function')continue;
        readable=true;const read=response[method].bind(response);
        response[method]=async(...args)=>{try{return await read(...args)}catch(error){throw failure(error)}finally{cleanup()}};
      }
      if(!readable||response.body===null)cleanup();
      return response;
    }catch(error){cleanup();throw failure(error)}
  };
  return request(opts);
}
