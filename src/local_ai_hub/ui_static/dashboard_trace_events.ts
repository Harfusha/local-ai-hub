// @ts-nocheck
function traceFiniteSequence(candidate,prior){return typeof candidate==='number'&&Number.isFinite(candidate)&&candidate>=prior?candidate:prior;}
const humanLabel=k=>String(k||'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()).replace(/\bApi\b/g,'API').replace(/\bId\b/g,'ID').replace(/\bUrl\b/g,'URL').replace(/\bHttp\b/g,'HTTP');

function renderAny(value){
  if(value===null||value===undefined)return '<span class="muted">—</span>';
  if(typeof value==='string'){return value.length>180?`<pre class="human-pre">${esc(value)}</pre>`:`<span class="human-value">${esc(value)||'<span class="muted">empty</span>'}</span>`}
  if(typeof value==='number'||typeof value==='boolean')return `<span class="human-value">${esc(String(value))}</span>`;
  if(Array.isArray(value))return value.length?`<div class="human-list">${value.map((v,i)=>`<div class="human-item"><div class="tiny muted">${i+1}</div>${renderAny(v)}</div>`).join('')}</div>`:'<div class="empty-human">empty list</div>';
  if(typeof value==='object'){const entries=Object.entries(value);return entries.length?`<div class="human-grid">${entries.map(([k,v])=>`<div>${esc(humanLabel(k))}</div><div>${renderAny(v)}</div>`).join('')}</div>`:'<div class="empty-human">empty object</div>'}
  return `<span class="human-value">${esc(String(value))}</span>`;
}
function traceSecretString(value){
  let text=String(value);
  text=text.replace(/\bBearer\s+[^\s,;]+/gi,'Bearer [redacted]');
  const name='(?:[A-Z0-9_.-]+[-_])?(?:authorization|proxy[-_]authorization|x[-_]api[-_]key|api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|auth[-_]?token|client[-_](?:secret|key)|secret(?:[-_]key)?|password|passwd|credentials?|private[-_]?key|session[-_]?token|cookie|set[-_]cookie|bearer|token)';
  const jsonSecret=new RegExp('(["\\\'])([A-Z0-9_.-]*(?:authorization|proxy[-_]authorization|x[-_]api[-_]key|api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|auth[-_]?token|client[-_](?:secret|key)|secret(?:[-_]key)?|password|passwd|credentials?|private[-_]?key|session[-_]?token|cookie|set[-_]cookie|bearer|token))\\1(\\s*:\\s*)("(?:\\\\.|[^"\\\\])*"|\\\'[^\\\']*\\\'|[^,\\s}\\]]+)','gi');
  text=text.replace(jsonSecret,(_match,quote,key,separator,secret)=>`${quote}${key}${quote}${separator}${secret.startsWith('"')||secret.startsWith("'")?secret[0]+'[redacted]'+secret[0]:'[redacted]'}`);
  const assignmentSecret=new RegExp('((?:^|[^A-Z0-9_.-])'+name+'\\s*=\\s*)("(?:\\\\.|[^"\\\\])*"|\\\'[^\\\']*\\\'|[^\\s,;}]+)','gi');
  text=text.replace(assignmentSecret,(_match,prefix,secret)=>prefix+(secret.startsWith('"')||secret.startsWith("'")?secret[0]+'[redacted]'+secret[0]:'[redacted]'));
  return text;
}
const traceUsageTokenFields=new Set(['inputtokens','outputtokens','prompttokens','completiontokens','totaltokens','cachedtokens','cachetokens','contexttokens','reasoningtokens','savedtokens','tokensaved','tokensaving','avoidedtokens','avoidedcloudtokens','compactoutputtokensavoidedest','usedtokens','estimatedtokens','actualtokens','promptbudgettokens']);
function traceSensitiveKey(key){const normalized=String(key??'').toLowerCase().replace(/[^a-z0-9]/g,'');if(traceUsageTokenFields.has(normalized))return false;return ['authorization','apikey','accesstoken','refreshtoken','idtoken','authtoken','sessiontoken','clientsecret','secret','password','passwd','credential','credentials','privatekey','setcookie','cookie','bearer','token'].some(fragment=>normalized.includes(fragment));}
function traceSensitiveField(key){return traceSensitiveKey(key);}
function traceSanitizeValue(value,seen=new WeakSet()){
  const cycleMarker='<cycle omitted>';
  if(value===null||value===undefined||typeof value==='number'||typeof value==='boolean')return value;
  if(typeof value==='string')return traceSecretString(value);
  if(Array.isArray(value)){
    if(seen.has(value))return cycleMarker;
    seen.add(value);
    const result=value.map(item=>traceSanitizeValue(item,seen));
    seen.delete(value);
    return result;
  }
  if(typeof value==='object'){
    if(seen.has(value))return cycleMarker;
    seen.add(value);
    const result=Object.fromEntries(Object.entries(value).map(([key,item])=>[key,traceSensitiveKey(key)?'[redacted]':traceSanitizeValue(item,seen)]));
    seen.delete(value);
    return result;
  }
  return String(value);
}
function traceRecorded(value){
  if(value===null||value===undefined)return false;
  if(typeof value==='string')return value.trim().length>0;
  if(Array.isArray(value))return value.length>0;
  return typeof value!=='object'||Object.keys(value).length>0;
}
function traceCaptureState(value,explicit=''){
  const hint=String(explicit??'').toLowerCase().replace(/[ -]+/g,'_');
  if(hint.includes('redact')||value==='<redacted>')return 'redacted';
  if(hint.includes('empty')||value==='')return 'empty';
  if(hint.includes('not_captured')||hint.includes('missing')||hint.includes('unavailable'))return 'not_captured';
  if(Array.isArray(value)&&value.length===0)return 'empty';
  if(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===0)return 'empty';
  return traceRecorded(value)?'produced':'not_captured';
}
function traceCaptureStateLabel(state){return ({produced:'Produced',empty:'Empty',not_captured:'Not captured',redacted:'Redacted'})[String(state||'').toLowerCase()]||'Unknown';}
function traceCaptureBadge(state,label='Capture state'){
  const safeState=['produced','empty','not_captured','redacted'].includes(String(state||''))?String(state):'not_captured';
  return `<span class="trace-capture-state ${safeState.replace('_','-')}" data-capture-state="${safeState}">${esc(label)} · ${esc(traceCaptureStateLabel(safeState))}</span>`;
}
function traceTimestampMs(value){
  if(typeof value!=='number'&&typeof value!=='string')return null;
  if(value==='')return null;
  const numeric=Number(value);
  if(Number.isFinite(numeric))return Math.abs(numeric)<100000000000?numeric*1000:numeric;
  const parsed=Date.parse(String(value));
  return Number.isFinite(parsed)?parsed:null;
}
function traceFirstRecorded(events,keys){
  for(const event of events||[]){
    const payload=event?.payload;
    if(!payload||typeof payload!=='object')continue;
    for(const key of keys){if(traceRecorded(payload[key]))return payload[key];}
  }
  return undefined;
}
function traceInlineText(value,limit=180,depth=0){
  if(value===null||value===undefined)return '';
  if(typeof value==='string'){const text=value.trim();return text.length>limit?text.slice(0,Math.max(0,limit-1))+'…':text;}
  if(typeof value==='number'||typeof value==='boolean')return String(value);
  if(depth>5)return 'nested data';
  if(Array.isArray(value))return value.slice(0,8).map(item=>traceInlineText(item,Math.max(32,Math.floor(limit/2)),depth+1)).filter(Boolean).join(', ')||(value.length?'…':'empty list');
  if(typeof value==='object'){
    for(const key of ['text','content','name','path','summary','description','value','id'])if(value[key]!==undefined){const text=traceInlineText(value[key],limit,depth+1);if(text)return text;}
    const parts=Object.entries(value).slice(0,4).map(([key,item])=>{const text=traceInlineText(item,Math.max(32,Math.floor(limit/2)),depth+1);return text?`${humanLabel(key)}: ${text}`:''}).filter(Boolean);
    return parts.join(' · ')||(Object.keys(value).length?'…':'empty object');
  }
  return String(value);
}
function promptText(value){return promptTextDepth(value,0);}
function promptTextDepth(value,depth=0){
  if(typeof value==='string')return value;
  if(depth>8)return 'nested data omitted';
  if(Array.isArray(value))return value.map(item=>promptTextDepth(item,depth+1)).filter(Boolean).join('\n');
  if(value&&typeof value==='object'){
    if(value.text!==undefined)return promptTextDepth(value.text,depth+1);
    if(value.content!==undefined)return promptTextDepth(value.content,depth+1);
    if(value.messages!==undefined)return promptTextDepth(value.messages,depth+1);
    return Object.entries(value).slice(0,40).map(([key,item])=>`${String(key).replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}: ${promptTextDepth(item,depth+1)}`).join('\n')||'empty object';
  }
  return value==null?'':String(value);
}
function promptBlock(text,limit=420){
  const source=String(text||''),empty='<span class="muted">empty</span>';
  if(source.length<=limit)return `<pre class="prompt-pre">${esc(source)||empty}</pre>`;
  const preview=source.slice(0,limit).trimEnd();
  return `<pre class="prompt-pre">${esc(preview)}\n…</pre><details class="prompt-context"><summary>Full message · ${n(source.length)} characters</summary><pre class="prompt-pre">${esc(source)}</pre></details>`;
}
function promptBody(text){
  const source=String(text||''),match=source.match(/(?:^|\n)(PRECOMPUTED|PREPROCESSED) (CACHE|INTELLIGENCE):/i);
  if(!match)return promptBlock(source);
  const split=match.index+(match[0].startsWith('\n')?1:0),main=source.slice(0,split).trim(),cache=source.slice(split).trim();
  return `${promptBlock(main)}<details class="prompt-context"><summary>Context cache · ${n(cache.length)} characters</summary><pre class="prompt-pre">${esc(cache)}</pre></details>`;
}
function humanSection(title,value){return `<section class="human-section"><h3>${esc(title)}</h3>${renderAny(value)}</section>`}
function rawFallback(obj){let raw='';try{raw=JSON.stringify(obj,null,2)}catch(e){raw=String(e)}return `<details class="raw-json"><summary>Raw JSON (fallback)</summary><pre>${esc(raw)}</pre></details>`}
function toggleTraceStep(button){const step=button.closest('.trace-step');if(!step)return;const key=String(step.dataset.traceStep||'');const open=!step.classList.contains('open');step.classList.toggle('open',open);button.setAttribute('aria-expanded',String(open));if(open)traceOpenSteps.add(key);else traceOpenSteps.delete(key)}
const traceInputFields=new Set(['input','input_text','input_data','user_input','arguments','args','prompt','messages','query','query_params','request','request_data','request_body','request_payload','body','form_data','headers','parameters','payload','method','path','url','endpoint']);
const traceOutputFields=new Set(['output','output_text','output_data','generated_text','response_text','response_body','result','result_data','response','content','text','answer','completion','stdout','stderr','return_value','items']);
const traceProcessFields=new Set(['state','status','stage','phase','progress','progress_percent','percent','step','step_index','current_step','total_steps','completed_steps','attempt','attempts','attempt_number','max_attempts','retry_count','retry_delay_ms','duration','duration_ms','duration_ns','elapsed','elapsed_ms','queue_time_ms','queue_wait_ms','started_at','finished_at','error','error_type','error_message','exception','failure','retry_after','delivery','background','chunks','truncated','status_code']);
function traceEventTitle(type){
 const titles={model_request:'Model input',thinking:'Thinking / reasoning',output_stream:'Model output',output_delta:'Model output chunk',tool_call:'Tool call',tool_result:'Tool result',cache_decision:'Cache decision',request_received:'Request received',handler_started:'Handler started',async_job_submitted:'Async job submitted',scheduled:'Scheduled',running:'Running',retry:'Retry',trace_truncated:'Trace truncated',completed:'Completed',complete:'Completed',done:'Completed',success:'Completed',succeeded:'Completed',failed:'Failed',error:'Error',cancelled:'Cancelled',canceled:'Cancelled',interrupted:'Interrupted',request_completed:'Request completed',request_failed:'Request failed'};
  return Object.prototype.hasOwnProperty.call(titles,type)?titles[type]:humanLabel(type||'Event');
}
function traceEventSummary(type,p){
  if(type==='model_request')return `Request to ${traceInlineText(p.model??p.provider??'model')}`;
  if(type==='tool_call')return `Calling ${traceInlineText(p.name??p.tool??'tool')}`;
  if(type==='tool_result')return p.isError||p.is_error||p.success===false||p.error?'Tool returned an error':'Tool returned a result';
  if(type==='cache_decision')return `${p.cache_hit?'Cache hit':'Cache miss'} · ${traceInlineText(p.cache_layer||'unknown layer')} · ${traceInlineText(p.semantic_miss_reason||p.decision||'reason unavailable')}`;
  if(type==='output_stream')return `${n(p.chunks||0)} output chunks${p.truncated?' · truncated':''}`;
  if(type==='output_delta')return 'Output content received';
  if(type==='thinking')return 'Thinking content received';
  if(type==='scheduled')return `Queued${p.model?` · ${traceInlineText(p.model)}`:''}`;
  if(type==='running')return `Started${p.action?` · ${traceInlineText(p.action)}`:''}`;
  if(type==='retry')return `Retry${p.attempts?` · attempt ${traceInlineText(p.attempts)}`:''}`;
  if(type==='request_received')return `${traceInlineText(p.method||'Request')}${p.path?` · ${traceInlineText(p.path)}`:''}`;
  if(type==='handler_started')return `Processing${p.action?` · ${traceInlineText(p.action)}`:''}`;
  if(type==='async_job_submitted')return 'Background job submitted';
  if(type==='trace_truncated')return 'Some trace data was omitted';
  if(/^(complete|completed|done|success|succeeded|finished)$/i.test(type))return 'Operation completed';
  if(/^(failed|error|request_failed)$/i.test(type))return traceInlineText(p.error??p.error_message??p.message??'Operation failed');
  for(const key of ['summary','message','action','name','tool','path','model','job_id','request_id']){
    const value=p[key];if((typeof value==='string'&&value.trim())||typeof value==='number')return String(value).slice(0,160);
  }
  return `${traceEventTitle(type)} event`;
}
function traceEventStatus(type,p,result){
  const r=result||{},raw=traceInlineText(p.state??p.status??r.state??r.status??'').trim(),eventState=`${type} ${raw}`;
  if(/cancel|interrupt/i.test(eventState))return {label:raw||traceEventTitle(type),tone:'warn'};
  if(/^(complete|completed|done|success|succeeded|finished|request_completed)$/i.test(type))return {label:'Completed',tone:'ok'};
  const failed=Boolean(p.error||p.error_message||p.exception||p.failure||r.error||r.error_message||r.exception||p.is_error||p.isError||r.is_error||r.isError||p.success===false||r.success===false||/fail|error|exception/i.test(eventState));
  if(failed)return {label:raw||'Error',tone:'bad'};
  if(raw)return {label:humanLabel(raw),tone:/queued|pending|running|retry|scheduled|progress/i.test(raw)?'warn':'ok'};
  if(p.success===true||r.success===true)return {label:'Success',tone:'ok'};
  if(/queued|pending|running|retry|scheduled|submitted|started|progress/i.test(type))return {label:traceEventTitle(type),tone:'warn'};
  if(type==='tool_call'&&result)return {label:'Completed',tone:'ok'};
  if(type==='tool_call'&&!result)return {label:'Waiting',tone:'warn'};
  return null;
}
function traceEventGroups(payload,excluded){
  const groups={input:{},output:{},process:{},metadata:{}};const skip=new Set(excluded||[]);
  Object.entries(payload&&typeof payload==='object'?payload:{}).forEach(([key,value])=>{
    if(skip.has(key))return;const normalized=key.toLowerCase();
    const group=traceInputFields.has(normalized)?'input':traceOutputFields.has(normalized)?'output':traceProcessFields.has(normalized)?'process':'metadata';
    groups[group][key]=value;
  });
  return groups;
}
function traceProgressInfo(payload){
  const p=payload&&typeof payload==='object'?payload:{};
  const number=value=>{if(value===null||value===undefined||typeof value==='boolean')return null;const raw=typeof value==='string'?value.trim().replace(/%$/,'').trim():value;if(raw==='')return null;const parsed=Number(raw);return Number.isFinite(parsed)?parsed:null};
  const ratio=(current,total)=>{const c=number(current),t=number(total);return c!==null&&t!==null&&c>=0&&t>0?{percent:Math.max(0,Math.min(100,c/t*100)),label:`${c} / ${t} steps`}:null};
  const nested=p.progress&&typeof p.progress==='object'?p.progress:null;
  if(nested){const steps=ratio(nested.current??nested.completed??nested.value,nested.total);if(steps)return steps;for(const key of ['percent','percentage']){const value=number(nested[key]);if(value!==null){const bounded=Math.max(0,Math.min(100,value));return {percent:bounded,label:`${Math.round(bounded)}%`}}}}
  for(const key of ['progress_percent','percent','progress']){
    const value=number(p[key]);if(value===null)continue;const percent=key==='progress'&&value>=0&&value<=1?value*100:value,bounded=Math.max(0,Math.min(100,percent));return {percent:bounded,label:`${Math.round(bounded)}%`};
  }
  return ratio(p.current_step??p.completed_steps??p.step_index??p.step,p.total_steps);
}
function traceProgressVisual(payload){
  const progress=traceProgressInfo(payload);if(!progress)return '';
  const width=Math.round(progress.percent*10)/10,label=String(progress.label||`${Math.round(width)}%`);
  return `<div class="trace-progress" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${width}"><span class="trace-progress-track"><span class="trace-progress-fill" style="width:${width}%"></span></span><span class="trace-progress-label">${esc(label)}</span></div>`;
}
function traceEventChips(metadata,process){
  const values={...(metadata||{}),...(process||{})},priority=['action','model','agent','attempts','attempt','attempt_number','max_attempts','retry_count','retry_delay_ms','duration_ms','duration_ns','elapsed_ms','elapsed','queue_wait_ms','queue_time_ms','status_code','current_step','total_steps','stage','phase','provider','job_id','request_id','delivery','background'];
  return Object.entries(values).filter(([key,value])=>!['current_step','completed_steps','step_index','total_steps','progress','progress_percent','percent','percentage'].includes(key.toLowerCase())&&(value===null||['string','number','boolean'].includes(typeof value))).sort(([a],[b])=>{const ai=priority.indexOf(a.toLowerCase()),bi=priority.indexOf(b.toLowerCase());return (ai<0?priority.length:ai)-(bi<0?priority.length:bi)}).slice(0,5).map(([key,value])=>`<span class="trace-event-chip"><strong>${esc(humanLabel(key))}:</strong> ${esc(value===null?'null':String(value).slice(0,72))}</span>`).join('');
}
function traceEventSection(title,content,kind){return `<section class="trace-event-section" data-kind="${kind}"><span class="trace-event-label">${esc(title)}</span><div class="trace-event-value">${content}</div></section>`}
function traceEventBody(event,events,index){
  const type=String(event?.event_type||'event'),budget=traceRenderBudget(8000),rawPayload=event?.payload,p=traceSanitizeValue(rawPayload&&typeof rawPayload==='object'&&!Array.isArray(rawPayload)?rawPayload:{value:rawPayload??'<malformed payload>'});let pairedResult=null,input='',output='',statusResult=null,groups;
  if(type==='tool_result'){
    const callId=p.call_id||'';
    if(callId&&events.slice(0,index).some(x=>x.event_type==='tool_call'&&((x.payload||{}).call_id||'')===callId))return '';
  }
  if(type==='model_request'){
    const prompt=p.prompt??p.messages??p.content??p.input??p.request??'';input=prompt?renderAny(prompt):'<span class="trace-empty-output">No input captured for this event</span>';groups=traceEventGroups(p,['prompt','messages','content','system','input','request']);
  }else if(type==='tool_call'){
    const callId=p.call_id||'';pairedResult=events.slice(index+1).find(x=>x.event_type==='tool_result'&&(!callId||((x.payload||{}).call_id||'')===callId));
    input=renderAny(p.arguments??p.input??{});output=pairedResult?renderAny(pairedResult.payload||{}):'';
    statusResult=pairedResult?.payload||null;
    groups=traceEventGroups(p,['arguments','input']);
  }else if(type==='tool_result'){
    groups=traceEventGroups(p);if(!Object.keys(groups.output).length)groups.output={result:p};
  }else if(type==='output_stream'){
    output=traceOutputValueMarkup(p.values?.length?p.values:p.text??'',budget,8000);groups=traceEventGroups(p,['text','values']);
  }else if(type==='output_delta'){
    output=traceOutputValueMarkup(p.text??'',budget,8000);groups=traceEventGroups(p,['text']);
  }else{
    groups=traceEventGroups(p);input=Object.keys(groups.input).length?renderAny(groups.input):'';output=Object.keys(groups.output).length?renderAny(groups.output):'';
  }
  const status=traceEventStatus(type,p,statusResult),badge=status?`<span class="trace-event-status ${status.tone}">${esc(humanLabel(status.label))}</span>`:'';
  const metadata=groups.metadata||{},chips=traceEventChips(metadata,groups.process),progress=traceProgressVisual(p);
  const summary=`<div class="trace-event-glance"><strong class="trace-event-summary">${esc(traceEventSummary(type,p))}</strong>${badge}${chips}</div>${progress}`;
  const details={...metadata,...(groups.process||{})},outputContent=output||(Object.keys(groups.output).length?renderAny(groups.output):'<span class="trace-empty-output">No output captured for this event</span>');
  const inputContent=input||(Object.keys(groups.input).length?renderAny(groups.input):'');
  const detailsPanel=Object.keys(details).length?`<details class="trace-event-meta"><summary>More details · ${Object.keys(details).length} fields</summary>${renderAny(details)}</details>`:'';
  return `<div class="trace-event-content">${summary}${traceEventSection('Output',outputContent,'output')}${inputContent?traceEventSection('Input',inputContent,'input'):''}${detailsPanel}</div>`;
}
