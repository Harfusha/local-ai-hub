from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local AI Hub — realtime</title>
<style>
:root{
  color-scheme:dark;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Inter",ui-sans-serif,system-ui,sans-serif;
  --bg:#090d14;--panel:#0f1724;--panel2:#141f30;--panel-head:#131d2e;
  --line:#1e293b;--line-light:#334155;--muted:#94a3b8;--fg:#e2e8f0;--fg-bright:#f8fafc;
  --ok:#34d399;--warn:#fbbf24;--bad:#f87171;--accent:#38bdf8;--accent2:#818cf8;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.45;font-size:12px}
button,input,select,textarea{font:inherit}
.top{position:sticky;top:0;z-index:25;background:rgba(9,13,20,0.92);border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}
.toolbar{display:flex;align-items:center;gap:10px;padding:9px 16px;flex-wrap:wrap}
.brand-wrap{display:flex;align-items:center;gap:8px;margin-right:6px}
.brand{font-weight:750;font-size:14px;color:var(--fg-bright);letter-spacing:-.015em}
.brand-icon{color:var(--accent);font-size:16px}
.pill{display:inline-flex;align-items:center;gap:5px;border:1px solid #2d3c52;border-radius:999px;padding:3px 9px;font-size:11px;font-weight:500}
.pill.ok{border-color:#065f46;color:var(--ok);background:#064e3b22}
.pill.warn-t{border-color:#78350f;color:var(--warn);background:#78350f22}
.pill.bad-t{border-color:#7f1d1d;color:var(--bad);background:#7f1d1d22}
.btn{background:#172233;color:var(--fg);border:1px solid #2e405a;border-radius:6px;padding:5px 11px;font-size:11px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:5px;transition:all .15s}
.btn:hover{background:#223249;border-color:#3d5578;color:#fff}
.btn.ok{background:#064e3b33;border-color:#059669;color:#6ee7b7}
.btn.ok:hover{background:#065f4655;border-color:#10b981;color:#a7f3d0}
.btn.bad{background:#450a0a33;border-color:#991b1b;color:#fca5a5}
.btn.bad:hover{background:#7f1d1d55;border-color:#dc2626;color:#fee2e2}
.btn.warn{background:#451a0333;border-color:#92400e;color:#fde68a}
.btn.warn:hover{background:#78350f55;border-color:#d97706;color:#fef3c7}
.spacer{margin-left:auto}
.muted,.tiny{color:var(--muted);font-size:11px}
.ok{color:var(--ok)}
.warn-t{color:var(--warn)}
.bad-t{color:var(--bad)}
.tabs{display:flex;gap:4px;padding:0 14px 8px;overflow-x:auto}
.tabbtn{border:0;background:transparent;color:#94a3b8;padding:7px 11px;border-radius:6px;cursor:pointer;white-space:nowrap;font-size:12px;font-weight:500;transition:all .15s}
.tabbtn:hover{background:#162233;color:#fff}
.tabbtn.active{background:#1e2d44;color:var(--accent);font-weight:600;box-shadow:inset 0 -2px 0 var(--accent)}
.tabbtn.tab-disabled{opacity:.55;color:#64748b}
.tabbtn .tab-badge{font-size:10px;margin-left:4px}
.subtabs{display:flex;gap:6px;padding:8px 12px;background:var(--panel-head);border-bottom:1px solid var(--line);flex-wrap:wrap}
.subtab-btn{background:#172233;color:var(--muted);border:1px solid #29384d;border-radius:5px;padding:4px 9px;font-size:11px;font-weight:500;cursor:pointer;transition:all .15s}
.subtab-btn:hover{color:#fff;background:#202e42}
.subtab-btn.active{background:#1d3557;border-color:var(--accent);color:var(--accent);font-weight:600}
.page{display:none;padding:14px}
.page.active{display:block}
.dash-group{margin-bottom:14px}
.group-title{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:7px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.grid{display:grid;gap:10px}
.grid-2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.grid-3{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.grid-4{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.grid-6{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card,.section{background:var(--panel);border:1px solid var(--line);border-radius:9px}
.card{padding:13px;min-height:92px;display:flex;flex-direction:column;justify-content:space-between;transition:border-color .15s}
.card:hover{border-color:var(--line-light)}
.label{color:var(--muted);font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.value{font-size:21px;font-weight:700;margin-top:5px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums;color:var(--fg-bright)}
.sub{color:#94a3b8;font-size:11px;margin-top:5px;line-height:1.45}
.section{margin-top:12px;overflow:hidden;border-radius:9px}
.section h2{font-size:12.5px;margin:0;padding:10px 14px;background:var(--panel-head);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:8px;font-weight:600}
.table-wrap{overflow:auto;max-height:520px}
table{width:100%;border-collapse:collapse;font-size:11px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #1a2538;white-space:nowrap}
th{position:sticky;top:0;background:var(--panel-head);color:#94a3b8;font-weight:600;z-index:2;letter-spacing:.02em}
tbody tr.click{cursor:pointer;transition:background .1s}
tbody tr.click:hover{background:#162338}
.kv{display:grid;grid-template-columns:minmax(140px,220px) 1fr;gap:8px 14px;padding:12px 14px;font-size:12px}
.kv>div:nth-child(odd){color:var(--muted);font-weight:500}
.split{display:grid;grid-template-columns:1.2fr .8fr;gap:12px}
.bar{height:5px;background:#202c3e;border-radius:4px;overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;background:#38bdf8}
.event{display:grid;grid-template-columns:82px 72px 110px 130px minmax(180px,1fr) 90px 85px;gap:7px;border-bottom:1px solid #1a2538;padding:7px 10px;font-size:11px}
.event:hover{background:#162338}
.events{max-height:650px;overflow:auto}
.empty{padding:16px;color:var(--muted);font-size:12px;text-align:center}
.chip{display:inline-block;border:1px solid #2d3e56;border-radius:5px;padding:2px 6px;margin:1px 3px 1px 0;font-size:10.5px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-variant-numeric:tabular-nums}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(4px);z-index:60;align-items:center;justify-content:center;padding:16px}
.modal-bg.open{display:flex}
.modal{width:min(900px,96vw);max-height:88vh;overflow:auto;background:#0e1522;border:1px solid #2f4059;border-radius:12px;box-shadow:0 24px 90px rgba(0,0,0,0.7);padding:0}
.modal-head{position:sticky;top:0;background:#141e30;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:11px 14px}
.modal pre{white-space:pre-wrap;word-break:break-word;padding:14px;margin:0;color:#c9d6e4;font-size:12px}
.badge-status{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.badge-running{background:#112238;color:#93c5fd;border:1px solid #2563eb}
.badge-complete{background:#0c2e1f;color:#86efac;border:1px solid #16a34a}
.badge-paused{background:#351f08;color:#fde047;border:1px solid #b45309}
.badge-waiting{background:#1f2937;color:#cbd5e1;border:1px solid #64748b}
.badge-error{background:#350c0c;color:#fca5a5;border:1px solid #b91c1c}
.pulse-dot{width:6px;height:6px;border-radius:50%;background:#38bdf8;box-shadow:0 0 6px #38bdf8;animation:pulse 1.2s infinite;display:inline-block}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.3;transform:scale(0.8)}}
.pipeline-stepper{display:flex;align-items:center;gap:2px;margin-top:4px}
.pipe-step{width:15px;height:15px;border-radius:3px;display:inline-flex;align-items:center;justify-content:center;font-size:8px;font-weight:bold;cursor:help;line-height:1}
.pipe-done{background:#14532d;color:#86efac;border:1px solid #16a34a}
.pipe-curr{background:#1e3a8a;color:#bfdbfe;border:1px solid #3b82f6;box-shadow:0 0 8px #3b82f6cc}
.pipe-pend{background:#17202c;color:#64748b;border:1px solid #263342}
.action-btn-sm{background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:4px;padding:3px 7px;font-size:10px;cursor:pointer;display:inline-flex;align-items:center;gap:3px}
.action-btn-sm:hover{background:#263545;color:#fff}
.action-btn-sm.danger:hover{background:#7f1d1d;color:#fca5a5;border-color:#b91c1c}
.diag-banner{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:8px;font-size:12px;margin:8px 0 10px;line-height:1.4}
.diag-banner.ok{background:#0c2e1f;border:1px solid #16a34a;color:#86efac}
.diag-banner.warn{background:#351f08;border:1px solid #b45309;color:#fde047}
.diag-banner.bad{background:#350c0c;border:1px solid #b91c1c;color:#fca5a5}
.diag-banner.info{background:#0f1d2e;border:1px solid #2563eb;color:#93c5fd}
.control-menu{position:relative;margin-left:auto}.control-menu summary{list-style:none;cursor:pointer;background:#19232d;border:1px solid #394758;border-radius:6px;padding:6px 10px;font-size:11px}.control-menu summary::-webkit-details-marker{display:none}.control-menu[open] summary{background:#243343;color:#fff}
.control-popover{position:absolute;right:0;top:calc(100% + 7px);z-index:30;min-width:330px;padding:10px;background:#10161d;border:1px solid #394758;border-radius:8px;box-shadow:0 16px 45px #000b;display:grid;grid-template-columns:1fr 1fr;gap:7px}
.control-popover .token{grid-column:1/-1;display:flex;gap:6px}
.control-popover .token input{min-width:0;flex:1;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 8px;font-size:11px}
.control-popover button{width:100%}
.project-toolbar{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.project-toolbar input,.project-toolbar select{background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px 9px;font-size:11px}
.project-toolbar input{flex:1;min-width:180px}
.project-toolbar select{min-width:118px}
.project-summary{margin-left:auto}
.project-table th:nth-child(1){width:25%}.project-table th:nth-child(2){width:33%}.project-table th:nth-child(3){width:22%}.project-table th:nth-child(4){width:12%}.project-table th:nth-child(5){width:8%}
.project-table td{vertical-align:middle}
.project-name{max-width:260px;overflow:hidden;text-overflow:ellipsis}
.project-activity{white-space:normal;line-height:1.35;max-width:390px}
.project-progress{min-width:150px}
.project-progress-line{display:flex;justify-content:space-between;font-size:10px}
.project-index{display:flex;gap:4px;flex-wrap:wrap}
.project-index .chip{font-size:10px;margin:0}
.project-actions{display:flex;gap:3px}
.primary-metric{font-size:20px;font-weight:650}
.sub strong{color:var(--fg)}
.spark-canvas{width:100%;height:32px;display:block;margin-top:6px}
@media(max-width:980px){.split{grid-template-columns:1fr}.event{grid-template-columns:72px 90px 1fr}.hide-sm{display:none}.page{padding:8px}.value{font-size:17px}}
@media(max-width:700px){.toolbar{padding:8px;gap:6px}.toolbar .brand{font-size:12px}.toolbar>.tiny{display:none}.control-menu{margin-left:0}.control-popover{position:fixed;left:8px;right:8px;top:72px;min-width:0}.tabs{padding:0 6px 6px}.tabbtn{padding:6px 8px}.project-toolbar{align-items:stretch}.project-toolbar input{flex-basis:100%}.project-summary{margin-left:0;width:100%}}
</style><style>
.system-card .value{font-size:15px}
.trace-running{color:var(--accent)}
.trace-done{color:var(--ok)}
.trace-failed{color:var(--bad)}
.trace-queued{color:var(--warn)}
.trace-toolbar{display:flex;gap:8px;align-items:center;padding:9px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.trace-toolbar select{background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:5px 8px;font:inherit;font-size:11px}
.human-shell{padding:12px}
.human-summary{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.human-summary .badge{border:1px solid #394758;border-radius:999px;padding:3px 8px;font-size:11px}
.human-summary .badge.ok{border-color:#16a34a}
.human-summary .badge.bad{border-color:#b91c1c}
.human-section{border:1px solid var(--line);border-radius:7px;margin:9px 0;overflow:hidden}
.human-section>h3{font-size:12px;margin:0;padding:8px 10px;background:#151d26;border-bottom:1px solid var(--line)}
.human-grid{display:grid;grid-template-columns:minmax(130px,220px) 1fr;gap:6px 12px;padding:10px;font-size:11px}
.human-grid>div:nth-child(odd){color:var(--muted)}
.human-value{white-space:pre-wrap;word-break:break-word;color:var(--fg)}
.human-pre{margin:0;padding:10px;background:#0d1219;color:#c9d6e4;white-space:pre-wrap;word-break:break-word;font:inherit;line-height:1.45;max-height:360px;overflow:auto}
.human-list{padding:8px 10px}
.human-item{padding:7px 0;border-bottom:1px solid #202a35}
.human-item:last-child{border-bottom:0}
.event-card{padding:8px 10px;border-bottom:1px solid #202a35}
.event-head{display:flex;gap:9px;align-items:center;margin-bottom:5px}
.event-type{color:var(--accent);font-weight:600}
.event-time{color:var(--muted);font-size:10px}
.trace-timeline{padding:10px}
.trace-step{border-left:2px solid #30445e;margin-left:9px;padding-left:12px;padding-bottom:10px}
.trace-step:last-child{padding-bottom:0}
.trace-step-head{display:flex;align-items:center;gap:8px;width:100%;text-align:left;background:#151d26;color:var(--fg);border:1px solid #334355;border-radius:6px;padding:8px 10px;cursor:pointer;font:inherit}
.trace-step-head:hover{background:#1b2a38}
.trace-step-index{color:var(--accent);font-weight:700}
.trace-step-chevron{margin-left:auto;color:var(--muted);transition:transform .15s}
.trace-step.open .trace-step-chevron{transform:rotate(90deg)}
.trace-step-body{display:none;margin-top:5px;border:1px solid #273544;border-radius:6px;overflow:hidden}
.trace-step.open .trace-step-body{display:block}
.trace-event{padding:8px 10px;border-bottom:1px solid #202a35}
.trace-event:last-child{border-bottom:0}
.trace-output{color:#c9d6e4;white-space:pre-wrap;word-break:break-word;background:#0d1219;padding:8px;max-height:260px;overflow:auto}
.trace-stream-summary{background:#0d1219;border:1px solid #263546;border-radius:6px;padding:8px}
.trace-stream-summary strong{display:block;color:var(--fg);font-size:11px;margin-bottom:6px}
.trace-stream-summary .trace-output{padding:0;border:0;max-height:180px}
.raw-json{margin-top:10px;border:1px solid #303c4a;border-radius:6px}
.raw-json summary{cursor:pointer;padding:8px 10px;color:var(--muted);font-size:11px}
.raw-json pre{max-height:320px}
.empty-human{padding:12px;color:var(--muted);font-size:11px}
</style></head><body>
<div class="top">
  <div class="toolbar">
    <div class="brand-wrap">
      <span class="brand-icon">⚡</span>
      <span class="brand">Local AI Hub</span>
    </div>
    <span id="conn" class="pill warn-t"><span class="pulse-dot"></span>connecting</span>
    <span id="updated" class="tiny"></span>
    <label class="tiny">SLO <select id="sloScope"><option value="process" selected>Since restart</option><option value="window">Last 30 days</option></select></label>
    <span class="tiny spacer">debug traces · bounded prompt/output retention</span>
    <span id="featSummary" class="pill tiny"></span>
    <details id="controlMenu" class="control-menu">
      <summary>Controls</summary>
      <div class="control-popover">
        <div class="token"><input type="password" id="apiToken" autocomplete="off" placeholder="API token (remote only)"><button class="btn" id="saveToken">Set token</button></div>
        <button class="btn ok" id="optDbBtn">Optimize DBs</button>
        <button class="btn warn" id="purgeCacheBtn">Purge Cache</button>
        <button class="btn" id="doctorBtn">Doctor</button>
        <button class="btn" id="pauseEvents">Pause events</button>
        <button class="btn warn" id="prepToggle">Pause preprocessing</button>
        <button class="btn" id="restartHub">Restart hub</button>
        <button class="btn bad" id="stopService">Stop service</button>
      </div>
    </details>
  </div>
  <div class="tabs">
    <button class="tabbtn active" data-tab="overview">📊 Overview</button>
    <button class="tabbtn" data-tab="work">⚡ Queue &amp; requests</button>
    <button class="tabbtn" data-tab="agentos" data-feature="agent_os">🤖 Agent OS</button>
    <button class="tabbtn" data-tab="projects" data-feature="preprocessing">📁 Projects</button>
    <button class="tabbtn" data-tab="explorer" data-feature="code_intelligence">🌲 Code Explorer</button>
    <button class="tabbtn" data-tab="commands" data-feature="commands">💻 Commands</button>
    <button class="tabbtn" data-tab="architecture" data-feature="code_intelligence">🏗️ Architecture</button>
    <button class="tabbtn" data-tab="performance">🧠 Models &amp; RAG</button>
    <button class="tabbtn" data-tab="reliability">🛡️ Reliability &amp; Logs</button>
    <button class="tabbtn" data-tab="config">⚙️ Configuration</button>
    <button class="tabbtn" data-tab="bundles" data-feature="preprocessing">📦 Bundles</button>
    <button class="tabbtn" data-tab="events">📡 Live events</button>
  </div>
</div>

<div id="overview" class="page active">
  <div class="dash-group">
    <div class="group-title"><span>Host &amp; System Health</span><span class="tiny muted">Core runtime state, capacity and supervisory control</span></div>
    <div class="grid grid-3">
      <div class="card"><div class="label">Hub health</div><div class="value primary-metric" id="health">…</div><div class="sub" id="uptime"></div></div>
      <div class="card system-card"><div class="label">Host Hardware</div><div class="value" id="sysUtil">…</div><div class="sub" id="sysSub"></div></div>
      <div class="card" id="agentStateCard" style="cursor:pointer" title="Click to open Agent OS inspector"><div class="label" style="display:flex;justify-content:space-between"><span>Agent OS State</span><span>↗</span></div><div class="value primary-metric" id="agentStateVal">…</div><div class="sub" id="agentStateSub"></div></div>
    </div>
  </div>

  <div class="dash-group">
    <div class="group-title"><span>Performance &amp; Cloud Avoidance</span><span class="tiny muted">Avoided tokens, estimated USD savings and tail latency</span></div>
    <div class="grid grid-6">
      <div class="card"><div class="label" id="handledRequestsLabel">Requests handled · since restart</div><div class="value primary-metric" id="handledRequests">…</div><div class="sub" id="handledRequestsSub"></div><canvas id="throughputSpark" class="spark-canvas" width="160" height="30"></canvas></div>
      <div class="card"><div class="label" id="tokensSavedLabel">Tokens saved · since restart</div><div class="value primary-metric" id="tokensSaved">…</div><div class="sub" id="tokensSavedSub"></div></div>
      <div class="card"><div class="label" id="dollarsSavedLabel">Estimated savings · since restart</div><div class="value primary-metric" id="dollarsSaved">…</div><div class="sub" id="dollarsSavedSub"></div></div>
      <div class="card"><div class="label" id="cacheLabel">Cache hit rate · since restart</div><div class="value primary-metric" id="cache">…</div><div class="sub" id="cacheSub"></div></div>
      <div class="card"><div class="label">Latency p50 / p95 / p99</div><div class="value" id="latency">…</div><div class="sub" id="queueWait"></div><canvas id="latencySpark" class="spark-canvas" width="160" height="30"></canvas></div>
      <div class="card"><div class="label" id="reliabilityLabel">Reliability · since restart</div><div class="value primary-metric" id="reliabilityValue">…</div><div class="sub" id="reliabilitySub"></div></div>
    </div>
  </div>

  <div class="dash-group">
    <div class="group-title"><span>Queues &amp; Execution</span><span class="tiny muted">Foreground scheduler and background workers</span></div>
    <div class="grid grid-2">
      <div class="card"><div class="label">Scheduler Queue</div><div class="value primary-metric" id="fgQueue">…</div><div class="sub" id="bgQueue"></div></div>
      <div class="card"><div class="label">Preprocessing Pipeline</div><div class="value primary-metric" id="prep">…</div><div class="sub" id="prepSub"></div></div>
    </div>
  </div>

  <div class="section" style="margin-top:12px;padding:12px 14px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <div><span class="label" style="font-size:11.5px">Configured Feature Modules</span><span class="tiny muted" style="margin-left:8px">Granular subsystem status &amp; tool projection</span></div>
      <span class="tiny muted" id="featStatusText">All modules active</span>
    </div>
    <div id="featurePills" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  </div>

  <div class="split" style="margin-top:12px">
    <section class="section"><h2>Current workload <span class="tiny" id="currentSummary"></span></h2><div class="table-wrap"><table><thead><tr><th>State</th><th>Agent/tenant</th><th>Source</th><th>Model</th><th>Wait</th><th>Processing</th><th>Reason</th></tr></thead><tbody id="overviewJobs"></tbody></table></div></section>
    <section class="section"><h2>Hotspots</h2><div id="hotspots" class="kv"></div></section>
  </div>
</div>

<div id="work" class="page">
  <section class="section"><h2>Scheduler queue <span class="tiny" id="queueSummary"></span></h2><div class="table-wrap"><table><thead><tr><th>State</th><th>Job</th><th>Agent/tenant</th><th>Source</th><th>Model</th><th>Priority</th><th>Wait</th><th>Processing</th><th>Reason</th></tr></thead><tbody id="jobs"></tbody></table></div></section>
  <section class="section"><h2>Active API requests <span class="tiny">monitoring endpoints excluded</span></h2><div class="table-wrap"><table><thead><tr><th>Request</th><th>Agent</th><th>Tenant</th><th>Action</th><th>Age</th></tr></thead><tbody id="activeReq"></tbody></table></div></section>
  <section class="section"><h2>Recent API requests <span class="tiny">persisted telemetry · monitoring endpoints excluded</span></h2><div class="table-wrap"><table><thead><tr><th>Time</th><th>Request</th><th>Agent</th><th>Tenant</th><th>Action</th><th>Status</th><th>Duration</th></tr></thead><tbody id="recentReq"></tbody></table></div></section>
  <section class="section"><h2>Agent debug traces <span class="tiny" id="traceSummary">full prompt/output · bounded retention</span></h2><div class="trace-toolbar"><span class="tiny">Click a trace for live events, model prompt, tool calls and output.</span><select id="traceKind"><option value="">All kinds</option><option value="api_request">API requests</option><option value="async_job">Async jobs</option></select><button class="btn" id="traceRefresh" style="padding:4px 8px;font-size:11px">Refresh</button></div><div class="table-wrap"><table><thead><tr><th>State</th><th>Kind</th><th>Action</th><th>Agent / tenant</th><th>Model</th><th>Created</th><th>Updated</th><th>Links</th></tr></thead><tbody id="traces"></tbody></table></div></section>
</div>

<div id="agentos" class="page">
  <div id="agentOsDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Agent OS feature is disabled in configuration</b> (<code>features.agent_os = false</code>). Durable task tracking and memory are inactive.</div>
  <section class="section">
    <h2><span style="display:flex;align-items:center;gap:8px">Agent Operating System <span class="tiny" id="agentOsState"></span></span><div style="display:flex;gap:6px;align-items:center"><button class="btn ok" id="agentOsRefresh" style="padding:4px 10px;font-size:11px">↻ Refresh</button><button class="btn warn" id="agentOsCleanup" style="padding:4px 10px;font-size:11px">🧹 Cleanup stale state</button></div></h2>
    <div class="subtabs">
      <button class="subtab-btn active" id="subtabTasks" data-agentos-tab="tasks">Tasks &amp; Contracts</button>
      <button class="subtab-btn" id="subtabMemory" data-agentos-tab="memory">Memory &amp; Facts</button>
      <button class="subtab-btn" id="subtabIncidents" data-agentos-tab="incidents">Negative Knowledge &amp; Incidents</button>
      <button class="subtab-btn" id="subtabVerification" data-agentos-tab="verification">Verification Receipts</button>
      <button class="subtab-btn" id="subtabContext" data-agentos-tab="context">Context Playground</button>
      <button class="subtab-btn" id="subtabLiveStream" data-agentos-tab="liveStream">Live Stream 🔴</button>
    </div>
  </section>

  <div id="agentOsTasksSec" style="display:block">
    <section class="section">
      <div class="project-toolbar">
        <input id="agentOsSearch" type="search" placeholder="Search tasks by ID, goal, next action..." autocomplete="off">
        <select id="agentOsTaskStatus" aria-label="Task status filter"><option value="">All task statuses</option><option value="planned">Planned</option><option value="active">Active</option><option value="verifying">Verifying</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="blocked">Blocked</option></select>
        <button class="btn ok" id="agentOsCreateTaskBtn" style="padding:5px 9px">+ Create Task</button>
        <span class="tiny project-summary" id="agentOsSummary"></span>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Status</th><th>Task ID</th><th>Goal</th><th>Scope</th><th>Phase / Next Action</th><th>Criteria</th><th>Updated</th></tr></thead><tbody id="agentOsTasksBody"></tbody></table></div>
    </section>
  </div>

  <div id="agentOsMemorySec" style="display:none">
    <section class="section">
      <div class="project-toolbar">
        <input id="agentOsMemSearch" type="search" placeholder="Search memory keys and values..." autocomplete="off">
        <select id="agentOsMemScope" aria-label="Memory scope"><option value="">All scopes</option><option value="task">Task</option><option value="session">Session</option><option value="repository">Repository</option><option value="user">User</option><option value="system">System</option></select>
        <select id="agentOsMemKind" aria-label="Memory kind"><option value="">All kinds</option><option value="fact">Fact</option><option value="decision">Decision</option><option value="preference">Preference</option><option value="pattern">Pattern</option><option value="negative_knowledge">Negative Knowledge</option></select>
        <button class="btn ok" id="agentOsRecordMemBtn" style="padding:5px 9px">+ Record Memory</button>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Scope</th><th>Kind</th><th>Key</th><th>Value</th><th>Confidence</th><th>Source</th><th>Created</th></tr></thead><tbody id="agentOsMemoryBody"></tbody></table></div>
    </section>
  </div>

  <div id="agentOsIncidentsSec" style="display:none">
    <section class="section">
      <div class="project-toolbar">
        <input id="agentOsIncSearch" type="search" placeholder="Search error class, root cause, verified fix..." autocomplete="off">
        <select id="agentOsIncFilter" aria-label="Incident status"><option value="">All incidents</option><option value="false">Unresolved</option><option value="true">Resolved with fix</option></select>
        <button class="btn warn" id="agentOsRecordIncBtn" style="padding:5px 9px">+ Record Anti-Pattern</button>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Incident ID</th><th>Operation</th><th>Error Class</th><th>Redacted Message</th><th>Root Cause</th><th>Verified Fix</th><th>Status</th></tr></thead><tbody id="agentOsIncBody"></tbody></table></div>
    </section>
  </div>

  <div id="agentOsVerificationSec" style="display:none">
    <section class="section">
      <h2>Receipt &amp; Completion Gating <span class="tiny">Verify if acceptance criteria have valid verifiable receipts</span></h2>
      <div style="padding:12px;display:flex;gap:8px;align-items:center">
        <input type="text" id="agentOsVerifyTaskId" placeholder="Enter Task ID (e.g. task_abc123)..." style="flex:1;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px 12px;font-size:12px">
        <button class="btn ok" id="agentOsVerifyBtn">Check Completion Gate</button>
      </div>
      <div id="agentOsVerifyOut" style="padding:12px"></div>
    </section>
  </div>

  <div id="agentOsContextSec" style="display:none">
    <section class="section">
      <h2>Context Compilation Playground <span class="tiny">Assemble bounded active task state, memories, negative knowledge &amp; active leases</span></h2>
      <div style="padding:12px;display:flex;gap:8px;align-items:center">
        <input type="text" id="agentOsCtxTaskId" placeholder="Task ID..." style="flex:1;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px 12px;font-size:12px">
        <input type="number" id="agentOsCtxBudget" value="4000" placeholder="Token budget" style="width:120px;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px;font-size:12px">
        <button class="btn ok" id="agentOsCtxCompileBtn">Compile Context</button>
      </div>
      <pre id="agentOsCtxOut" style="margin:0;padding:12px;background:#0d1219;color:#c9d6e4;font-size:11px;max-height:450px;overflow:auto;display:none;border-top:1px solid #1e293b"></pre>
    </section>
  </div>
  <div id="agentOsLiveStreamSec" style="display:none">
    <section class="section">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px">
        <div style="display:flex;align-items:center;gap:10px">
          <span class="badge-status badge-waiting" id="sseStreamBadge">Connecting…</span>
          <span class="tiny muted" id="sseStreamStats">0 events received</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <select id="sseKindFilter" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:4px;padding:4px 8px;font-size:11px">
            <option value="">All event kinds</option>
            <option value="task.">Tasks (task.*)</option>
            <option value="memory.">Memory (memory.*)</option>
            <option value="incident.">Incidents (incident.*)</option>
            <option value="verification.">Verification (verification.*)</option>
            <option value="policy.">Policy (policy.*)</option>
          </select>
          <button class="btn" id="sseReconnectBtn" style="padding:4px 8px;font-size:11px">Reconnect</button>
          <button class="btn warn" id="sseClearBtn" style="padding:4px 8px;font-size:11px">Clear Feed</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Seq</th><th>Time</th><th>Stream ID</th><th>Kind</th><th>Actor</th><th>Payload / Details</th></tr>
          </thead>
          <tbody id="agentOsLiveStreamBody"></tbody>
        </table>
      </div>
    </section>
  </div>
</div>

<div id="projects" class="page">
  <div id="prepDiagnosticBar" class="diag-banner info" style="display:none"></div>
  <section class="section">
    <h2><span style="display:flex;align-items:center;gap:8px">Projects <span class="tiny" id="prepState"></span></span><div style="display:flex;gap:6px;align-items:center"><button class="btn warn" id="prepAllToggle" style="padding:4px 10px;font-size:11px">Pause all</button><button class="btn ok" id="regProjectBtn" style="padding:4px 10px;font-size:11px">+ Register</button><button class="btn warn" id="cleanMissingBtn" style="padding:4px 10px;font-size:11px">🧹 Clean missing</button></div></h2>
    <div class="project-toolbar"><input id="projectSearch" type="search" placeholder="Search projects…" autocomplete="off"><select id="projectFilter" aria-label="Project status"><option value="all">All states</option><option value="running">Running</option><option value="waiting">Waiting</option><option value="error">Error</option><option value="paused">Paused</option><option value="ready">Ready</option></select><select id="projectSort" aria-label="Project sort"><option value="priority">Operational priority</option><option value="name">Name</option><option value="progress">Progress</option><option value="recent">Recent activity</option></select><span class="tiny project-summary" id="projectSummary"></span></div>
    <div class="table-wrap"><table class="project-table"><thead><tr><th>Project</th><th>State &amp; activity</th><th>Phase &amp; progress</th><th>Indexes</th><th>Actions</th></tr></thead><tbody id="projectsBody"></tbody></table></div>
  </section>
</div>

<div id="explorer" class="page">
  <div id="intelDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Code Intelligence is disabled in configuration</b> (<code>features.code_intelligence = false</code>). Symbol search and AST outline are unavailable.</div>
  <section class="section">
    <h2>Code &amp; AST Symbol Inspector <span class="tiny">Search any class, function or method across indexed projects</span></h2>
    <div style="padding:12px;display:flex;gap:8px">
      <input type="text" id="codeSearchInput" placeholder="Symbol name (e.g. LocalAIApp, PlayerController, CalculateTax)..." style="flex:1;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px 12px;font-size:12px">
      <button class="btn ok" id="codeSearchBtn">Inspect Symbol</button>
    </div>
    <div id="symbolDetails" style="padding:12px;display:none">
      <div style="display:flex;gap:12px;margin-bottom:8px;font-size:12px;flex-wrap:wrap">
        <span><b>Symbol:</b> <span id="symName" class="chip"></span></span>
        <span><b>Kind:</b> <span id="symKind" class="chip"></span></span>
        <span><b>File:</b> <span id="symPath" class="muted"></span></span>
        <span><b>Lines:</b> <span id="symLines" class="mono"></span></span>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">
        <button class="btn" id="findDeclBtn">Find Declaration</button>
        <button class="btn" id="findRefsBtn">Find References</button>
        <button class="btn" id="findImplBtn">Find Implementations</button>
        <button class="btn" id="genTestsBtn">Generate Tests</button>
        <button class="btn warn" id="impactCheckBtn">Analyze Impact</button>
        <button class="btn ok" id="resolveImpBtn">Resolve Imports</button>
      </div>
      <pre id="symCode" style="background:#0d1219;padding:12px;border-radius:6px;overflow:auto;max-height:420px;font-size:12px;border:1px solid #273341;color:#dbe5ef"></pre>
    </div>
  </section>

  <section class="section" style="margin-top:12px">
    <h2>File AST Outline &amp; Diagnostics <span class="tiny">Inspect AST hierarchy and compiler diagnostics for any file</span></h2>
    <div style="padding:12px;display:flex;gap:8px">
      <input type="text" id="codeFileInput" placeholder="File path (e.g. src/local_ai_hub/app.py)..." style="flex:1;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px 12px;font-size:12px">
      <button class="btn" id="codeOutlineBtn">Outline AST</button>
      <button class="btn warn" id="codeDiagBtn">Check Diagnostics</button>
    </div>
    <div id="fileAnalysisDetails" style="padding:12px;display:none">
      <h3 id="fileAnalysisTitle" style="font-size:12px;margin:0 0 8px"></h3>
      <div id="fileAnalysisContent"></div>
    </div>
  </section>
</div>

<div id="commands" class="page">
  <div id="cmdDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Commands feature is disabled in configuration</b> (<code>features.commands = false</code>). Command classification and execution are blocked.</div>
  <section class="section">
    <h2>Safe command runner <span class="tiny">same fail-closed policy broker used by agents</span></h2>
    <div style="padding:12px;display:grid;grid-template-columns:minmax(180px,.7fr) minmax(280px,2fr) auto auto;gap:8px">
      <input id="cmdRoot" placeholder="Repository root" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px">
      <input id="cmdInput" placeholder="pytest -q / npm test / cargo check …" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px">
      <button class="btn" id="cmdClassify">Classify</button>
      <button class="btn ok" id="cmdRun">Run allowed command</button>
    </div>
    <pre id="cmdOutput" style="margin:0;padding:12px;white-space:pre-wrap;max-height:360px;overflow:auto;background:#0d1219;color:#c9d6e4;font-size:11px"></pre>
  </section>
  <section class="section"><h2>Running commands <span class="tiny" id="commandState"></span></h2><div class="table-wrap"><table><thead><tr><th>Command</th><th>CWD</th><th>Tenant</th><th>Class</th><th>Age</th><th>Timeout</th></tr></thead><tbody id="activeCommands"></tbody></table></div></section>
  <div class="split"><section class="section"><h2>Command broker statistics</h2><div id="commandStats" class="kv"></div></section><section class="section"><h2>Blocked by policy</h2><div class="table-wrap"><table><thead><tr><th>Reason</th><th>Count</th></tr></thead><tbody id="blockedReasons"></tbody></table></div></section></div>
</div>

<div id="architecture" class="page">
  <section class="section">
    <h2>Project Dependency Graph <span class="tiny" id="archSummary"></span></h2>
    <div style="padding:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      <button class="btn" id="archRefresh">Refresh projects</button>
      <input type="text" id="symbolInput" placeholder="Symbol name (e.g. LocalAIApp)..." style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 10px;font-size:11px">
      <button class="btn" id="symbolGraphBtn">View Call-Graph</button>
      <button class="btn warn" id="deadCodeBtn">Scan Dead Code</button>
      <button class="btn ok" id="auditDepsBtn">Audit Security</button>
      <span class="tiny muted">Drag nodes to rearrange · Click symbol nodes for details</span>
    </div>
    <svg id="archSvg" style="width:100%;height:520px;background:#0d1219;border-radius:6px;display:block"></svg>
    <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>From</th><th>To</th><th>Type</th><th>Shared label / Reference</th></tr></thead><tbody id="archEdgesTable"></tbody></table></div>
  </section>
  <section class="section" id="deadCodeSec" style="display:none"><h2>Detected Dead Code &amp; Unused Symbols <span class="tiny" id="deadCodeSummary"></span></h2><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Kind</th><th>File</th><th>Line</th><th>Container</th><th>Reason</th></tr></thead><tbody id="deadCodeTable"></tbody></table></div></section>
  <section class="section" id="auditSec" style="display:none"><h2>Dependency Vulnerability &amp; CVE Audit <span class="tiny" id="auditSummary"></span></h2><div class="table-wrap"><table><thead><tr><th>Package</th><th>Severity</th><th>Installed</th><th>Safe Version</th><th>Advisory</th><th>Manifest</th></tr></thead><tbody id="auditTable"></tbody></table></div></section>
</div>

<div id="performance" class="page">
  <section class="section">
    <h2>Live Telemetry Waves <span class="tiny">Real-time p95 latency &amp; queue wait (HTML5 Canvas · zero external CDN)</span></h2>
    <div style="padding:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px">
        <span><span class="chip" style="border-color:#38bdf8;color:#38bdf8">● Latency p95</span> <span class="chip" style="border-color:#34d399;color:#34d399">● Queue Wait</span></span>
        <span class="tiny muted">30 rolling sample ticks</span>
      </div>
      <canvas id="liveChartCanvas" width="800" height="150" style="width:100%;height:150px;background:#080c13;border-radius:6px;border:1px solid #1e293b;display:block"></canvas>
    </div>
  </section>

  <div class="split" style="margin-top:12px">
    <section class="section">
      <h2>Installed Local Models <span class="tiny">Ollama engine integration</span></h2>
      <div style="padding:12px" id="installedModelsList"><div class="tiny muted">Loading installed models…</div></div>
    </section>
    <section class="section">
      <h2>RAG Vector Workspaces <span class="tiny">Persistent semantic code index</span></h2>
      <div style="padding:12px" id="ragWorkspacesList"><div class="tiny muted">Loading RAG workspaces…</div></div>
    </section>
  </div>

  <section class="section" style="margin-top:12px">
    <h2>RAG Semantic Search Testbed <span class="tiny">Test dense retrieval and re-ranking across indexed repositories</span></h2>
    <div style="padding:12px;display:flex;gap:8px;flex-wrap:wrap">
      <input type="text" id="ragSearchInput" placeholder="Semantic query (e.g. how does telemetry flush work?)..." style="flex:1;min-width:260px;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px 12px;font-size:12px">
      <select id="ragSearchWsSelect" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 10px;font-size:11px"><option value="">Select workspace…</option></select>
      <button class="btn ok" id="ragSearchBtn">Semantic Search</button>
    </div>
    <div id="ragSearchResults" style="padding:12px;display:none"></div>
  </section>

  <section class="section" style="margin-top:12px"><h2>Execution profiles <span class="tiny">configured capacity; context packing remains adaptive</span></h2><div class="table-wrap"><table><thead><tr><th>Model</th><th>Tier</th><th>Context</th><th>Max</th><th>Parallel</th><th>Thinking</th><th>Prompt cap</th></tr></thead><tbody id="executionProfiles"></tbody></table></div></section>
  <div class="split"><section class="section"><h2>Model statistics</h2><div class="table-wrap"><table><thead><tr><th>Model</th><th>Calls</th><th>Avg</th><th>Load</th><th>Fails</th></tr></thead><tbody id="models"></tbody></table></div></section><section class="section"><h2>Cache layers</h2><div class="table-wrap"><table><thead><tr><th>Layer</th><th>Calls</th><th>Avg</th><th>Tokens saved</th></tr></thead><tbody id="cacheLayers"></tbody></table></div></section></div>
  <div class="split"><section class="section"><h2>Agents</h2><div class="table-wrap"><table><thead><tr><th>Agent</th><th>Requests</th><th>Local AI</th><th>Avg</th><th>Fails</th></tr></thead><tbody id="agents"></tbody></table></div></section><section class="section"><h2>Execution routes</h2><div class="table-wrap"><table><thead><tr><th>Route</th><th>Task</th><th>Complexity</th><th>Calls</th><th>Avg</th><th>Fails</th></tr></thead><tbody id="routes"></tbody></table></div></section></div>
  <section class="section"><h2>HTTP tail latency <span class="tiny">per action · excludes policy rejections</span></h2><div class="table-wrap"><table><thead><tr><th>Action</th><th>Calls</th><th>p50</th><th>p95</th><th>p99</th><th>Fails</th></tr></thead><tbody id="httpTail"></tbody></table></div></section>
  <section class="section"><h2>Active Multi-Agent File Leases <span class="tiny">Prevents conflicting agent edits</span></h2><div class="table-wrap"><table><thead><tr><th>Lease ID</th><th>Paths</th><th>Tenant</th><th>Purpose</th><th>Expires</th><th>Actions</th></tr></thead><tbody id="activeLeasesBody"></tbody></table></div></section>
</div>

<div id="reliability" class="page">
  <div class="split">
    <section class="section"><h2>Recent error fingerprints</h2><div class="table-wrap"><table><thead><tr><th>Component</th><th>Operation</th><th>Count</th><th>Recovered</th><th>Last seen</th></tr></thead><tbody id="errors"></tbody></table></div></section>
    <section class="section"><h2>Runtime / scheduler counters</h2><div id="runtimeCounters" class="kv"></div></section>
  </div>
  <section class="section"><h2>Code-intelligence process control <span class="tiny">bounded Serena / CodeGraph sessions</span></h2><div style="padding:12px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="intelRediscover">Rediscover executables</button><button class="btn warn" id="intelReset">Reset all sessions</button><span class="tiny" id="intelControlStatus"></span></div></section>
  <section class="section">
    <h2><span>Operational log tail</span><div style="display:flex;gap:6px;align-items:center"><input type="text" id="logFilterInput" placeholder="Filter logs…" style="background:#0d141c;color:var(--fg);border:1px solid #334355;border-radius:5px;padding:3px 7px;font-size:11px;width:150px"><select id="logLinesSelect" style="background:#0d141c;color:var(--fg);border:1px solid #334355;border-radius:5px;padding:3px 6px;font-size:11px"><option value="100">100 lines</option><option value="250" selected>250 lines</option><option value="500">500 lines</option></select><button class="btn" id="loadLogs" style="padding:3px 8px">Refresh</button><button class="btn" id="copyLogsBtn" style="padding:3px 8px">Copy</button></div></h2>
    <pre id="logTail" style="margin:0;padding:12px;white-space:pre-wrap;max-height:420px;overflow:auto;background:#0d1219;color:#c9d6e4;font-size:11px">Click Refresh to load logs.</pre>
  </section>
</div>

<div id="config" class="page">
  <section class="section">
    <h2>Runtime configuration <span class="tiny">safe override sidecar · restart required after save</span></h2>
    <div style="padding:14px">
      <div class="dash-group"><div class="group-title">Hardware &amp; Engine</div><div class="kv" style="padding:0;margin-bottom:12px"><div>Hardware profile</div><div><select id="cfgProfile" style="background:#172233;color:var(--fg);border:1px solid #2e405a;border-radius:6px;padding:6px 10px"><option>auto</option><option>cpu</option><option>low</option><option>balanced</option><option>high</option><option>max</option></select></div></div></div>
      <div class="dash-group"><div class="group-title">Core MCP Tools</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px"><label><input type="checkbox" id="cfgFeatStatus"> status (local_ai_status)</label><label><input type="checkbox" id="cfgFeatRepo"> repo (local_ai_repo)</label><label><input type="checkbox" id="cfgFeatTasks"> tasks (local_ai_task &amp; Ollama)</label><label><input type="checkbox" id="cfgFeatRag"> rag (local_ai_rag)</label><label><input type="checkbox" id="cfgFeatCommands"> commands (local_ai_command)</label><label><input type="checkbox" id="cfgFeatCoord"> coord (local_ai_coord)</label><label><input type="checkbox" id="cfgFeatArtifacts"> artifacts (local_ai_artifact)</label></div></div>
      <div class="dash-group"><div class="group-title">Code Intelligence &amp; Indexing</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px"><label><input type="checkbox" id="cfgPreprocess"> Preprocessing enabled</label><label><input type="checkbox" id="cfgIntel"> Managed code intelligence</label><label><input type="checkbox" id="cfgSerena"> Serena backend</label><label><input type="checkbox" id="cfgCodegraph"> CodeGraphContext backend</label></div></div>
      <div class="dash-group"><div class="group-title">Advanced Subsystems</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px"><label><input type="checkbox" id="cfgFeatSubagents"> Subagents (Ollama workers)</label><label><input type="checkbox" id="cfgFeatAgentOs"> Agent OS (durable memory/receipts)</label><label><input type="checkbox" id="cfgFeatDashboard"> Web Dashboard</label></div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:6px"><button class="btn ok" id="cfgSave">Save overrides</button><button class="btn" id="cfgReload">Reload view</button><button class="btn warn" id="cfgReset">Reset dashboard overrides</button><span class="tiny" id="cfgStatus"></span></div>
    </div>
  </section>
  <section class="section"><h2>Effective configuration <span class="tiny" id="cfgPath"></span></h2><pre id="cfgPreview" style="margin:0;padding:14px;white-space:pre-wrap;max-height:520px;overflow:auto;background:#090d14;color:#c9d6e4;font-size:11px"></pre></section>
</div>

<div id="bundles" class="page">
  <section class="section">
    <h2>Project Bundles — Export &amp; Import</h2>
    <div style="padding:12px">
      <p class="tiny muted">Bundles compress preprocessed index (AST, deterministic facts, RAG vectors and semantic cards) for instant restore on a different machine without re-indexing.</p>
      <div class="split" style="margin-top:10px">
        <div><h3 style="font-size:12px;margin:0 0 8px">Export Bundle</h3><table><thead><tr><th>Project</th><th>Status</th><th>Action</th></tr></thead><tbody id="bundleExportTable"></tbody></table></div>
        <div><h3 style="font-size:12px;margin:0 0 8px">Import Bundle</h3><div style="display:flex;flex-direction:column;gap:8px"><input type="file" id="bundleFile" accept=".zip,application/zip" style="color:var(--fg);font-size:12px"><input type="text" id="bundleTargetRoot" placeholder="Optional target repository root" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px"><button class="btn" id="bundleImport">Import selected ZIP</button><div id="bundleImportStatus" class="tiny muted"></div></div></div>
      </div>
    </div>
  </section>
</div>

<div id="events" class="page"><section class="section"><h2>Live activity <span class="tiny">RAM ring buffer · display pause does not pause runtime</span></h2><div id="eventList" class="events"></div></section></div>

<div id="modalBg" class="modal-bg"><div class="modal"><div class="modal-head"><strong id="modalTitle">Details</strong><span id="modalLive" class="tiny" style="margin-left:10px"></span><button class="btn spacer" id="modalClose">Close</button></div><div id="modalBody"></div></div></div>

<script>
let cursor=0,paused=false,last=null,lastTraces=[];
const latencySparkData=[], throughputSparkData=[], liveChartLatency=[], liveChartQueue=[];

const traceStyles=document.createElement('style');
traceStyles.textContent='.trace-inspector-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:12px;background:linear-gradient(135deg,#172535,#11171e);border:1px solid #33485f;border-radius:8px}.trace-kicker{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}.trace-inspector-head strong{font-size:15px;display:block;overflow-wrap:anywhere}.trace-metrics{display:flex;gap:7px;flex-wrap:wrap;padding:8px 0 2px;color:var(--muted);font-size:10px}.trace-metrics span{border:1px solid #2b3948;border-radius:999px;padding:3px 7px}.trace-tabs{display:flex;gap:5px;overflow:auto;padding:10px 0 2px;border-bottom:1px solid var(--line)}.trace-tab{background:transparent;color:var(--muted);border:0;border-bottom:2px solid transparent;padding:7px 9px;cursor:pointer;white-space:nowrap;font-size:11px}.trace-tab:hover,.trace-tab.active{color:var(--fg);border-bottom-color:var(--accent)}.trace-view{min-height:80px}.tool-pair{display:grid;gap:6px}.tool-part{border-left:3px solid #6d86a8;background:#0d141c;padding:8px;border-radius:4px}.tool-result{border-left-color:var(--ok)}.tool-label{color:var(--accent);font-weight:700;font-size:11px;margin-bottom:6px}.tool-label .tiny{margin-left:7px;color:var(--fg);font-weight:400}.tool-pending{color:var(--warn);font-size:11px;padding:7px 0}.trace-raw-panel pre{margin:0}';
document.head.append(traceStyles);

const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=v=>Number(v||0).toLocaleString(), ms=v=>{v=Number(v||0);return v>=1000?(v/1000).toFixed(v>=10000?1:2)+' s':Math.round(v)+' ms'}, durSec=s=>{s=Number(s||0);if(s<60)return Math.round(s)+'s';if(s<3600)return Math.floor(s/60)+'m '+Math.round(s%60)+'s';return Math.floor(s/3600)+'h '+Math.floor((s%3600)/60)+'m'}, age=msv=>durSec(Number(msv||0)/1000);

// Lightweight pure-canvas chart renderer
function drawSpark(canvasId, points, strokeColor, fillColor){
  const cv=$(canvasId);if(!cv||!points.length)return;
  const ctx=cv.getContext('2d');if(!ctx)return;
  const w=cv.width,h=cv.height;
  ctx.clearRect(0,0,w,h);
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
  renderLine(series1, '#38bdf8', 'rgba(56,189,248,0.1)');
  renderLine(series2, '#34d399', 'rgba(52,211,153,0.1)');
}

const tracePageStyles=document.createElement('style');
tracePageStyles.textContent='.trace-page{height:calc(100vh - 112px);min-height:560px;padding:12px!important}.trace-layout{display:grid;grid-template-columns:300px minmax(0,1fr);height:100%;min-height:0;gap:12px}.trace-sidebar,.trace-main{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-height:0;overflow:hidden}.trace-sidebar{display:flex;flex-direction:column}.trace-sidebar-head{padding:12px;border-bottom:1px solid var(--line);background:#151d26}.trace-sidebar-head strong{display:block;font-size:14px;margin:7px 0 3px}.trace-sidebar-list{overflow:auto;padding:6px}.trace-side-item{display:block;width:100%;text-align:left;background:transparent;color:var(--fg);border:1px solid transparent;border-radius:7px;padding:9px;margin:2px 0;cursor:pointer}.trace-side-item:hover{background:#1a2734;border-color:#33485f}.trace-side-item.active{background:#1c3042;border-color:var(--accent)}.trace-side-top{display:flex;align-items:center;gap:7px}.trace-side-state{width:7px;height:7px;border-radius:50%;background:var(--warn);flex:0 0 auto}.trace-side-state.done{background:var(--ok)}.trace-side-state.failed{background:var(--bad)}.trace-side-action{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-side-meta{display:block;color:var(--muted);font-size:10px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-main{overflow:auto;padding:18px}.trace-main-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}.trace-main-head h1{font-size:18px;margin:0;overflow-wrap:anywhere}.trace-main-head .spacer{margin-left:auto}.trace-select-empty{display:grid;place-items:center;min-height:420px;color:var(--muted);text-align:center;border:1px dashed #33485f;border-radius:8px}.trace-main .human-shell{padding:0}.trace-main .human-section{margin:12px 0}.trace-main .trace-timeline{padding:12px}.trace-page .trace-raw-panel{max-width:none}@media(max-width:900px){.trace-page{height:auto;min-height:calc(100vh - 112px)}.trace-layout{grid-template-columns:1fr}.trace-sidebar{max-height:280px}.trace-main{min-height:620px}}';
document.head.append(tracePageStyles);

const workPageStyles=document.createElement('style');
workPageStyles.textContent='.work-page{display:grid!important;grid-template-columns:minmax(0,1.55fr) minmax(320px,.9fr);gap:12px;align-items:start}.work-page>.work-summary{grid-column:1/-1}.work-panel{min-width:0}.work-panel-1{grid-column:1;grid-row:2}.work-panel-2{grid-column:2;grid-row:2}.work-panel-3{grid-column:1;grid-row:3}.work-panel-4{grid-column:2;grid-row:3}.work-summary{padding:14px!important}.work-summary-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.work-kicker{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}.work-summary h2{margin:0}.work-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}.work-kpis>div{background:#0d141c;border:1px solid #2b3948;border-radius:7px;padding:9px 10px}.work-kpis span{display:block;color:var(--muted);font-size:10px}.work-kpis strong{display:block;font-size:18px;margin-top:3px}.work-panel h2{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.work-panel .table-wrap{max-height:390px;overflow:auto}.work-panel table{width:100%;table-layout:fixed}.work-panel th{position:sticky;top:0;z-index:1;background:#151d26}.work-panel td{vertical-align:top;overflow-wrap:anywhere}.work-panel-1 th:nth-child(1){width:13%}.work-panel-1 th:nth-child(2){width:20%}.work-panel-1 th:nth-child(3){width:24%}.work-panel-1 th:nth-child(4){width:17%}.work-panel-1 th:nth-child(5){width:26%}.work-panel-2 th:nth-child(1){width:27%}.work-panel-2 th:nth-child(2){width:30%}.work-panel-2 th:nth-child(3){width:27%}.work-panel-2 th:nth-child(4){width:16%}.work-panel-3 th:nth-child(1){width:14%}.work-panel-3 th:nth-child(2){width:22%}.work-panel-3 th:nth-child(3){width:23%}.work-panel-3 th:nth-child(4){width:23%}.work-panel-3 th:nth-child(5){width:18%}.work-panel-4 th:nth-child(1){width:13%}.work-panel-4 th:nth-child(2){width:22%}.work-panel-4 th:nth-child(3){width:22%}.work-panel-4 th:nth-child(4){width:18%}.work-panel-4 th:nth-child(5){width:15%}.work-panel-4 th:nth-child(6){width:10%}.work-state{display:inline-block;border:1px solid #3b4b5e;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px;white-space:nowrap}.work-state.live{border-color:#4f8edb;color:var(--accent)}.work-state.bad{border-color:#a64c4c;color:var(--bad)}.timing-label{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.04em}.work-panel-4 .tiny{line-height:1.35}@media(max-width:1050px){.work-page{grid-template-columns:1fr}.work-page>.work-summary,.work-panel-1,.work-panel-2,.work-panel-3,.work-panel-4{grid-column:1;grid-row:auto}.work-panel .table-wrap{max-height:320px}}@media(max-width:620px){.work-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.work-summary-head{display:block}.work-summary-head>.tiny{display:block;margin-top:6px}.work-panel table{table-layout:auto;min-width:650px}.work-panel .table-wrap{overflow:auto}}';
document.head.append(workPageStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-side-state.interrupted{background:var(--warn)}.trace-interrupted{color:var(--warn)}.work-page{display:none!important}.work-page.active{display:grid!important}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.work-page.active .work-panel-4{grid-column:1/-1!important;grid-row:3!important}.work-page.active .work-panel-4 .table-wrap{max-height:460px}.work-page.active .work-panel-3{grid-column:1/-1!important;grid-row:4!important}</style>');

const workFilterStyles=document.createElement('style');
workFilterStyles.textContent='.work-filter{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}.work-filter input,.work-filter select{background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px 9px;font:inherit;font-size:11px}.work-filter input{flex:1;min-width:220px}.work-filter select{min-width:125px}.work-filter .btn{padding:6px 9px;font-size:11px}.work-filter-summary{color:var(--muted);font-size:10px}';
document.head.append(workFilterStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-sidebar-controls{display:flex;gap:6px;padding:8px 8px 2px}.trace-sidebar-controls input,.trace-sidebar-controls select{min-width:0;width:100%;background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 7px;font:inherit;font-size:10px}.trace-sidebar-controls select{width:116px;flex:0 0 116px}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-main,.trace-step-body,.trace-event,.human-section{min-width:0}.prompt-meta{display:flex;gap:5px;flex-wrap:wrap;padding:7px 8px;border-bottom:1px solid #202a35}.prompt-chip{border:1px solid #394758;border-radius:999px;padding:2px 7px;color:var(--muted);font-size:9px}.prompt-chip strong{color:var(--fg)}.prompt-messages{display:grid;gap:6px;padding:7px}.prompt-card{border:1px solid #2d3d4e;border-left:3px solid #5b8def;border-radius:6px;overflow:hidden}.prompt-card.role-system{border-left-color:#a78bfa}.prompt-card.role-user{border-left-color:#38bdf8}.prompt-card.role-assistant{border-left-color:#4ade80}.prompt-card-head{display:flex;align-items:center;gap:7px;padding:6px 8px;background:#151d26;color:var(--fg);font-size:10px;font-weight:700}.prompt-card-head .tiny{margin-left:auto}.prompt-pre{margin:0;padding:7px 8px;background:#0d1219;color:#d7e2ef;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.3;font-size:11px;max-height:150px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}.prompt-context{margin:0 8px 8px;border:1px solid #334355;border-radius:5px;background:#111923}.prompt-context summary{cursor:pointer;padding:6px 8px;color:var(--muted);font-size:9px}.prompt-context .prompt-pre{max-height:180px;border-top:1px solid #273544}.prompt-fallback{padding:8px}</style>');

const nativeFetch=window.fetch.bind(window);
let apiToken='';
$('apiToken').value='';

function setupTraceInspector(){
  if($('traceInspector'))return;
  document.body.insertAdjacentHTML('beforeend','<div id="traceInspector" class="page trace-page"><div class="trace-layout"><aside class="trace-sidebar"><div class="trace-sidebar-head"><button class="btn" data-trace-back>← Queue & requests</button><strong>Agent trace history</strong><span class="tiny" id="traceSideSummary">Select a run to inspect</span></div><div id="traceSidebarList" class="trace-sidebar-list"></div></aside><main class="trace-main"><div class="trace-main-head"><div><h1 id="tracePageTitle">Select an agent trace</h1><span id="tracePageLive" class="tiny"></span></div><button class="btn spacer" data-trace-back>Back</button></div><div id="tracePageBody" class="trace-select-empty">Choose a trace from the left.</div></main></div></div>');
}
setupTraceInspector();
if($('traceSidebarList')&&!$('traceHistorySearch')){$('traceSidebarList').insertAdjacentHTML('beforebegin','<div class="trace-sidebar-controls"><input id="traceHistorySearch" type="search" placeholder="Search history…" autocomplete="off"><select id="traceHistoryState" aria-label="History state"><option value="useful">Live + completed</option><option value="">All history</option><option value="interrupted">Interrupted</option><option value="failed">Failed</option></select></div>')}

let sloScope=$('sloScope').value;
$('sloScope').onchange=()=>{sloScope=$('sloScope').value;pollStatus()};
$('saveToken').onclick=()=>{apiToken=$('apiToken').value.trim();pollStatus()};

async function apiFetch(path,opts={}){
  opts={...opts};const h=new Headers(opts.headers||{});if(apiToken)h.set('X-LocalAI-Token',apiToken);opts.headers=h;
  let r=await nativeFetch(path,opts);
  if(r.status===401&&!apiToken){
    const entered=prompt('Local AI Hub API token');
    if(entered){apiToken=entered.trim();$('apiToken').value=apiToken;try{sessionStorage.setItem('localAiHubToken',apiToken)}catch{};h.set('X-LocalAI-Token',apiToken);r=await nativeFetch(path,{...opts,headers:h})}
  }
  return r;
}
const rows=(id,items,fn,cols)=>{$(id).innerHTML=(items&&items.length)?items.map(fn).join(''):`<tr><td colspan="${cols}" class="muted">none</td></tr>`};
const dataStore=new Map(); let seq=0; function clickableRow(obj,html){const id='d'+(++seq);dataStore.set(id,obj);return `<tr class="click" data-detail="${id}">${html}</tr>`}

let traceTimer=null,activeTraceId='',traceSeq=0,traceEvents=[],traceOpenSteps=new Set(),traceView='timeline',activeTraceData=null;
const humanLabel=k=>String(k||'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()).replace(/\bApi\b/g,'API').replace(/\bId\b/g,'ID').replace(/\bUrl\b/g,'URL').replace(/\bHttp\b/g,'HTTP');

function renderAny(value){
  if(value===null||value===undefined)return '<span class="muted">—</span>';
  if(typeof value==='string'){return value.length>180?`<pre class="human-pre">${esc(value)}</pre>`:`<span class="human-value">${esc(value)||'<span class="muted">empty</span>'}</span>`}
  if(typeof value==='number'||typeof value==='boolean')return `<span class="human-value">${esc(String(value))}</span>`;
  if(Array.isArray(value))return value.length?`<div class="human-list">${value.map((v,i)=>`<div class="human-item"><div class="tiny muted">${i+1}</div>${renderAny(v)}</div>`).join('')}</div>`:'<div class="empty-human">empty list</div>';
  if(typeof value==='object'){const entries=Object.entries(value);return entries.length?`<div class="human-grid">${entries.map(([k,v])=>`<div>${esc(humanLabel(k))}</div><div>${renderAny(v)}</div>`).join('')}</div>`:'<div class="empty-human">empty object</div>'}
  return `<span class="human-value">${esc(String(value))}</span>`;
}
function promptText(value){
  if(typeof value==='string')return value;
  if(Array.isArray(value))return value.map(promptText).filter(Boolean).join('\n');
  if(value&&typeof value==='object'){
    if(value.text!==undefined)return promptText(value.text);
    if(value.content!==undefined)return promptText(value.content);
    if(value.messages!==undefined)return promptText(value.messages);
    return '';
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
function renderModelPrompt(prompt){
  const p=prompt&&typeof prompt==='object'?prompt:{},messages=Array.isArray(p.messages)?p.messages:[];
  if(!messages.length)return `<div class="prompt-fallback"><div class="prompt-card"><div class="prompt-card-head"><span>Model request</span></div>${promptBody(promptText(p.prompt??p.content??p.system??prompt))}</div></div>`;
  const cards=messages.map((message,index)=>{const role=String(message?.role||'message').toLowerCase(),label=role==='system'?'System instructions':role==='user'?'Task / user prompt':role==='assistant'?'Assistant context':humanLabel(role),text=promptText(message?.content??message?.text??message);return `<article class="prompt-card role-${esc(role)}"><div class="prompt-card-head"><span>${esc(label)}</span><span class="tiny">Message ${index+1} · ${n(text.length)} characters</span></div>${promptBody(text)}</article>`}).join('');
  const options=p.options&&typeof p.options==='object'?p.options:null,meta=[p.model&&`Model: ${p.model}`,`Messages: ${messages.length}`,p.stream!==undefined&&`Stream: ${p.stream?'on':'off'}`,p.keep_alive&&`Keep alive: ${p.keep_alive}`].filter(Boolean).map(x=>`<span class="prompt-chip"><strong>${esc(String(x).split(':')[0])}</strong>${esc(String(x).includes(':')?':'+String(x).split(':').slice(1).join(':'):'')}</span>`).join('');
  return `<div class="prompt-panel"><div class="prompt-meta">${meta}</div><div class="prompt-messages">${cards}</div>${options?`<details class="prompt-context"><summary>Generation settings · ${Object.keys(options).length} values</summary>${renderAny(options)}</details>`:''}</div>`;
}
function humanSection(title,value){return `<section class="human-section"><h3>${esc(title)}</h3>${renderAny(value)}</section>`}
function rawFallback(obj){let raw='';try{raw=JSON.stringify(obj,null,2)}catch(e){raw=String(e)}return `<details class="raw-json"><summary>Raw JSON (fallback)</summary><pre>${esc(raw)}</pre></details>`}
function toggleTraceStep(button){const step=button.closest('.trace-step');if(!step)return;const key=String(step.dataset.traceStep||'');const open=!step.classList.contains('open');step.classList.toggle('open',open);button.setAttribute('aria-expanded',String(open));if(open)traceOpenSteps.add(key);else traceOpenSteps.delete(key)}
function traceEventBody(event,events,index){
  const type=String(event.event_type||'event'),p=event.payload||{};
  if(type==='model_request')return renderModelPrompt(p);
  if(type==='tool_result'){
    const callId=p.call_id||'';
    if(callId&&events.slice(0,index).some(x=>x.event_type==='tool_call'&&((x.payload||{}).call_id||'')===callId))return '';
  }
  if(type==='tool_call'){
    const callId=p.call_id||'',result=events.slice(index+1).find(x=>x.event_type==='tool_result'&&(!callId||((x.payload||{}).call_id||'')===callId));
    return `<div class="tool-pair"><div class="tool-part tool-call"><div class="tool-label">Tool call <span class="tiny">${esc(p.name||p.tool||'unnamed')}</span></div>${renderAny(p.arguments??p.input??p)}</div>${result?`<div class="tool-part tool-result"><div class="tool-label">Tool result</div>${renderAny(result.payload||{})}</div>`:`<div class="tool-pending">Waiting for tool result…</div>`}</div>`;
  }
  if(type==='output_stream')return `<div class="trace-stream-summary"><strong>Model output · ${n(p.chunks||0)} chunks</strong><div class="trace-output">${esc(p.text||'')}${p.truncated?'…':''}</div></div>`;
  if(type==='output_delta')return `<div class="trace-output">${esc(p.text||'')}</div>`;
  return renderAny(p);
}
function compactTimelineEvents(events){
  const compact=[];let stream=null,streamBytes=0;
  (events||[]).forEach(event=>{
    const type=String(event.event_type||'event'),payload=event.payload||{};
    if(type==='output_delta'){
      if(!stream){stream={event_type:'output_stream',created_at:event.created_at,seq:event.seq,payload:{text:'',chunks:0,truncated:false}};compact.push(stream)}
      const text=String(payload.text||'');stream.payload.chunks+=1;stream.payload.text+=streamBytes<12000?text:'';streamBytes+=text.length;stream.seq=event.seq;
      if(streamBytes>12000)stream.payload.truncated=true;
      return;
    }
    if(type==='tool_result'){const callId=payload.call_id||'';if(callId&&compact.some(x=>x.event_type==='tool_call'&&((x.payload||{}).call_id||'')===callId))return;}
    compact.push(event);
  });
  return compact;
}
function traceTimeline(events){
  const groups=[];let current=null;
  (events||[]).forEach(event=>{const type=String(event.event_type||'event'),payload=event.payload||{};if(type==='model_request'||!current){current={index:groups.length+1,label:type==='model_request'?'Model request':'Execution',events:[]};groups.push(current)}if(type!=='model_request'&&payload&&payload.step){const step=Number(payload.step);current=groups.find(g=>g.step===step)||current}if(type==='model_request'&&payload&&payload.step)current.step=Number(payload.step);current.events.push(event)});
  if(!groups.length)return '<div class="empty-human">Waiting for agent events…</div>';
  return `<div class="trace-timeline">${groups.map((group,index)=>{const key=String(group.step||group.index),open=traceOpenSteps.size?traceOpenSteps.has(key):index===groups.length-1,eventsForDisplay=compactTimelineEvents(group.events);return `<div class="trace-step ${open?'open':''}" data-trace-step="${esc(key)}"><button class="trace-step-head" data-trace-toggle aria-expanded="${open}"><span class="trace-step-index">Step ${esc(key)}</span><span>${esc(humanLabel(group.label))}</span><span class="tiny">${group.events.length} events · ${eventsForDisplay.length} shown</span><span class="trace-step-chevron">▶</span></button><div class="trace-step-body">${eventsForDisplay.map((event,eventIndex)=>{const type=String(event.event_type||'event'),body=traceEventBody(event,eventsForDisplay,eventIndex);if(!body)return '';return `<div class="trace-event"><div class="event-head"><span class="event-type">${esc(humanLabel(type))}</span><span class="event-time">${event.created_at?new Date(event.created_at*1000).toLocaleTimeString():'—'} · #${esc(event.seq)}</span></div>${body}</div>`}).join('')}</div></div>`}).join('')}</div>`;
}
function renderHumanModal(obj){
  if(obj===null||typeof obj!=='object'){$('modalBody').innerHTML=`<div class="human-shell">${renderAny(obj)}${rawFallback(obj)}</div>`;return}
  const entries=Array.isArray(obj)?[]:Object.entries(obj),scalar=[],complex=[];
  entries.forEach(([k,v])=>(v&&typeof v==='object')?complex.push([k,v]):scalar.push([k,v]));
  const status=obj.state||obj.status||(obj.success===true?'success':obj.success===false?'failed':'');
  const summary=status?`<div class="human-summary"><span class="badge ${status==='failed'||status==='error'?'bad':'ok'}">${esc(humanLabel(status))}</span>${obj.error?`<span class="bad-t">${esc(obj.error)}</span>`:''}</div>`:'';
  const scalarGrid=scalar.length?`<section class="human-section"><h3>Summary</h3><div class="human-grid">${scalar.map(([k,v])=>`<div>${esc(humanLabel(k))}</div><div>${renderAny(v)}</div>`).join('')}</div></section>`:'';
  $('modalBody').innerHTML=`<div class="human-shell">${summary}${scalarGrid}${complex.map(([k,v])=>humanSection(humanLabel(k),v)).join('')}${rawFallback(obj)}</div>`;
}
function traceTab(label,id){return `<button class="trace-tab ${traceView===id?'active':''}" data-trace-view="${id}" aria-selected="${traceView===id}">${label}</button>`}
function traceStatus(item){const state=String(item?.state||'queued');return state==='failed'&&/hub restarted|service stopped|shutdown/i.test(String(item?.error||''))?'interrupted':state}
function traceDisplayState(item){const state=traceStatus(item);return state==='interrupted'?'Interrupted':humanLabel(state)}
function traceRaw(payload){let raw='';try{raw=JSON.stringify(payload,null,2)}catch(e){raw=String(e)}return `<section class="human-section trace-raw-panel"><h3>Raw JSON (fallback)</h3><pre class="human-pre">${esc(raw)}</pre></section>`}
function renderTraceDetail(d){
  activeTraceData=d;const s=d?.session||{},events=d?.events||[],payload={session:{trace_id:s.trace_id,kind:s.kind,state:s.state,tenant:s.tenant,agent:s.agent,action:s.action,source:s.source,model:s.model,request_id:s.request_id,async_job_id:s.async_job_id,scheduler_job_id:s.scheduler_job_id,created_at:s.created_at,updated_at:s.updated_at,finished_at:s.finished_at,error:s.error,text_bytes:s.text_bytes},main_agent_prompt:s.effective_payload||{},original_request:s.request||{},output:s.output||'',response:s.response||{},events};
  $('tracePageTitle').textContent=String(s.action||s.source||'Agent trace');$('tracePageLive').textContent=d?.terminal?'terminal · retained':'● live · auto-refresh';$('tracePageLive').className='tiny '+(d?.terminal?'ok':'trace-running');
  const state=traceDisplayState(s),displayState=traceStatus(s),stateClass=(displayState==='failed'||displayState==='error')?'bad':(displayState==='interrupted'?'warn':(d?.terminal?'ok':'warn'));
  const header=`<div class="trace-inspector-head"><div><div class="trace-kicker">Agent execution</div><strong>${esc(s.action||s.source||'Trace')}</strong><div class="tiny">${esc(s.agent||'unknown agent')} · ${esc(s.model||'model not recorded')}</div></div><span class="badge ${stateClass}">${esc(state)}</span></div><div class="trace-metrics"><span>${events.length} events</span><span>${esc(s.tenant||'no tenant')}</span><span>${s.text_bytes||0} bytes retained</span></div>`;
  const timeline=`<section class="human-section"><h3>Agent timeline (${events.length})</h3>${traceTimeline(events)}</section>`,prompt=renderModelPrompt(payload.main_agent_prompt)+humanSection('Original request',payload.original_request),output=humanSection('Output',payload.output),response=humanSection('Final response',payload.response),views={timeline, prompt:prompt, output:output+response, events:`<section class="human-section"><h3>All events</h3>${renderAny(events)}</section>`, raw:traceRaw(payload)},content=views[traceView]||timeline;
  $('tracePageBody').className='trace-page-body';$('tracePageBody').innerHTML=`<div class="human-shell">${header}<nav class="trace-tabs" aria-label="Trace views">${traceTab('Timeline','timeline')}${traceTab('Prompt','prompt')}${traceTab('Output','output')}${traceTab('Events','events')}${traceTab('Raw','raw')}</nav><div class="trace-view">${content}</div></div>`;
}
function setTraceView(view){if(!['timeline','prompt','output','events','raw'].includes(view))return;traceView=view;if(activeTraceData)renderTraceDetail(activeTraceData)}
async function openTrace(id){
  activeTraceId=String(id||'');traceSeq=0;traceEvents=[];traceOpenSteps=new Set();traceView='timeline';activeTraceData=null;
  renderTraceList(lastTraces);switchTab('traceInspector');
  if(traceTimer)clearInterval(traceTimer);
  const poll=async()=>{
    if(!activeTraceId)return;
    try{
      const r=await apiFetch('/v1/debug-traces/'+encodeURIComponent(activeTraceId)+'?since_seq='+traceSeq,{cache:'no-store'}),d=await r.json();
      if(d.success){
        traceSeq=Number(d.next_seq||traceSeq);traceEvents=traceEvents.concat(d.events||[]);renderTraceDetail({...d,events:traceEvents});
        if(d.terminal){clearInterval(traceTimer);traceTimer=null}
      }else{openModal(d,'Trace error');clearInterval(traceTimer);traceTimer=null}
    }catch(e){$('tracePageLive').textContent='refresh failed: '+e.message}
  };
  await poll();traceTimer=setInterval(poll,1000);
}
function openModal(obj,title='Details'){$('modalLive').textContent='';$('modalTitle').textContent=title;renderHumanModal(obj);$('modalBg').classList.add('open')}
$('modalClose').onclick=()=>{$('modalBg').classList.remove('open');activeTraceId='';activeTraceData=null;if(traceTimer)clearInterval(traceTimer);traceTimer=null};
$('modalBg').onclick=e=>{if(e.target===$('modalBg'))$('modalClose').click()};

document.addEventListener('click',e=>{
  const tab=e.target.closest?.('[data-trace-view]');if(tab){setTraceView(tab.dataset.traceView);return}
  const pageTrace=e.target.closest?.('[data-trace-page-id]');if(pageTrace){openTrace(pageTrace.dataset.tracePageId);return}
  const back=e.target.closest?.('[data-trace-back]');if(back){switchTab('work');return}
  const toggle=e.target.closest?.('[data-trace-toggle]');if(toggle){toggleTraceStep(toggle);return}
  if(e.target.closest('button, a, input, select, textarea, .action-btn-sm, [data-project-action], [data-export-root]'))return;
  const trace=e.target.closest?.('[data-trace-id]');if(trace){openTrace(trace.dataset.traceId);return}
  const tr=e.target.closest?.('[data-detail]');if(tr)openModal(dataStore.get(tr.dataset.detail)||{},'Details');
});

function switchTab(tabId){
  if(!tabId||!$(tabId))return;
  document.querySelectorAll('.tabbtn').forEach(x=>x.classList.toggle('active',x.dataset.tab===tabId));
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===tabId));
  try{localStorage.setItem('activeTab',tabId)}catch{}
  if(location.hash.replace('#','')!==tabId)history.replaceState(null,'','#'+tabId);
  if(tabId==='architecture'&&!archData)loadArchGraph();
  if(tabId==='config')loadConfigView();
  if(tabId==='agentos')loadAgentOsView();
  if(tabId==='performance'){loadInstalledModels();loadRagWorkspaces();loadActiveLeases();}
}
document.querySelectorAll('.tabbtn').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
window.addEventListener('hashchange',()=>switchTab(location.hash.replace('#','')));
$('pauseEvents').onclick=e=>{paused=!paused;e.target.textContent=paused?'Resume events':'Pause events'};
async function post(path,payload){const r=await apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});return await r.json()}

async function loadConfigView(){
  try{
    const r=await apiFetch('/v1/config',{cache:'no-store'}),d=await r.json();
    if(!d.success){$('cfgStatus').textContent=d.error||'failed';return}
    const c=d.config||{},feat=c.features||{};
    $('cfgProfile').value=c.hardware?.profile||'auto';
    $('cfgPreprocess').checked=c.preprocessing?.enabled!==false&&feat.preprocessing!==false;
    $('cfgIntel').checked=c.code_intelligence?.enabled!==false&&feat.code_intelligence!==false;
    $('cfgSerena').checked=!!c.code_intelligence?.serena_enabled;
    $('cfgCodegraph').checked=!!c.code_intelligence?.codegraph_enabled;
    if($('cfgFeatStatus'))$('cfgFeatStatus').checked=feat.status!==false;
    if($('cfgFeatRepo'))$('cfgFeatRepo').checked=feat.repo!==false;
    if($('cfgFeatTasks'))$('cfgFeatTasks').checked=feat.tasks!==false;
    if($('cfgFeatRag'))$('cfgFeatRag').checked=feat.rag!==false;
    if($('cfgFeatCommands'))$('cfgFeatCommands').checked=feat.commands!==false;
    if($('cfgFeatCoord'))$('cfgFeatCoord').checked=feat.coord!==false;
    if($('cfgFeatArtifacts'))$('cfgFeatArtifacts').checked=feat.artifacts!==false;
    if($('cfgFeatSubagents'))$('cfgFeatSubagents').checked=feat.subagents!==false;
    if($('cfgFeatAgentOs'))$('cfgFeatAgentOs').checked=feat.agent_os!==false;
    if($('cfgFeatDashboard'))$('cfgFeatDashboard').checked=feat.dashboard!==false;
    $('cfgPath').textContent=(d.config_path||'')+(d.runtime_override_path?' · overrides '+d.runtime_override_path:'');
    $('cfgPreview').textContent=JSON.stringify(c,null,2);
    $('cfgStatus').textContent='';
  }catch(e){$('cfgStatus').textContent=String(e)}
}
$('cfgReload').onclick=loadConfigView;
$('cfgSave').onclick=async()=>{
  const settings={
    'hardware.profile':$('cfgProfile').value,
    'preprocessing.enabled':$('cfgPreprocess').checked,
    'code_intelligence.enabled':$('cfgIntel').checked,
    'code_intelligence.serena_enabled':$('cfgSerena').checked,
    'code_intelligence.codegraph_enabled':$('cfgCodegraph').checked,
    'features.status':$('cfgFeatStatus')?$('cfgFeatStatus').checked:true,
    'features.repo':$('cfgFeatRepo')?$('cfgFeatRepo').checked:true,
    'features.tasks':$('cfgFeatTasks')?$('cfgFeatTasks').checked:true,
    'features.rag':$('cfgFeatRag')?$('cfgFeatRag').checked:true,
    'features.commands':$('cfgFeatCommands')?$('cfgFeatCommands').checked:true,
    'features.coord':$('cfgFeatCoord')?$('cfgFeatCoord').checked:true,
    'features.artifacts':$('cfgFeatArtifacts')?$('cfgFeatArtifacts').checked:true,
    'features.code_intelligence':$('cfgIntel').checked,
    'features.preprocessing':$('cfgPreprocess').checked,
    'features.subagents':$('cfgFeatSubagents')?$('cfgFeatSubagents').checked:true,
    'features.agent_os':$('cfgFeatAgentOs')?$('cfgFeatAgentOs').checked:true,
    'features.dashboard':$('cfgFeatDashboard')?$('cfgFeatDashboard').checked:true
  };
  const r=await post('/v1/config/update',{action:'update',settings});
  $('cfgStatus').textContent=r.success?'saved · restart hub to apply':('error: '+(r.error||'failed'));
  if(r.success)loadConfigView();
};
$('cfgReset').onclick=async()=>{
  if(!confirm('Reset dashboard-managed configuration overrides?'))return;
  const r=await post('/v1/config/update',{action:'reset'});
  $('cfgStatus').textContent=r.success?'overrides reset · restart hub to apply':('error: '+(r.error||'failed'));
  if(r.success)loadConfigView();
};

$('cmdClassify').onclick=async()=>{const command=$('cmdInput').value.trim();if(!command)return;$('cmdOutput').textContent=JSON.stringify(await post('/v1/command',{action:'classify',command}),null,2)};
$('cmdRun').onclick=async()=>{
  const command=$('cmdInput').value.trim(),cwd=$('cmdRoot').value.trim();
  if(!command||!cwd){$('cmdOutput').textContent='Repository root and command are required.';return}
  const c=await post('/v1/command',{action:'classify',command});
  if(!c?.classification?.allowed){$('cmdOutput').textContent=JSON.stringify(c,null,2);return}
  if(!confirm('Run this '+c.classification.class+' command?\n\n'+command))return;
  $('cmdRun').disabled=true;
  try{$('cmdOutput').textContent=JSON.stringify(await post('/v1/command',{action:'run',command,cwd,force:true}),null,2)}
  finally{$('cmdRun').disabled=false;pollStatus()}
};

$('intelRediscover').onclick=async()=>{$('intelControlStatus').textContent='working…';const r=await post('/v1/code-intelligence/control',{action:'rediscover'});$('intelControlStatus').textContent=r.success?'rediscovery complete':'error: '+(r.error||'failed');pollStatus()};
$('intelReset').onclick=async()=>{if(!confirm('Reset all managed Serena/CodeGraph MCP sessions?'))return;$('intelControlStatus').textContent='working…';const r=await post('/v1/code-intelligence/control',{action:'reset',backend:'all'});$('intelControlStatus').textContent=r.success?'sessions reset':'error: '+(r.error||'failed');pollStatus()};

let logLines=['Click Refresh to load logs.'];
async function loadLogsTail(){
  try{
    const lines=$('logLinesSelect')?.value||'250';
    const r=await apiFetch('/v1/logs/tail?lines='+lines,{cache:'no-store'}),d=await r.json();
    logLines=d.success?(d.lines||[]):[JSON.stringify(d,null,2)];
    renderFilteredLogs();
  }catch(e){$('logTail').textContent=String(e)}
}
function renderFilteredLogs(){
  const q=String($('logFilterInput')?.value||'').trim().toLowerCase();
  const filtered=q?logLines.filter(l=>l.toLowerCase().includes(q)):logLines;
  $('logTail').textContent=filtered.length?filtered.join('\n'):'No log lines matching filter.';
}
$('loadLogs').onclick=loadLogsTail;
$('logFilterInput')?.addEventListener('input',renderFilteredLogs);
$('logLinesSelect')?.addEventListener('change',loadLogsTail);
$('copyLogsBtn')?.addEventListener('click',()=>{
  navigator.clipboard.writeText($('logTail').textContent||'');
  $('copyLogsBtn').textContent='Copied!';
  setTimeout(()=>{$('copyLogsBtn').textContent='Copy'},1500);
});

let preprocessActionInFlight=false;
async function setPreprocessing(action){
  if(preprocessActionInFlight)return;
  preprocessActionInFlight=true;
  const buttons=[$('prepToggle'),$('prepAllToggle')].filter(Boolean);
  buttons.forEach(b=>b.disabled=true);
  try{
    const result=await post('/v1/preprocess',{action});
    if(result?.success){last={...last,preprocessing:result};render(last)}
    await pollStatus();
  }catch(e){alert('Preprocessing action failed: '+(e.message||e));await pollStatus()}
  finally{buttons.forEach(b=>b.disabled=false);preprocessActionInFlight=false}
}
function togglePreprocessing(){return setPreprocessing(last?.preprocessing?.paused?'resume':'pause')}
$('prepToggle').onclick=togglePreprocessing;
$('prepAllToggle').onclick=togglePreprocessing;

function refreshProjectList(){renderProjects(last?.preprocessing?.projects||[])}
$('projectSearch').oninput=e=>{projectQuery=e.target.value;refreshProjectList()};
$('projectFilter').onchange=e=>{projectFilter=e.target.value;refreshProjectList()};
$('projectSort').onchange=e=>{projectSort=e.target.value;refreshProjectList()};

const PHASES = [
  {id:'inventory', name:'Discovery', icon:'📁', desc:'File inventory & change discovery'},
  {id:'hash', name:'Content Hash', icon:'⚡', desc:'SHA256 content hashing & cache linking'},
  {id:'code_index', name:'AST Symbols', icon:'🌲', desc:'Symbol & callgraph extraction'},
  {id:'deterministic', name:'Declarative Facts', icon:'📋', desc:'Routes, models & configs'},
  {id:'serena', name:'Serena', icon:'S', desc:'Semantic/LSP project index'},
  {id:'codegraph', name:'CodeGraph', icon:'G', desc:'Repository relationship graph'},
  {id:'lexical', name:'Full-Text Search', icon:'🔍', desc:'FTS5 lexical keyword index'},
  {id:'rag', name:'Vector RAG', icon:'🧠', desc:'768-dim CPU code embeddings'},
  {id:'files', name:'Semantic Cards', icon:'📄', desc:'cached semantic context cards'},
  {id:'modules', name:'Module Graph', icon:'📦', desc:'Module topology synthesis'},
  {id:'project', name:'Architecture', icon:'🏗️', desc:'Project-level graph'},
  {id:'hot_queries', name:'Intent Pre-warm', icon:'🔥', desc:'Top query pre-warming'},
  {id:'complete', name:'Ready', icon:'✅', desc:'Fully indexed & synchronized'}
];

function renderStepper(currIdx, isComplete, status) {
  return `<div class="pipeline-stepper" title="Pipeline: ${isComplete ? 'All '+PHASES.length+' phases complete' : 'Phase ' + currIdx + ' active'}">` +
    PHASES.map((p, i) => {
      const stepNum = i + 1;
      let cls = 'pipe-pend', sym = stepNum;
      if (isComplete || stepNum < currIdx) { cls = 'pipe-done'; sym = '✓'; }
      else if (stepNum === currIdx) { cls = (status === 'error') ? 'pipe-pend bad-t' : 'pipe-curr'; sym = p.icon; }
      return `<span class="pipe-step ${cls}" title="${stepNum}. ${p.name}: ${p.desc}">${sym}</span>`;
    }).join('') + `</div>`;
}

let projectQuery='',projectFilter='all',projectSort='priority';
function projectState(x){
  const progress=Number(x.overall_progress_pct||0);
  if(x.phase==='complete'||x.status==='complete'||progress>=100)return 'ready';
  if(x.paused||x.status==='paused')return 'paused';
  if(x.status==='error'||x.last_error)return 'error';
  if(x.waiting||x.status==='waiting')return 'waiting';
  if(x.status==='running')return 'running';
  return 'queued';
}

function renderProjects(items){
  const source=Array.isArray(items)?items:[],query=projectQuery.trim().toLowerCase();
  const rank={error:0,running:1,waiting:2,queued:3,paused:4,ready:5};
  const visible=source.filter(x=>{
    const state=projectState(x),haystack=[x.project,x.root,x.active_detail,x.phase].join(' ').toLowerCase();
    return (!query||haystack.includes(query))&&(projectFilter==='all'||state===projectFilter);
  });
  visible.sort((a,b)=>{
    if(projectSort==='name')return String(a.project||'').localeCompare(String(b.project||''));
    if(projectSort==='progress')return Number(b.overall_progress_pct||0)-Number(a.overall_progress_pct||0)||String(a.project||'').localeCompare(String(b.project||''));
    if(projectSort==='recent')return Number(b.updated_at||b.last_complete_at||0)-Number(a.updated_at||a.last_complete_at||0)||String(a.project||'').localeCompare(String(b.project||''));
    return (rank[projectState(a)]??9)-(rank[projectState(b)]??9)||String(a.project||'').localeCompare(String(b.project||''));
  });
  const summary=$('projectSummary');
  if(summary)summary.textContent=`${visible.length} of ${source.length} projects`;
  rows('projectsBody',visible,x=>{
    const state=projectState(x),tot=Math.max(1,Number(x.files||0)),ragFiles=Number(x.rag_files||0),cards=Number(x.file_cards||0),ragPct=Math.round(ragFiles/tot*100),cardPct=Math.round(cards/tot*100),overall=Math.max(0,Math.min(100,Number(x.overall_progress_pct||0))),phasePct=Math.max(0,Math.min(100,Number(x.phase_progress_pct||0))),isComplete=state==='ready',isWorktree=(x.root||'').toLowerCase().includes('worktree');
    const badge={running:['badge-running','Running','<span class="pulse-dot"></span>'],waiting:['badge-waiting','Waiting',''],paused:['badge-paused','Paused',''],error:['badge-error','Error',''],ready:['badge-complete','Ready','✓ ']}[state]||['badge-waiting','Queued',''];
    const activityText=x.active_detail||(isComplete?'100% synchronized · real-time sync':state==='paused'?(x.global_paused?'Globally paused':'Project paused'):state==='waiting'?'Waiting for preprocessing slot':state==='error'?(x.last_error_short||'Pipeline error'):'Processing queue');
    const activityCls=isComplete?'ok':state==='error'?'bad-t':state==='paused'?'warn-t':state==='waiting'?'muted':'';
    const progressAge=Number(x.progress_age_seconds),progressHint=Number.isFinite(progressAge)?(progressAge<5?'live checkpoint':`${durSec(progressAge)} since last checkpoint`):'';
    const phaseObj=PHASES.find(ph=>ph.id===x.phase)||(isComplete?PHASES[PHASES.length-1]:{name:x.phase||'Inventory',icon:'⚙️'}),phaseTitle=isComplete?`${PHASES.length}/${PHASES.length} Ready`:`${n(x.phase_index||1)}/${PHASES.length} ${phaseObj.icon} ${phaseObj.name}`;
    const actions=`<div class="project-actions"><button class="action-btn-sm" data-project-action="${state==='paused'?'resume':'pause'}" data-project-root="${esc(x.root)}" title="${state==='paused'?'Resume project preprocessing':'Pause project'}">${state==='paused'?'▶ Resume':'⏸ Pause'}</button><button class="action-btn-sm" data-project-action="refresh" data-project-root="${esc(x.root)}" title="Force re-scan and synchronize">↻</button><button class="action-btn-sm danger" data-project-action="delete" data-project-root="${esc(x.root)}" data-project-name="${esc(x.project)}" title="Unregister / Delete project">🗑</button></div>`;
    return clickableRow(x,`<td><div class="project-name"><b>${esc(x.project)}</b>${isWorktree?'<span class="chip" style="font-size:9px;color:var(--accent2);border-color:#584578">worktree</span>':''}</div><div class="tiny muted mono project-root" title="${esc(x.root)}">${esc(x.root)}</div></td><td><span class="badge-status ${badge[0]}">${badge[2]}${badge[1]}</span><div class="tiny ${activityCls} project-activity" title="${esc(x.active_detail||activityText)}">${esc(activityText)}</div><div class="tiny muted">${esc(progressHint)}</div></td><td><div class="project-progress-line"><b>${phaseTitle}</b><span>${overall}%</span></div><div class="bar project-progress"><i style="width:${overall}%;background:${state==='error'?'var(--bad)':isComplete?'var(--ok)':'var(--accent)'}"></i></div><div class="tiny muted">${phasePct}% in phase</div></td><td><div class="project-index"><span class="${ragFiles>=tot?'ok':''}">🧠 RAG ${ragPct}%</span><span class="${cards>=tot*0.9?'ok':''}">📄 Cards ${cardPct}%</span></div></td><td>${actions}</td>`);
  },5);
}
async function projectAction(root, action) {
  try { await post('/v1/preprocess', { root, action }); await pollStatus(); } catch(e) { alert('Action error: ' + e); }
}
$('regProjectBtn').onclick = () => {
  const path = prompt('Enter absolute path of project or repository to register:');
  if (!path || !path.trim()) return;
  const force = confirm('Perform initial force re-scan for all files? (Cancel for incremental fast sync)');
  projectRegister(path.trim(), force);
};
async function projectRegister(root, force) {
  try {
    const r = await post('/v1/preprocess', { root, action: force ? 'refresh' : 'register' });
    openModal(r, 'Project Registration: ' + root);
    await pollStatus();
  } catch(e) {
    openModal({ error: String(e) }, 'Registration Error');
  }
}
$('cleanMissingBtn').onclick = async () => {
  if (!confirm('Scan registered projects and prune deleted/missing worktree directories from database? (Reusable content caches remain preserved)')) return;
  try {
    const r = await post('/v1/preprocess', { action: 'cleanup_deleted' });
    openModal(r, 'Missing Worktrees Cleanup Results');
    await pollStatus();
  } catch(e) {
    openModal({ error: String(e) }, 'Cleanup Error');
  }
};
async function deleteProjectDialog(root, name) {
  const choice = prompt(
    `Unregister / Delete Project "${name}"?\nRoot: ${root}\n\n` +
    `Type 1 to UNREGISTER only (preserves deduplicated cache for instant reuse)\n` +
    `Type 2 to PURGE all workspace index data and unregister completely\n\n` +
    `Enter choice (1 or 2):`,
    "1"
  );
  if (!choice) return;
  const purge = choice.trim() === "2";
  try {
    const r = await post('/v1/preprocess', { root, action: 'unregister', purge_data: purge });
    openModal(r, (purge ? 'Purged & Unregistered: ' : 'Unregistered: ') + name);
    await pollStatus();
  } catch(e) {
    openModal({ error: String(e) }, 'Unregister Error');
  }
}

$('restartHub').onclick=async()=>{if(!confirm('Restart Local AI Hub now? Running requests will be interrupted and may retry from cache/recovery journal.'))return;try{await post('/v1/control',{action:'restart_hub'})}catch{} };
$('stopService').onclick=async()=>{if(!confirm('Stop Local AI Hub and disable automatic restart? Start it later with hubctl/service start.'))return;try{await post('/v1/control',{action:'stop_service'});$('conn').textContent='stopping';$('conn').className='pill warn-t'}catch{} };
$('optDbBtn').onclick=async()=>{try{const r=await post('/v1/maintenance/optimize_db',{});openModal(r,'Database Optimization & WAL Checkpoint Results')}catch(e){openModal({error:String(e)},'Error')}};
$('purgeCacheBtn').onclick=async()=>{if(!confirm('Purge cache entries older than 7 days?'))return;try{const r=await post('/v1/maintenance/purge_cache',{days:7});openModal(r,'Cache Purge Results')}catch(e){openModal({error:String(e)},'Error')}};
$('doctorBtn').onclick=async()=>{try{const r=await post('/v1/doctor',{});openModal(r,'Local AI Hub Doctor Health Diagnostics')}catch(e){openModal({error:String(e)},'Error')}};

// Symbol Search & Inspector
$('codeSearchBtn').onclick=async()=>{
  const sym=$('codeSearchInput').value.trim();if(!sym)return;
  try{
    const r=await(await apiFetch('/v1/code/symbol?symbol='+encodeURIComponent(sym))).json();
    if(r.success){
      $('symbolDetails').style.display='block';
      $('symName').textContent=r.name||sym;
      $('symKind').textContent=r.kind||'symbol';
      $('symPath').textContent=r.path||'unknown';
      $('symLines').textContent=(r.line||0)+'-'+(r.end_line||0);
      $('symCode').textContent=r.snippet||r.code||'// No snippet available';
    }else{openModal(r,'Symbol Search')}
  }catch(e){openModal({error:String(e)},'Error')}
};
$('codeSearchInput').onkeydown=e=>{if(e.key==='Enter')$('codeSearchBtn').click()};
$('genTestsBtn').onclick=async()=>{const path=$('symPath').textContent,sym=$('symName').textContent;if(!path)return;try{const r=await post('/v1/generate_tests',{file:path,symbol:sym});openModal(r,'Generated Automated Unit Tests')}catch(e){openModal({error:String(e)},'Error')}};
$('impactCheckBtn').onclick=async()=>{const path=$('symPath').textContent,sym=$('symName').textContent;if(!path)return;try{const r=await post('/v1/refactor_impact',{file:path,symbol:sym});openModal(r,'Refactoring Impact & Risk Analysis')}catch(e){openModal({error:String(e)},'Error')}};
$('resolveImpBtn').onclick=async()=>{const sym=$('symName').textContent;if(!sym)return;try{const r=await post('/v1/resolve_imports',{symbols:[sym],language:'csharp'});openModal(r,'Missing Imports & Namespace Resolver')}catch(e){openModal({error:String(e)},'Error')}};
$('findDeclBtn')?.addEventListener('click',async()=>{const sym=$('symName').textContent;if(!sym)return;try{const r=await(await apiFetch('/v1/code/find_declaration?symbol='+encodeURIComponent(sym))).json();openModal(r,'Declaration: '+sym)}catch(e){openModal({error:String(e)},'Error')}});
$('findRefsBtn')?.addEventListener('click',async()=>{const sym=$('symName').textContent;if(!sym)return;try{const r=await(await apiFetch('/v1/code/find_referencing_symbols?symbol='+encodeURIComponent(sym))).json();openModal(r,'Referencing Symbols: '+sym)}catch(e){openModal({error:String(e)},'Error')}});
$('findImplBtn')?.addEventListener('click',async()=>{const sym=$('symName').textContent;if(!sym)return;try{const r=await(await apiFetch('/v1/code/find_implementations?symbol='+encodeURIComponent(sym))).json();openModal(r,'Implementations: '+sym)}catch(e){openModal({error:String(e)},'Error')}});

// File AST Outline & Diagnostics
$('codeOutlineBtn')?.addEventListener('click',async()=>{
  const path=$('codeFileInput')?.value?.trim();if(!path)return;
  try{
    const r=await(await apiFetch('/v1/code/ast_outline?path='+encodeURIComponent(path))).json();
    $('fileAnalysisDetails').style.display='block';
    $('fileAnalysisTitle').textContent='AST Structure: '+path;
    if(r.classes||r.functions||r.imports){
      let html='<div style="display:grid;gap:8px">';
      if(r.classes?.length)html+=`<div><b>Classes (${r.classes.length}):</b><div style="margin-top:4px">${r.classes.map(c=>`<span class="chip">class <b>${esc(c.name)}</b> (${c.line}-${c.end_line})</span>`).join(' ')}</div></div>`;
      if(r.functions?.length)html+=`<div><b>Functions / Methods (${r.functions.length}):</b><div style="margin-top:4px">${r.functions.map(f=>`<span class="chip">fn <b>${esc(f.name)}</b> (${f.line}-${f.end_line})</span>`).join(' ')}</div></div>`;
      if(r.imports?.length)html+=`<div><b>Imports (${r.imports.length}):</b><div style="margin-top:4px">${r.imports.slice(0,25).map(i=>`<span class="chip mono">${esc(i)}</span>`).join(' ')}</div></div>`;
      html+='</div>';
      $('fileAnalysisContent').innerHTML=html;
    }else{
      $('fileAnalysisContent').innerHTML=`<pre style="background:#0d1219;padding:10px;border-radius:6px;max-height:300px;overflow:auto">${esc(JSON.stringify(r,null,2))}</pre>`;
    }
  }catch(e){openModal({error:String(e)},'Outline Error')}
});
$('codeDiagBtn')?.addEventListener('click',async()=>{
  const path=$('codeFileInput')?.value?.trim();if(!path)return;
  try{
    const r=await(await apiFetch('/v1/code/diagnostics?path='+encodeURIComponent(path))).json();
    $('fileAnalysisDetails').style.display='block';
    $('fileAnalysisTitle').textContent='Diagnostics: '+path;
    const diags=r.diagnostics||[];
    if(diags.length){
      $('fileAnalysisContent').innerHTML=`<table><thead><tr><th>Severity</th><th>Line</th><th>Column</th><th>Message</th></tr></thead><tbody>${diags.map(d=>`<tr><td><span class="chip ${d.severity==='error'?'bad-t':'warn-t'}">${esc(d.severity)}</span></td><td>${n(d.line)}</td><td>${n(d.column)}</td><td>${esc(d.message)}</td></tr>`).join('')}</tbody></table>`;
    }else{
      $('fileAnalysisContent').innerHTML='<div class="ok" style="padding:10px">✅ No compiler or linter diagnostics reported. Clean file.</div>';
    }
  }catch(e){openModal({error:String(e)},'Diagnostics Error')}
});

function ensureHttpTailTable(){
  const performance=$('performance');if(!performance||$('httpTail'))return;
  performance.insertAdjacentHTML('beforeend','<section class="section"><h2>HTTP tail latency <span class="tiny">per action · excludes policy rejections</span></h2><div class="table-wrap"><table><thead><tr><th>Action</th><th>Calls</th><th>p50</th><th>p95</th><th>p99</th><th>Fails</th></tr></thead><tbody id="httpTail"></tbody></table></div></section>');
}
function setupWorkLayout(){
  const work=$('work');if(!work||work.dataset.refined)return;work.dataset.refined='1';work.classList.add('work-page');
  const sections=[...work.children].filter(x=>x.classList.contains('section'));sections.forEach((x,i)=>x.classList.add('work-panel','work-panel-'+(i+1)));
  const headers=[['State','Work item','Model / source','Timing','Reason'],['Request','Agent / tenant','Action','Age'],['Time','Request','Agent / tenant','Action','Result / duration'],['State','Kind / action','Agent / tenant','Model','Last activity','Link']];
  sections.forEach((section,index)=>{const row=section.querySelector('thead tr');if(row&&headers[index])row.innerHTML=headers[index].map(x=>`<th>${x}</th>`).join('')});
  work.insertAdjacentHTML('afterbegin','<section class="section work-summary"><div class="work-summary-head"><div><div class="work-kicker">Operations center</div><h2>Live work <span class="tiny">prioritized view</span></h2></div><span class="tiny">Click any row to inspect its trace</span></div><div class="work-kpis"><div><span>Queued</span><strong id="workQueued">—</strong></div><div><span>Running</span><strong id="workRunning">—</strong></div><div><span>Active API</span><strong id="workActive">—</strong></div><div><span>Retained traces</span><strong id="workRetained">—</strong></div></div><div class="work-filter"><input id="workSearch" type="search" placeholder="Search agent, tenant, action, model…" autocomplete="off"><select id="workState" aria-label="Work state"><option value="">All states</option><option value="running">Running</option><option value="queued">Queued</option><option value="failed">Failed</option><option value="completed">Completed</option></select><button class="btn" id="workReset">Reset</button><span class="work-filter-summary" id="workFilterSummary"></span></div></section>');
  $('workSearch').oninput=()=>last&&render(last);$('workState').onchange=()=>last&&render(last);$('workReset').onclick=()=>{$('workSearch').value='';$('workState').value='';if(last)render(last)};
}
function workVisible(items){const query=String($('workSearch')?.value||'').trim().toLowerCase(),state=String($('workState')?.value||'').toLowerCase();return (items||[]).filter(item=>{const itemState=String(item.state||item.status||'').toLowerCase(),hay=Object.values(item||{}).join(' ').toLowerCase();return (!query||hay.includes(query))&&(!state||(state==='completed'?['completed','complete','succeeded','success','done'].includes(itemState):itemState===state||(state==='running'&&itemState==='processing')))});}
function workState(state){const value=String(state||'queued'),cls=value==='failed'||value==='error'?'bad':(value==='running'||value==='processing'?'live':'');return `<span class="work-state ${cls}">${esc(value)}</span>`}
function workSchedulerRow(job){const inner=`<td>${workState(job.state)}</td><td><strong>#${n(job.job_id)}</strong><div class="tiny">${esc(job.tenant||'—')}</div></td><td><strong>${esc(job.model||'—')}</strong><div class="tiny">${esc(job.source||'—')}</div></td><td><span class="timing-label">wait</span> ${ms(job.wait_ms)}<div><span class="timing-label">run</span> ${ms(job.service_ms)}</div></td><td>${esc(job.wait_reason||'ready')}</td>`;return schedulerRow(job,inner,5)}
function workActiveRequestRow(request){const inner=`<td><strong>${esc(request.request_id||'—')}</strong></td><td>${esc(request.agent||'—')}<div class="tiny">${esc(request.tenant||'—')}</div></td><td>${esc(request.action||'—')}</td><td>${age(request.age_ms)}</td>`;return requestRow(request,inner,4)}
function workRecentRequestRow(request){const inner=`<td>${request.created_at?new Date(request.created_at*1000).toLocaleTimeString():'—'}</td><td><strong>${esc(request.request_id||'—')}</strong></td><td>${esc(request.agent||'—')}<div class="tiny">${esc(request.tenant||'—')}</div></td><td>${esc(request.action||'—')}</td><td><span class="${request.success?'ok':'bad-t'}">${n(request.status_code)||'—'}</span><div class="tiny">${ms(request.duration_ms)}</div></td>`;return requestRow(request,inner,5)}

function render(s){
  last=s;dataStore.clear();seq=0;
  const q=s.scheduler||{},o=s.observability||{},p=s.preprocessing||{},bg=s.background_gpu||{},h=s.headless||{},r=s.runtime_stats||{},ss=q.stats||{},rp=s.runtime_profile||{},cmd=r.commands||{};
  ensureHttpTailTable();setupWorkLayout();

  (function renderFeaturePills(){
    const feat=s.features||{};
    const mods=[
      {k:'status',label:'Status',tool:'local_ai_status',tab:'overview'},
      {k:'repo',label:'Repo',tool:'local_ai_repo',tab:'projects'},
      {k:'tasks',label:'Tasks',tool:'local_ai_task',tab:'performance'},
      {k:'rag',label:'RAG',tool:'local_ai_rag',tab:'performance'},
      {k:'commands',label:'Commands',tool:'local_ai_command',tab:'commands'},
      {k:'coord',label:'Coord',tool:'local_ai_coord',tab:'work'},
      {k:'artifacts',label:'Artifacts',tool:'local_ai_artifact',tab:'overview'},
      {k:'code_intelligence',label:'Code intel',tool:'AST / Serena / Graph',tab:'explorer'},
      {k:'preprocessing',label:'Preprocessing',tool:'Background workers',tab:'projects'},
      {k:'subagents',label:'Subagents',tool:'Ollama workers',tab:'performance'},
      {k:'agent_os',label:'Agent OS',tool:'Durable memory/receipts',tab:'agentos'},
      {k:'dashboard',label:'Dashboard',tool:'Web UI',tab:'config'},
    ];
    const pills=$('featurePills');
    if(pills){
      const disabledMods=mods.filter(m=>feat[m.k]===false);
      const enabledCount=mods.filter(m=>feat[m.k]!==false).length;
      pills.innerHTML=mods.map(m=>{
        const off=feat[m.k]===false;
        return `<button class="chip" data-goto-tab="${m.tab}" style="cursor:pointer;${off?'border-color:#7f1d1d;color:#f87171;background:#450a0a33':'border-color:#065f46;color:#34d399;background:#064e3b22'}" title="${m.k}: ${off?'disabled':'active'} · tool: ${m.tool}"><b>${m.label}</b> ${off?'<span class="tiny bad-t">✗ off</span>':'<span class="tiny ok">✓ on</span>'}</button>`;
      }).join('');
      pills.querySelectorAll('[data-goto-tab]').forEach(btn=>btn.onclick=()=>switchTab(btn.dataset.gotoTab));
      const txt=$('featStatusText');
      if(txt){
        if(disabledMods.length){txt.innerHTML=`<span class="warn-t">${disabledMods.length} module${disabledMods.length>1?'s':''} disabled</span>`;txt.title=disabledMods.map(m=>m.k).join(', ');}
        else{txt.innerHTML='<span class="ok">All 12 modules active</span>';txt.title='';}
      }
      const sumEl=$('featSummary');
      if(sumEl){
        sumEl.style.cursor='pointer';
        sumEl.onclick=()=>switchTab('config');
        if(disabledMods.length){sumEl.textContent=enabledCount+'/'+mods.length+' modules active';sumEl.className='pill tiny warn-t';}
        else{sumEl.textContent='12/12 modules active ✓';sumEl.className='pill tiny ok';}
      }
    }
    document.querySelectorAll('.tabbtn[data-feature]').forEach(b=>{
      const f=b.dataset.feature;
      const off=feat[f]===false;
      b.classList.toggle('tab-disabled',off);
      let badge=b.querySelector('.tab-badge');
      if(off){if(!badge){badge=document.createElement('span');badge.className='tab-badge bad-t';badge.textContent='(off)';b.appendChild(badge);}}
      else if(badge){badge.remove();}
    });
    if($('cmdDisabledBanner'))$('cmdDisabledBanner').style.display=feat.commands===false?'flex':'none';
    if($('intelDisabledBanner'))$('intelDisabledBanner').style.display=feat.code_intelligence===false?'flex':'none';
    if($('agentOsDisabledBanner'))$('agentOsDisabledBanner').style.display=feat.agent_os===false?'flex':'none';
    if(feat.commands===false){
      if($('cmdRun')){$('cmdRun').disabled=true;$('cmdRun').title='Commands feature disabled';}
      if($('cmdClassify')){$('cmdClassify').disabled=true;$('cmdClassify').title='Commands feature disabled';}
    }else{
      if($('cmdRun')){$('cmdRun').disabled=false;$('cmdRun').title='';}
      if($('cmdClassify')){$('cmdClassify').disabled=false;$('cmdClassify').title='';}
    }
    if(feat.tasks===false){
      if($('fgQueue'))$('fgQueue').innerHTML='<span class="muted">local LLM tasks disabled</span>';
      if($('bgQueue'))$('bgQueue').innerHTML='<span class="muted">tasks feature disabled (features.tasks=false)</span>';
    }
    if(feat.preprocessing===false){
      if($('prep'))$('prep').innerHTML='<span class="muted">disabled</span>';
      if($('prepSub'))$('prepSub').textContent='features.preprocessing = false';
    }
    if(feat.agent_os===false){
      if($('agentStateVal'))$('agentStateVal').innerHTML='<span class="muted">disabled</span>';
      if($('agentStateSub'))$('agentStateSub').textContent='features.agent_os = false';
    }
  })();

  const scopeLabel=sloScope==='process'?'since restart':'30d';
  $('handledRequestsLabel').textContent='Requests handled · '+scopeLabel;
  $('tokensSavedLabel').textContent='Tokens saved · '+scopeLabel;
  $('dollarsSavedLabel').textContent='Estimated savings · '+scopeLabel;
  $('cacheLabel').textContent='Cache hit rate · '+scopeLabel;
  $('reliabilityLabel').textContent='Reliability · '+scopeLabel;

  const firstProject=(p.projects||[]).find(x=>x.root);
  if(firstProject&&!$('cmdRoot').value)$('cmdRoot').value=firstProject.root;

  $('health').innerHTML=`<span class="${s.hub_online&&s.ollama_online?'ok':s.hub_online?'warn-t':'bad-t'}">${s.hub_online?'hub ✓':'hub ✗'} / ${s.ollama_online?'ollama ✓':'ollama ✗'} / ${esc(h.state||'n/a')}</span>`;
  $('uptime').textContent='uptime '+durSec(s.uptime_seconds)+' · supervisor restarts '+n(h.restarts);

  const ep=(rp.execution||{}).models||[];
  const httpTail=o.http_tail_latency||{};
  rows('httpTail',httpTail.by_action||[],x=>clickableRow(x,`<td>${esc(x.action)}</td><td>${n(x.events)}</td><td>${ms(x.p50_duration_ms)}</td><td>${ms(x.p95_duration_ms)}</td><td>${ms(x.p99_duration_ms)}</td><td>${n(x.failures)}</td>`),6);

  $('fgQueue').textContent=n(q.foreground_queued)+' queued / '+n(q.foreground_inflight)+' running';
  $('bgQueue').textContent='background '+n(q.background_queued)+' queued / '+n(q.inflight_background)+' running · '+(q.background_allowed?'idle work allowed':'yielding');

  const http=o.http||{},cohorts=o.cohorts||{},agentHttp=cohorts.agent_http||{},inference=cohorts.inference||{},policy=cohorts.policy_rejection||{},savedTokens=Math.max(0,Number(o.cloud_tokens_avoided_est||0)),savedUsd=Number(o.estimated_savings_usd||0),rate=Number(o.cloud_token_cost_usd_per_million||0);
  $('handledRequests').textContent=n(agentHttp.events);
  $('handledRequestsSub').textContent=n(agentHttp.failures)+' operational failures · '+n(policy.events)+' policy rejections';
  $('tokensSaved').textContent=n(savedTokens);
  $('tokensSavedSub').textContent='avoided cloud tokens · '+n(o.cache_hits)+' cache hits';
  $('dollarsSaved').textContent='≈ $'+savedUsd.toFixed(2);
  $('dollarsSavedSub').textContent='estimate · $'+rate.toFixed(2)+' / 1M avoided tokens';
  $('cache').textContent=((o.cache_hit_rate||0)*100).toFixed(1)+'%';
  $('cacheSub').textContent=n(o.cache_hits)+' hits · '+n(o.inference_events)+' local inference events';
  $('latency').textContent=ms(agentHttp.p50_duration_ms)+' / '+ms(agentHttp.p95_duration_ms)+' / '+ms(agentHttp.p99_duration_ms);
  $('queueWait').textContent='local inference p95 '+ms(inference.p95_duration_ms)+' · avg queue wait '+ms(o.avg_queue_wait_ms);
  $('reliabilityValue').innerHTML=`<span class="${agentHttp.failures?'warn-t':'ok'}">${n(agentHttp.failures)} failures</span>`;
  $('reliabilitySub').textContent=n(policy.events)+' policy rejections · '+n(inference.fallback_count)+' fallbacks · '+n(inference.degraded_count)+' degraded · '+n(inference.retry_count)+' retries';

  // Update real-time rolling sparkline and wave data
  const curP95=Number(agentHttp.p95_duration_ms||0);
  const curWait=Number(o.avg_queue_wait_ms||0);
  const curRps=Number(agentHttp.events||0);
  latencySparkData.push(curP95);if(latencySparkData.length>25)latencySparkData.shift();
  throughputSparkData.push(curRps);if(throughputSparkData.length>25)throughputSparkData.shift();
  liveChartLatency.push(curP95);if(liveChartLatency.length>30)liveChartLatency.shift();
  liveChartQueue.push(curWait);if(liveChartQueue.length>30)liveChartQueue.shift();

  drawSpark('latencySpark', latencySparkData, '#38bdf8', 'rgba(56,189,248,0.12)');
  drawSpark('throughputSpark', throughputSparkData, '#34d399', 'rgba(52,211,153,0.12)');
  drawDualChart('liveChartCanvas', liveChartLatency, liveChartQueue);

  const agState=s.agent_state||{};
  if($('agentStateVal')){
    if(agState.enabled){
      const act=agState.active_tasks_count||0,mem=agState.memory_records_count;
      $('agentStateVal').innerHTML='<span class="ok">healthy ✓</span>';
      $('agentStateSub').textContent=n(act)+' active task'+(act===1?'':'s')+(mem!==undefined?' · '+n(mem)+' memories':'');
    }else{
      $('agentStateVal').innerHTML='<span class="muted">disabled</span>';
      $('agentStateSub').textContent='agent_state.enabled = false';
    }
  }
  if($('agentStateCard'))$('agentStateCard').onclick=()=>switchTab('agentos');

  $('prep').textContent=(p.paused?'paused':(p.processing_projects?'active':'idle'))+' · '+n(p.steps)+' steps';
  $('prepSub').textContent=n(p.active_projects)+' active · '+n(p.processing_projects)+'/'+n(p.max_preprocessing_projects)+' preprocessing · '+n(p.waiting_projects)+' waiting';

  const allJobs=[...(q.inflight_jobs||[]),...(q.pending_jobs||[])];
  $('currentSummary').textContent=n(q.foreground_queued)+' queued · '+n(q.foreground_inflight)+' running';
  rows('overviewJobs',allJobs.slice(0,12),j=>schedulerRow(j,`<td>${esc(j.state)}</td><td>${esc(j.tenant)}</td><td>${esc(j.source)}</td><td>${esc(j.model)}</td><td>${ms(j.wait_ms)}</td><td>${ms(j.service_ms)}</td><td>${esc(j.wait_reason)}</td>`),7);

  const hs=o.hotspots||[];
  $('hotspots').innerHTML=hs.length?hs.map((x,i)=>`<div>${esc(x.type||'signal')}</div><div><span class="chip">${esc(x.signal||'')}</span> ${esc(x.value??x.value_ms??x.count??'')}</div>`).join(''):'<div>Status</div><div class="ok">No persistent hotspot detected</div>';

  const visibleJobs=workVisible(allJobs),visibleActive=workVisible(o.active_requests||[]),visibleRecent=workVisible(o.recent_http||[]);
  $('queueSummary').textContent=n(q.foreground_queued)+' fg + '+n(q.background_queued)+' bg queued · '+n(q.foreground_inflight)+' fg + '+n(q.inflight_background)+' bg running';
  $('workQueued').textContent=n((q.foreground_queued||0)+(q.background_queued||0));
  $('workRunning').textContent=n((q.foreground_inflight||0)+(q.inflight_background||0));
  $('workActive').textContent=n((o.active_requests||[]).length);
  $('workRetained').textContent=n(lastTraces.length);
  $('workFilterSummary').textContent=`showing ${visibleJobs.length+visibleActive.length+visibleRecent.length} live/history items`;

  rows('jobs',visibleJobs,j=>workSchedulerRow(j),5);
  rows('activeReq',visibleActive,x=>workActiveRequestRow(x),4);
  rows('recentReq',visibleRecent,x=>workRecentRequestRow(x),5);
  renderTraceList(lastTraces);

  const diagBar=$('prepDiagnosticBar');
  if(diagBar){
    const projs=p.projects||[], isGlobPaused=!!p.paused, isEnabled=p.enabled!==false;
    const hasErr=projs.some(x=>x.status==='error'||x.last_error);
    const allDone=projs.length>0&&projs.every(x=>x.status==='complete'||(x.overall_progress_pct||0)>=100);
    const bgYield=p.scheduler_background_allowed===false;
    diagBar.style.display='flex';
    if(!isEnabled){
      diagBar.className='diag-banner bad';
      diagBar.innerHTML=`<span>❌ <b>Preprocessing is disabled in configuration</b> (<code>preprocessing.enabled = false</code>). Enable it in the Configuration tab.</span>`;
    }else if(isGlobPaused){
      diagBar.className='diag-banner warn';
      diagBar.innerHTML=`<span style="flex:1">⏸ <b>Preprocessing is GLOBALLY PAUSED</b>. Background workers and real-time synchronization are stopped.</span><button class="btn ok" onclick="setPreprocessing('resume')" style="padding:3px 8px;font-size:11px">▶ Resume Preprocessing</button>`;
    }else if(!projs.length){
      diagBar.className='diag-banner info';
      diagBar.innerHTML=`<span style="flex:1">ℹ️ <b>No projects currently registered</b>. Preprocessing is idle waiting for workspace registration. Click <b>+ Register Project</b> or call <code>local_ai_repo(action='preprocess')</code> from an agent.</span><button class="btn ok" onclick="$('regProjectBtn').click()" style="padding:3px 8px;font-size:11px">+ Register Project</button>`;
    }else if(hasErr){
      const errProjs=projs.filter(x=>x.status==='error'||x.last_error).map(x=>x.project||x.root).join(', ');
      diagBar.className='diag-banner bad';
      diagBar.innerHTML=`<span style="flex:1">⚠️ <b>Errors detected in project preprocessing:</b> ${esc(errProjs)}. Check status column below for error details.</span><button class="btn" onclick="pollStatus()" style="padding:3px 8px;font-size:11px">Refresh status</button>`;
    }else if(allDone){
      diagBar.className='diag-banner ok';
      diagBar.innerHTML=`<span>✅ <b>All ${projs.length} registered project(s) are 100% indexed and synchronized</b>. Real-time file change watcher (FS watcher) is active.</span>`;
    }else if(bgYield){
      diagBar.className='diag-banner warn';
      diagBar.innerHTML=`<span>⏳ <b>Background preprocessing is yielding:</b> Foreground agent requests are currently active on GPU/models. Preprocessing will resume automatically when queue clears.</span>`;
    }else{
      const runningNames=projs.filter(x=>x.status==='running').map(x=>x.project).join(', ');
      diagBar.className='diag-banner info';
      diagBar.innerHTML=`<span>⚡ <b>Preprocessing is active:</b> ${esc(runningNames||'Processing queue')}. Extracting AST symbols, RAG embeddings and semantic cards...</span>`;
    }
  }

  const prepPaused=!!p.paused;
  $('prepState').textContent=n((p.projects||[]).length)+' registered projects · global '+(prepPaused?'paused':'running');
  $('prepToggle').textContent=prepPaused?'Resume preprocessing':'Pause preprocessing';
  $('prepAllToggle').textContent=prepPaused?'Resume all projects':'Pause all projects';
  renderProjects(p.projects||[]);

  rows('executionProfiles',ep,x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${esc(x.tier)}</td><td>${n(x.num_ctx)}</td><td>${n(x.max_ctx)}</td><td>${n(x.parallel_limit)}</td><td>${x.think?'on':'role-gated/off'}</td><td>${n(x.prompt_budget_tokens)}</td>`),7);
  rows('models',o.by_model||[],x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${ms(x.avg_load_ms)}</td><td>${n(x.failures)}</td>`),5);
  rows('cacheLayers',o.cache_layers||[],x=>clickableRow(x,`<td>${esc(x.layer)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.cloud_tokens_avoided_est)}</td>`),4);
  rows('agents',o.by_agent||[],x=>clickableRow(x,`<td>${esc(x.agent)}</td><td>${n(x.requests)}</td><td>${n(x.local_inference_calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`),5);
  rows('routes',o.execution_routes||[],x=>clickableRow(x,`<td>${esc(x.route)}</td><td>${esc(x.task_type)}</td><td>${esc(x.complexity)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`),6);

  $('commandState').textContent=n(cmd.active_count)+' running';
  rows('activeCommands',cmd.active||[],x=>clickableRow(x,`<td>${esc(x.command)}</td><td>${esc(x.cwd)}</td><td>${esc(x.tenant)}</td><td>${esc(x.class)}</td><td>${age(x.age_ms)}</td><td>${durSec(x.timeout_seconds)}</td>`),6);
  $('commandStats').innerHTML=`<div>Executed</div><div>${n(cmd.executed)}</div><div>Cache hits / misses</div><div>${n(cmd.hits)} / ${n(cmd.misses)}</div><div>Coalesced waiters</div><div>${n(cmd.coalesced_waiters)}</div><div>Policy blocked</div><div>${n(cmd.blocked)}</div>`;
  rows('blockedReasons',Object.entries(cmd.blocked_by_reason||{}),x=>clickableRow({reason:x[0],count:x[1]},`<td>${esc(x[0])}</td><td>${n(x[1])}</td>`),2);

  rows('errors',o.recent_errors||[],x=>clickableRow(x,`<td>${esc(x.component)}</td><td>${esc(x.operation)}</td><td>${n(x.count)}</td><td>${n(x.recovered_count)}</td><td>${x.last_seen?new Date(x.last_seen*1000).toLocaleTimeString():'—'}</td>`),5);
  $('runtimeCounters').innerHTML=`<div>Scheduler submitted</div><div>${n(ss.submitted)}</div><div>Completed / failed</div><div>${n(ss.completed)} / ${n(ss.failed)}</div><div>Model switches</div><div>${n(ss.model_switches)}</div><div>Queue rejections</div><div>${n(ss.queue_rejections)}</div><div>Caller timeouts</div><div>${n(ss.caller_timeouts)}</div><div>Background yields</div><div>${n(ss.background_yields)}</div><div>Supervisor restarts</div><div>${n(h.restarts)}</div>`;
  renderBundles(s);
}

function schedulerRow(job,html,cols){const linked=lastTraces.find(x=>String(x.scheduler_job_id||'')===String(job.job_id||''));const id=linked?.trace_id||job.trace_id;if(id)return `<tr class="click" data-trace-id="${esc(id)}">${html}</tr>`;return clickableRow(job,html)}
function requestRow(request,html,cols){const linked=lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''));if(linked)return `<tr class="click" data-trace-id="${esc(linked.trace_id)}">${html}</tr>`;return clickableRow(request,html)}

function renderTraceList(items){
  const kind=$('traceKind')?.value||'',historyQuery=String($('traceHistorySearch')?.value||'').trim().toLowerCase(),historyState=$('traceHistoryState')?.value||'useful',visible=workVisible(items||[]).filter(x=>!kind||x.kind===kind).filter(x=>{const state=traceStatus(x),hay=[x.action,x.kind,x.agent,x.tenant,x.model,x.error].filter(Boolean).join(' ').toLowerCase();return (!historyQuery||hay.includes(historyQuery))&&(historyState==='useful'?(state!=='interrupted'&&state!=='failed'):(!historyState||state===historyState))});
  $('traceSummary').textContent=`${visible.length} shown · ${n(items?.length||0)} retained · full prompt/output · bounded retention`;
  if($('workRetained'))$('workRetained').textContent=n(items?.length||0);
  rows('traces',visible,x=>{const state=traceStatus(x),cls='trace-'+state,links=[x.async_job_id&&('job '+String(x.async_job_id).slice(0,10)),x.scheduler_job_id&&('sched '+String(x.scheduler_job_id).slice(0,10))].filter(Boolean).join(' · '),activity=x.updated_at&&x.created_at?durSec(Math.max(0,Number(x.updated_at)-Number(x.created_at))):'—';return `<tr class="click" data-trace-id="${esc(x.trace_id)}"><td class="${cls}">${esc(humanLabel(state))}</td><td><strong>${esc(humanLabel(x.kind||'trace'))}</strong><div class="tiny">${esc(x.action||'—')}</div></td><td>${esc(x.agent||'—')}<div class="tiny">${esc(x.tenant||'—')}</div></td><td>${esc(x.model||'—')}</td><td>${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'}<div class="tiny">${esc(activity)} total</div></td><td class="tiny">${esc(links||'open trace')}</td></tr>`},6);
  $('traceSideSummary').textContent=`${visible.length} trace${visible.length===1?'':'s'} · click to inspect`;
  $('traceSidebarList').innerHTML=visible.length?visible.map(x=>{const state=traceStatus(x),label=state==='interrupted'?'Interrupted':state,cls=state==='interrupted'?'interrupted':(state==='failed'||state==='error'?'failed':(x.terminal||state==='completed'||state==='succeeded'?'done':'')),kindLabel=x.kind==='api_request'?'API request':humanLabel(x.kind||'trace');return `<button class="trace-side-item ${String(x.trace_id)===activeTraceId?'active':''}" data-trace-page-id="${esc(x.trace_id)}"><span class="trace-side-top"><span class="trace-side-state ${cls}"></span><span class="trace-side-action">${esc(x.action||x.kind||'Trace')}</span><span class="tiny spacer">${esc(label)}</span></span><span class="trace-side-meta">${esc(x.agent||'unknown agent')} · ${esc(kindLabel)}</span><span class="trace-side-meta">${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'} · ${esc(x.tenant||'no tenant')}</span></button>`}).join(''):'<div class="empty-human">No retained traces</div>';
}
async function pollTraces(){try{const kind=$('traceKind')?.value||'',suffix=kind?'&kind='+encodeURIComponent(kind):'',r=await apiFetch('/v1/debug-traces?limit=100'+suffix,{cache:'no-store'}),d=await r.json();if(d.success){lastTraces=d.items||[];renderTraceList(lastTraces)}}catch(e){console.warn('trace refresh failed',e)}}
$('traceRefresh')?.addEventListener('click',pollTraces);$('traceKind')?.addEventListener('change',()=>renderTraceList(lastTraces));
$('traceHistorySearch')?.addEventListener('input',()=>renderTraceList(lastTraces));$('traceHistoryState')?.addEventListener('change',()=>renderTraceList(lastTraces));

let statusPollInFlight=false,hasLiveStatus=false;
async function probeHealth(){
  try{
    const r=await nativeFetch('/health',{cache:'no-store'});
    if(r.ok&&!hasLiveStatus){$('conn').textContent='online';$('conn').className='pill ok'}
  }catch(e){if(!hasLiveStatus){$('conn').textContent='offline';$('conn').className='pill bad-t'}}
}
async function pollStatus(){
  if(statusPollInFlight)return;
  statusPollInFlight=true;
  try{
    const r=await apiFetch('/v1/live/status?light=1&scope='+sloScope,{cache:'no-store'}),s=await r.json();
    render(s);hasLiveStatus=true;$('conn').textContent='live';$('conn').className='pill ok';$('updated').textContent='updated '+new Date().toLocaleTimeString();
    try{
      const gr=await apiFetch('/v1/hardware/system',{cache:'no-store'});
      if(gr.ok){
        const sys=await gr.json(), g=sys.gpu||{}, ram=sys.ram||{};
        const cpuUtil=Number(sys.cpu_utilization_pct||0), ramPct=Number(ram.used_pct||0);
        const gpuHtml=g.available?(()=>{const gUtil=Number(g.gpu_utilization_pct||0);return `<div style="display:flex;justify-content:space-between;align-items:center"><span>CPU ${cpuUtil}% · GPU ${gUtil}%</span><span class="tiny muted">${sys.cpu_count||1} threads</span></div><div class="bar"><i style="width:${Math.max(cpuUtil,gUtil)}%;background:${gUtil>80||cpuUtil>80?'var(--bad)':gUtil>50||cpuUtil>50?'var(--warn)':'var(--ok)'}"></i></div>`})():`<div style="display:flex;justify-content:space-between;align-items:center"><span>CPU ${cpuUtil}%</span><span class="tiny muted">${sys.cpu_count||1} threads</span></div><div class="bar"><i style="width:${cpuUtil}%;background:${cpuUtil>80?'var(--bad)':cpuUtil>50?'var(--warn)':'var(--ok)'}"></i></div>`;
        $('sysUtil').innerHTML=gpuHtml;
        const vram=g.available?(g.vram_total_mb?` · VRAM ${Math.round(g.vram_used_mb||0)} / ${Math.round(g.vram_total_mb)} MB`:g.unified_memory_mb?` · Unified memory ${Math.round(g.unified_memory_mb)} MB`:''):'';
        $('sysSub').textContent=`RAM ${ram.used_gb||0} / ${ram.total_gb||0} GB (${ramPct}%)${vram}`;
      }
    }catch{}
  }catch(e){console.error('dashboard status refresh failed',e);$('conn').textContent=hasLiveStatus?'stale':'offline';$('conn').className=hasLiveStatus?'pill warn-t':'pill bad-t'}
  finally{statusPollInFlight=false}
}
function renderEvents(events){if(paused||!events.length)return;const box=$('eventList');const html=events.slice(-120).reverse().map(e=>{const id='d'+(++seq);dataStore.set(id,e);return `<div class="event click" data-detail="${id}"><span>${new Date((e.created_at||0)*1000).toLocaleTimeString()}</span><span>${esc(e.agent||e.kind||'')}</span><span>${esc(e.event_type||'')}</span><span>${esc(e.action||e.stage||'')}</span><span class="hide-sm">${esc(e.model||e.tenant||'')}</span><span>${e.duration_ms?ms(e.duration_ms):''}</span><span class="${e.success===false?'bad-t':''}">${e.success===false?'FAIL':''}</span></div>`}).join('');box.innerHTML=html||'<div class="empty">no events</div>'}
async function pollEvents(){try{const r=await apiFetch('/v1/live?after='+cursor+'&limit=200',{cache:'no-store'}),d=await r.json();cursor=Number(d.cursor||cursor);renderEvents(d.events||[])}catch{}}

probeHealth();pollStatus();pollEvents();pollTraces();
setInterval(probeHealth,5000);setInterval(pollStatus,3000);setInterval(pollEvents,1000);setInterval(pollTraces,2000);

// ── Architecture Graph ────────────────────────────────────────────────────────
let archData=null,archNodes=[],archEdges=[],archDragging=null;
async function loadArchGraph(){
  try{
    const r=await apiFetch('/v1/cross_project_graph',{cache:'no-store'});
    if(!r.ok)return;
    archData=await r.json();
    renderArchGraph();
  }catch(e){console.warn('arch graph error',e)}
}
function renderArchGraph(){
  if(!archData)return;
  const svg=$('archSvg');
  const W=svg.clientWidth||800,H=svg.clientHeight||520;
  const nodes=(archData.nodes||[]).map((n,i)=>({...n,x:W/2+Math.cos(i/Math.max(1,archData.nodes.length)*2*Math.PI)*200,y:H/2+Math.sin(i/Math.max(1,archData.nodes.length)*2*Math.PI)*160,vx:0,vy:0}));
  const edges=archData.edges||[];
  archNodes=nodes;archEdges=edges;
  $('archSummary').textContent=nodes.length+' projects · '+edges.length+' connections · '+n(archData.shared_packages||0)+' shared packages';
  rows('archEdgesTable',edges,e=>`<tr><td>${esc(e.from?.split('/').pop()||e.from)}</td><td>${esc(e.to?.split('/').pop()||e.to)}</td><td><span class="chip">${esc(e.type)}</span></td><td>${esc(e.label)}</td></tr>`,4);
  drawArch(svg,nodes,edges,W,H);
  runSimulation(svg,nodes,edges,W,H);
}
function drawArch(svg,nodes,edges,W,H){
  svg.innerHTML='';
  const defs=document.createElementNS('http://www.w3.org/2000/svg','defs');
  const marker=document.createElementNS('http://www.w3.org/2000/svg','marker');
  marker.setAttribute('id','arr');marker.setAttribute('markerWidth','6');marker.setAttribute('markerHeight','4');marker.setAttribute('refX','6');marker.setAttribute('refY','2');marker.setAttribute('orient','auto');
  const mp=document.createElementNS('http://www.w3.org/2000/svg','polygon');mp.setAttribute('points','0 0, 6 2, 0 4');mp.setAttribute('fill','#4a6080');marker.appendChild(mp);defs.appendChild(marker);svg.appendChild(defs);
  const nodeIdx=Object.fromEntries(nodes.map((n,i)=>[n.root,i]));
  edges.forEach(e=>{
    const s=nodes[nodeIdx[e.from]],t=nodes[nodeIdx[e.to]];
    if(!s||!t)return;
    const line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('class','arch-edge');line.setAttribute('x1',s.x);line.setAttribute('y1',s.y);line.setAttribute('x2',t.x);line.setAttribute('y2',t.y);
    line.setAttribute('stroke',e.type==='shared_route'?'#7b5fff':'#3a5572');line.setAttribute('stroke-width','1.5');line.setAttribute('marker-end','url(#arr)');
    svg.appendChild(line);
  });
  nodes.forEach((nd,i)=>{
    const g=document.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('transform',`translate(${nd.x},${nd.y})`);
    const circ=document.createElementNS('http://www.w3.org/2000/svg','circle');
    circ.setAttribute('r','26');circ.setAttribute('fill','#1a2d40');circ.setAttribute('stroke','#5380a8');circ.setAttribute('stroke-width','1.5');circ.style.cursor='grab';
    const lbl=document.createElementNS('http://www.w3.org/2000/svg','text');
    lbl.setAttribute('text-anchor','middle');lbl.setAttribute('dy','4');lbl.setAttribute('fill','#c5d4e5');lbl.setAttribute('font-size','10');
    lbl.textContent=(nd.root||'').split(/[\\/]/).pop()?.slice(0,12)||'?';
    g.appendChild(circ);g.appendChild(lbl);
    g.addEventListener('mousedown',ev=>{ev.preventDefault();archDragging={node:nd,svg,dx:ev.clientX-nd.x,dy:ev.clientY-nd.y}});
    svg.appendChild(g);
  });
  svg.addEventListener('mousemove',ev=>{if(!archDragging)return;archDragging.node.x=ev.clientX-archDragging.dx;archDragging.node.y=ev.clientY-archDragging.dy;updateArchPositions(svg,nodes,edges)});
  svg.addEventListener('mouseup',()=>{archDragging=null});
}
function updateArchPositions(svg,nodes,edges){
  const lines=svg.querySelectorAll('.arch-edge');const nodeIdx=Object.fromEntries(nodes.map((n,i)=>[n.root,i]));
  lines.forEach((l,i)=>{const e=edges[i];if(!e)return;const s=nodes[nodeIdx[e.from]],t=nodes[nodeIdx[e.to]];if(!s||!t)return;l.setAttribute('x1',s.x);l.setAttribute('y1',s.y);l.setAttribute('x2',t.x);l.setAttribute('y2',t.y)});
  const gs=svg.querySelectorAll('g');nodes.forEach((nd,i)=>{if(gs[i])gs[i].setAttribute('transform',`translate(${nd.x},${nd.y})`)});
}
function runSimulation(svg,nodes,edges,W,H){
  const nodeIdx=Object.fromEntries(nodes.map((n,i)=>[n.root,i]));
  let t=0;
  function tick(){
    if(t++>200||archDragging)return;
    nodes.forEach(n=>{n.vx*=0.9;n.vy*=0.9;n.vx+=(W/2-n.x)*0.002;n.vy+=(H/2-n.y)*0.002});
    nodes.forEach((a,i)=>nodes.forEach((b,j)=>{if(i>=j)return;const dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1;const f=Math.max(0,80-d)/d*0.5;a.vx-=f*dx;a.vy-=f*dy;b.vx+=f*dx;b.vy+=f*dy}));
    edges.forEach(e=>{const s=nodes[nodeIdx[e.from]],t2=nodes[nodeIdx[e.to]];if(!s||!t2)return;const dx=t2.x-s.x,dy=t2.y-s.y,d=Math.sqrt(dx*dx+dy*dy)||1;const f=(d-120)/d*0.15;s.vx+=f*dx;s.vy+=f*dy;t2.vx-=f*dx;t2.vy-=f*dy});
    nodes.forEach(nd=>{nd.x=Math.max(30,Math.min(W-30,nd.x+nd.vx));nd.y=Math.max(30,Math.min(H-30,nd.y+nd.vy))});
    updateArchPositions(svg,nodes,edges);requestAnimationFrame(tick);
  }
  tick();
}
$('archRefresh')?.addEventListener('click',loadArchGraph);
$('symbolGraphBtn')?.addEventListener('click',async()=>{
  const sym=$('symbolInput')?.value?.trim();
  try{
    const r=await apiFetch('/v1/symbol_callgraph?symbol='+encodeURIComponent(sym||''),{cache:'no-store'});
    if(!r.ok)return;
    const d=await r.json();
    if(d.nodes&&d.nodes.length){
      archData={nodes:d.nodes.map(n=>({root:n.id,label:n.label})),edges:d.edges.map(e=>({from:e.from,to:e.to,type:e.type,label:e.type}))};
      renderArchGraph();
    }else{alert('No callgraph nodes found for symbol: '+sym)}
  }catch(e){console.warn(e)}
});
$('deadCodeBtn')?.addEventListener('click',async()=>{
  $('deadCodeBtn').disabled=true;$('deadCodeBtn').textContent='Scanning…';
  try{
    const r=await apiFetch('/v1/dead_code',{cache:'no-store'});
    const d=await r.json();
    $('deadCodeSec').style.display='block';
    $('deadCodeSummary').textContent=n(d.dead_symbols_count||0)+' potentially unused symbols';
    rows('deadCodeTable',d.dead_symbols||[],s=>`<tr><td><b>${esc(s.name)}</b></td><td><span class="chip">${esc(s.kind)}</span></td><td>${esc(s.path)}</td><td>${n(s.line)}</td><td>${esc(s.container||'—')}</td><td class="muted">${esc(s.reason)}</td></tr>`,6);
  }catch(e){alert('Dead code scan failed: '+e.message)}
  finally{$('deadCodeBtn').disabled=false;$('deadCodeBtn').textContent='Scan Dead Code'}
});
$('auditDepsBtn')?.addEventListener('click',async()=>{
  $('auditDepsBtn').disabled=true;$('auditDepsBtn').textContent='Auditing…';
  try{
    const r=await apiFetch('/v1/audit_dependencies',{cache:'no-store'});
    const d=await r.json();
    $('auditSec').style.display='block';
    $('auditSummary').textContent=`Score ${d.security_score||'A'} · ${n(d.total_dependencies||0)} packages · ${n(d.vulnerability_count||0)} advisories`;
    rows('auditTable',d.vulnerabilities||[],v=>`<tr><td><b>${esc(v.package)}</b></td><td><span class="chip ${v.severity==='HIGH'?'bad-t':'warn-t'}">${esc(v.severity)}</span></td><td>${esc(v.installed_version)}</td><td class="ok">${esc(v.fixed_version)}</td><td>${esc(v.advisory)}</td><td class="muted">${esc(v.manifest_path)}</td></tr>`,6);
  }catch(e){alert('Security audit failed: '+e.message)}
  finally{$('auditDepsBtn').disabled=false;$('auditDepsBtn').textContent='Audit Security'}
});

// ── Bundles ────────────────────────────────────────────────────────────────────
function renderBundles(s){
  const projs=s?.preprocessing?.projects||[];
  $('bundleExportTable').innerHTML=projs.length?projs.map(p=>`<tr><td>${esc(p.project)}</td><td><span class="chip">${esc(p.status)}</span> ${n(p.overall_progress_pct||0)}%</td><td><button class="btn" data-export-root="${esc(p.root||'')}">Export</button></td></tr>`).join(''):`<tr><td colspan="3" class="muted">No projects</td></tr>`;
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-project-action],[data-export-root]');
  if(!button)return;
  event.stopPropagation();
  if(button.dataset.exportRoot!==undefined){exportBundle(button.dataset.exportRoot);return}
  const root=button.dataset.projectRoot||'';
  if(button.dataset.projectAction==='delete')deleteProjectDialog(root,button.dataset.projectName||'');
  else projectAction(root,button.dataset.projectAction);
});
async function exportBundle(root){
  const r=await apiFetch('/v1/bundle/export',{method:'POST',headers:{'Content-Type':'application/zip'},body:JSON.stringify({root})});
  if(!r.ok){alert('Export failed: '+(await r.text()));return;}
  const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bundle.zip';a.click();URL.revokeObjectURL(url);
}
$('bundleImport')?.addEventListener('click',async()=>{
  const file=$('bundleFile')?.files?.[0];if(!file){$('bundleImportStatus').textContent='Select a file first';return;}
  $('bundleImportStatus').textContent='Uploading…';
  const target=$('bundleTargetRoot')?.value?.trim()||'';const suffix=target?'?target_root='+encodeURIComponent(target):'';
  try{
    const r=await apiFetch('/v1/bundle/import'+suffix,{method:'POST',headers:{'Content-Type':'application/zip'},body:await file.arrayBuffer()});
    const d=await r.json();
    $('bundleImportStatus').textContent=d.success?'Import successful: '+String(d.root||''):'Error: '+String(d.error||'failed');
  }catch(e){$('bundleImportStatus').textContent='Upload error: '+e.message}
});

// ── Agent OS ──────────────────────────────────────────────────────────────────
let agentOsTasks=[], agentOsMemories=[], agentOsIncidents=[];
async function loadAgentOsView(){
  try{
    const [tasksRes, memRes, incRes] = await Promise.all([
      apiFetch('/v1/agent-state/tasks', {cache:'no-store'}).then(r=>r.json()).catch(()=>({tasks:[]})),
      apiFetch('/v1/agent-state/memory', {cache:'no-store'}).then(r=>r.json()).catch(()=>({records:[]})),
      post('/v1/agent-state/incidents', {action:'list', limit:100}).catch(()=>({incidents:[]})),
    ]);
    agentOsTasks=tasksRes.tasks||[];
    agentOsMemories=memRes.records||[];
    agentOsIncidents=incRes.incidents||[];
    renderAgentOsView();
  }catch(e){console.warn('Agent OS view load error', e)}
}

let sseSource=null, sseEvents=[], sseEventCount=0, sseDebounceTimer=null;

function connectAgentOsStream(){
  if(sseSource){
    try{ sseSource.close(); }catch(e){}
    sseSource=null;
  }
  const badge=$('sseStreamBadge');
  if(badge){ badge.className='badge-status badge-waiting'; badge.textContent='Connecting…'; }
  const token=localStorage.getItem('apiToken')||'';
  const url='/v1/agent-state/events/stream'+(token?'?token='+encodeURIComponent(token):'');
  try{
    sseSource=new EventSource(url);
    sseSource.onopen=()=>{
      if(badge){ badge.className='badge-status badge-complete'; badge.textContent='🟢 Live Stream Connected'; }
    };
    sseSource.onerror=()=>{
      if(badge){ badge.className='badge-status badge-error'; badge.textContent='🔴 Disconnected (Retrying…)'; }
    };
    sseSource.onmessage=(e)=>{
      try{
        const data=JSON.parse(e.data);
        handleAgentOsStreamEvent(data);
      }catch(err){}
    };
  }catch(e){
    if(badge){ badge.className='badge-status badge-error'; badge.textContent='Error: '+e.message; }
  }
}

function handleAgentOsStreamEvent(ev){
  sseEventCount++;
  sseEvents.unshift(ev);
  if(sseEvents.length>200) sseEvents.pop();
  if($('sseStreamStats')) $('sseStreamStats').textContent=`${sseEventCount} events received`;
  renderLiveStreamTable();

  // Debounced auto-refresh of background tables when state changes
  clearTimeout(sseDebounceTimer);
  sseDebounceTimer=setTimeout(()=>{
    loadAgentOsView();
  }, 1200);
}

function renderLiveStreamTable(){
  const filter=String($('sseKindFilter')?.value||'').trim();
  const filtered=filter?sseEvents.filter(e=>String(e.kind||'').startsWith(filter)):sseEvents;
  rows('agentOsLiveStreamBody', filtered, ev=>{
    const seq=esc(ev.seq!==undefined?ev.seq:'—');
    const dt=ev.timestamp?new Date(ev.timestamp*1000).toLocaleTimeString():'—';
    const stream=esc(ev.stream_id||'—');
    const kind=esc(ev.kind||'unknown');
    const actor=esc(ev.actor||'system');
    let payloadStr=typeof ev.payload==='object'?JSON.stringify(ev.payload):String(ev.payload||'');
    if(payloadStr.length>85) payloadStr=payloadStr.slice(0,82)+'...';
    let kindBadge='badge-waiting';
    if(kind.startsWith('task.')) kindBadge='badge-running';
    else if(kind.startsWith('verification.')) kindBadge='badge-complete';
    else if(kind.startsWith('incident.')) kindBadge='badge-error';
    return clickableRow(ev, `<td><strong>${seq}</strong></td><td class="tiny">${dt}</td><td class="tiny mono">${stream}</td><td><span class="badge-status ${kindBadge}">${kind}</span></td><td class="tiny">${actor}</td><td class="tiny mono" title="${esc(typeof ev.payload==='object'?JSON.stringify(ev.payload,null,2):payloadStr)}">${esc(payloadStr)}</td>`);
  }, 6);
}

$('sseReconnectBtn')?.addEventListener('click', connectAgentOsStream);
$('sseClearBtn')?.addEventListener('click', () => {
  sseEvents = [];
  renderLiveStreamTable();
});
$('sseKindFilter')?.addEventListener('change', renderLiveStreamTable);

function switchAgentOsSubtab(tabKey){
  const subtabs=['tasks','memory','incidents','verification','context','liveStream'];
  subtabs.forEach(t=>{
    const btn=$('subtab'+t.charAt(0).toUpperCase()+t.slice(1));
    const sec=$('agentOs'+t.charAt(0).toUpperCase()+t.slice(1)+'Sec');
    if(btn)btn.classList.toggle('active',t===tabKey);
    if(sec)sec.style.display=t===tabKey?'block':'none';
  });
  if(tabKey==='liveStream' && !sseSource){
    connectAgentOsStream();
  }
}
document.querySelectorAll('.subtab-btn[data-agentos-tab]').forEach(btn=>{
  btn.addEventListener('click',()=>switchAgentOsSubtab(btn.dataset.agentosTab));
});

function renderAgentOsView(){
  const query=String($('agentOsSearch')?.value||'').trim().toLowerCase();
  const statusFilter=String($('agentOsTaskStatus')?.value||'').trim().toLowerCase();
  const filteredTasks=agentOsTasks.filter(t=>{
    const st=String(t.status||'').toLowerCase();
    if(statusFilter&&st!==statusFilter)return false;
    if(!query)return true;
    const hay=[t.task_id,t.contract?.goal,t.checkpoint?.phase,t.checkpoint?.next_action].join(' ').toLowerCase();
    return hay.includes(query);
  });

  const memQuery=String($('agentOsMemSearch')?.value||'').trim().toLowerCase();
  const memScope=String($('agentOsMemScope')?.value||'').trim().toLowerCase();
  const memKind=String($('agentOsMemKind')?.value||'').trim().toLowerCase();
  const filteredMem=agentOsMemories.filter(m=>{
    if(memScope&&String(m.scope||'').toLowerCase()!==memScope)return false;
    if(memKind&&String(m.kind||'').toLowerCase()!==memKind)return false;
    if(!memQuery)return true;
    const hay=[m.key,typeof m.value==='object'?JSON.stringify(m.value):String(m.value||''),m.source].join(' ').toLowerCase();
    return hay.includes(memQuery);
  });

  const incQuery=String($('agentOsIncSearch')?.value||'').trim().toLowerCase();
  const incFilter=String($('agentOsIncFilter')?.value||'').trim();
  const filteredInc=agentOsIncidents.filter(i=>{
    if(incFilter!==''){const resBool=incFilter==='true';if(!!i.verified_fix!==resBool)return false;}
    if(!incQuery)return true;
    const hay=[i.incident_id,i.error_class,i.redacted_message,i.root_cause,i.verified_fix].join(' ').toLowerCase();
    return hay.includes(incQuery);
  });

  if($('agentOsSummary'))$('agentOsSummary').textContent=`${filteredTasks.length} tasks · ${filteredMem.length} memories · ${filteredInc.length} incidents`;
  if($('agentOsState')){
    const act=agentOsTasks.filter(t=>String(t.status).toLowerCase()==='active').length;
    $('agentOsState').textContent=`${act} active · ${agentOsTasks.length} total tasks · ${agentOsMemories.length} memories`;
  }
  if($('subtabTasks'))$('subtabTasks').textContent=`Tasks (${agentOsTasks.length})`;
  if($('subtabMemory'))$('subtabMemory').textContent=`Memory (${agentOsMemories.length})`;
  if($('subtabIncidents'))$('subtabIncidents').textContent=`Negative Knowledge (${agentOsIncidents.length})`;

  rows('agentOsTasksBody',filteredTasks,t=>{
    const st=String(t.status||'planned').toLowerCase();
    const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
    const goal=esc(t.contract?.goal||'—');
    const chk=t.checkpoint?`${esc(t.checkpoint.phase||'')} ➔ ${esc(t.checkpoint.next_action||'')}`:'—';
    const crit=(t.contract?.acceptance_criteria||[]).length?(t.contract.acceptance_criteria.length+' criteria'):'—';
    const dt=t.updated_at?new Date(t.updated_at*1000).toLocaleTimeString():'—';
    return clickableRow(t,`<td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td><strong>${esc(t.task_id)}</strong></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${esc(t.contract?.scope||'task')}</span></td><td class="tiny">${chk}</td><td class="tiny">${esc(crit)}</td><td class="tiny">${dt}</td>`);
  },7);

  rows('agentOsMemoryBody',filteredMem,m=>{
    const sc=esc(m.scope||'task');
    const kd=esc(m.kind||'fact');
    const k=esc(m.key||'—');
    let v=typeof m.value==='object'?JSON.stringify(m.value):String(m.value||'');
    if(v.length>55)v=v.slice(0,52)+'...';
    const conf=m.confidence!==undefined?Math.round(m.confidence*100)+'%':'—';
    const src=esc(m.source||'—');
    const dt=m.created_at?new Date(m.created_at*1000).toLocaleTimeString():'—';
    return clickableRow(m,`<td><span class="chip">${sc}</span></td><td><span class="chip">${kd}</span></td><td><strong>${k}</strong></td><td class="tiny mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${esc(v)}</td><td class="tiny">${conf}</td><td class="tiny">${src}</td><td class="tiny">${dt}</td>`);
  },7);

  rows('agentOsIncBody',filteredInc,i=>{
    const id=esc(i.incident_id||'—');
    const op=esc(i.outcome?.tool_name||'agent');
    const ec=esc(i.error_class||'Error');
    let msg=esc(i.redacted_message||'');
    if(msg.length>45)msg=msg.slice(0,42)+'...';
    const cause=esc(i.root_cause||'—');
    const fix=esc(i.verified_fix||'—');
    const statusChip=i.verified_fix?'<span class="chip ok">resolved</span>':'<span class="chip warn-t">unresolved</span>';
    return clickableRow(i,`<td><strong>${id}</strong></td><td><span class="chip">${op}</span></td><td><span class="chip bad-t">${ec}</span></td><td class="tiny" title="${esc(i.redacted_message||'')}">${msg}</td><td class="tiny">${cause}</td><td class="tiny ok">${fix}</td><td>${statusChip}</td>`);
  },7);
}

$('agentOsRefresh')?.addEventListener('click',loadAgentOsView);
$('agentOsCleanup')?.addEventListener('click',async()=>{
  if(!confirm('Run bounded Agent OS cleanup to purge expired events and stale snapshots?'))return;
  try{
    const res=await post('/v1/agent-state/cleanup',{});
    openModal(res,'Agent OS Cleanup Result');
    await loadAgentOsView();
  }catch(e){openModal({error:String(e)},'Cleanup Error')}
});
$('agentOsSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsTaskStatus')?.addEventListener('change',renderAgentOsView);
$('agentOsMemSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsMemScope')?.addEventListener('change',renderAgentOsView);
$('agentOsMemKind')?.addEventListener('change',renderAgentOsView);
$('agentOsIncSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsIncFilter')?.addEventListener('change',renderAgentOsView);

// Create Task Modal / Dialog
$('agentOsCreateTaskBtn')?.addEventListener('click',async()=>{
  const goal=prompt('Enter task goal description:');
  if(!goal||!goal.trim())return;
  const criteriaRaw=prompt('Enter acceptance criteria (comma-separated):','');
  const criteria=criteriaRaw?criteriaRaw.split(',').map(s=>s.trim()).filter(Boolean):[];
  try{
    const res=await post('/v1/agent-state/tasks',{
      action:'create',
      goal:goal.trim(),
      acceptance_criteria:criteria,
      scope:'task'
    });
    openModal(res,'Created Durable Agent Task');
    await loadAgentOsView();
  }catch(e){openModal({error:String(e)},'Task Creation Error')}
});

// Record Memory Dialog
$('agentOsRecordMemBtn')?.addEventListener('click',async()=>{
  const key=prompt('Enter memory key:');
  if(!key||!key.trim())return;
  const value=prompt('Enter memory value:');
  if(value===null)return;
  const scope=prompt('Enter scope (task, session, repository, user, system):','task')||'task';
  const kind=prompt('Enter kind (fact, decision, preference, pattern, negative_knowledge):','fact')||'fact';
  try{
    const res=await post('/v1/agent-state/memory',{
      action:'record',
      key:key.trim(),
      value:value.trim(),
      scope:scope.trim().toLowerCase(),
      kind:kind.trim().toLowerCase(),
      confidence:1.0
    });
    openModal(res,'Recorded Memory Entry');
    await loadAgentOsView();
  }catch(e){openModal({error:String(e)},'Record Memory Error')}
});

// Record Incident Dialog
$('agentOsRecordIncBtn')?.addEventListener('click',async()=>{
  const errorClass=prompt('Enter error class / anti-pattern:','LogicError');
  if(!errorClass||!errorClass.trim())return;
  const message=prompt('Enter failure description:','');
  const rootCause=prompt('Enter identified root cause:','');
  const verifiedFix=prompt('Enter verified fix or rule to prevent recurrence:','');
  try{
    const res=await post('/v1/agent-state/incidents',{
      action:'record',
      error_class:errorClass.trim(),
      message:message||'',
      root_cause:rootCause||'',
      verified_fix:verifiedFix||''
    });
    openModal(res,'Recorded Failure Anti-Pattern');
    await loadAgentOsView();
  }catch(e){openModal({error:String(e)},'Incident Record Error')}
});

// Verification Check
$('agentOsVerifyBtn')?.addEventListener('click',async()=>{
  const taskId=$('agentOsVerifyTaskId')?.value?.trim();
  if(!taskId){alert('Enter a Task ID to check completion');return;}
  try{
    const res=await post('/v1/agent-state/verification',{action:'completion',task_id:taskId});
    const c=res.completion||{};
    const canComplete=c.can_complete;
    $('agentOsVerifyOut').innerHTML=`<div class="diag-banner ${canComplete?'ok':'bad'}"><b>Status:</b> ${canComplete?'All acceptance criteria verified with valid receipts! Ready to complete.':'Task cannot complete yet. Outstanding criteria or missing evidence receipts.'}</div><div class="kv"><div>Complete Allowed</div><div class="${canComplete?'ok':'bad-t'}">${canComplete?'TRUE':'FALSE'}</div><div>Pending Criteria</div><div>${esc((c.pending_criteria||[]).join(', ')||'none')}</div><div>Passed Criteria</div><div>${esc((c.passed_criteria||[]).join(', ')||'none')}</div></div>`;
  }catch(e){$('agentOsVerifyOut').innerHTML=`<div class="bad-t">Verification check error: ${esc(e.message||e)}</div>`}
});

// Context Compile
$('agentOsCtxCompileBtn')?.addEventListener('click',async()=>{
  const taskId=$('agentOsCtxTaskId')?.value?.trim();
  const budget=Number($('agentOsCtxBudget')?.value||4000);
  try{
    const res=await post('/v1/agent-state/context',{action:'compile',task_id:taskId||'',token_budget:budget});
    const pre=$('agentOsCtxOut');
    pre.style.display='block';
    pre.textContent=res.text||JSON.stringify(res,null,2);
  }catch(e){$('agentOsCtxOut').style.display='block';$('agentOsCtxOut').textContent='Compilation failed: '+(e.message||e)}
});

// ── Models, RAG & Leases ──────────────────────────────────────────────────────
async function loadInstalledModels(){
  try{
    const r=await apiFetch('/v1/models',{cache:'no-store'}),d=await r.json();
    const models=d.data||[];
    const list=$('installedModelsList');
    if(list){
      list.innerHTML=models.length?models.map(m=>`<span class="chip ok">🤖 <b>${esc(m.id)}</b></span>`).join(' '):'<span class="muted">No models detected via Ollama</span>';
    }
  }catch(e){if($('installedModelsList'))$('installedModelsList').textContent='Failed to load models'}
}

async function loadRagWorkspaces(){
  try{
    const r=await apiFetch('/v1/rag/workspaces',{cache:'no-store'}),d=await r.json();
    const wss=d.workspaces||[];
    const list=$('ragWorkspacesList');
    const sel=$('ragSearchWsSelect');
    if(list){
      list.innerHTML=wss.length?wss.map(w=>`<div style="margin-bottom:4px"><span class="chip">📚 <b>${esc(w.workspace||w.id||w)}</b></span> <span class="tiny muted">${n(w.document_count||w.count||0)} chunks</span></div>`).join(''):'<span class="muted">No RAG workspaces registered</span>';
    }
    if(sel){
      const current=sel.value;
      sel.innerHTML='<option value="">Select workspace…</option>'+wss.map(w=>{const wid=w.workspace||w.id||w;return `<option value="${esc(wid)}">${esc(wid)}</option>`}).join('');
      if(current)sel.value=current;
    }
  }catch(e){if($('ragWorkspacesList'))$('ragWorkspacesList').textContent='Failed to load workspaces'}
}

async function loadActiveLeases(){
  try{
    const r=await apiFetch('/v1/leases',{cache:'no-store'}),d=await r.json();
    const leases=d.leases||[];
    rows('activeLeasesBody',leases,l=>{
      const id=esc(l.lease_id||'—');
      const paths=Array.isArray(l.paths)?l.paths.map(p=>`<span class="chip mono">${esc(p)}</span>`).join(' '):esc(l.path||'');
      const tenant=esc(l.tenant||'—');
      const purp=esc(l.purpose||'agent edit');
      const exp=l.expires_in_seconds?durSec(l.expires_in_seconds):'—';
      const action=`<button class="action-btn-sm danger" data-release-lease="${id}">Release</button>`;
      return clickableRow(l,`<td><strong>${id}</strong></td><td>${paths}</td><td>${tenant}</td><td class="tiny">${purp}</td><td class="tiny ok">${exp}</td><td>${action}</td>`);
    },6);
  }catch(e){console.warn('Leases load error',e)}
}
document.addEventListener('click',async e=>{
  const btn=e.target.closest?.('[data-release-lease]');
  if(!btn)return;
  const leaseId=btn.dataset.releaseLease;
  try{
    await post('/v1/leases/release',{lease_id:leaseId});
    await loadActiveLeases();
  }catch(err){alert('Release lease error: '+err)}
});

$('ragSearchBtn')?.addEventListener('click',async()=>{
  const q=$('ragSearchInput')?.value?.trim();
  const ws=$('ragSearchWsSelect')?.value?.trim();
  if(!q||!ws){alert('Enter query and select workspace');return;}
  $('ragSearchBtn').disabled=true;$('ragSearchBtn').textContent='Searching…';
  try{
    const res=await post('/v1/rag/search',{workspace:ws,query:q,top_k:6});
    const results=res.results||[];
    const out=$('ragSearchResults');
    out.style.display='block';
    if(results.length){
      out.innerHTML=`<h3 style="font-size:12px;margin:0 0 8px">Top ${results.length} Matches in ${esc(ws)}</h3>`+
        results.map((r,i)=>`<div style="margin-bottom:8px;padding:8px;background:#0d1219;border:1px solid #273546;border-radius:6px"><div style="display:flex;justify-content:space-between;margin-bottom:4px"><span class="chip mono"><b>${esc(r.file_path||r.path||'unknown')}</b></span><span class="chip ok">Score: ${r.score!==undefined?Number(r.score).toFixed(3):'—'}</span></div><pre style="margin:0;font-size:11px;color:#d7e2ef;max-height:160px;overflow:auto">${esc(r.content||r.text||'')}</pre></div>`).join('');
    }else{
      out.innerHTML='<div class="muted">No matches found for query.</div>';
    }
  }catch(err){alert('RAG search error: '+err)}
  finally{$('ragSearchBtn').disabled=false;$('ragSearchBtn').textContent='Semantic Search'}
});

// Quick keyboard tab shortcuts
window.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;
  if(e.key==='1')switchTab('overview');
  if(e.key==='2')switchTab('work');
  if(e.key==='3')switchTab('agentos');
  if(e.key==='4')switchTab('projects');
  if(e.key==='5')switchTab('explorer');
  if(e.key==='6')switchTab('commands');
  if(e.key==='7')switchTab('architecture');
  if(e.key==='8')switchTab('performance');
  if(e.key==='9')switchTab('reliability');
  if(e.key==='0')switchTab('config');
});

const initTab = location.hash.replace('#','') || localStorage.getItem('activeTab') || 'overview';
switchTab(initTab);
</script></body></html>"""
