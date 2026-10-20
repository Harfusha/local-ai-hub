from test_dashboard_polish import extract, run_javascript


def test_current_health_does_not_reclassify_history_as_active_failures():
    run_javascript(extract('function dashboardTelemetryState(', 'function dashboardFreshness('), """
const base={hub_online:true,ollama_online:true,headless:{state:'running',restarts:12}};
for(const scope of ['process','window']){
  const snapshot={...base,observability:{scope,data_available:true,writer:{activity_observed:true,accounting_balanced:true,dropped:0,writer_errors:0,pending:0,accepted:2404,written:2404},
    cohorts:{agent_http:{events:2404,failures:2404,p50_duration_ms:1,p95_duration_ms:2,p99_duration_ms:3},policy_rejection:{events:47},inference:{retry_count:8,degraded_count:3}},
    sessions:[{status:'crashed'}]}};
  assert.equal(dashboardHealth(snapshot).level,'healthy');
  assert.doesNotMatch(dashboardHealth(snapshot).reason,/2404|restart|dropped|rejection/);
}
const incomplete=dashboardHealth({...base,observability:{data_available:true,writer:{activity_observed:true,accounting_balanced:true,dropped:30,writer_errors:2}}});
assert.equal(incomplete.level,'attention');
assert.match(incomplete.reason,/telemetry coverage is incomplete/i);
assert.equal(dashboardHealth({...base,hub_online:false}).level,'degraded');
assert.equal(dashboardHealth({...base,headless:{state:'stopped'}}).level,'degraded');
assert.equal(dashboardHealth({...base,headless:{state:'running',open_incidents:2}}).level,'attention');
assert.equal(dashboardHealth({...base,headless:{state:'running',open_incidents:0,blocked_requests:2}}).level,'attention');
assert.equal(dashboardHealth({...base,dependency_status:{runtime:{degraded:true}}}).level,'attention');
const unavailable=dashboardHealth({...base,observability:{data_available:false},dependency_status:{'telemetry.summary':{degraded:true}}});
assert.equal(unavailable.level,'attention');
assert.match(unavailable.reason,/telemetry data is unavailable or stale/i);
""")


def test_reliability_keeps_live_health_and_historical_counts_separate():
    source = extract('function dashboardTelemetryState(', 'function dashboardFreshness(')
    source += extract('function renderReliabilitySummary(', 'function schedulerRow(')
    run_javascript(source, """
const elements=Object.fromEntries(['reliabilityHeadline','reliabilityTrend','reliabilityAction','requestHistoryStatus','workState','workSearch','requestHistorySearch','requestHistoryAction','requestHistoryPeriod'].map(id=>[id,{}]));
const $=id=>elements[id],n=v=>String(v??0),esc=v=>String(v);
let tab='',last=null;const switchTab=value=>tab=value;
renderReliabilitySummary({hub_online:true,ollama_online:true,headless:{state:'running',restarts:9},observability:{scope:'window',data_available:true,writer:{activity_observed:true,accounting_balanced:true,dropped:0,writer_errors:0,pending:0,accepted:2404,written:2404},cohorts:{agent_http:{events:2404,failures:2404,p50_duration_ms:1,p95_duration_ms:2,p99_duration_ms:3},policy_rejection:{events:0}},sessions:[{status:'crashed'}]}});
assert.match(elements.reliabilityHeadline.innerHTML,/Healthy/);
assert.match(elements.reliabilityHeadline.innerHTML,/2404/);
assert.match(elements.reliabilityHeadline.innerHTML,/Last 30 days/);
assert.doesNotMatch(elements.reliabilityTrend.textContent,/active request failures|Failure trend/);
elements.reliabilityAction.onclick();
assert.equal(tab,'work');assert.equal(elements.requestHistoryStatus.value,'failed');
renderReliabilitySummary({hub_online:true,ollama_online:true,observability:{data_available:false}});
assert.match(elements.reliabilityHeadline.innerHTML,/Unavailable/);
""")


def test_events_without_result_are_informational_and_http_errors_fail():
    run_javascript(extract('function eventSeverity(', 'function renderEvents('), """
assert.equal(eventSeverity({event_type:'admin.authorization'}),'info');
assert.equal(eventSeverity({success:true}),'success');
assert.equal(eventSeverity({success:true,status_code:503}),'failure');
assert.equal(eventSeverity({success:false}),'failure');
assert.equal(eventSeverity({status:'retrying'}),'warning');
""")


def test_chart_samples_do_not_mix_periods_or_duplicate_filter_renders():
    source = extract('function recordTelemetrySnapshot(', 'function dashboardHealth(')
    run_javascript(source, """
let lastChartSnapshot=null,lastChartScope=null;
const latencySparkData=[],throughputSparkData=[],liveChartLatency=[],liveChartQueue=[];
const a={scope:'process',data_available:true,cohorts:{agent_http:{events:3,p95_duration_ms:20}},avg_queue_wait_ms:2};
recordTelemetrySnapshot(a);recordTelemetrySnapshot(a);
assert.deepEqual(liveChartLatency,[20]);
recordTelemetrySnapshot({...a,scope:'window',cohorts:{agent_http:{events:200,p95_duration_ms:100}}});
assert.deepEqual(liveChartLatency,[100]);
recordTelemetrySnapshot({scope:'window',data_available:false});
assert.deepEqual(liveChartLatency,[]);
""")


