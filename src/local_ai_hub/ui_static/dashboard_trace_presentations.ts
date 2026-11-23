// @ts-nocheck
function renderRagSearchPresentation(model){
  const budget=traceRenderBudget(),retrieval=traceSanitizeValue(tracePresentationPayload(model,'retrieval')||{}),query=tracePresentationPick(retrieval,['query','search_query','term'],''),answer=tracePresentationPick(retrieval,['answer','response','summary'],''),rawResults=retrieval.results??retrieval.hits??retrieval.sources,malformed=rawResults!==undefined&&!Array.isArray(rawResults),results=Array.isArray(rawResults)&&rawResults.length?rawResults:Array.isArray(retrieval.sources)?retrieval.sources:[],ranked=results.map((item,index)=>({item,index,score:Number(item?.score??item?.relevance??item?.similarity)})).sort((a,b)=>Number.isFinite(a.score)&&Number.isFinite(b.score)?b.score-a.score||a.index-b.index:Number.isFinite(a.score)?-1:Number.isFinite(b.score)?1:a.index-b.index);
  const truncation=retrieval.truncated??retrieval.truncation;
  let rows='',shown=0;
   for(const entry of ranked){
    const item=entry.item,source=item&&typeof item==='object'?item:{},title=traceSearchText(source.title??source.name??source.path??source.file??source.filename??item,240)||'Result',provider=traceSearchText(source.provider??source.source??'',120),snippet=traceSearchText(source.snippet??source.text??source.content??source.summary??source.description??item,700),path=traceSearchText(source.path??source.file??source.filename??'',400),start=source.start_line??source.startLine,end=source.end_line??source.endLine,location=start!==undefined?path+' · line '+traceInlineText(start)+(end!==undefined?'–'+traceInlineText(end):''):path;
    const payload=traceAgentLoopPrimaryValue(item),extra=(Number.isFinite(entry.score)?traceSummaryCard('score',entry.score,budget):'')+(provider?traceSummaryCard('provider',provider,budget):'')+(location?traceSummaryCard('path',location,budget):'')+traceCodeBlock('Full result payload',payload,budget,{limit:1800});
    const row='<article class="trace-search-result-row"><div class="trace-search-rank">'+(shown+1)+'</div><div class="trace-search-result-main"><strong>'+esc(title)+'</strong>'+(provider?'<span class="tiny">'+esc(provider)+'</span>':'')+(snippet?'<div class="trace-search-snippet">'+esc(snippet)+'</div>':'<div class="trace-primary-empty">No snippet captured</div>')+'<details class="trace-secondary-details trace-rag-result-details" data-trace-key="'+traceRagResultKey(item)+'" data-trace-collapsible><summary>More result details</summary><div class="trace-optional-body">'+extra+'</div></details></div></article>';
     rows+=row;shown++;
   }
   const notice='';
  const primary='<section class="trace-primary trace-search-presentation"><div class="trace-primary-head"><h2>Search</h2><span class="tiny">'+results.length+(results.length===1?' result':' results')+'</span></div>'+(traceSummaryCard('Query',query,budget,{key:'query',limit:1800})||'<div class="trace-primary-empty">No query captured</div>')+(traceSummaryCard('answer',answer,budget,{limit:3500})||'<div class="trace-primary-empty">No answer captured</div>')+'<div class="trace-summary-card trace-search-count"><h3>result count</h3>'+results.length+'</div>'+(malformed?'<div class="trace-primary-empty">Malformed results · Results payload must be an array</div>':'')+notice+'<div class="trace-list-card trace-search-results"><h3>ranked results</h3>'+(rows||'<div class="trace-primary-empty">No results found</div>')+'</div></section>';
  const metadata=[['project',traceProjectLabel(model)],['root',retrieval.root],['mode',retrieval.mode],['provider',retrieval.provider],['limit',retrieval.top_k??retrieval.limit]].filter(([,value])=>traceMeaningfulValue(value)).map(([label,value])=>traceSummaryCard(label,value,budget,{limit:450})).join('');
  return traceFinalizeMarkup(primary+traceSecondaryDetails('Search metadata',metadata),budget);
}
function renderAsyncJobPresentation(model){
  const budget=traceRenderBudget(),safeModel=traceSanitizeValue(model||{}),lifecycle=safeModel.lifecycle||{},rawAsyncJob=safeModel.presentation&&typeof safeModel.presentation==='object'&&!Array.isArray(safeModel.presentation)?safeModel.presentation.asyncJob:undefined,malformedAsyncJob=rawAsyncJob!==undefined&&(!rawAsyncJob||typeof rawAsyncJob!=='object'||Array.isArray(rawAsyncJob)),payload=malformedAsyncJob?{}:traceSanitizeValue(tracePresentationPayload(safeModel,'asyncJob'));
  const stateText=malformedAsyncJob?'malformed':traceInlineText(payload.status??lifecycle.state??lifecycle.status??'').trim().toLowerCase().replace(/\s+/g,'_'),terminalState=/^(complete|completed|success|succeeded|failed|error|cancelled|canceled|interrupted)$/.test(stateText),terminal=lifecycle.terminal===true||(lifecycle.terminal!==false&&terminalState),liveState=malformedAsyncJob?'malformed':terminal?'finished':(/^(queued|pending|waiting|running|active|processing|live|streaming)$/.test(stateText)||lifecycle.terminal===false?'live / incomplete':'incomplete');
  const jobType=malformedAsyncJob?'malformed async job':tracePresentationPick(payload,['job_type','jobType','type','kind'],safeModel.identity?.action||safeModel.session?.kind||'background job'),status=malformedAsyncJob?'malformed':tracePresentationPick(payload,['status','state'],lifecycle.state??''),progress=tracePresentationPick(payload,['progress','progress_percent','percent','completed','current','total'],lifecycle.progress??''),queueWait=tracePresentationPick(payload,['queue_wait_ms','queue_wait','queue_time_ms'],''),retries=tracePresentationPick(payload,['retries','retry_count','attempts'],''),result=tracePresentationPick(payload,['result','output'],safeModel.output),error=tracePresentationPick(payload,['error'],safeModel.errors);
  const workerInput=tracePresentationPick(payload,['worker_input'],''),workerOutput=tracePresentationPick(payload,['worker_output'],''),correlations=safeModel.correlations&&typeof safeModel.correlations==='object'?safeModel.correlations:'',secondary=[workerInput?traceSecondaryDetails('Worker input',tracePresentationField('worker input',workerInput,'',traceRenderBudget(),{mode:'technical'})):'',workerOutput?traceSecondaryDetails('Worker output',tracePresentationField('worker output',workerOutput,'',traceRenderBudget(),{mode:'technical'})):'',Object.keys(correlations||{}).length?traceSecondaryDetails('Correlations',tracePresentationField('correlations',correlations,'',traceRenderBudget(),{mode:'technical'})):'',Array.isArray(safeModel.events)&&safeModel.events.length?traceSecondaryDetails('Event timeline',traceCodexTimeline(safeModel,'Async job',traceRenderBudget(),true,safeModel.events)):''].join('');
  const left=[traceMeaningfulValue(jobType)?traceSummaryCard('job type',jobType,budget,{bounded:true}):'',traceMeaningfulValue(liveState)?traceSummaryCard('capture state',liveState,budget,{bounded:true}):'',traceMeaningfulValue(status)?traceSummaryCard('status',status,budget,{bounded:true}):'',traceMeaningfulValue(lifecycle.state)&&String(lifecycle.state)!==String(status)?traceSummaryCard('lifecycle',lifecycle.state,budget,{bounded:true}):'',traceMeaningfulValue(progress)?traceSummaryCard('progress',progress,budget,{bounded:true}):'',traceMeaningfulValue(queueWait)?traceSummaryCard('queue wait',queueWait,budget,{bounded:true}):'',traceMeaningfulValue(retries)?traceSummaryCard('retries',retries,budget,{bounded:true}):''];
  const right=[traceMeaningfulValue(result)?traceCodeBlock('result',result,budget,{bounded:true}):'',traceMeaningfulValue(error)?traceSummaryCard('error',error,budget,{bounded:true}):''];
  return tracePresentationColumns('Async job',left,right,budget,'','Request details','Result details',true)+secondary;
}
function renderRequestResponsePresentation(model){
  const budget=traceRenderBudget(),safeModel=traceSanitizeValue(model||{}),timing=safeModel.timing||{};
  const request=safeModel.session?.request&&typeof safeModel.session.request==='object'?safeModel.session.request:{},method=request.method??safeModel.identity?.method??safeModel.session?.method,path=request.path??safeModel.identity?.path??safeModel.session?.path,action=safeModel.identity?.action??safeModel.session?.action,reqVal=traceRecorded(method)||traceRecorded(path)||traceRecorded(action)?{method,path,action}:undefined,statusVal=safeModel.lifecycle?.status_code??safeModel.session?.status_code??safeModel.session?.state??safeModel.lifecycle?.state,duration=safeModel.timing?.duration_ms??safeModel.timing?.elapsed_ms??safeModel.session?.duration_ms??safeModel.session?.elapsed_ms,requestBody=safeModel.input??request.body??request.payload??request.data,responseBody=safeModel.response??safeModel.output??safeModel.session?.response??safeModel.session?.output,outputBody=safeModel.response&&traceRecorded(safeModel.output)?safeModel.output:undefined,error=safeModel.errors,hasCore=traceRecorded(reqVal)||traceRecorded(requestBody)||traceRecorded(responseBody)||traceRecorded(error)||traceRecorded(safeModel.lifecycle?.status_code)||traceRecorded(safeModel.session?.state)||traceRecorded(duration);
  if(!hasCore)return '';
  const technical=[request.headers?traceSecondaryDetails('Headers',tracePresentationField('headers',request.headers,'',traceRenderBudget(),{mode:'technical'})):'',safeModel.actor&&traceMeaningfulValue({agent:safeModel.actor.agent,owner:safeModel.actor.owner})?traceSecondaryDetails('Actor',tracePresentationField('actor',{agent:safeModel.actor.agent,owner:safeModel.actor.owner},'',traceRenderBudget(),{mode:'technical'})):'',safeModel.correlations&&typeof safeModel.correlations==='object'&&Object.keys(safeModel.correlations).length?traceSecondaryDetails('Correlations',tracePresentationField('correlations',safeModel.correlations,'',traceRenderBudget(),{mode:'technical'})):'',traceRecorded(safeModel.retainedBytes)?traceSecondaryDetails('Retained bytes',tracePresentationField('bytes',safeModel.retainedBytes,'',traceRenderBudget(),{mode:'technical'})):'',traceMeaningfulValue(timing)?traceSecondaryDetails('Lifecycle timing',tracePresentationField('timing',timing,'',traceRenderBudget(),{mode:'technical'})):''].join('');
  const left=[
    traceMeaningfulValue(reqVal)?traceSummaryCard('request',reqVal,budget,{bounded:true}):'',
    traceMeaningfulValue(requestBody)?traceSummaryCard('request body',requestBody,budget,{bounded:true}):'',
    traceRecorded(duration)?traceSummaryCard('duration',duration,budget,{bounded:true}):''
  ];
  const right=[
     traceMeaningfulValue(responseBody)?(typeof responseBody==='string'?traceCodeBlock('response',responseBody,budget,{key:'response',bounded:true}):traceSummaryCard('response',responseBody,budget,{full:true,bounded:true})):'',
    traceMeaningfulValue(outputBody)?traceCodeBlock('output',outputBody,budget,{bounded:true}):'',
    traceMeaningfulValue(statusVal)?traceSummaryCard('status',statusVal,budget,{bounded:true}):'',
    traceMeaningfulValue(error)?traceSummaryCard('error',error,budget,{bounded:true}):''
  ];
  return tracePresentationColumns('Request / response',left,right,budget,'','Request details','Result details',true)+technical;
}
function traceUnmappedPresentation(model,kind){
  if(kind==='model_chat')return tracePresentationField('error',model.errors,'',traceRenderBudget(),{mode:'primary',limit:1800});
  const key={command:'command',review:'review',repo_intelligence:'repoOperation',rag_search:'retrieval',async_job:'asyncJob'}[kind];if(!key)return '';
  const payload=tracePresentationPayload(model,key),known=new Set(Object.keys(payload)),budget=traceRenderBudget(),cards=[];
  const consumed=kind==='review'?(payload.findings??payload.text??model.output):kind==='repo_intelligence'?tracePresentationPick(payload,['result','output','response','text','result_context'],model.output):kind==='async_job'?tracePresentationPick(payload,['result','output'],model.output):undefined;
  for(const [label,source] of [['input',model.input],['output',model.output],['response',model.response],['error',kind==='rag_search'?model.errors:undefined]]){
    if(!traceRecorded(source))continue;
    const scalar=typeof source!=='object'||Array.isArray(source);
    if(scalar&&(label==='output'||label==='response')&&traceMeaningfulValue(consumed)&&JSON.stringify(source)===JSON.stringify(consumed))continue;
    const extra=scalar?source:Object.fromEntries(Object.entries(source).filter(([field])=>!known.has(field)));
    if(traceMeaningfulValue(extra))cards.push(tracePresentationField('Captured '+label,extra,'',budget,{mode:'primary',limit:1800}));
  }
  return cards.length?'<section class="trace-primary trace-captured-fallback"><h3>Additional captured content</h3>'+traceMarkupItems(cards,6500)+'</section>':'';
}
function tracePresentationAttention(model,kind){
  const safe=traceSanitizeValue(model||{}),items=[];
  if(kind==='model_chat'){const output=safe.output??safe.presentation?.modelOutput,explicit=(safe.finalResponseStatus??safe.presentation?.finalResponseStatus??safe.session?.final_response_status??safe.captureStates?.output??''),state=traceCaptureState(output,explicit);if(state==='empty')items.push('Final response was empty');else if(state==='not_captured')items.push('Final response not captured');}
  if(kind==='command'){const command=tracePresentationPayload(safe,'command')||{};if(command.success===false||traceRecorded(command.error))items.push(command.error||'Command failed');}
  if(kind==='review'&&safe.presentation?.review?.status&&/failed|blocked|changes requested/i.test(String(safe.presentation.review.status)))items.push(safe.presentation.review.status);
  if(kind==='async_job'){const job=tracePresentationPayload(safe,'asyncJob')||{};if(traceRecorded(job.error))items.push(job.error);}
  if(kind==='request_response'&&traceRecorded(safe.errors))items.push(safe.errors);
  return items;
}
function traceWrapPresentationRenderer(renderer,title,subtitle,kind,model){const budget=traceRenderBudget(),primary=renderer(model)+traceUnmappedPresentation(model,kind),secondary=tracePresentationField('Capture state',model?.captureStates||{},'',budget,{mode:'technical'});return tracePresentationShell(title,subtitle,primary,secondary,tracePresentationAttention(model,kind));}
const traceBaseRenderModelChatPresentation=renderModelChatPresentation,traceBaseRenderAgentLoopPresentation=renderAgentLoopPresentation,traceBaseRenderCommandPresentation=renderCommandPresentation,traceBaseRenderReviewPresentation=renderReviewPresentation,traceBaseRenderRepoIntelligencePresentation=renderRepoIntelligencePresentation,traceBaseRenderRagSearchPresentation=renderRagSearchPresentation,traceBaseRenderAsyncJobPresentation=renderAsyncJobPresentation,traceBaseRenderRequestResponsePresentation=renderRequestResponsePresentation;
renderModelChatPresentation=model=>traceWrapPresentationRenderer(traceBaseRenderModelChatPresentation,'Model chat','what the model received and returned','model_chat',model);
renderAgentLoopPresentation=model=>traceWrapPresentationRenderer(traceBaseRenderAgentLoopPresentation,'Agent loop','tool execution','agent_loop',model);
renderCommandPresentation=model=>traceWrapPresentationRenderer(traceBaseRenderCommandPresentation,'Command','command input and result','command',model);
renderReviewPresentation=model=>traceWrapPresentationRenderer(traceBaseRenderReviewPresentation,'Review','request findings and recommendation','review',model);
renderRepoIntelligencePresentation=model=>traceWrapPresentationRenderer(traceBaseRenderRepoIntelligencePresentation,'Repository intelligence','repository operation result','repo_intelligence',model);
renderRagSearchPresentation=model=>traceWrapPresentationRenderer(traceBaseRenderRagSearchPresentation,'Search','retrieval results','rag_search',model);
renderAsyncJobPresentation=model=>traceWrapPresentationRenderer(traceBaseRenderAsyncJobPresentation,'Async job','background worker lifecycle','async_job',model);
renderRequestResponsePresentation=model=>traceWrapPresentationRenderer(traceBaseRenderRequestResponsePresentation,'Request / response','request outcome','request_response',model);
function renderTracePresentation(model){const specializedKinds=['agent_loop','model_chat','command','review','repo_intelligence','rag_search','async_job','request_response'],requested=String(model.presentation?.kind||tracePresentationKind(model)||'request_response').toLowerCase();if(!specializedKinds.includes(requested)){const budget=traceRenderBudget(),inputOutput=renderTraceInputOutputPresentation(model),error=tracePresentationField('error',model.errors,'No error captured',budget,{mode:'primary'});return inputOutput+(error?tracePresentationColumns('Captured error',[error],[],budget,'','Captured error','',true):'');}const inputOutput='',kind=requested;let specialized='';if(kind==='agent_loop')specialized=renderAgentLoopPresentation(model);else if(kind==='model_chat')specialized=renderModelChatPresentation(model);else if(kind==='command')specialized=renderCommandPresentation(model);else if(kind==='review')specialized=renderReviewPresentation(model);else if(kind==='repo_intelligence')specialized=renderRepoIntelligencePresentation(model);else if(kind==='rag_search')specialized=renderRagSearchPresentation(model);else if(kind==='async_job')specialized=renderAsyncJobPresentation(model);else if(kind==='request_response')specialized=renderRequestResponsePresentation(model);return inputOutput+specialized;}
function renderTracePresentation(model){const kind=model.presentation?.kind||tracePresentationKind(model),specializedKinds=['agent_loop','model_chat','command','review','vision_review','repo_intelligence','rag_search','async_job','request_response'],inputOutput=specializedKinds.includes(kind)?'':renderTraceInputOutputPresentation(model);if(!specializedKinds.includes(kind)){const budget=traceRenderBudget(),error=tracePresentationField('error',model.errors,'No error captured',budget,{mode:'primary'});return inputOutput+(error?tracePresentationColumns('Captured error',[error],[],budget,'','Captured error','',true):'');}let specialized='';if(kind==='agent_loop')specialized=renderAgentLoopPresentation(model);else if(kind==='model_chat')specialized=renderModelChatPresentation(model);else if(kind==='command')specialized=renderCommandPresentation(model);else if(kind==='vision_review')specialized=renderVisionReviewPresentation(model);else if(kind==='review')specialized=renderReviewPresentation(model);else if(kind==='repo_intelligence')specialized=renderRepoIntelligencePresentation(model);else if(kind==='rag_search')specialized=renderRagSearchPresentation(model);else if(kind==='async_job')specialized=renderAsyncJobPresentation(model);else if(kind==='request_response')specialized=renderRequestResponsePresentation(model);return inputOutput+specialized;}
function traceDisplayModel(detail){
  const rawSession=detail?.session||{},rawEvents=Array.isArray(detail?.events)?detail.events:[];
  const rawEventProjection=traceBoundedEvents(rawEvents),session=traceSanitizeValue(traceDisplaySession(rawSession)),events=rawEventProjection.events;
  const requestReceived=events.find(event=>event?.event_type==='request_received');
  const requestPayload=requestReceived?.payload&&typeof requestReceived.payload==='object'?requestReceived.payload:{};
  const redactedTraceId=String(rawSession.trace_id||'');
  const effectivePayload=rawSession.effective_payload;
  const modelInput=traceFirstRecorded(rawEvents,['prompt','messages','content','input','arguments','args','query']);
  const requestInput=traceFirstRecorded(rawEvents,['request','request_body','request_payload','body','form_data','payload']);
  const input=traceRecorded(modelInput)?modelInput:traceRecorded(effectivePayload)?effectivePayload:traceRecorded(session.request)?session.request:requestInput;
  const responseData=rawSession.response&&typeof rawSession.response==='object'?rawSession.response:{},responseText=responseData.text??responseData.response??responseData.message?.content??(typeof rawSession.response==='string'?rawSession.response:''),output=traceRecorded(rawSession.output)?rawSession.output:traceRecorded(responseText)?responseText:traceFirstRecorded(rawEvents,['output','output_text','generated_text','text','content','result','response','response_body','answer','completion']);
  const thinking=traceRecorded(rawSession.thinking)?rawSession.thinking:traceRecorded(responseData.thinking)?responseData.thinking:rawEvents.filter(event=>['thinking','assistant_thinking','reasoning','assistant_reasoning'].includes(String(event?.event_type||'').toLowerCase())).map(event=>event?.payload?.text??event?.payload?.thinking??event?.payload?.content??'').join('');
  const finalResponseStatus=String(session.final_response_status??responseData.final_response_status??'');
  const response=traceRecorded(rawSession.response)?rawSession.response:traceFirstRecorded(rawEvents,['response','response_body','result']);
  const eventErrors=events.filter(event=>traceRecorded(event?.payload?.error)||traceRecorded(event?.payload?.error_message)||event?.payload?.success===false).map(event=>event.payload);
  const errors=traceRecorded(session.error)?[session.error,...eventErrors]:eventErrors;
  const modelExecutions=events.filter(event=>event?.event_type==='model_request'||event?.event_type==='output_stream'||event?.event_type==='output_delta');
  const toolCalls=events.filter(event=>event?.event_type==='tool_call'||event?.event_type==='tool_result');
  const createdAtMs=traceTimestampMs(session.created_at),finishedAtMs=traceTimestampMs(session.finished_at),storedDurationMs=Number(session.duration_ms),hasStoredDuration=session.duration_ms!==null&&session.duration_ms!==undefined&&session.duration_ms!==''&&Number.isFinite(storedDurationMs),derivedDurationMs=createdAtMs!==null&&finishedAtMs!==null&&finishedAtMs>=createdAtMs?finishedAtMs-createdAtMs:undefined,durationMs=hasStoredDuration?Math.max(0,storedDurationMs):derivedDurationMs;
  const timing={created_at:session.created_at,updated_at:session.updated_at,finished_at:session.finished_at,duration_ms:durationMs,elapsed_ms:session.elapsed_ms??durationMs};
  const identity={trace_id:redactedTraceId||session.trace_id,kind:session.kind,action:session.action,source:session.source,method:session.method||requestPayload.method,path:session.path||requestPayload.path||requestPayload.url||requestPayload.endpoint,request_id:session.request_id||requestPayload.request_id};
  const lifecycle={state:traceDisplayState(session),terminal:Boolean(detail?.terminal),status_code:session.status_code};
  const actor={agent:session.agent,owner:session.owner};
  const correlations={request_id:session.request_id||requestPayload.request_id,async_job_id:session.async_job_id||requestPayload.async_job_id,scheduler_job_id:session.scheduler_job_id||requestPayload.scheduler_job_id,job_id:session.job_id||requestPayload.job_id};
  const retainedBytes=Number(session.text_bytes||session.retained_bytes||0);
  const availability={
    input:traceRecorded(input),output:traceRecorded(output),thinking:traceRecorded(thinking),response:traceRecorded(response),errors:errors.length>0,
    events:events.length>0,modelExecutions:modelExecutions.length>0,toolCalls:toolCalls.length>0,
  };
  const captureStates={input:traceCaptureState(input),output:traceCaptureState(output,finalResponseStatus),thinking:traceCaptureState(thinking),response:traceCaptureState(response),errors:traceCaptureState(errors),events:traceCaptureState(events),modelExecutions:traceCaptureState(modelExecutions),toolCalls:traceCaptureState(toolCalls)};
  const eventsTotal=Math.max(Number(detail?.events_total||detail?.eventsTotal||0),rawEventProjection.eventsTotal),eventsTruncated=rawEventProjection.eventsTruncated,project=traceProjectLabel({project:rawSession.project,workspace:rawSession.workspace,request:session.request,effective_payload:effectivePayload,root:rawSession.root})||traceProjectLabel(input),model={identity,lifecycle,timing,actor,correlations,retainedBytes,input,output,thinking,response,finalResponseStatus,errors,events,eventsTotal,eventsTruncated,modelExecutions,toolCalls,effectivePayload,availability,captureStates,session,project};
  model.presentation=tracePresentationData(model);
  model.panels=[
    tracePanel('input','Input',()=>humanSection('Input',input),availability.input),
    tracePanel('output','Output',()=>humanSection('Output',output),availability.output),
    tracePanel('thinking','Thinking',()=>humanSection('Thinking / reasoning',thinking),availability.thinking),
    tracePanel('response','Response',()=>humanSection('Response',response),availability.response),
    tracePanel('errors','Errors',()=>humanSection('Errors',errors),availability.errors),
    tracePanel('timeline','Timeline',()=>traceTimeline(events.slice(-100)),availability.events),
    tracePanel('model','Model execution',()=>traceTimeline(modelExecutions.slice(-100)),availability.modelExecutions),
    tracePanel('agent_context','Agent context',()=>humanSection('Agent context',effectivePayload),traceRecorded(effectivePayload)),
    tracePanel('tools','Tool calls',()=>humanSection('Tool calls',toolCalls.slice(-100)),availability.toolCalls),
    tracePanel('events','Events',()=>traceEventList(events),availability.events),
    tracePanel('raw','Raw',()=>traceRaw(detail),true),
  ];
  return model;
}
function traceAvailability(model,unavailableCopy={}){
  const labels=[['input','Input'],['output','Output'],['thinking','Thinking'],['response','Response'],['errors','Error details'],['events','Events'],['modelExecutions','Model execution'],['toolCalls','Tool calls']];
  return `<section class="human-section"><h3>Trace data availability</h3><div class="human-list">${labels.map(([key,label])=>{const state=model.captureStates?.[key]??(model.availability[key]?'produced':'not_captured');return `<div class="human-item">${traceCaptureBadge(state,label)}${state==='not_captured'?`<span class="muted">${esc(unavailableCopy[key]||traceUnavailable(label))}</span>`:''}</div>`}).join('')}</div></section>`;
}
function traceSummary(model,unavailableCopy){
  const summary={identity:model.identity,lifecycle:model.lifecycle,timing:model.timing,actor:model.actor,correlations:model.correlations,retained_bytes:model.retainedBytes};
  return `<section class="human-section"><h3>Universal request summary</h3>${renderAny(summary)}</section>${traceAvailability(model,unavailableCopy)}`;
}
function traceHumanTitle(model){
  const kind=String(model?.presentation?.kind||'').toLowerCase();
  return ({rag_search:'Search',model_chat:'Model request',agent_loop:'Agent run',command:'Command run',review:'Review',vision_review:'Frontend vision review',repo_intelligence:'Repository lookup',async_job:'Background job',request_response:'Request'}[kind]||'Request');
}
function tracePrimaryInput(value){
  if(value?.capture_status==='metadata_only'&&Object.keys(value).every(key=>['capture_status','field_count'].includes(key)))return undefined;
  const technical=traceTechnicalSettings(value);
  if(value&&typeof value==='object'&&!Array.isArray(value))return Object.fromEntries(Object.entries(value).filter(([key])=>!Object.hasOwn(technical,key)));
  return value;
}
function traceTechnicalSettings(value){
  if(!value||typeof value!=='object'||Array.isArray(value))return {};
  const keys=new Set(['project','project_name','projectname','workspace','workspace_name','workspacename','root','repo_root','repository_root','repository','repo','cwd','working_directory','command_settings','project_settings','settings','config','model','temperature','top_p','max_tokens','max_output_tokens','timeout','retries','provider']);
  return Object.fromEntries(Object.entries(value).filter(([key])=>keys.has(String(key).replace(/([a-z])([A-Z])/g,'$1_$2').toLowerCase())));
}
function traceMainContent(title,field,value){
  const recorded=traceRecorded(value),text=recorded?traceContentText(value):'';
  const content=recorded?`<pre>${esc(text)}</pre>`:'<div class="trace-primary-empty">nezaznamenané</div>';
  const copy=recorded?`<button type="button" class="btn" data-trace-copy="${field}">Copy</button>`:'';
  return `<section class="trace-primary-card ${field}"><div class="trace-primary-card-head"><h2>${title}</h2>${copy}</div>${content}</section>`;
}
function traceContentText(value){
  if(typeof value==='string'){
    const trimmed=value.trim();
    if((trimmed.startsWith('{')&&trimmed.endsWith('}'))||(trimmed.startsWith('[')&&trimmed.endsWith(']'))){
      try{return JSON.stringify(JSON.parse(trimmed),null,2)}catch{}
    }
    return value;
  }
  try{return JSON.stringify(value,null,2)??String(value)}catch{return String(value)}
}
function traceMetricRow(metrics){
  const available=metrics?.available===true,missing='nezaznamenané';
  const numeric=key=>{
    if(!available)return null;
    const raw=metrics[key];
    if(typeof raw==='number')return Number.isFinite(raw)?raw:null;
    if(typeof raw==='string'&&raw.trim()!==''){const parsed=Number(raw);return Number.isFinite(parsed)?parsed:null;}
    return null;
  };
  const value=key=>{const parsed=numeric(key);return parsed===null?missing:parsed.toLocaleString();};
  const rate=numeric('cache_hit_rate'),hitRate=rate===null?missing:`${(rate*100).toFixed(1)}%`;
  return `<div class="trace-metrics" aria-label="Trace metrics" title="Počty použitých a ušetřených tokenů jsou odhady z telemetry."><span>Vstupní tokeny (odhad) · ${value('input_tokens')}</span><span>Výstupní tokeny (odhad) · ${value('output_tokens')}</span><span>Cache zásahy · ${value('cache_hits')}</span><span>Úspěšnost cache · ${hitRate}</span><span>Ušetřené tokeny (odhad) · ${value('avoided_cloud_tokens')}</span></div>`;
}
 function renderTraceDetail(d){
  const body=$('tracePageBody'),existing=body?.querySelector('#traceTechnicalDetails');if(existing)traceOptionalDetailsOpen=existing.open;
  const collapsibleState={...captureTraceCollapsibleDetails(body),technical:traceOptionalDetailsOpen};
  const scrollPositions=captureTraceScrollPositions(body),thinkingDetailsOpen=captureTraceThinkingDetails(body),traceMain=body?.closest('.trace-main'),mainScrollTop=traceMain?.scrollTop||0,mainScrollLeft=traceMain?.scrollLeft||0;
  activeTraceData=d;const model=traceDisplayModel(d),s=model.session,panels=model.panels.filter(panel=>panel.available),technicalPanels=panels.filter(panel=>!['input','output','response'].includes(panel.id));
  if(!technicalPanels.some(panel=>panel.id===traceView))traceView=technicalPanels[0]?.id||'';
  const titleEl=$('tracePageTitle'),liveEl=$('tracePageLive');if(titleEl)titleEl.textContent=traceHumanTitle(model);
  if(liveEl){liveEl.textContent=d?.terminal?'finished':'● live · updating';liveEl.className='tiny '+(d?.terminal?'ok':'trace-running');}
  const state=traceStatus(s),stateClass=(state==='failed'||state==='error')?'bad':(state==='interrupted'?'warn':(d?.terminal?'ok':'warn'));
  const command=s.action||traceHumanTitle(model),project=model.project?` · ${model.project}`:'',timestamp=Number(s.created_at)>0?new Date(Number(s.created_at)*1000).toLocaleString():'nezaznamenané';
  const header=`<div class="trace-inspector-head"><div class="trace-header-title"><h1>${esc(command+project)}</h1><span class="badge ${stateClass}">${esc(state)}</span></div><div class="trace-header-meta"><span class="trace-header-time">${esc(timestamp)}</span>${d?.payload_truncated?'<span>Obsah zkrácen limitem trace úložiště</span>':''}<button type="button" class="btn" data-trace-export>Download redacted trace page</button></div></div>`;
  const requestResponseMarkup=model.presentation?.kind==='request_response'?renderTracePresentation(model):'';
  const primaryMarkup=`<section class="trace-primary"><div class="trace-primary-grid">${traceMainContent('Input','input',tracePrimaryInput(model.input))}${traceMainContent('Output','output',model.output)}</div></section>${requestResponseMarkup}`;
  const historyControls=d?.has_older_events||d?.has_newer_events?`<div class="trace-header-meta">${d?.has_older_events?'<button type="button" class="btn" data-trace-event-page="older">Load older events</button>':''}${d?.has_newer_events?'<button type="button" class="btn" data-trace-event-page="newer">Load newer events</button>':''}</div>`:'';
  const panelMarkup=technicalPanels.map(panel=>{const selected=panel.id===traceView,content=selected?panel.render():'';return `<div id="trace-panel-${esc(panel.id)}" class="trace-view" role="tabpanel" aria-label="${esc(panel.label)}"${selected?'':' hidden'}>${content}</div>`}).join('');
  const technicalGroups=[['Kontext',['thinking','agent_context']],['Průběh',['timeline','model','tools','events']],['Chyby',['errors']],['Pokročilé',['raw']]];
  const technicalOptions=technicalGroups.map(([label,ids])=>{const options=technicalPanels.filter(panel=>ids.includes(panel.id));return options.length?`<optgroup label="${esc(label)}">${options.map(panel=>`<option value="${esc(panel.id)}"${panel.id===traceView?' selected':''}>${esc(panel.label)}</option>`).join('')}</optgroup>`:''}).join('');
  const requestSettingsValue={...traceTechnicalSettings(model.input),...traceTechnicalSettings(s.request)};
  const requestSettings=Object.keys(requestSettingsValue).length?`<details class="trace-optional-details" data-trace-collapsible data-trace-key="request-settings"><summary>Command / project settings</summary><div class="trace-optional-body">${humanSection('Settings',traceSanitizeValue(requestSettingsValue))}</div></details>`:'';
  const detailPolicy='Tajné klíče a přístupové tokeny jsou redigované; běžný obsah zůstává viditelný.';
  const summaryDetails=`<details class="trace-optional-details" data-trace-collapsible data-trace-key="technical-summary"><summary>Souhrn požadavku a dostupnost dat</summary>${traceSummary(model,{})}</details>`;
  const technical=`<details class="trace-optional-details" id="traceTechnicalDetails" data-trace-collapsible data-trace-key="technical"${traceOptionalDetailsOpen?' open':''}><summary>Nastavení a technické údaje</summary><div class="trace-optional-body"><p class="tiny muted">${detailPolicy}</p><label class="trace-view-picker"><span>Zobrazit</span><select data-trace-view-select aria-label="Technické údaje">${technicalOptions}</select></label>${panelMarkup}${summaryDetails}${requestSettings}${historyControls}</div></details>`;
  if(body){body.className='trace-page-body';body.innerHTML=`<div class="human-shell">${header}${traceMetricRow(d?.metrics)}${primaryMarkup}${technical}</div>`;
    body.querySelector('[data-trace-export]')?.addEventListener('click',()=>downloadRedactedTracePage(activeTraceId));
  }
  const restore=()=>{restoreTraceCollapsibleDetails($('tracePageBody'),collapsibleState);restoreTraceThinkingDetails($('tracePageBody'),thinkingDetailsOpen);restoreTraceScrollPositions($('tracePageBody'),scrollPositions);const next=$('tracePageBody')?.closest('.trace-main');if(next){next.scrollTop=mainScrollTop;next.scrollLeft=mainScrollLeft}};
  if(window.requestAnimationFrame)window.requestAnimationFrame(restore);else restore();
 }