def test_rag_contents_do_not_prove_index_readiness():
    from local_ai_hub.dashboard_contracts import WORKSPACE_INVENTORY_JS

    run_javascript(WORKSPACE_INVENTORY_JS + extract('function ragWorkspaceIdentity(', 'async function loadRagWorkspaces('), """
const list={},summary={},$=id=>id==='ragWorkspacesList'?list:id==='ragWorkspaceSummary'?summary:null;
const esc=String,n=String,humanLabel=String;
const ragWorkspaces=[{root:'C:/repo',chunks:100}];
renderRagWorkspaces();
assert.match(list.innerHTML,/100 chunks/);
assert.match(list.innerHTML,/status unreported/);
assert.doesNotMatch(list.innerHTML,/>ready</i);
""")


def test_bundle_progress_does_not_hide_an_error():
    source=extract('function projectState(', 'function groupedProjects(')
    source+=extract('function renderBundles(', "document.addEventListener('click',event=>")
    run_javascript(source, """
const table={},$=()=>table,esc=String,n=String;
const groupedProjects=items=>items;
const preprocessingSummary=()=>({available:true});
assert.equal(projectState({status:'error',overall_progress_pct:100}),'error');
assert.equal(projectState({status:'running',overall_progress_pct:100}),'running');
renderBundles({preprocessing:{projects:[{project:'repo',root:'C:/repo',status:'error',overall_progress_pct:100}]}});
assert.doesNotMatch(table.innerHTML,/Ready to export/);
assert.match(table.innerHTML,/Partial index/);
""")


def test_live_freshness_is_independent_of_historical_sample_timestamp():
    source = extract('function dashboardTelemetryState(', 'function redactDiagnostic(')
    run_javascript(source, """
const elements=Object.fromEntries(['overviewHealthLevel','overviewHealthEvidence','overviewFreshness','overviewHealthAction','overviewHealthSummary','overviewAnnouncement','overviewHistorySummary'].map(id=>[id,{style:{}}]));
const $=id=>elements[id],age=String,switchTab=()=>{};let lastOverviewAnnouncement='';
const now=1900000000000,base={hub_online:true,ollama_online:true,headless:{state:'running'},observability:{updated_at:1,data_available:true,writer:{activity_observed:true,accounting_balanced:true,dropped:0,writer_errors:0,pending:0,accepted:2404,written:2404},cohorts:{agent_http:{events:2404,failures:2404,p50_duration_ms:1,p95_duration_ms:2,p99_duration_ms:3},policy_rejection:{events:0}}}};
renderOverviewHealth(base,now,now);
assert.equal(elements.overviewHealthLevel.textContent,'Healthy');
assert.ok(elements.overviewHistorySummary.textContent.includes((2404).toLocaleString()));
renderOverviewHealth(base,now-200000,now);
assert.equal(elements.overviewHealthLevel.textContent,'Status stale');
""")


def test_repository_selection_is_an_empty_state_not_a_load_failure():
    source=extract('function renderAgentOsLoadErrors(', "$('agentOsRefresh')")
    run_javascript(source, """
const elements=Object.fromEntries(['agentOsRoot','agentOsState','agentOsSummary','agentOsTasksBody','agentOsMemoryBody','agentOsIncBody'].map(id=>[id,{value:''}]));
const $=id=>elements[id],esc=String;
const agentOsLoadErrors={tasks:'Choose a repository root above',memory:'Choose a repository root above',incidents:'Choose a repository root above'};
renderAgentOsLoadErrors();
assert.equal(elements.agentOsState.textContent,'Select a repository');
assert.doesNotMatch(elements.agentOsSummary.textContent,/failed|could not|unavailable/i);
assert.doesNotMatch(elements.agentOsTasksBody.innerHTML,/Unavailable|warn-t/);
""")


def test_http_delivery_success_does_not_hide_operation_failure():
    run_javascript(extract('function requestOutcome(', 'function workRecentRequestRow('), """
assert.equal(requestOutcome({success:false,status_code:200}).label,'Failed · HTTP 200');
assert.equal(requestOutcome({success:true,status_code:503}).failed,true);
assert.equal(requestOutcome({success:true,status_code:200}).label,'Succeeded · HTTP 200');
assert.equal(requestOutcome({}).label,'Result unreported');
""")


def test_navigation_starts_new_pages_at_their_heading():
    source=extract('function switchTab(', "\ndocument.querySelectorAll('.tabbtn').forEach(b=>")
    run_javascript(source, """
let current='overview',scrolls=0,focused=0;
let tracesPollAbortController=null;
const pollTraces=()=>{};
const pages=['overview','config'].map(id=>({id,classList:{toggle:(name,active)=>{if(active)current=id}}}));
const tabs=pages.map(p=>({dataset:{tab:p.id},classList:{toggle:()=>{}},setAttribute:()=>{}}));
const $=id=>({querySelector:()=>({focus:()=>focused++})});
const document={querySelector:()=>({id:current}),querySelectorAll:selector=>selector==='.page'?pages:tabs};
const window={scrollTo:()=>scrolls++},localStorage={setItem:()=>{}},location={hash:'#overview'},history={replaceState:()=>{}};
const loadConfigView=()=>{},loadAgentOsView=()=>{},loadRagWorkspaces=()=>{},loadActiveLeases=()=>{},loadWorktrees=()=>{},loadLogsTail=()=>{};
switchTab('config');assert.equal(scrolls,1);assert.equal(focused,1);
switchTab('config');assert.equal(scrolls,1);
""")