function setTraceView(view){if(!activeTraceData)return;const model=traceDisplayModel(activeTraceData);if(!model.panels.some(panel=>panel.available&&panel.id===view))return;traceView=view;renderTraceDetail(activeTraceData)}
async function downloadRedactedTracePage(traceId){
  const id=String(traceId||'').trim();if(!id)return;
  try{
    const response=await apiFetch('/api/debug-traces/'+encodeURIComponent(id)+'/export?since_seq=0&limit=1000&max_bytes=8388608',{cache:'no-store'});
    const data=await response.json();if(!response.ok||data?.success!==true)throw new Error(data?.error||'Redacted trace export failed');
    const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),anchor=document.createElement('a');
    anchor.href=url;anchor.download='local-ai-hub-trace-redacted.json';document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){const status=$('detailedTelemetryStatus');if(status)status.textContent=String(error?.message||'Redacted trace export failed').slice(0,240);}
}
async function fetchTraceContentPages(traceId,field,budget={used:0,limit:8*1024*1024}){
  let offset=0;const chunks=[];let encoding='text',storageTruncated=false;
  for(;;){
    const path='/api/debug-traces/'+encodeURIComponent(traceId)+'?full=1&content_field='+encodeURIComponent(field)+'&content_offset='+offset;
    const response=await apiFetch(path,{cache:'no-store'}),data=await response.json();
    if(!data.success||!data.content_page)throw new Error(data.error||'Trace content page unavailable');
    const page=data.content_page;if(Number(page.offset)!==offset)throw new Error('Trace content cursor changed');
    encoding=page.encoding||encoding;storageTruncated=storageTruncated||Boolean(page.storage_truncated);const pageText=String(page.text||'');
    if(pageText.length&&budget.used+pageText.length>=budget.limit)throw new Error('Dashboard reveal limit exceeded');
    budget.used+=pageText.length;chunks.push(pageText);
    if(!page.has_more)break;
    const next=Number(page.next_offset);if(!Number.isSafeInteger(next)||next<=offset)throw new Error('Trace content cursor did not advance');offset=next;
  }
  const text=chunks.join('');
  if(encoding==='text')return {value:text,storageTruncated};
  if(!text)return {value:{},storageTruncated};
  if(encoding==='text')return {value:text,storageTruncated};
  try{const value=JSON.parse(text);return {value,storageTruncated}}
  catch{return {value:text,storageTruncated,invalidJson:true}}
}
async function fetchPrimaryTraceContent(traceId,detail){
  const session={...(detail?.session||{})},budget={used:0,limit:8*1024*1024};let truncated=Boolean(detail?.payload_truncated);
  for(const field of ['request','effective_payload','output','response']){
    try{const loaded=await fetchTraceContentPages(traceId,field,budget);if(loaded.value!==undefined)session[field]=loaded.value;truncated=truncated||loaded.storageTruncated;}catch(error){if(/limit exceeded/i.test(String(error?.message||error)))throw error;}
  }
  return {...detail,session,full_payload_requested:true,payload_truncated:truncated};
}
async function fetchTraceMetrics(traceId){
  const response=await apiFetch('/api/debug-traces/'+encodeURIComponent(traceId)+'/metrics',{cache:'no-store'}),data=await response.json();
  if(!data?.success||!data.metrics||typeof data.metrics!=='object')return null;
  return data.metrics;
}
async function loadTraceEventPage(direction){
  if(!activeTraceId||!traceEvents.length)return;
  const older=direction==='older',firstSeq=Number(traceEvents[0]?.seq||0),lastSeq=Number(traceEvents[traceEvents.length-1]?.seq||0),cursor=older?firstSeq:lastSeq;
  if(!cursor)return;
  try{
    const pageCursor=older?'before_seq='+cursor:'since_seq='+cursor;
    const response=await apiFetch('/api/debug-traces/'+encodeURIComponent(activeTraceId)+'?'+pageCursor+'&limit=500',{cache:'no-store'}),data=await response.json();
    if(!data.success)throw new Error(data.error||'Trace event page unavailable');
    const events=Array.isArray(data.events)?data.events:[];let storedTruncation=false;
    if(!events.length)return;
    traceEvents=events;const more=Boolean(data.events_has_more);
    activeTraceData={...activeTraceData,...data,session:activeTraceData.session,events:traceEvents,events_total:traceEventTotal,events_before_seq:events[0].seq,has_older_events:older?more:Boolean(activeTraceData.has_older_events),has_newer_events:older?true:more,payload_truncated:Boolean(activeTraceData.payload_truncated||storedTruncation)};
    renderTraceDetail(activeTraceData);
  }catch(error){openModal({error:String(error?.message||error)},'Trace history unavailable');}
}
function setTraceDetailsOpen(open){const body=$('tracePageBody');if(!body)return;body.querySelectorAll('details[data-trace-collapsible],#traceTechnicalDetails').forEach(detail=>{detail.open=Boolean(open)});}
function copyTraceFinalResponse(btn){if(!activeTraceData)return;const model=traceDisplayModel(activeTraceData);if(!traceRecorded(model.output)){if(btn){btn.textContent='No final response';setTimeout(()=>{btn.textContent='Copy final response'},1500)}return;}copyText(promptText(model.output),btn);}
function copyTraceContent(field,btn){if(!activeTraceData)return;const model=traceDisplayModel(activeTraceData),value=field==='input'?tracePrimaryInput(model.input):model.output;if(!traceRecorded(value))return;copyText(traceContentText(value),btn);}
function renderTraceLoadState(state,message){
  const body=$('tracePageBody');if(!body)return;
  const heading=state==='loading'?'Loading trace':state==='paused'?'Trace loading paused':'Trace unavailable';
  const detail=(activeTraceData?'Showing the last loaded details. ':'')+message;
  const markup=`<section class="diag-banner ${state==='error'?'bad':'warn'}" role="status" aria-live="polite" id="traceLoadState"><b>${esc(heading)}</b><p>${esc(detail)}</p></section>`;
  if(activeTraceData){$('traceLoadState')?.remove();body.insertAdjacentHTML('afterbegin',markup)}
  else{body.className='trace-page-body';body.innerHTML=markup}
  const live=$('tracePageLive');if(live){live.textContent=heading;live.className='tiny '+(state==='error'?'bad':'warn')}
}
async function openTrace(id,options={}){
  const requestTimeoutMs=Math.max(1,Number(options.requestTimeoutMs)||15000);
  const pollTraceId=String(id||''),pollGeneration=++tracePollGeneration;activeTraceId=pollTraceId;traceSeq=0;traceEvents=[];traceEventTotal=0;traceOpenSteps=new Set();traceView='timeline';activeTraceData=null;traceOptionalDetailsOpen=false;
  renderTraceLoadState('loading','Fetching the selected trace…');
  renderTraceList(lastTraces);switchTab('traceInspector');
  if(traceDetailPoller){traceDetailPoller.stop();traceDetailPoller=null}
  let pollInFlight=false,lastTracePollSignature='',terminalPayloadRequested=false,timeoutHandle=null,requestTimedOut=false;
  const poll=async isCurrent=>{
    if(!activeTraceId||pollTraceId!==activeTraceId||pollGeneration!==tracePollGeneration||pollInFlight||!isCurrent())return false;
    pollInFlight=true;
    const controller=typeof AbortController==='function'?new AbortController():null;
    tracePollAbortController=controller;
    try{
      const sinceSeq=traceSeq,opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
      const request=apiFetch('/api/debug-traces/'+encodeURIComponent(pollTraceId)+'?since_seq='+sinceSeq+'&limit=100&max_bytes=8388608',opts).then(async response=>({response,data:await response.json()}));
      const timeout=new Promise((_,reject)=>{timeoutHandle=setTimeout(()=>{requestTimedOut=true;controller?.abort();reject(new Error(`Trace request timed out after ${Math.ceil(requestTimeoutMs/1000)} seconds`))},requestTimeoutMs)});
      const {response:r,data:d}=await Promise.race([request,timeout]);
      if(!isCurrent()||pollGeneration!==tracePollGeneration||pollTraceId!==activeTraceId)return false;
      if(d.cursor_reset){traceSeq=0;traceEvents=[];traceEventTotal=0;}
      if(r.ok&&d.success===true){
        const signature=JSON.stringify([d.state,d.terminal,d.next_seq,d.events_total,d.updated_at,d.error]);
        const changed=signature!==lastTracePollSignature;lastTracePollSignature=signature;
        traceSeq=traceFiniteSequence(d.next_seq,traceSeq);traceEventTotal=Math.max(traceEventTotal,traceSeq,Number(d.events_total||d.eventsTotal||0));const next=traceAppendEvents(traceEvents,d.events,traceEventTotal);traceEvents=next.events;traceEventTotal=next.eventsTotal;
        if(changed||$('traceLoadState'))renderTraceDetail({...d,events:traceEvents,events_total:traceEventTotal,has_older_events:traceEventTotal>traceEvents.length,events_before_seq:traceEvents[0]?.seq||0,has_newer_events:false});
        if(d.terminal&&!terminalPayloadRequested){
          terminalPayloadRequested=true;const requestedTraceId=pollTraceId,base={...d,events:traceEvents,events_total:traceEventTotal};
          fetchPrimaryTraceContent(requestedTraceId,base).then(full=>{if(activeTraceId!==requestedTraceId||pollGeneration!==tracePollGeneration)return;activeTraceData={...activeTraceData,...full,metrics:activeTraceData?.metrics};renderTraceDetail(activeTraceData);}).catch(error=>{if(activeTraceId===requestedTraceId){activeTraceData={...activeTraceData,full_payload_error:String(error?.message||error)};renderTraceDetail(activeTraceData);}});
          fetchTraceMetrics(requestedTraceId).then(metrics=>{if(activeTraceId!==requestedTraceId||pollGeneration!==tracePollGeneration||!metrics)return;activeTraceData={...activeTraceData,metrics};renderTraceDetail(activeTraceData);}).catch(()=>{});
        }
        if(d.terminal&&!d.has_more&&!d.events_has_more&&pollGeneration===tracePollGeneration&&pollTraceId===activeTraceId){traceDetailPoller?.stop();traceDetailPoller=null}
        return {changed};
      }else if(d.retryable===true){
        renderTraceLoadState(d.error_code==='operational_mode_blocked'?'paused':'error',(d.error||'HTTP '+r.status)+'. Retrying automatically while this page is open.');return false;
      }else{renderTraceLoadState('error',d.error||'HTTP '+r.status);traceDetailPoller?.stop();traceDetailPoller=null;return false}
    }catch(e){if(isCurrent()&&pollGeneration===tracePollGeneration&&pollTraceId===activeTraceId&&(!controller?.signal.aborted||requestTimedOut)){const message=requestTimedOut?`Trace request timed out after ${Math.ceil(requestTimeoutMs/1000)} seconds`:String(e?.message||e);renderTraceLoadState('error',message+'. Retrying automatically while this page is open.');}return false;
    }finally{if(timeoutHandle!==null){clearTimeout(timeoutHandle);timeoutHandle=null}pollInFlight=false;if(tracePollAbortController===controller)tracePollAbortController=null}
  };
  traceDetailPoller=createDashboardStatusPoller(poll,{baseDelay:1000,maxDelay:30000});
  traceDetailPoller.start();
}
let projectInspectorGeneration=0;
let activeProjectInspectorRoot='';
let activeProjectInspectorData=null;
function openModal(obj,title='',entityType=''){
  const inspectorGeneration=++projectInspectorGeneration;
  if($('modalLive'))$('modalLive').textContent='';
  if(!$('modalBody'))return;
  const type=entityType||inferEntityType(obj);
  activeProjectInspectorRoot=type==='project'?String(obj.root||''):'';
  activeProjectInspectorData=type==='project'?obj:null;
  const defaultTitle=title||(
    type==='task'?'Task Inspector':
    type==='memory'?'Memory Record':
    type==='incident'?'Negative Knowledge / Anti-Pattern':
    type==='event'?'Live Event Inspector':
    type==='project'?'Project Pipeline Inspector':
    type==='doctor'?'Health Diagnostics':
    type==='code_intel'?'Code Intelligence':
    type==='lease'?'Active File Lease':
    type==='command'?'Active Command':
    type==='error'?'Error Fingerprint':
    type==='db_opt'?'Database Optimization':
    type==='cache_purge'?'Cache Purge Summary':
    type==='http_tail'?'HTTP Tail Latency':
    type==='execution_profile'?'Execution Profile':
    type==='model_stat'?'Model Metrics':
    type==='cache_layer'?'Cache Layer Analysis':
    type==='agent_stat'?'Agent Telemetry':
    type==='route_stat'?'Execution Route':
    type==='blocked_reason'?'Command Policy Block':
    type==='scheduler_job'?'Scheduler Job':
    type==='session'?'Process Session Details':
    type==='http_request'?'HTTP Request':'Details'
  );
  if($('modalTitle'))$('modalTitle').textContent=defaultTitle;
  if(type==='task')renderTaskModal(obj);
  else if(type==='memory')renderMemoryModal(obj);
  else if(type==='incident')renderIncidentModal(obj);
  else if(type==='event')renderLiveStreamModal(obj);
  else if(type==='project'){
    renderProjectModal(obj);
    loadProjectDetails(obj,inspectorGeneration);
  }
  else if(type==='doctor')renderDoctorModal(obj);
  else if(type==='code_intel')renderCodeIntelModal(obj,defaultTitle);
  else if(type==='lease')renderActiveLeaseModal(obj);
  else if(type==='command')renderActiveCommandModal(obj);
  else if(type==='error')renderErrorFingerprintModal(obj);
  else if(type==='db_opt')renderDbOptModal(obj);
  else if(type==='cache_purge')renderCachePurgeModal(obj);
  else if(type==='http_tail')renderHttpTailModal(obj);
  else if(type==='execution_profile')renderExecutionProfileModal(obj);
  else if(type==='model_stat')renderModelStatModal(obj);
  else if(type==='audit_vulnerability')renderAuditVulnModal(obj);
  else if(type==='dead_code')renderDeadCodeModal(obj);
  else if(type==='arch_edge')renderArchEdgeModal(obj);
  else if(type==='cache_layer')renderCacheLayerModal(obj);
  else if(type==='agent_stat')renderAgentStatModal(obj);
  else if(type==='route_stat')renderRouteStatModal(obj);
  else if(type==='blocked_reason')renderBlockedReasonModal(obj);
  else if(type==='scheduler_job')renderSchedulerJobModal(obj);
  else if(type==='http_request')renderHttpRequestModal(obj);
  else renderHumanModal(obj);
  if($('modalBg'))$('modalBg').classList.add('open');
  if($('modalBody'))$('modalBody').scrollTop=0;
}

let activeTaskInspectorState=null;
let trajectoryTaskId='',trajectoryAfterSeq=0,trajectorySnapshotSeq=null,trajectoryHasMore=false,trajectoryGaps=[],trajectoryEvents=[],trajectoryLoading=false,trajectoryPageError='',trajectoryGeneration=0;

