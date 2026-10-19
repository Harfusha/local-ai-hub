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
.toolbar select{background:#172233;color:var(--fg);border:1px solid #2e405a;border-radius:5px;padding:3px 8px;font-size:11px}
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
.kv>div:nth-child(even){overflow-wrap:anywhere;word-break:break-word;min-width:0}
.split{display:grid;grid-template-columns:1.2fr .8fr;gap:12px}
@media(max-width:860px){.split{grid-template-columns:1fr}.hide-sm{display:none}}
.bar{height:5px;background:#202c3e;border-radius:4px;overflow:hidden;margin-top:6px}
.bar>i{display:block;height:100%;background:#38bdf8}
.event-header{display:grid;grid-template-columns:82px 72px 110px 130px minmax(180px,1fr) 90px 85px;gap:7px;border-bottom:1px solid var(--line-light);padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);background:var(--panel-head)}
.event{display:grid;grid-template-columns:82px 72px 110px 130px minmax(180px,1fr) 90px 85px;gap:7px;border-bottom:1px solid #1a2538;padding:7px 10px;font-size:11px}
.event:hover{background:#162338}
.events{max-height:650px;overflow:auto}
.empty{padding:16px;color:var(--muted);font-size:12px;text-align:center}
.chip{display:inline-block;border:1px solid #2d3e56;border-radius:5px;padding:2px 6px;margin:1px 3px 1px 0;font-size:10.5px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-variant-numeric:tabular-nums}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(4px);z-index:60;align-items:center;justify-content:center;padding:16px}
.modal-bg.open{display:flex}
.modal{width:min(900px,96vw);max-height:90vh;height:auto;display:flex;flex-direction:column;background:#0e1522;border:1px solid #2f4059;border-radius:12px;box-shadow:0 24px 90px rgba(0,0,0,0.7);padding:0;overflow:hidden}
.modal-head{flex:0 0 auto;background:#141e30;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:11px 14px;position:static}
#modalBody{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain}
#modalBody::-webkit-scrollbar{width:8px}
#modalBody::-webkit-scrollbar-track{background:#0b1118}
#modalBody::-webkit-scrollbar-thumb{background:#283a50;border-radius:4px}
#modalBody::-webkit-scrollbar-thumb:hover{background:#3b5678}
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
.control-popover .tiny.muted{grid-column:1/-1;padding-top:4px;font-weight:600;color:var(--muted);letter-spacing:0.02em}
.control-popover>button{width:100%}
.control-notice{grid-column:1/-1;white-space:normal;line-height:1.5;color:var(--muted);margin:2px 0 4px}
.project-toolbar{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.project-toolbar input:not([type=checkbox]):not([type=radio]),.project-toolbar select{background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px 9px;font-size:11px}
.project-toolbar input:not([type=checkbox]):not([type=radio]){flex:1;min-width:180px}
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
@media(max-width:980px){.split{grid-template-columns:1fr}.event,.event-header{grid-template-columns:72px 90px 1fr}.hide-sm{display:none}.page{padding:8px}.value{font-size:17px}}
@media(max-width:700px){.toolbar{padding:8px;gap:6px}.toolbar .brand{font-size:12px}.toolbar>.tiny{display:none}.control-menu{margin-left:0}.control-popover{position:fixed;left:8px;right:8px;top:72px;min-width:0}.tabs{padding:0 6px 6px}.tabbtn{padding:6px 8px}.project-toolbar{align-items:stretch}.project-toolbar input:not([type=checkbox]):not([type=radio]){flex-basis:100%}.project-summary{margin-left:0;width:100%}}

.settings-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:16px}
.settings-options label{display:flex;align-items:center;gap:10px;padding:13px 14px;border:1px solid var(--line);border-radius:8px;background:#111c29;cursor:pointer;min-width:0;font-size:13px}
.settings-options label:has(input:checked){border-color:#2c5c79;background:#102336}
.settings-options label:has(input:disabled){cursor:not-allowed;opacity:.6}
.feature-details summary{font-size:13px}.feature-details .label{display:none}
@media(max-width:900px){.settings-options{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.settings-options{grid-template-columns:1fr}.event-header{display:none}.event{grid-template-columns:72px minmax(0,1fr) auto;gap:8px 12px;padding:14px}.event>span:nth-child(1){grid-area:1/1}.event>span:nth-child(2){grid-area:1/2}.event>span:nth-child(7){grid-area:1/3}.event>span:nth-child(3){grid-area:2/1;font-size:11px;color:var(--muted)}.event>span:nth-child(4){grid-area:2/2}.event>span:nth-child(6){grid-area:2/3}.event>span:nth-child(5){display:none}}

.bundle-layout{grid-template-columns:minmax(0,1.8fr) minmax(290px,1fr);align-items:start}
.bundle-table{table-layout:fixed}.bundle-table th:nth-child(1){width:35%}.bundle-table th:nth-child(2){width:22%}.bundle-table th:nth-child(3){width:24%}.bundle-table th:nth-child(4){width:19%}
.bundle-table td{white-space:normal;overflow-wrap:anywhere;font-size:12px}.bundle-table td .btn{white-space:normal;padding:7px 9px;font-size:12px}
.bundle-table td:nth-child(1)>div{font-size:11px}.bundle-table td:nth-child(3){color:var(--muted)}
input[type=file]{padding:7px;line-height:1.5}input[type=file]::file-selector-button{font:inherit;color:var(--fg);background:#22354b;border:1px solid #405671;border-radius:5px;padding:5px 9px;margin-right:10px;cursor:pointer}
@media(max-width:1000px){.bundle-layout{grid-template-columns:1fr}}
@media(max-width:600px){.bundle-table,.bundle-table tbody{display:block;width:100%}.bundle-table thead{display:none}.bundle-table tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));padding:12px 0;border-bottom:1px solid var(--line);gap:8px 12px}.bundle-table td{display:block;padding:0;border:0;min-width:0}.bundle-table td:first-child,.bundle-table td:last-child{grid-column:1/-1}.bundle-table td:last-child .btn{width:100%;justify-content:center}}
</style><style>
.system-card .value{font-size:15px}
.trace-running{color:var(--accent)}
.trace-done{color:var(--ok)}
.trace-failed{color:var(--bad)}
.trace-queued{color:var(--warn)}
.trace-toolbar{display:flex;gap:8px;align-items:center;padding:9px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.trace-toolbar select{background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:5px 8px;font:inherit;font-size:11px}
.request-filter{display:flex;gap:8px;align-items:center;padding:9px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.request-filter input,.request-filter select{background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 8px;font:inherit;font-size:11px}
.request-filter input{flex:1;min-width:220px}
.request-summary{margin-left:auto}
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
.trace-event-content{display:grid;gap:8px;padding:2px 0}
.trace-event-glance{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.trace-event-summary{font-weight:600;overflow-wrap:anywhere}
.trace-progress{display:grid;grid-template-columns:minmax(90px,1fr) auto;align-items:center;gap:6px 10px;padding:7px 9px;border:1px solid #293746;border-radius:7px;background:#111820}
.trace-progress-track{height:7px;overflow:hidden;border-radius:99px;background:#263341}
.trace-progress-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,#6b9fff,#61c79a);transition:width .2s ease}
.trace-progress-label{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.trace-event-status,.trace-event-chip{display:inline-flex;align-items:center;border:1px solid #394758;border-radius:999px;padding:2px 7px;font-size:10px;color:var(--muted)}
.trace-event-status.ok{color:#79d2a3;border-color:#326a4c;background:#163123}
.trace-event-status.warn{color:#e8c77a;border-color:#776235;background:#302816}
.trace-event-status.bad{color:#ff9999;border-color:#784747;background:#351e22}
.trace-event-section{display:grid;grid-template-columns:54px minmax(0,1fr);gap:8px;align-items:start;width:100%;padding:7px 0;border-top:1px solid #273544;min-width:0}
.trace-event-label{padding-top:2px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.trace-event-section[data-kind="input"] .trace-event-label{color:#8eb4ff}
.trace-event-section[data-kind="output"] .trace-event-label{color:#79d2a3}
.trace-event-value{min-width:0;width:100%;overflow-wrap:anywhere}
.trace-event-value .human-grid{width:100%}
.trace-empty-output{color:var(--muted);font-size:11px}
.trace-event-meta{min-width:0;border-top:1px solid #273544;padding-top:6px}
.trace-event-meta summary{cursor:pointer;color:var(--muted);font-size:11px}
.trace-event-meta .human-grid{margin-top:7px}
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
.modal-hero{flex:0 0 auto;padding:14px 16px;background:linear-gradient(135deg,#131d2e,#0c1420);border-bottom:1px solid var(--line)}
.modal-body-wrap{padding:16px;display:flex;flex-direction:column;gap:14px}
.modal-card{flex-shrink:0;background:#0c121a;border:1px solid #243447;border-radius:8px;overflow:hidden}
.modal-card,.modal-actions-bar,.raw-json,.modal-form,.modal-checklist{flex-shrink:0}
.modal-card-head{padding:8px 12px;background:#131d2b;border-bottom:1px solid #202e3f;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;display:flex;justify-content:space-between;align-items:center}
.modal-card-body{padding:12px;overflow-wrap:anywhere}
.modal-actions-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding-top:6px}
.modal-form{display:flex;flex-direction:column;gap:12px}
.modal-form .form-group{display:flex;flex-direction:column;gap:5px}
.modal-form label{font-size:11px;font-weight:600;color:var(--fg)}
.modal-form .form-hint{font-size:10px;color:var(--muted)}
.modal-form input,.modal-form select,.modal-form textarea{background:#131d2b;color:var(--fg);border:1px solid #2d3f56;border-radius:6px;padding:8px 10px;font:inherit;font-size:12px}
.modal-form input:focus,.modal-form select:focus,.modal-form textarea:focus{border-color:var(--accent);outline:none}
.modal-checklist{display:flex;flex-direction:column;gap:6px}
.modal-checklist-item{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;background:#131b26;border:1px solid #223142;border-radius:6px}
.modal-checklist-item .item-text{font-size:13px;line-height:1.45;flex:1;min-width:0;overflow-wrap:anywhere;color:#dbe4ee}
.task-criterion-state{flex:0 0 auto;padding:4px 9px;border-radius:999px;border:1px solid;font-size:10px;font-weight:700;white-space:nowrap}
.task-criterion-state.is-verified{background:#0c2e1f;color:#86efac;border-color:#16a34a}
.task-criterion-state.is-pending{background:#30230a;color:#fcd34d;border-color:#a16207}
.task-criterion-state.is-failed{background:#2b1215;color:#fecaca;border-color:#b91c1c}
.task-criterion-state.is-stale{background:#30230a;color:#fde68a;border-color:#a16207}
.task-criterion-state.is-unavailable{background:#1b2532;color:#cbd5e1;border-color:#64748b}
.task-criteria-summary{font-size:11px;font-weight:700;color:#cbd5e1}
.task-criteria-summary.is-verified{color:#86efac}
.task-criteria-summary.is-pending{color:#fcd34d}
.task-criteria-summary.is-failed{color:#fecaca}
.task-gate-result{margin-top:10px;padding:10px 12px;border:1px solid #64748b;border-radius:7px;background:#111b29;color:#dbe4ee;font-size:12px;line-height:1.45}
.task-gate-result.is-ok{background:#0c241b;border-color:#15803d;color:#bbf7d0}
.task-gate-result.is-warning{background:#2b210d;border-color:#a16207;color:#fde68a}
.task-gate-result.is-failed{background:#2b1215;border-color:#b91c1c;color:#fecaca}
.task-terminal-state{display:flex;align-items:center;gap:10px;padding:12px;border:1px solid #334155;border-radius:7px;background:#111b29;color:#dbe4ee;line-height:1.45}
.task-terminal-state.is-completed{background:#0c241b;border-color:#15803d;color:#bbf7d0}
.task-terminal-state.is-failed{background:#2b1215;border-color:#b91c1c;color:#fecaca}
.task-terminal-state strong{font-size:11px;letter-spacing:.04em;text-transform:uppercase}
.modal-radio-option{display:flex;gap:10px;padding:10px 12px;border:1px solid #2a3c52;border-radius:8px;background:#111823;cursor:pointer;transition:border-color .15s}
.modal-radio-option:hover{border-color:var(--accent)}
.modal-radio-option input[type="radio"]{margin-top:3px}
.doc-check-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}
.doc-check-card{padding:10px 12px;border-radius:6px;border:1px solid #223142;background:#101620;display:flex;gap:10px;align-items:flex-start}
.doc-check-icon{font-size:16px;line-height:1;margin-top:2px}
.doc-check-title{font-weight:600;font-size:12px;margin-bottom:2px}
.doc-check-detail{font-size:11px;color:var(--muted)}
.copy-btn{background:#192535;border:1px solid #2b3d54;border-radius:4px;color:var(--fg);padding:2px 7px;font-size:10px;cursor:pointer}
.copy-btn:hover{background:#23354a;color:#fff}
.code-box{background:#0b1017;border:1px solid #212e3e;border-radius:6px;padding:10px;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:11px;color:#d7e2ef;max-height:280px;overflow:auto;white-space:pre-wrap;word-break:break-word}
/* Shared dashboard visual system. */
body{font-size:14px;line-height:1.55}
.page{padding:28px 24px 48px;max-width:1480px;margin-inline:auto;min-width:0}
.page-heading{margin:0 0 24px;max-width:85ch}
.page-heading h1{font-size:28px;line-height:1.2;letter-spacing:-.035em;margin:0 0 7px;color:var(--fg-bright);font-weight:700}
.page-heading p{margin:0;color:var(--muted);font-size:14px;line-height:1.6}
.toolbar,.tabs{max-width:1480px;margin-inline:auto}
.toolbar{gap:12px;padding:14px 24px}
.brand{font-size:16px}.toolbar>label.tiny{display:flex;align-items:center;gap:8px}
.tabs{padding:0 24px 12px;scrollbar-width:thin;gap:4px}
.tabbtn{padding:10px 12px;min-height:40px;font-size:13px}
.btn,.action-btn-sm,.copy-btn,.subtab-btn{min-height:36px;padding:7px 12px;font-size:13px;line-height:1.35;border-radius:7px}
.btn.primary{background:#173b59;border-color:#317eaf;color:#e0f2fe;font-weight:600}
.btn.primary:hover{background:#205173;border-color:var(--accent)}
.btn:disabled,button:disabled{opacity:.5;cursor:not-allowed}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
input:not([type=checkbox]):not([type=radio]),select,textarea{background:#111c29;color:var(--fg);border:1px solid #34465e;border-radius:7px;padding:8px 11px;font:inherit;font-size:13px;min-height:36px;max-width:100%}
input::placeholder,textarea::placeholder{color:#8d9db3;opacity:1}
input[type=checkbox],input[type=radio]{accent-color:var(--accent);width:16px;height:16px;flex:0 0 auto;margin:0;vertical-align:middle}
.project-toolbar input:not([type=checkbox]):not([type=radio]),.project-toolbar select,.request-filter input,.request-filter select,.modal-form input,.modal-form select,.modal-form textarea,.toolbar select{font-size:13px;padding:8px 11px;background:#111c29;border-color:#34465e;border-radius:7px}
.project-toolbar,.request-filter{padding:14px 16px;gap:10px}
.project-toolbar label{display:inline-flex;align-items:center;gap:8px;white-space:nowrap}
.project-summary,.request-summary{font-size:12px;color:var(--muted)}
.grid{gap:16px}.grid>*{min-width:0}
.grid-2{grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))}
.grid-3{grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))}
.grid-4{grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr))}
.grid-6{grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr))}
.card{padding:20px;min-height:132px;border-radius:12px;gap:8px;justify-content:flex-start}
.label{font-size:11px;letter-spacing:.055em}.value,.primary-metric{font-size:27px;line-height:1.25;margin-top:4px;letter-spacing:-.025em}
.card .sub{margin-top:auto;padding-top:8px}.sub,.tiny,.muted{font-size:12px}.sub{line-height:1.6}
.dash-group{margin-bottom:24px}.group-title{flex-wrap:wrap;gap:8px;margin-bottom:12px;font-size:12px;line-height:1.5}
.group-title>.tiny{text-transform:none;font-weight:400;letter-spacing:0}
.section{margin-top:20px;border-radius:12px}.section h2{padding:16px 18px;font-size:15px;flex-wrap:wrap;line-height:1.5}
.section h2>.tiny{font-weight:400;max-width:70ch}
.section .section{margin-top:0}.split{gap:20px}.split>*{min-width:0}
.table-wrap{max-height:580px;scrollbar-width:thin;overscroll-behavior:contain}
table{font-size:13px}th,td{padding:12px 14px;vertical-align:top}th{font-size:12px;font-weight:600}tbody tr:hover{background:#142135}
.project-table{table-layout:fixed;min-width:1100px}.project-table th:nth-child(1){width:25%}.project-table th:nth-child(2){width:27%}.project-table th:nth-child(3){width:21%}.project-table th:nth-child(4){width:12%}.project-table th:nth-child(5){width:15%}
.project-name,.project-root,.project-activity{max-width:100%;overflow-wrap:anywhere;white-space:normal;line-height:1.55}.project-name{overflow:visible}
.project-actions{gap:6px;flex-wrap:wrap}.project-actions .action-btn-sm{padding:6px 9px;font-size:12px;min-height:32px}
.project-progress{min-width:0}.project-progress-line{font-size:11px;gap:8px}.project-progress-line b{white-space:normal}.project-index{gap:7px;font-size:12px}
.empty{padding:32px 18px;font-size:13px;line-height:1.6;text-align:center}
.kv{font-size:13px;padding:16px 18px;gap:12px 20px;grid-template-columns:minmax(140px,34%) minmax(0,1fr)}
.chip,.badge-status,.pill{font-size:11px;line-height:1.45}.chip{padding:3px 7px}.badge-status{padding:4px 9px}
.subtabs{padding:12px 16px;gap:8px}.subtab-btn{font-size:12px}
.control-menu summary{font-size:13px;min-height:36px;padding:8px 12px}.control-popover{padding:16px;gap:10px;width:370px;min-width:0;max-height:calc(100dvh - 110px);overflow:auto}
.control-popover .tiny.muted{font-size:11px;text-transform:uppercase;letter-spacing:.06em;padding-top:8px}
.control-notice{font-size:12px;line-height:1.6}.diag-banner{padding:14px 16px;font-size:13px;flex-wrap:wrap;line-height:1.55}
.arena-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.arena-grid>*{min-width:0}
.metric-status{margin:0 0 14px;color:var(--muted);font-size:13px}.metric-status.warn-t{color:var(--warn)}
.metric-details{margin-top:16px;padding:15px 18px;border:1px solid var(--line);border-radius:10px;color:var(--muted);background:var(--panel)}
.metric-details summary{cursor:pointer;color:var(--fg);font-weight:600}.metric-details p{max-width:85ch}.metric-details pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.8 ui-monospace,Consolas,monospace;margin-bottom:0}
.modal-head{padding:16px 18px}.modal-form label{font-size:13px}.modal-form .form-hint{font-size:12px;line-height:1.55}.modal-actions-bar{gap:10px;flex-wrap:wrap}
.event,.event-header{font-size:12px;padding:12px 14px;align-items:start}.event>span,.event-header>span{min-width:0;overflow-wrap:anywhere;white-space:normal}
pre,.code-box{font-size:12px;line-height:1.7;tab-size:2}
@media(min-width:1100px){.grid-6{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:1000px){.split{grid-template-columns:1fr}.group-title>.tiny{width:100%}.section h2>.tiny{width:100%}}
@media(max-width:600px){.page{padding:20px 14px 32px}.page-heading{margin-bottom:20px}.page-heading h1{font-size:24px}.page-heading p{font-size:13px}.toolbar{padding:12px 14px;gap:8px}.tabs{padding:0 14px 10px}.tabbtn{font-size:12px;padding:9px 11px}.toolbar>.spacer{flex-basis:100%;margin-left:0}.control-menu{margin-left:auto}.control-popover{position:fixed;left:12px;right:12px;top:110px;width:auto;min-width:0;max-height:calc(100dvh - 134px)}.grid-6{grid-template-columns:repeat(2,minmax(0,1fr))}.card{padding:16px;min-height:132px}.value,.primary-metric{font-size:23px}.group-title>.tiny{display:none}.section h2{padding:14px 16px}.section h2 .spacer{margin-left:0}.project-toolbar,.request-filter{padding:12px}.project-toolbar input:not([type=checkbox]):not([type=radio]),.request-filter input{min-width:0;flex-basis:100%}.project-toolbar select,.request-filter select{flex:1;min-width:130px}.project-toolbar .project-summary{width:100%}.arena-grid{grid-template-columns:1fr}.kv{grid-template-columns:1fr;gap:4px}.kv>div:nth-child(even){margin-bottom:12px}.modal-bg{padding:8px}.modal{max-height:94dvh}.modal-form{grid-template-columns:1fr}.reliability-footer{align-items:stretch!important}.reliability-footer>div{flex-wrap:wrap}.reliability-footer .btn{white-space:normal}}
@media(max-width:380px){.grid-6{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style></head><body>
<div class="top">
  <div class="toolbar">
    <div class="brand-wrap">
      <span class="brand-icon">⚡</span>
      <span class="brand">Local AI Hub</span>
    </div>
    <span id="conn" class="pill warn-t"><span class="pulse-dot"></span>connecting</span>
    <span id="activityModeBadge" class="pill warn-t" data-mode="unknown">Mode: Unknown</span>
    <span id="updated" class="tiny"></span>
    <label class="tiny">Metrics period <select id="sloScope"><option value="process" selected>Since restart</option><option value="window">Last 30 days</option></select></label>
    <span id="featSummary" class="pill tiny"></span>
    <details id="controlMenu" class="control-menu">
      <summary>Controls</summary>
      <div class="control-popover">
        <div class="tiny muted">Diagnostics</div>
        <button class="btn" id="detailedTelemetryToggle" aria-pressed="false">Detailed telemetry: Off</button>
        <span class="tiny control-notice">Agent debug traces · off by default; payloads available when enabled</span>
        <button class="btn ok" id="optDbBtn">Optimize databases</button>
        <button class="btn" id="doctorBtn">Run diagnostics</button>
        <button class="btn" id="pauseEvents">Pause live events</button>
        <div class="tiny muted">Runtime control</div>
        <div class="tiny muted">Set activity mode</div>
        <button class="btn" id="activityModeActive" data-activity-mode="active" aria-pressed="false">Active</button>
        <button class="btn" id="activityModeGaming" data-activity-mode="gaming" aria-pressed="false">Gaming</button>
        <button class="btn" id="activityModeMaintenance" data-activity-mode="maintenance" aria-pressed="false">Maintenance</button>
        <span id="activityModeStatus" class="tiny muted" role="status" aria-live="polite">Checking mode…</span>
        <button class="btn warn" id="prepToggle">Pause preprocessing</button>
        <div class="tiny muted">Destructive maintenance</div>
        <button class="btn warn" id="purgeCacheBtn" data-control-action="purge_cache">Purge expired cache</button>
      </div>
    </details>
  </div>
  <div class="tabs">
    <button class="tabbtn active" data-tab="overview">📊 Overview</button>
    <button class="tabbtn" data-tab="work">⚡ Queue &amp; requests</button>
    <button class="tabbtn" data-tab="agentos" data-feature="agent_os">🤖 Agent OS</button>
    <button class="tabbtn" data-tab="projects" data-feature="preprocessing">📁 Projects</button>
    <button class="tabbtn" data-tab="commands" data-feature="commands">💻 Commands</button>
    <button class="tabbtn" data-tab="performance">🧠 Models &amp; RAG</button>
    <button class="tabbtn" data-tab="reliability">🛡️ Reliability &amp; Logs</button>
    <button class="tabbtn" data-tab="config">⚙️ Configuration</button>
    <button class="tabbtn" data-tab="bundles" data-feature="preprocessing">📦 Bundles</button>
    <button class="tabbtn" data-tab="events">📡 Live events</button>
  </div>
</div>

<div id="overview" class="page active">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-overview">Overview</h1><p>Current runtime, workload and token efficiency.</p></header>
  <section id="overviewHealthSummary" class="section" style="margin-bottom:12px;padding:14px;border-left:4px solid var(--accent)">
    <div class="label">Current runtime health</div>
    <div class="value primary-metric" id="overviewHealthLevel">Loading runtime health…</div>
    <div class="sub" id="overviewHealthEvidence">Waiting for live status.</div>
    <div class="tiny muted" id="overviewFreshness">Timestamp unavailable</div>
    <div class="tiny muted" id="overviewHistorySummary" style="margin-top:8px">Historical telemetry loading…</div>
    <button type="button" class="btn" id="overviewHealthAction" style="margin-top:10px">Open details</button>
    <div id="overviewAnnouncement" aria-live="polite" aria-atomic="true" style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0"></div>
  </section>
  <div class="dash-group">
    <div class="group-title"><span>Host &amp; System Health</span><span class="tiny muted">Core runtime state, capacity and supervisory control</span></div>
    <div class="grid grid-3" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
      <div class="card" id="hubHealthCard" style="cursor:pointer" title="Click to open Reliability &amp; Restart history"><div class="label" style="display:flex;justify-content:space-between"><span>Hub health</span><span>↗</span></div><div class="value primary-metric" id="health">…</div><div class="sub" id="uptime"></div></div>
      <div class="card system-card"><div class="label">Host Hardware</div><div class="value" id="sysUtil">…</div><div class="sub" id="sysSub"></div></div>
      <div class="card" id="loadedModelCard" style="cursor:pointer" title="Click to open Models &amp; RAG tab"><div class="label" style="display:flex;justify-content:space-between"><span>Loaded Model</span><span>↗</span></div><div class="value primary-metric" id="loadedModelVal">…</div><div class="sub" id="loadedModelSub"></div></div>
      <div class="card" id="agentStateCard" style="cursor:pointer" title="Click to open Agent OS inspector"><div class="label" style="display:flex;justify-content:space-between"><span>Agent OS State</span><span>↗</span></div><div class="value primary-metric" id="agentStateVal">…</div><div class="sub" id="agentStateSub"></div></div>
    </div>
  </div>

  <div class="dash-group">
    <div class="group-title"><span>Performance &amp; Token Efficiency</span><span class="tiny muted">Net cloud avoidance after agent tool-call/read overhead, local compute reuse and tail latency</span></div>
    <p id="efficiencyStatus" class="metric-status" role="status">Loading telemetry…</p>
    <div class="grid grid-6">
      <div class="card"><div class="label">Requests handled</div><div class="value primary-metric" id="handledRequests">…</div><div class="sub" id="handledRequestsSub"></div><canvas id="throughputSpark" class="spark-canvas" width="160" height="30"></canvas></div>
      <div class="card"><div class="label">Net cloud token delta</div><div class="value primary-metric" id="tokensSaved">…</div><div class="sub" id="tokensSavedSub"></div></div>
      <div class="card"><div class="label">Estimated savings</div><div class="value primary-metric" id="dollarsSaved">…</div><div class="sub" id="dollarsSavedSub"></div></div>
      <div class="card"><div class="label">Generation cache hit rate</div><div class="value primary-metric" id="cache">…</div><div class="sub" id="cacheSub"></div></div>
      <div class="card"><div class="label">Latency p50 / p95 / p99</div><div class="value" id="latency">…</div><div class="sub" id="queueWait"></div><canvas id="latencySpark" class="spark-canvas" width="160" height="30"></canvas></div>
      <div class="card"><div class="label">Recorded request failures</div><div class="value primary-metric" id="reliabilityValue">…</div><div class="sub" id="reliabilitySub"></div></div>
    </div>
    <details class="metric-details"><summary>How token savings are estimated</summary><p>Signed source/context baseline minus the tokens spent calling tools and reading their responses. Negative values mean additional cloud token cost. Local compute reuse and schema exposure are separate diagnostics.</p><pre id="efficiencyBreakdown">Waiting for accounting data.</pre></details>
  </div>

  <div class="dash-group">
    <div class="group-title"><span>Queues &amp; Execution</span><span class="tiny muted">Foreground scheduler and background workers</span></div>
    <div class="grid grid-2">
      <div class="card"><div class="label">Scheduler Queue</div><div class="value primary-metric" id="fgQueue">…</div><div class="sub" id="bgQueue"></div></div>
      <div class="card"><div class="label">Preprocessing Pipeline</div><div class="value primary-metric" id="prep">…</div><div class="sub" id="prepSub"></div></div>
    </div>
  </div>

  <details class="metric-details feature-details"><summary>Enabled capabilities</summary>
    <div style="display:flex;align-items:center;justify-content:space-between;margin:12px 0 8px">
      <div><span class="label" style="font-size:11.5px">Configured Feature Modules</span><span class="tiny muted" style="margin-left:8px">Granular subsystem status &amp; tool projection</span></div>
      <span class="tiny muted" id="featStatusText">Loading capability settings…</span>
    </div>
    <div id="featurePills" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  </details>

  <div class="split" style="margin-top:12px">
    <section class="section"><h2>Current workload <span class="tiny" id="currentSummary"></span></h2><div class="table-wrap"><table><thead><tr><th>State</th><th>Agent</th><th>Source</th><th>Model</th><th>Wait</th><th>Processing</th><th>Reason</th></tr></thead><tbody id="overviewJobs"></tbody></table></div></section>
    <section class="section"><h2>Historical telemetry hotspots <span class="tiny">Selected metrics period · retained samples</span></h2><div id="hotspots" class="kv"></div></section>
  </div>
</div>

<div id="work" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-work">Queue &amp; requests</h1><p>Follow live work and inspect retained request history.</p></header>
  <section class="section"><h2>Live scheduler work <span class="tiny" id="queueSummary">Current queue only; not request history.</span></h2><div class="table-wrap"><table><thead><tr><th>State</th><th>Job</th><th>Agent</th><th>Source</th><th>Model</th><th>Priority</th><th>Wait</th><th>Processing</th><th>Reason</th></tr></thead><tbody id="jobs"></tbody></table></div></section>
  <section class="section"><h2>Active API requests <span class="tiny">monitoring endpoints excluded</span></h2><div class="table-wrap"><table><thead><tr><th>Request</th><th>Agent</th><th>Action</th><th>Age</th></tr></thead><tbody id="activeReq"></tbody></table></div></section>
  <section class="section"><h2>Request history — Recent API requests <span class="tiny">Persisted API telemetry; distinct from scheduler work and Agent OS task runs.</span></h2><div class="request-filter"><input id="requestHistorySearch" aria-label="Search request history" type="search" placeholder="Search request ID, route, project, agent, error…" autocomplete="off"><select id="requestHistoryAction" aria-label="Filter by endpoint"><option value="">All endpoints</option></select><select id="requestHistoryStatus" aria-label="Filter by status"><option value="">All results</option><option value="failed">Failed</option><option value="2xx">2xx</option><option value="4xx">4xx</option><option value="5xx">5xx</option></select><select id="requestHistoryPeriod" aria-label="Filter by time"><option value="">All loaded</option><option value="3600">Last hour</option><option value="86400">Last 24 hours</option><option value="604800">Last 7 days</option><option value="2592000">Last 30 days</option></select><button class="btn" id="requestHistoryReset">Reset</button><span class="tiny request-summary" id="requestHistorySummary">0 requests</span></div><div class="table-wrap"><table><thead><tr><th>Time</th><th>Request</th><th>Project</th><th>Agent</th><th>Action</th><th>Status</th><th>Trace availability</th><th>Duration</th></tr></thead><tbody id="recentReq"></tbody></table></div></section>
</div>

<div id="agentos" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-agentos">Agent OS</h1><p>Tasks, memory and incident knowledge for a selected repository.</p></header>
  <div id="agentOsDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Agent OS feature is disabled in configuration</b> (<code>features.agent_os = false</code>). Durable task tracking and memory are inactive.</div>
  <section class="section">
    <h2><span style="display:flex;align-items:center;gap:8px">Agent Operating System <span class="tiny" id="agentOsState">0 active · 0 total tasks · 0 memories</span></span><div style="display:flex;gap:6px;align-items:center"><button class="btn primary" id="agentOsRefresh" style="padding:4px 10px;font-size:11px">↻ Refresh</button><button class="btn warn" id="agentOsCleanup" style="padding:4px 10px;font-size:11px">🧹 Cleanup stale state</button></div></h2>
    <div class="project-toolbar">
      <select id="agentOsRepoSelect" aria-label="Repository filter for Agent OS" style="max-width:240px">
        <option value="">All repositories (všechny repozitáře)</option>
      </select>
      <input id="agentOsRoot" list="worktreeRoots" aria-label="Repository root for Agent OS" placeholder="Or enter specific repository root" style="flex:1">
      <span class="tiny muted">Viewing tasks across all repositories or select specific root.</span>
    </div>
    <div class="subtabs">
      <button class="subtab-btn active" id="subtabTasks" data-agentos-tab="tasks">Tasks &amp; Contracts</button>
      <button class="subtab-btn" id="subtabMemory" data-agentos-tab="memory">Memory &amp; Facts</button>
      <button class="subtab-btn" id="subtabIncidents" data-agentos-tab="incidents">Negative Knowledge &amp; Incidents</button>
      <button class="subtab-btn" id="subtabTrajectories" data-agentos-tab="trajectories">Run History &amp; Inspect</button>
    </div>
  </section>


  <div id="agentOsTasksSec" style="display:block">
    <section class="section">
      <div class="project-toolbar">
        <input id="agentOsSearch" aria-label="Search tasks" type="search" placeholder="Search tasks by ID, goal, next action..." autocomplete="off">
        <select id="agentOsTaskStatus" aria-label="Task status filter"><option value="">All task statuses</option><option value="planned">Planned</option><option value="active">Active</option><option value="verifying">Verifying</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="blocked">Blocked</option></select>
        <button class="btn primary" id="agentOsCreateTaskBtn" style="padding:5px 9px">+ Create Task</button>
        <span class="tiny project-summary" id="agentOsSummary"></span>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Status</th><th>Task ID</th><th>Repository</th><th>Goal</th><th>Scope</th><th>Phase / Next Action</th><th>Criteria</th><th>Updated</th></tr></thead><tbody id="agentOsTasksBody"></tbody></table></div>
    </section>
  </div>

  <div id="agentOsMemorySec" style="display:none">
    <section class="section">
      <div class="project-toolbar">
        <input id="agentOsMemSearch" aria-label="Search memories" type="search" placeholder="Search memory keys and values..." autocomplete="off">
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
        <input id="agentOsIncSearch" aria-label="Search incidents" type="search" placeholder="Search error class, root cause, verified fix..." autocomplete="off">
        <select id="agentOsIncFilter" aria-label="Incident status"><option value="">All incidents</option><option value="unresolved">Unresolved</option><option value="resolved">Resolved with fix</option></select>
        <button class="btn warn" id="agentOsRecordIncBtn" style="padding:5px 9px">+ Record Anti-Pattern</button>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Incident ID</th><th>Status</th><th>Attempts</th><th>Operation</th><th>Error Class</th><th>Redacted Message</th><th>Root Cause</th><th>Verified Fix</th></tr></thead><tbody id="agentOsIncBody"></tbody></table></div>
    </section>
  </div>

  <div id="agentOsTrajectoriesSec" style="display:none">
    <section class="section">
      <div class="project-toolbar">
        <input id="trajSearch" aria-label="Search task runs" type="search" placeholder="Search task runs..." autocomplete="off">
        <button class="btn ok" id="trajRefreshBtn" style="padding:5px 9px">↻ Refresh Run History</button>
        <span class="tiny project-summary" id="trajSummary">Durable Agent OS tasks, checkpoints, and verification receipts — no HTTP request history.</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Task</th><th>Goal</th><th>Paths / receipts</th><th>Reported tokens</th><th>State</th><th>Actions</th></tr></thead>
          <tbody id="trajTableBody"></tbody>
        </table>
      </div>
      <div id="trajDetailPanel" style="padding:12px;border-top:1px solid var(--line);display:none">
        <h3 id="trajDetailTitle" style="font-size:13px;margin:0 0 8px"></h3>
        <div id="trajStepsList" class="trace-timeline"></div>
      </div>
    </section>
    <section class="section">
      <h2>Request trace inspector <span class="tiny" id="traceSummary">Request/model/tool evidence; separate from Agent task runs.</span></h2>
      <p class="tiny" id="tracePrivacyNotice">Podrobný obsah je vypnutý ve výchozím stavu. Podrobná telemetrie ukládá úplný endpoint input/output lokálně.</p>
      <div class="trace-toolbar"><span class="tiny">Inspect request events, model prompts, tool calls, and outputs.</span><button class="btn ok" id="visionReviewOpen" style="padding:4px 8px;font-size:11px">Frontend vision review</button><select id="traceKind" aria-label="Trace kind"><option value="">All kinds</option><option value="api_request">API requests</option><option value="async_job">Async jobs</option></select><button class="btn" id="traceRefresh" style="padding:4px 8px;font-size:11px">Refresh</button></div>
      <div class="table-wrap"><table><thead><tr><th>State</th><th>Kind</th><th>Action</th><th>Agent</th><th>Model</th><th>Created</th><th>Updated</th><th>Links</th></tr></thead><tbody id="traces"></tbody></table></div>
    </section>
  </div>
</div>


<div id="projects" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-projects">Projects</h1><p>Manage registered repositories and follow indexing progress.</p></header>
  <div id="prepDiagnosticBar" class="diag-banner info" style="display:none"></div>
  <section class="section">
    <h2><span style="display:flex;align-items:center;gap:8px">Projects <span class="tiny" id="prepState">0 registered projects · global running</span></span><div style="display:flex;gap:6px;align-items:center"><button class="btn warn" id="prepAllToggle" style="padding:4px 10px;font-size:11px">Pause all projects</button><button class="btn primary" id="regProjectBtn" style="padding:4px 10px;font-size:11px">+ Register</button><button class="btn warn" id="cleanMissingBtn" style="padding:4px 10px;font-size:11px">🧹 Clean missing</button></div></h2>
    <div class="project-toolbar"><input id="projectSearch" aria-label="Search projects" type="search" placeholder="Search repository identity, project, or worktree…" autocomplete="off"><select id="projectFilter" aria-label="Project status"><option value="all">All states</option><option value="running">Running</option><option value="waiting">Waiting</option><option value="error">Error</option><option value="paused">Paused</option><option value="ready">Ready</option></select><label class="tiny"><input id="projectGroupWorktrees" type="checkbox" checked> Group worktrees</label><select id="projectSort" aria-label="Project sort"><option value="priority">Operational priority</option><option value="name">Name</option><option value="progress">Progress</option><option value="recent">Recent activity</option></select><span class="tiny project-summary" id="projectSummary">0 of 0 projects</span></div>
    <div class="table-wrap"><table class="project-table"><thead><tr><th>Project</th><th>State &amp; activity</th><th>Phase &amp; progress</th><th>Indexes</th><th>Actions</th></tr></thead><tbody id="projectsBody"></tbody></table></div>
  </section>
</div>

<div id="commands" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-commands">Commands</h1><p>Running commands, broker activity and repository worktrees.</p></header>
  <div id="cmdDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Commands feature is disabled in configuration</b> (<code>features.commands = false</code>). Command classification and execution are blocked.</div>
  <section class="section"><h2>Running commands <span class="tiny" id="commandState">0 running</span></h2><div class="table-wrap"><table><thead><tr><th>Command</th><th>CWD</th><th>Class</th><th>Age</th><th>Timeout</th></tr></thead><tbody id="activeCommands"></tbody></table></div></section>
  <div class="split"><section class="section"><h2>Command broker statistics <span class="tiny">Since restart</span></h2><div id="commandStats" class="kv"></div></section><section class="section"><h2>Blocked by policy</h2><div class="table-wrap"><table><thead><tr><th>Reason</th><th>Count</th></tr></thead><tbody id="blockedReasons"></tbody></table></div></section></div>
  <section class="section" style="margin-top:12px">
    <h2>Registered Git Worktrees &amp; Subagent Sandboxes <span class="tiny" id="worktreeSummary">Choose a repository root</span></h2>
    <div class="project-toolbar">
      <input id="worktreeRoot" aria-label="Repository root for worktrees" placeholder="Choose or enter repository root" list="worktreeRoots" style="flex:1;min-width:220px">
      <datalist id="worktreeRoots"></datalist>
      <button class="btn primary" id="refreshWorktreesBtn">↻ Refresh Worktrees</button>
      <button class="btn warn" id="pruneWorktreesBtn">🧹 Prune Stale Worktrees</button>
      <span class="tiny muted project-summary">Isolated worktrees prevent concurrent file write collisions</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Worktree Directory</th><th>Branch</th><th>HEAD Commit</th><th>Status</th><th>Action</th></tr></thead>
        <tbody id="worktreesTable"></tbody>
      </table>
    </div>
  </section>
</div>


<div id="performance" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-performance">Models &amp; RAG</h1><p>Model performance, semantic indexes and execution profiles.</p></header>
  <section class="section">
    <h2>Telemetry snapshots <span class="tiny" id="performanceMetricsScope">Selected metrics period · retained samples</span></h2>
    <div style="padding:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px">
        <span><span class="chip" style="border-color:#38bdf8;color:#38bdf8">● Latency p95</span> <span class="chip" style="border-color:#34d399;color:#34d399">● Period average queue wait</span></span>
        <span class="tiny muted">Last 30 status snapshots · not individual requests</span>
      </div>
      <canvas id="liveChartCanvas" role="img" aria-label="Live telemetry graph. Waiting for samples." width="800" height="150" style="width:100%;height:150px;background:#080c13;border-radius:6px;border:1px solid #1e293b;display:block"></canvas>
      <div id="liveChartEmpty" class="tiny muted" style="display:none;padding-top:8px">No latency or queue samples yet.</div>
      <div id="liveChartSummary" class="tiny muted" style="padding-top:8px">Waiting for telemetry samples.</div>
    </div>
  </section>

  <section class="section" style="margin-top:12px">
    <h2>RAG Vector Workspaces <span class="tiny">Persistent semantic code index</span></h2>
    <div class="project-toolbar"><input id="ragWorkspaceSearch" aria-label="Search RAG workspaces" type="search" placeholder="Search RAG workspaces…" autocomplete="off"><span class="tiny" id="ragWorkspaceSummary">Workspace identity and index status.</span></div>
    <div id="ragWorkspacesList" style="padding:12px"><div class="tiny muted">Loading RAG workspaces…</div></div>
  </section>

  <section class="section" style="margin-top:12px">
    <h2>Local Model Arena <span class="tiny">Side-by-side prompt testbed comparing fast tier vs smart tier</span></h2>
    <div style="padding:12px">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
        <input type="text" id="arenaPromptInput" aria-label="Arena test prompt" placeholder="Test prompt (e.g. Write a Python function with LRU cache to solve knapsack problem)..." style="flex:1;min-width:min(320px,100%)">
        <button class="btn primary" id="arenaRunBtn">Run Arena Benchmark</button>
      </div>
      <div class="arena-grid">
        <div class="card" style="min-height:180px">
          <div class="label" id="arenaFastLabel">Fast Tier (Auto)</div>
          <div id="arenaFastStats" class="tiny muted" style="margin:4px 0">Ready</div>
          <pre id="arenaFastOutput" class="code-box" style="margin-top:6px;min-height:120px"></pre>
        </div>
        <div class="card" style="min-height:180px">
          <div class="label" id="arenaSmartLabel">Smart Tier (High Complexity)</div>
          <div id="arenaSmartStats" class="tiny muted" style="margin:4px 0">Ready</div>
          <pre id="arenaSmartOutput" class="code-box" style="margin-top:6px;min-height:120px"></pre>
        </div>
      </div>
    </div>
  </section>

  <section class="section" style="margin-top:12px">
    <h2>Loaded Runtime Models &amp; Context <span class="tiny">Resident models in Ollama with allocated context length and VRAM</span></h2>
    <div class="table-wrap"><table><thead><tr><th>Model</th><th>Context Window</th><th>Params</th><th>Quant</th><th>VRAM / Memory</th><th>GPU Offload</th><th>Status / TTL</th></tr></thead><tbody id="loadedModelsBody"></tbody></table></div>
  </section>

  <section class="section" style="margin-top:12px"><h2>Execution profiles <span class="tiny">configured capacity; context packing remains adaptive</span></h2>
<div class="table-wrap"><table><thead><tr><th>Model</th><th>Tier</th><th>Context</th><th>Max</th><th>Parallel</th><th>Thinking</th><th>Prompt cap</th></tr></thead><tbody id="executionProfiles"></tbody></table></div></section>
  <div class="split"><section class="section"><h2>Model statistics <span class="tiny">Selected metrics period · retained samples</span></h2><div class="table-wrap"><table><thead><tr><th>Model</th><th>Calls</th><th>Avg</th><th>Load</th><th>Fails</th></tr></thead><tbody id="models"></tbody></table></div></section><section class="section"><h2>Cache layers</h2><div class="table-wrap"><table><thead><tr><th>Layer</th><th>Calls</th><th>Avg</th><th>Context tokens avoided</th></tr></thead><tbody id="cacheLayers"></tbody></table></div></section></div>
  <div class="split"><section class="section"><h2>Agents</h2><div class="table-wrap"><table><thead><tr><th>Agent</th><th>Requests</th><th>Local AI</th><th>Avg</th><th>Fails</th></tr></thead><tbody id="agents"></tbody></table></div></section><section class="section"><h2>Execution routes</h2><div class="table-wrap"><table><thead><tr><th>Route</th><th>Task</th><th>Complexity</th><th>Calls</th><th>Avg</th><th>Fails</th></tr></thead><tbody id="routes"></tbody></table></div></section></div>
  <section class="section"><h2>HTTP tail latency <span class="tiny">per action · excludes policy rejections</span></h2><div class="table-wrap"><table><thead><tr><th>Action</th><th>Calls</th><th>p50</th><th>p95</th><th>p99</th><th>Fails</th></tr></thead><tbody id="httpTail"></tbody></table></div></section>
  <section class="section"><h2>Active Multi-Agent File Leases <span class="tiny">Prevents conflicting agent edits</span></h2><div class="table-wrap"><table><thead><tr><th>Lease ID</th><th>Paths</th><th>Purpose</th><th>Expires</th><th>Actions</th></tr></thead><tbody id="activeLeasesBody"></tbody></table></div></section>
</div>

<div id="reliability" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-reliability">Reliability &amp; logs</h1><p>Current service checks, recorded errors and process history.</p></header>
  <section class="section" id="reliabilitySummary"><h2>Runtime health &amp; recorded history <span class="tiny">Current checks and historical totals are independent.</span></h2><div id="reliabilityHeadline" class="kv"></div><div class="reliability-footer" style="padding:10px 14px;border-top:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap"><div class="tiny muted" id="reliabilityTrend">Historical telemetry loading…</div><button class="btn" id="reliabilityAction">Open request history</button></div></section>
  <div class="split">
    <section class="section"><h2>Recent error fingerprints</h2><div class="table-wrap"><table><thead><tr><th>Component</th><th>Operation</th><th>Diagnostic</th><th>Count</th><th>Recovered</th><th>Last seen</th></tr></thead><tbody id="errors"></tbody></table></div></section>
    <section class="section"><h2>Runtime / scheduler counters <span class="tiny">Since restart · independent of metrics period</span></h2><div id="runtimeCounters" class="kv"></div></section>
  </div>
  <section class="section">
    <h2>Process session &amp; restart history <span class="tiny">Up to 100 sessions started in the last 30 days · retained event accounting</span></h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Started</th><th>Uptime</th><th>Status</th><th>Events</th><th>Gen cache hit rate</th><th>Net tokens saved</th><th>Version</th></tr>
        </thead>
        <tbody id="sessionRows"></tbody>
      </table>
    </div>
  </section>
  <section class="section">
    <h2><span>Operational log tail</span><div style="display:flex;gap:6px;align-items:center"><input type="text" id="logFilterInput" aria-label="Filter operational logs" placeholder="Filter logs…" style="width:150px"><select id="logLinesSelect" aria-label="Log line count" ><option value="100">100 lines</option><option value="250" selected>250 lines</option><option value="500">500 lines</option></select><button class="btn" id="loadLogs" style="padding:3px 8px">Refresh</button><button class="btn" id="copyLogsBtn" style="padding:3px 8px">Copy</button></div></h2>
    <pre id="logTail" style="margin:0;padding:12px;white-space:pre-wrap;max-height:420px;overflow:auto;background:#0d1219;color:#c9d6e4;font-size:11px">Click Refresh to load logs.</pre>
  </section>
</div>

<div id="config" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-config">Configuration</h1><p>Review settings and save deliberate changes to the Hub.</p></header>
  <section class="section">
    <h2>Runtime configuration <span class="tiny">Saved changes apply after restart</span></h2>
    <div style="padding:14px">
      <div class="dash-group"><div class="group-title">Hardware &amp; Engine</div><div class="kv" style="padding:0;margin-bottom:12px"><div>Hardware profile</div><div><select id="cfgProfile" aria-label="Hardware profile" ><option>auto</option><option>cpu</option><option>integrated</option><option>low</option><option>balanced</option><option>high</option><option>max</option></select></div></div></div>
      <div class="dash-group"><div class="group-title">Core MCP Tools</div><div class="settings-options"><label><input type="checkbox" id="cfgFeatStatus"> Status checks</label><label><input type="checkbox" id="cfgFeatRepo"> Repository tools</label><label><input type="checkbox" id="cfgFeatTasks"> Local AI tasks</label><label><input type="checkbox" id="cfgFeatRag"> RAG search</label><label><input type="checkbox" id="cfgFeatCommands"> Command broker</label><label><input type="checkbox" id="cfgFeatCoord"> Coordination</label><label><input type="checkbox" id="cfgFeatArtifacts"> Artifacts</label></div></div>
      <div class="dash-group"><div class="group-title">Code Intelligence &amp; Indexing</div><div class="settings-options"><label><input type="checkbox" id="cfgPreprocess"> Preprocessing enabled</label><label><input type="checkbox" id="cfgIntel"> Managed code intelligence</label><label><input type="checkbox" id="cfgSerena"> Serena backend</label></div></div>
      <div class="dash-group"><div class="group-title">Advanced Subsystems</div><div class="settings-options"><label><input type="checkbox" id="cfgFeatSubagents"> Local AI workers</label><label><input type="checkbox" id="cfgFeatAgentOs"> Agent OS</label><label><input type="checkbox" id="cfgFeatDashboard"> Dashboard</label></div></div>
      <div class="tiny muted" style="margin:4px 0 7px">Scope and impact: saves only dashboard-managed overrides. Restart applies changes; reset removes only those overrides.</div><div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:6px"><button class="btn primary" id="cfgSave">Save overrides (restart required)</button><button class="btn" id="cfgReload">Reload view</button><button class="btn warn" id="cfgReset">Reset dashboard overrides</button><span class="tiny" id="cfgStatus" role="status"></span></div>
    </div>
  </section>
  <details class="metric-details"><summary>Advanced: effective configuration <span class="tiny" id="cfgPath"></span></summary><pre id="cfgPreview" style="margin:12px 0 0;padding:14px;white-space:pre-wrap;max-height:520px;overflow:auto;background:#090d14;color:#c9d6e4;font-size:12px"></pre></details>
</div>

<div id="bundles" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-bundles">Bundles</h1><p>Export available indexes or import a repository bundle.</p></header>
  <section class="section">
    <h2>Project Bundles — Export &amp; Import</h2>
    <div style="padding:12px">
      <p class="tiny muted">Bundles compress preprocessed index (AST, deterministic facts, RAG vectors and semantic cards) for instant restore on a different machine without re-indexing.</p>
      <div class="split bundle-layout" style="margin-top:10px">
        <div class="card" style="padding:12px"><h3 style="font-size:12px;margin:0 0 8px">Export Bundle</h3><div class="table-wrap"><table class="bundle-table"><thead><tr><th>Repository identity</th><th>Bundle readiness</th><th>Index contents</th><th>Action</th></tr></thead><tbody id="bundleExportTable"></tbody></table></div></div>
        <div class="card" style="padding:12px"><h3 style="font-size:12px;margin:0 0 8px">Import Bundle</h3><div style="display:flex;flex-direction:column;gap:8px"><input type="file" id="bundleFile" aria-label="Bundle ZIP file" accept=".zip,application/zip" ><input type="text" id="bundleTargetRoot" aria-label="Target repository root" placeholder="Optional target repository root" ><button class="btn primary" id="bundleImport">Import selected ZIP</button><div id="bundleImportStatus" class="tiny muted"></div></div></div>
      </div>
    </div>
  </section>
</div>

<div id="events" class="page">
  <header class="page-heading"><h1 tabindex="-1" id="page-title-events">Live events</h1><p>Recent activity from the runtime event buffer.</p></header><section class="section"><h2>Live activity <span class="tiny">RAM ring buffer · display pause does not pause runtime</span></h2><div class="project-toolbar"><select id="eventSeverity" aria-label="Event severity"><option value="">All severities</option><option value="failure">Failures</option><option value="warning">Warnings</option><option value="success">Successful</option><option value="info">Informational / result unreported</option></select><input id="eventSource" type="search" placeholder="Event source, agent, action…" aria-label="Event source"><span class="tiny" id="eventSummary">No events received.</span></div><div class="event-header"><span>Time</span><span>Agent</span><span>Type</span><span>Action / Stage</span><span class="hide-sm">Model</span><span>Duration</span><span>Status</span></div><div id="eventList" class="events"></div></section></div>

<div id="modalBg" class="modal-bg" role="dialog" aria-modal="true" aria-labelledby="modalTitle"><div class="modal"><div class="modal-head"><strong id="modalTitle">Details</strong><span id="modalLive" class="tiny" style="margin-left:10px"></span><button class="btn spacer" id="modalClose">Close</button></div><div id="modalBody"></div></div></div>
<div id="visionReviewModal" class="modal-bg" role="dialog" aria-modal="true" aria-label="Frontend vision review"><div class="modal vision-review-modal"><div class="modal-head"><strong>Frontend vision review</strong><span class="tiny" id="visionReviewStatus" aria-live="polite"></span><button class="btn spacer" id="visionReviewClose">Close</button></div><div id="visionReviewBody" class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Review input</span><span class="tiny">PNG/JPEG or current-tab evidence</span></div><div class="modal-card-body"><label class="modal-form"><span>Screenshot</span><input id="visionScreenshot" aria-label="Screenshot for frontend review" type="file" accept="image/png,image/jpeg,image/webp"></label><label class="modal-form"><span>Prompt</span><textarea id="visionPrompt" aria-label="Frontend review instructions" rows="4" maxlength="20000" placeholder="What should the visual critic inspect?"></textarea></label><div class="modal-actions-bar"><button class="btn" id="visionCaptureCurrentTab" type="button">Capture current tab</button><span id="visionCaptureState" class="trace-capture-state not-captured" data-capture-state="not_captured">Capture state · Not captured</span></div><div id="visionCaptureError" class="diag-banner bad" role="alert" style="display:none"></div><input id="visionFindingId" type="hidden"><button class="btn ok" id="visionReviewSubmit" type="button">Run vision review</button></div></div><div id="visionReviewResult" aria-live="polite"></div></div></div></div>

<script>
let cursor=0,paused=false,last=null,lastTraces=[],lastOverviewAnnouncement='',lastOverviewReceivedAt=0;
const latencySparkData=[], throughputSparkData=[], liveChartLatency=[], liveChartQueue=[];
let lastChartSnapshot=null,lastChartScope=null;

const traceStyles=document.createElement('style');
document.head.append(traceStyles);
traceStyles.textContent+='.trace-main-head #tracePageTitle,.trace-main-head #tracePageLive{display:none}.trace-inspector-head{align-items:center}.trace-header-title{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.trace-header-title h1{margin:0;font-size:16px;overflow-wrap:anywhere}.trace-header-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:11px}.trace-header-time{font-variant-numeric:tabular-nums}.trace-primary{margin:10px 0 14px}.trace-primary-grid{display:grid;grid-template-columns:1fr;gap:10px}.trace-primary-card{min-width:0;border:1px solid #33485f;border-radius:8px;background:#0d141c;overflow:hidden}.trace-primary-card.input{border-color:#41659a}.trace-primary-card.output{border-color:#397658}.trace-primary-card-head{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 11px;background:#151d26}.trace-primary-card-head h2{margin:0;font-size:12px}.trace-primary-card pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:12px;max-height:60vh;overflow:auto;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.trace-primary-empty{padding:12px;color:var(--muted);font-size:12px}.trace-metrics{display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:8px 0;color:var(--muted);font-size:11px}.trace-metrics span{border:1px solid #2b3948;border-radius:999px;padding:4px 8px}.trace-optional-details{margin-top:12px}@media(max-width:700px){.trace-inspector-head{align-items:flex-start;flex-direction:column}.trace-primary-card pre{max-height:50vh}}';
document.head.insertAdjacentHTML('beforeend','<style>.vision-review-modal{width:min(980px,96vw)}.vision-review-modal .modal-body-wrap{padding:12px;overflow-y:auto}.vision-review-modal .modal-card-body{display:grid;gap:10px}.vision-review-modal textarea{width:100%;box-sizing:border-box;background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px;font:inherit;resize:vertical}.vision-review-modal input[type=file]{color:var(--fg)}.vision-review-modal .modal-actions-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.trace-vision-provenance{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}.trace-vision-provenance span{border:1px solid #2b3948;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px}.trace-vision-summary{border-color:#41659a}.trace-vision-findings{display:grid;gap:8px}.trace-vision-finding{border:1px solid #33485f;border-left:3px solid var(--accent);border-radius:7px;background:#0d141c;padding:10px}.trace-vision-finding.blocker,.trace-vision-finding.high{border-left-color:var(--bad)}.trace-vision-finding-head{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.trace-vision-finding-head strong{overflow-wrap:anywhere}.trace-vision-finding .trace-chip{margin:0}.trace-vision-finding-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.trace-vision-evidence{margin-top:8px}.trace-vision-evidence img{max-width:100%;height:auto;border:1px solid #33485f;border-radius:5px}.trace-vision-error{border-color:#784747;color:#ffb1b1}.trace-vision-empty{color:var(--muted);padding:8px 0}</style>');
 document.head.insertAdjacentHTML('beforeend','<style>.trace-inspector-context{display:flex;align-items:flex-end;gap:8px;flex-direction:column}.trace-project-label{border:1px solid #41659a;border-radius:999px;padding:4px 8px;color:#c7dcff;font-size:10px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-search-presentation,.trace-model-presentation{border:1px solid #33485f;border-radius:8px;background:#0c121a;padding:12px}.trace-search-query{border:1px solid #2d4965;border-left:3px solid #5b8def;border-radius:6px;background:#111b26;padding:9px 10px;overflow-wrap:anywhere}.trace-search-query strong,.trace-search-answer strong{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}.trace-search-spec{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0;color:var(--muted);font-size:10px}.trace-search-spec span{border:1px solid #2b3948;border-radius:999px;padding:3px 7px}.trace-search-results{margin-top:12px}.trace-search-results h3{margin:0 0 5px;font-size:11px}.trace-search-result-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;gap:9px;align-items:start;border-top:1px solid #273544;padding:8px 0;min-width:0}.trace-search-rank{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;background:#1c3042;color:#c7dcff;font-size:10px}.trace-search-result-main{min-width:0;overflow-wrap:anywhere}.trace-search-result-main strong{display:block;overflow-wrap:anywhere}.trace-search-result-main>.tiny{display:block;margin-top:2px}.trace-search-snippet{color:#c9d5e2;font-size:11px;line-height:1.35;margin-top:4px;overflow-wrap:anywhere}.trace-search-score{color:var(--muted);font-size:10px;padding-top:3px}.trace-search-answer{border-top:1px solid #273544;margin-top:8px;padding-top:9px;overflow-wrap:anywhere}.trace-model-presentation .trace-primary-card{min-height:0}.trace-model-presentation .trace-chat-message{border-top:0;padding:0}.trace-model-presentation .trace-chat-role{display:none}.trace-model-presentation .prompt-pre{max-height:260px}.trace-summary-card,.trace-code-card,.trace-list-card{border:1px solid #273544;border-radius:6px;background:#0d141c;padding:10px;margin-bottom:8px}.trace-summary-card h3,.trace-code-card h3,.trace-list-card h3{margin:0 0 6px;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.trace-summary-value{overflow-wrap:anywhere}.trace-chip{display:inline-block;padding:2px 6px;border-radius:4px;background:#172535;border:1px solid #2d4965;font-size:11px;margin:2px}.trace-obj-field{margin-bottom:4px;overflow-wrap:anywhere}.trace-obj-key{color:var(--muted);font-size:11px;font-weight:600}.trace-obj-val{font-size:11px}.trace-primary-groups{display:grid;gap:8px;margin-top:10px}.trace-primary-group{border:1px solid #273544;border-radius:6px;background:#0d141c}.trace-primary-group>summary{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 10px;cursor:pointer;color:var(--fg);font-size:11px;font-weight:700;list-style:none}.trace-primary-group>summary::-webkit-details-marker{display:none}.trace-primary-group>summary::after{content:\"+\";color:var(--muted);font-size:15px;line-height:1}.trace-primary-group[open]>summary::after{content:\"−\"}.trace-primary-group-body{padding:0 10px 10px}.trace-primary-group .trace-primary-card{border:0;background:transparent;padding:0;margin:0}.trace-primary-group .trace-primary-card h3{display:none}.trace-primary-group .trace-primary-value{padding-top:2px}@media(max-width:700px){.trace-inspector-context{align-items:flex-end}.trace-project-label{max-width:150px}}</style>');

const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), escJs=v=>esc(JSON.stringify(v));
const n=v=>Number(v||0).toLocaleString(), ms=v=>{v=Number(v||0);return v>=1000?(v/1000).toFixed(v>=10000?1:2)+' s':Math.round(v)+' ms'}, durSec=s=>{s=Number(s||0);if(s<60)return Math.round(s)+'s';if(s<3600)return Math.floor(s/60)+'m '+Math.round(s%60)+'s';if(s<86400)return Math.floor(s/3600)+'h '+Math.floor((s%3600)/60)+'m';return Math.floor(s/86400)+'d '+Math.floor((s%86400)/3600)+'h'}, age=msv=>durSec(Number(msv||0)/1000), formatBytes=b=>{b=Number(b||0);if(b<=0)return '0 B';const u=['B','KB','MB','GB','TB'],i=Math.min(u.length-1,Math.floor(Math.log(b)/Math.log(1024)));return (b/Math.pow(1024,i)).toFixed(i>1?1:0)+' '+u[i];};

function dashboardPreprocessingHealth(preprocessing={},dependencies={},features={}){
  const disabled=features.preprocessing===false||preprocessing.enabled===false;
  if(disabled)return {available:true,statsAvailable:true,errorCount:0,disabled:true};
  const unavailable=preprocessing.success===false||dependencies['preprocessing.status']?.degraded===true||!Array.isArray(preprocessing.projects);
  const statsAvailable=dependencies['preprocessing.stats']?.degraded!==true;
  if(unavailable)return {available:false,statsAvailable,errorCount:null};
  const errorCount=preprocessing.projects.filter(project=>String(project?.status||'').toLowerCase()==='error').length;
  return {available:true,statsAvailable,errorCount,disabled:false};
}

function dashboardHealthBadge(status={}){
  const dependencies=status.dependency_status&&typeof status.dependency_status==='object'&&!Array.isArray(status.dependency_status)?Object.entries(status.dependency_status).filter(([name])=>name!=='telemetry.summary').map(([,value])=>value):[];
  const degradedCount=dependencies.filter(item=>item&&item.degraded===true).length;
  const preprocessingDeps=status.dependency_status&&typeof status.dependency_status==='object'&&!Array.isArray(status.dependency_status)?status.dependency_status:{};
  const preprocessingAdvertised=Object.hasOwn(status,'preprocessing')||Object.hasOwn(preprocessingDeps,'preprocessing.status')||Object.hasOwn(preprocessingDeps,'preprocessing.stats');
  const preprocessing=preprocessingAdvertised?dashboardPreprocessingHealth(status.preprocessing||{},status.dependency_status||{},status.features||{}):{available:true,statsAvailable:true,errorCount:0,disabled:false};
  const preprocessingWarning=preprocessingAdvertised&&(!preprocessing.available||!preprocessing.statsAvailable||preprocessing.errorCount>0);
  const telemetryOnlyFailure=status.dependency_status?.['telemetry.summary']?.degraded&&degradedCount===0;
  const degraded=(status.success===false&&!telemetryOnlyFailure)||degradedCount>0;
  const ollamaState=status.ollama_status||((status.ollama_online==null)?'unknown':status.ollama_online?'online':'offline');
  const className=status.hub_online?(degraded||ollamaState!=='online'||preprocessingWarning?'warn-t':'ok'):'bad-t';
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
  if($('tokensSaved'))$('tokensSaved').textContent=metricText(netDelta);
  if($('tokensSavedSub'))$('tokensSavedSub').textContent=period+' · '+(calls===null?'Accounted call count unavailable':calls?n(calls)+' accounted calls':'No accounted calls yet')+(!state.complete?' · partial estimate':'');
  if($('dollarsSaved'))$('dollarsSaved').textContent=observability.estimated_savings_pricing_mode==='incomplete'||observability.estimated_savings_usd==null?'Unknown':formatEstimatedUsd(observability.estimated_savings_usd);
  if($('dollarsSavedSub'))$('dollarsSavedSub').textContent=(observability.estimated_savings_pricing_mode==='incomplete'?'Known channel subtotals: input '+formatChannelSavings(observability.estimated_input_savings_usd,observability.cloud_input_token_cost_usd_per_million)+' · output '+formatChannelSavings(observability.estimated_output_savings_usd,observability.cloud_output_token_cost_usd_per_million)+' · historical channel costs unknown':observability.estimated_savings_pricing_mode==='input_output'?'Separate input/output rates':'Cost unavailable')+' · '+period+(!state.complete?' · incomplete data':'');
  if(period==='Last 30 days'){
    for(const id of ['handledRequestsSub','cacheSub','queueWait'])if($(id))$(id).textContent='Retained samples · '+$(id).textContent;
  }
  if(breakdown)breakdown.textContent+='\nUSD input rate: '+(observability.cloud_input_token_cost_usd_per_million==null?'unknown':'$'+Number(observability.cloud_input_token_cost_usd_per_million).toFixed(2)+' / 1M')+'\nUSD output rate: '+(observability.cloud_output_token_cost_usd_per_million==null?'unknown':'$'+Number(observability.cloud_output_token_cost_usd_per_million).toFixed(2)+' / 1M');
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
  const failedChecks=Object.entries(snapshot.dependency_status||{}).filter(([name,value])=>!name.startsWith('runtime_stats.')&&name!=='telemetry.summary'&&value?.degraded).map(([name])=>name);
  if(failedChecks.length)signals.push('unavailable checks: '+failedChecks.join(', '));
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
  if(!telemetry){
    signals.push('telemetry data is unavailable or stale');
  }else{
    if(!telemetry.available)signals.push('telemetry data is unavailable or stale');
    else if(!telemetry.activityObserved)signals.push('telemetry writer activity is unobserved');
    else if(!telemetry.accountingBalanced)signals.push('telemetry writer accounting is unbalanced');
    else if(telemetry.pending>20)signals.push(`telemetry writer has ${telemetry.pending} pending record${telemetry.pending===1?'':'s'}`);
    else if(telemetry.summaryCacheStale)signals.push('telemetry summary is stale');
    else if(!telemetry.complete)signals.push('telemetry coverage is incomplete');
  }
  const dataCompleteness=!telemetry?'unknown':!telemetry.available?'unavailable':telemetry.complete?'complete':'incomplete';
  const functionalFailure=hubOnline===false||heartbeatStale||terminalStatuses.includes(status)||['degraded','stale'].includes(status)||current.degraded===true||failedChecks.length>0||Boolean(!preprocessing.disabled&&preprocessing.errorCount>0);
  const functionalUncertainty=preprocessingAdvertised&&(!preprocessing.available||!preprocessing.statsAvailable);
  const functionalHealth=functionalFailure?'degraded':functionalUncertainty||ollamaStatus!=='online'||['attention','warning','warn','partial'].includes(status)?'attention':'healthy';
  const finish=health=>({...health,process_liveness:processLiveness,data_completeness:dataCompleteness,functional_health:functionalHealth,reason:`${health.reason} Process liveness: ${processLiveness}; data completeness: ${dataCompleteness}; functional health: ${functionalHealth}.`});
  const actionTab=openIssues||count(current.blocked_requests)?'work':'reliability';
  const actionLabel=actionTab==='work'?'Open queue and requests':'Open reliability details';
  if(hubOnline===false||heartbeatStale||['degraded','down','offline','unavailable','crashed','stopped','stale'].includes(status)||current.degraded===true){
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
  renderLine(series1, '#38bdf8', 'rgba(56,189,248,0.1)');
  renderLine(series2, '#34d399', 'rgba(52,211,153,0.1)');
}

const tracePageStyles=document.createElement('style');
tracePageStyles.textContent='.trace-page{height:calc(100vh - 112px);min-height:560px;padding:12px!important}.trace-layout{display:grid;grid-template-columns:300px minmax(0,1fr);height:100%;min-height:0;gap:12px}.trace-sidebar,.trace-main{background:var(--panel);border:1px solid var(--line);border-radius:8px;min-height:0;overflow:hidden}.trace-sidebar{display:flex;flex-direction:column}.trace-sidebar-head{padding:12px;border-bottom:1px solid var(--line);background:#151d26}.trace-sidebar-head strong{display:block;font-size:14px;margin:7px 0 3px}.trace-sidebar-list{overflow:auto;padding:6px}.trace-side-item{display:block;width:100%;text-align:left;background:transparent;color:var(--fg);border:1px solid transparent;border-radius:7px;padding:9px;margin:2px 0;cursor:pointer}.trace-side-item:hover{background:#1a2734;border-color:#33485f}.trace-side-item.active{background:#1c3042;border-color:var(--accent)}.trace-side-top{display:flex;align-items:center;gap:7px}.trace-side-state{width:7px;height:7px;border-radius:50%;background:var(--warn);flex:0 0 auto}.trace-side-state.done{background:var(--ok)}.trace-side-state.failed{background:var(--bad)}.trace-side-action{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-side-meta{display:block;color:var(--muted);font-size:10px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.trace-main{overflow:auto;padding:18px}.trace-main-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}.trace-main-head h1{font-size:18px;margin:0;overflow-wrap:anywhere}.trace-main-head .spacer{margin-left:auto}.trace-select-empty{display:grid;place-items:center;min-height:420px;color:var(--muted);text-align:center;border:1px dashed #33485f;border-radius:8px}.trace-main .human-shell{padding:0}.trace-main .human-section{margin:12px 0}.trace-main .trace-timeline{padding:12px}.trace-page .trace-raw-panel{max-width:none}@media(max-width:900px){.trace-page{height:auto;min-height:calc(100vh - 112px)}.trace-layout{grid-template-columns:1fr}.trace-sidebar{max-height:280px}.trace-main{min-height:620px}}';
document.head.append(tracePageStyles);

const workPageStyles=document.createElement('style');
workPageStyles.textContent='.work-page{display:grid!important;grid-template-columns:minmax(0,1.55fr) minmax(320px,.9fr);gap:12px;align-items:start}.work-page>.work-summary{grid-column:1/-1}.work-panel{min-width:0}.work-panel-1{grid-column:1;grid-row:2}.work-panel-2{grid-column:2;grid-row:2}.work-panel-3{grid-column:1;grid-row:3}.work-panel-4{grid-column:2;grid-row:3}.work-summary{padding:14px!important}.work-summary-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.work-kicker{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}.work-summary h2{margin:0}.work-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}.work-kpis>div{background:#0d141c;border:1px solid #2b3948;border-radius:7px;padding:9px 10px}.work-kpis span{display:block;color:var(--muted);font-size:10px}.work-kpis strong{display:block;font-size:18px;margin-top:3px}.work-panel h2{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.work-panel .table-wrap{max-height:390px;overflow:auto}.work-panel table{width:100%;table-layout:fixed}.work-panel th{position:sticky;top:0;z-index:1;background:#151d26}.work-panel td{vertical-align:top;overflow-wrap:anywhere}.work-panel-1 th:nth-child(1){width:13%}.work-panel-1 th:nth-child(2){width:20%}.work-panel-1 th:nth-child(3){width:24%}.work-panel-1 th:nth-child(4){width:17%}.work-panel-1 th:nth-child(5){width:26%}.work-panel-2 th:nth-child(1){width:27%}.work-panel-2 th:nth-child(2){width:30%}.work-panel-2 th:nth-child(3){width:27%}.work-panel-2 th:nth-child(4){width:16%}.work-panel-3 th:nth-child(1){width:12%}.work-panel-3 th:nth-child(2){width:14%}.work-panel-3 th:nth-child(3){width:9%}.work-panel-3 th:nth-child(4){width:14%}.work-panel-3 th:nth-child(5){width:31%}.work-panel-3 th:nth-child(6){width:10%}.work-panel-3 th:nth-child(7){width:10%}.work-panel-3 td{white-space:normal;overflow-wrap:anywhere;word-break:break-word}.work-panel-4 th:nth-child(1){width:13%}.work-panel-4 th:nth-child(2){width:22%}.work-panel-4 th:nth-child(3){width:22%}.work-panel-4 th:nth-child(4){width:18%}.work-panel-4 th:nth-child(5){width:15%}.work-panel-4 th:nth-child(6){width:10%}.work-state{display:inline-block;border:1px solid #3b4b5e;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px;white-space:nowrap}.work-state.live{border-color:#4f8edb;color:var(--accent)}.work-state.bad{border-color:#a64c4c;color:var(--bad)}.timing-label{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.04em}.work-panel-4 .tiny{line-height:1.35}@media(max-width:1050px){.work-page{grid-template-columns:1fr}.work-page>.work-summary,.work-panel-1,.work-panel-2,.work-panel-3,.work-panel-4{grid-column:1;grid-row:auto}.work-panel .table-wrap{max-height:320px}}@media(max-width:620px){.work-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.work-summary-head{display:block}.work-summary-head>.tiny{display:block;margin-top:6px}.work-panel table{table-layout:auto;min-width:650px}.work-panel .table-wrap{overflow:auto}}';
document.head.append(workPageStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-side-state.interrupted{background:var(--warn)}.trace-interrupted{color:var(--warn)}.work-page{display:none!important}.work-page.active{display:grid!important}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.work-page.active .work-panel-4{grid-column:1/-1!important;grid-row:3!important}.work-page.active .work-panel-4 .table-wrap{max-height:460px}.work-page.active .work-panel-3{grid-column:1/-1!important;grid-row:4!important}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.work-panel-3 th:nth-child(1){width:10%}.work-panel-3 th:nth-child(2){width:12%}.work-panel-3 th:nth-child(3){width:9%}.work-panel-3 th:nth-child(4){width:10%}.work-panel-3 th:nth-child(5){width:20%}.work-panel-3 th:nth-child(6){width:11%}.work-panel-3 th:nth-child(7){width:9%}.work-panel-3 th:nth-child(8){width:12%}.work-panel-3 th:nth-child(9){width:7%}.work-panel-3 td:nth-child(8),.work-panel-3 td:nth-child(9){white-space:nowrap;overflow-wrap:normal;word-break:normal}</style>');

const workFilterStyles=document.createElement('style');
workFilterStyles.textContent='.work-filter{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}.work-filter input,.work-filter select{background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px 9px;font:inherit;font-size:11px}.work-filter input{flex:1;min-width:220px}.work-filter select{min-width:125px}.work-filter .btn{padding:6px 9px;font-size:11px}.work-filter-summary{color:var(--muted);font-size:10px}';
document.head.append(workFilterStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-sidebar-controls{display:flex;gap:6px;padding:8px 8px 2px}.trace-sidebar-controls input,.trace-sidebar-controls select{min-width:0;width:100%;background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 7px;font:inherit;font-size:10px}.trace-sidebar-controls select{width:116px;flex:0 0 116px}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-main,.trace-step-body,.trace-event,.human-section{min-width:0}.prompt-meta{display:flex;gap:5px;flex-wrap:wrap;padding:7px 8px;border-bottom:1px solid #202a35}.prompt-chip{border:1px solid #394758;border-radius:999px;padding:2px 7px;color:var(--muted);font-size:9px}.prompt-chip strong{color:var(--fg)}.prompt-messages{display:grid;gap:6px;padding:7px}.prompt-card{border:1px solid #2d3d4e;border-left:3px solid #5b8def;border-radius:6px;overflow:hidden}.prompt-card.role-system{border-left-color:#a78bfa}.prompt-card.role-user{border-left-color:#38bdf8}.prompt-card.role-assistant{border-left-color:#4ade80}.prompt-card-head{display:flex;align-items:center;gap:7px;padding:6px 8px;background:#151d26;color:var(--fg);font-size:10px;font-weight:700}.prompt-card-head .tiny{margin-left:auto}.prompt-pre{margin:0;padding:7px 8px;background:#0d1219;color:#d7e2ef;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.3;font-size:11px;max-height:150px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}.prompt-context{margin:0 8px 8px;border:1px solid #334355;border-radius:5px;background:#111923}.prompt-context summary{cursor:pointer;padding:6px 8px;color:var(--muted);font-size:9px}.prompt-context .prompt-pre{max-height:180px;border-top:1px solid #273544}.prompt-fallback{padding:8px}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-codex-timeline,.trace-codex-timeline *{min-width:0;max-width:100%;box-sizing:border-box}.trace-codex-timeline .trace-timeline-event,.trace-codex-timeline .trace-tool-card{overflow:hidden;overflow-wrap:anywhere;word-break:break-word}.trace-codex-timeline .trace-timeline-marker,.trace-codex-timeline h4,.trace-codex-timeline .trace-tool-field,.trace-codex-timeline .human-grid,.trace-codex-timeline .human-value{overflow-wrap:anywhere;word-break:break-word}.trace-codex-timeline pre{max-width:100%;white-space:pre-wrap;overflow:auto}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-primary{margin:0 0 14px}.trace-primary-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:8px}.trace-primary-head h2{margin:0;font-size:14px}.trace-primary-grid{display:grid;grid-template-columns:1fr;gap:10px}.trace-primary-card{min-width:0;border:1px solid #33485f;border-radius:8px;overflow:hidden;background:#0d141c}.trace-primary-card.input{border-color:#41659a}.trace-primary-card.output{border-color:#397658}.trace-primary-card h3{margin:0;padding:9px 11px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;background:#151d26}.trace-primary-card.input h3{color:#a9c6ff}.trace-primary-card.output h3{color:#9be7b8}.trace-primary-value{min-width:0;padding:10px;overflow-wrap:anywhere}.trace-primary-value .human-grid{padding:0}.trace-primary-empty{color:var(--muted);font-size:11px}.trace-presentation-actions{display:flex;align-items:center;justify-content:flex-end;gap:5px;flex-wrap:wrap;margin:0 0 8px}.trace-presentation-actions .btn{padding:4px 7px;font-size:10px}.trace-capture-state{display:inline-flex;align-items:center;border:1px solid #394758;border-radius:999px;padding:3px 7px;font-size:10px;white-space:nowrap}.trace-capture-state.produced{border-color:#397658;color:#9be7b8}.trace-capture-state.empty{border-color:#8b6d31;color:#f4d58b}.trace-capture-state.not-captured{border-color:#536274;color:#aeb9c7}.trace-capture-state.redacted{border-color:#795a9b;color:#d9b8ff}.trace-optional-details{width:100%;box-sizing:border-box;border:1px solid #2d3d4e;border-radius:8px;background:#0c121a}.trace-optional-details>summary{cursor:pointer;padding:10px 12px;color:var(--fg);font-size:11px;font-weight:700}.trace-optional-details>summary::marker{color:var(--accent)}.trace-optional-details[open]>summary{border-bottom:1px solid #273544}.trace-optional-body{padding:0 12px 12px;min-width:0;overflow-wrap:anywhere}.trace-optional-body .human-section:first-child{margin-top:12px}.trace-chat-columns{display:grid;grid-template-columns:1fr;gap:10px;align-items:start}.trace-chat-column{min-width:0}.trace-chat-input{border-color:#41659a}.trace-chat-output{border-color:#397658}.trace-chat-message{border-top:1px solid #273544;padding:9px 0}.trace-chat-message:first-child{border-top:0;padding-top:0}.trace-chat-role{color:var(--accent);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em}.trace-chat-meta{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 8px}.trace-chat-meta span{border:1px solid #2b3948;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px}.trace-tool-timeline{display:grid;gap:8px;margin-top:10px}.trace-tool-card{border:1px solid #33485f;border-left:3px solid var(--accent);border-radius:6px;background:#0b131b;padding:9px}.trace-tool-card.error{border-left-color:var(--bad)}.trace-tool-card h4{margin:0 0 6px;font-size:11px}.trace-tool-card pre{max-height:220px;overflow:auto;margin:4px 0 0}.trace-tool-field{margin-top:7px}.trace-tool-field strong{color:var(--muted);font-size:10px;text-transform:uppercase}.trace-tool-field .human-pre{margin:4px 0 0}@media(max-width:700px){.trace-primary-grid,.trace-chat-columns{grid-template-columns:1fr}}</style>');

document.head.insertAdjacentHTML('beforeend','<style>.trace-presentation-field{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:6px 12px;align-items:start;padding:7px 0;min-width:0}.trace-presentation-field+ .trace-presentation-field{border-top:1px solid #273544}.trace-presentation-field>strong{color:var(--muted);font-size:10px;line-height:1.4;overflow-wrap:anywhere}.trace-presentation-field>div,.trace-presentation-field>span,.trace-presentation-field>pre,.trace-presentation-field>details{min-width:0;overflow-wrap:anywhere}.trace-command-top{border:1px solid #2d3d4e;border-radius:8px;background:#0c121a;padding:10px;margin:0 0 14px}.trace-command-top>h3{margin:0 0 4px;font-size:12px;color:var(--fg)}@media(max-width:700px){.trace-presentation-field{grid-template-columns:1fr;gap:3px}.trace-command-top{padding:8px}}</style>');
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
if($('detailedTelemetryToggle'))$('detailedTelemetryToggle').onclick=async()=>{
  const enabled=!Boolean(last?.debug_traces?.enabled);
  const button=$('detailedTelemetryToggle');if(button)button.disabled=true;
  try{
    const result=await post('/api/config/update',{settings:{'debug_traces.enabled':enabled}});
    if(!result?.success)throw new Error(result?.error||'Unable to update telemetry');
    last={...last,debug_traces:{...(last?.debug_traces||{}),enabled}};
    syncDetailedTelemetryToggle(enabled);
    if(activeTraceData)renderTraceDetail(activeTraceData);
  }catch(error){if($('modalLive'))$('modalLive').textContent='Telemetry setting failed: '+String(error?.message||error);}
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
  const root=$('agentOsRoot')?.value?.trim();
  if(!root)throw new Error('Choose a repository root in Agent OS first.');
  if(String(options.method||'GET').toUpperCase()==='GET'){
    path+=String(path).includes('?')?'&':'?';
    path+='root='+encodeURIComponent(root);
  }else{
    const payload=options.body?JSON.parse(options.body):{};
    options={...options,body:JSON.stringify({...payload,root})};
  }
  return {path,options};
}
async function apiFetch(path,opts={}){
  const scoped=scopeAgentOsRequest(path,opts);path=scoped.path;opts=scoped.options;
  opts={...opts};const h=new Headers(opts.headers||{});h.set('X-LocalAI-Client','dashboard');opts.headers=h;
  const request=async requestOpts=>{
    const next={...requestOpts};let controller=null,timer=null;
    if(!next.signal&&typeof AbortController==='function'){
      controller=new AbortController();next.signal=controller.signal;
      const requestedTimeout=Number(next.timeoutMs),timeoutMs=Number.isFinite(requestedTimeout)&&requestedTimeout>0?requestedTimeout:30000;
      timer=setTimeout(()=>controller.abort(),Math.max(1000,timeoutMs));
    }
    delete next.timeoutMs;
    try{return await nativeFetch(path,next)}finally{if(timer)clearTimeout(timer)}
  };
  return request(opts);
}
function setFrontendVisionCaptureState(state,label){const el=$('visionCaptureState');if(!el)return;const normalized=['produced','empty','not_captured','redacted'].includes(String(state||''))?String(state):'not_captured';el.className=`trace-capture-state ${normalized.replace('_','-')}`;el.dataset.captureState=normalized;el.textContent=`Capture state · ${label||traceCaptureStateLabel(normalized)}`;}
function setFrontendVisionCaptureError(message){const el=$('visionCaptureError');if(!el)return;const text=String(message||'');el.textContent=text;el.style.display=text?'':'none';}
function openFrontendVisionReviewModal(prefill={}){const modal=$('visionReviewModal');if(!modal)return;window.frontendVisionCapture={};modal.classList.add('open');if($('visionPrompt'))$('visionPrompt').value=String(prefill.prompt||'');if($('visionFindingId'))$('visionFindingId').value=String(prefill.findingId||'');if($('visionScreenshot'))$('visionScreenshot').value='';if($('visionReviewResult'))$('visionReviewResult').innerHTML='';if($('visionReviewStatus'))$('visionReviewStatus').textContent='';setFrontendVisionCaptureError('');setFrontendVisionCaptureState('not_captured','Not captured');}
function closeFrontendVisionReviewModal(){const modal=$('visionReviewModal');if(modal)modal.classList.remove('open');}
function captureFrontendVisionTab(){
  const requestId=`vision-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
  setFrontendVisionCaptureError('');setFrontendVisionCaptureState('not_captured','Waiting for current-tab bridge…');
  window.postMessage({type:'LOCAL_AI_VISION_CAPTURE_REQUEST',request_id:requestId,prompt:String($('visionPrompt')?.value||'')},'*');
}
function consumeFrontendVisionCapture(result){
  const payload=result&&typeof result==='object'?result:{};
  if(payload.success!==true){setFrontendVisionCaptureState('not_captured','Capture failed');setFrontendVisionCaptureError(payload.error||payload.error_code||'Current-tab capture failed.');return;}
  window.frontendVisionCapture=payload;setFrontendVisionCaptureState('produced','Captured current tab');setFrontendVisionCaptureError('');
}
if(typeof window!=='undefined')window.addEventListener('message',event=>{if(event?.data?.type==='LOCAL_AI_VISION_CAPTURE_RESULT')consumeFrontendVisionCapture(event.data.result||event.data)});
function readFrontendVisionFile(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(new Error('Screenshot could not be read.'));reader.onload=()=>resolve(String(reader.result||''));reader.readAsDataURL(file);});}
function renderFrontendVisionReviewResult(result){const target=$('visionReviewResult');if(!target)return;const model={output:result,session:{model:result?.model||'',source:result?.source||'upload'},identity:{action:'/api/vision/review'},lifecycle:{state:result?.success===false?'failed':'completed'}};target.innerHTML=typeof renderVisionReviewPresentation==='function'?renderVisionReviewPresentation(model):`<pre>${esc(JSON.stringify(result||{},null,2))}</pre>`;}
async function submitFrontendVisionReview(){
  const prompt=String($('visionPrompt')?.value||'').trim(),file=$('visionScreenshot')?.files?.[0],capture=window.frontendVisionCapture||{};
  if(!prompt){setFrontendVisionCaptureError('Prompt is required.');return;}
  if(!file&&!capture.bundle_artifact_id&&!capture.screenshot_artifact_id){setFrontendVisionCaptureError('Provide a screenshot or capture the current tab.');return;}
  const submit=$('visionReviewSubmit');if(submit){submit.disabled=true;submit.textContent='Reviewing…';}
  try{
    const image=file?await readFrontendVisionFile(file):capture.screenshot;
    const result=await post('/api/vision/review',{prompt,source:file?'upload':'current_tab',image:image||'',bundle_artifact_id:capture.bundle_artifact_id||'',screenshot_artifact_id:capture.screenshot_artifact_id||'',dom_artifact_id:capture.dom_artifact_id||'',accessibility_artifact_id:capture.accessibility_artifact_id||''});
    if(result?.success===false){setFrontendVisionCaptureError(result.error?.message||result.error||result.error_code||'Vision review failed.');if(result.error_code==='permission_denied')setFrontendVisionCaptureState('not_captured','Permission denied');return;}
    if($('visionReviewStatus'))$('visionReviewStatus').textContent=`${result.model||'vision model'} · ${result.source||'local'}`;renderFrontendVisionReviewResult(result);
  }catch(error){setFrontendVisionCaptureError(String(error));}
  finally{if(submit){submit.disabled=false;submit.textContent='Run vision review';}}
}
if($('visionReviewClose'))$('visionReviewClose').onclick=closeFrontendVisionReviewModal;
if($('visionReviewOpen'))$('visionReviewOpen').onclick=()=>openFrontendVisionReviewModal();
if($('visionCaptureCurrentTab'))$('visionCaptureCurrentTab').onclick=captureFrontendVisionTab;
if($('visionReviewSubmit'))$('visionReviewSubmit').onclick=submitFrontendVisionReview;
const rows=(id,items,fn,cols,emptyText='No active items recorded')=>{const el=$(id);if(!el)return;el.innerHTML=(items&&items.length)?items.map(fn).join(''):`<tr><td colspan="${cols}" class="muted" style="text-align:center;padding:16px 10px;font-style:italic">${emptyText}</td></tr>`};
function copyText(text, btn){
  try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(String(text)).catch(()=>{});}}catch{}
  if(btn){
    const oldText=btn.textContent;
    btn.textContent='Copied!';
    setTimeout(()=>{btn.textContent=oldText},1500);
  }
}
function renderCodeIntelModal(d,title){
  if(d.code||d.tests||d.test_code){
    const code=d.code||d.tests||d.test_code;
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-card">
          <div class="modal-card-head">
            <span>${esc(title||'Generated Unit Tests')}</span>
            <button class="copy-btn" onclick="copyText(${esc(JSON.stringify(code))},this)">📋 Copy Code</button>
          </div>
          <div class="modal-card-body">
            <pre class="code-box" style="margin:0;max-height:450px">${esc(code)}</pre>
          </div>
        </div>
      </div>
    `;
    return;
  }
  if(d.callers||d.impact||d.affected_files){
    const callers=d.callers||[];
    const files=d.affected_files||d.files||[];
    const risk=d.risk||d.risk_score||'medium';
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-hero" style="border-radius:6px;border:1px solid #2d3e56">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <b>Refactoring Risk Assessment</b>
            <span class="badge-status ${risk==='high'?'badge-error':risk==='medium'?'badge-paused':'badge-complete'}">${esc(String(risk).toUpperCase())} RISK</span>
          </div>
        </div>
        <div class="modal-card">
          <div class="modal-card-head"><span>Direct Callers (${callers.length})</span></div>
          <div class="modal-card-body">
            ${callers.length?callers.map(c=>`<div style="padding:4px 0"><span class="chip"><b>${esc(c.name||c)}</b></span> <span class="tiny muted">${esc(c.file||'')}</span></div>`).join(''):'<div class="muted tiny">No direct callers detected.</div>'}
          </div>
        </div>
        <div class="modal-card">
          <div class="modal-card-head"><span>Impacted Files (${files.length})</span></div>
          <div class="modal-card-body">
            ${files.length?files.map(f=>`<div style="padding:4px 0" class="mono tiny">${esc(f)}</div>`).join(''):'<div class="muted tiny">No downstream files impacted.</div>'}
          </div>
        </div>
      </div>
    `;
    return;
  }
  if(d.imports||d.missing_imports){
    const imps=d.imports||d.missing_imports||[];
    const code=Array.isArray(imps)?imps.join('\n'):String(imps);
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-card">
          <div class="modal-card-head">
            <span>Resolved Missing Imports</span>
            <button class="copy-btn" onclick="copyText(${esc(JSON.stringify(code))},this)">📋 Copy Imports</button>
          </div>
          <div class="modal-card-body">
            <pre class="code-box" style="margin:0">${esc(code)}</pre>
          </div>
        </div>
      </div>
    `;
    return;
  }
  if(d.symbols||d.declarations||d.references||d.implementations){
    const items=d.symbols||d.declarations||d.references||d.implementations||[];
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="modal-card">
          <div class="modal-card-head"><span>Results (${items.length})</span></div>
          <div class="modal-card-body">
            ${items.length?items.map(s=>`
              <div style="padding:6px 0;border-bottom:1px solid #1f2c3d">
                <div style="display:flex;justify-content:space-between">
                  <b>${esc(s.name||s.symbol||'symbol')}</b>
                  <span class="chip">${esc(s.kind||'reference')}</span>
                </div>
                <div class="tiny mono muted" style="margin-top:2px">${esc(s.path||s.file||'')}:${n(s.line||s.start_line||0)}</div>
                ${s.snippet?`<pre class="code-box" style="margin-top:4px;padding:6px">${esc(s.snippet)}</pre>`:''}
              </div>
            `).join(''):'<div class="muted tiny">No matching occurrences found.</div>'}
          </div>
        </div>
      </div>
    `;
    return;
  }
  renderHumanModal(d);
}

function renderDeadCodeModal(s){
  const name=s.name||'Symbol';
  const kind=s.kind||'symbol';
  const path=s.path||'';
  const line=s.line||0;
  const cont=s.container||'—';
  const reason=s.reason||'No callers found across repository AST callgraph';
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">CODEBASE OPTIMIZATION · UNUSED SYMBOL</div>
          <h2 style="margin:2px 0 0;font-size:16px"><b>${esc(name)}</b> <span class="chip">${esc(kind)}</span></h2>
        </div>
        <span class="badge-status badge-waiting">CANDIDATE</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Location &amp; Reason</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>File Path</div><div class="mono tiny">${esc(path)}:${n(line)}</div>
            <div>Container / Parent</div><div>${esc(cont)}</div>
            <div>Analysis Finding</div><div class="warn-t"><b>${esc(reason)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderAuditVulnModal(v){
  const pkg=v.package||'Package';
  const sev=v.severity||'MEDIUM';
  const inst=v.installed_version||'—';
  const fixed=v.fixed_version||'—';
  const adv=v.advisory||'Security advisory';
  const manifest=v.manifest_path||'—';
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">DEPENDENCY VULNERABILITY ADVISORY</div>
          <h2 style="margin:2px 0 0;font-size:16px">🛡️ <b>${esc(pkg)}</b></h2>
        </div>
        <span class="badge-status ${sev==='HIGH'||sev==='CRITICAL'?'badge-error':'badge-waiting'}">${esc(sev)} SEVERITY</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Advisory Information</span></div>
        <div class="modal-card-body">
          <div style="font-size:12px;margin-bottom:8px">${esc(adv)}</div>
          <div class="kv" style="padding:0">
            <div>Package</div><div><b>${esc(pkg)}</b></div>
            <div>Installed Version</div><div class="bad-t"><b>${esc(inst)}</b></div>
            <div>Fixed Version</div><div class="ok"><b>${esc(fixed)}</b></div>
            <div>Manifest Path</div><div class="mono tiny">${esc(manifest)}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderArchEdgeModal(e){
  const fromName=e.from?.split(/[\\/]/).pop()||e.from;
  const toName=e.to?.split(/[\\/]/).pop()||e.to;
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">ARCHITECTURE DEPENDENCY LINK</div>
          <h2 style="margin:2px 0 0;font-size:16px"><b>${esc(fromName)}</b> ➔ <b>${esc(toName)}</b></h2>
        </div>
        <span class="chip ok">${esc(e.type||'dependency')}</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Connection Information</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Source Project</div><div class="mono tiny">${esc(e.from)}</div>
            <div>Target Dependency</div><div class="mono tiny">${esc(e.to)}</div>
            <div>Relationship Kind</div><div><b>${esc(e.type)}</b></div>
            <div>Context / Evidence</div><div>${esc(e.label||'Direct dependency / import linkage')}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function inferEntityType(obj){
  if(!obj||typeof obj!=='object')return 'raw';
  if(obj.task_id)return 'task';
  if(obj.key&&(obj.value!==undefined||obj.scope||obj.kind))return 'memory';
  if(obj.incident_id||(obj.error_class&&obj.root_cause))return 'incident';
  if(obj.stream_id||obj.event_type||obj.stage)return 'event';
  if(obj.project&&obj.root)return 'project';
  if(obj.lease_id)return 'lease';
  if(obj.command&&obj.cwd)return 'command';
  if(obj.component&&(obj.operation||obj.count!==undefined))return 'error';
  if(obj.session_id)return 'session';
  if(obj.checks&&Array.isArray(obj.checks))return 'doctor';
  if(obj.code||obj.tests||obj.test_code||obj.missing_imports||obj.callers)return 'code_intel';
  if(obj.databases_optimized!==undefined)return 'db_opt';
  if(obj.purged_entries!==undefined)return 'cache_purge';
  if(obj.tier&&obj.num_ctx!==undefined)return 'execution_profile';
  if(obj.layer&&obj.context_tokens_avoided_est!==undefined)return 'cache_layer';
  if(obj.local_inference_calls!==undefined)return 'agent_stat';
  if(obj.route&&obj.task_type&&obj.complexity)return 'route_stat';
  if(obj.action&&obj.p50_duration_ms!==undefined)return 'http_tail';
  if(obj.avg_load_ms!==undefined&&obj.model)return 'model_stat';
  if(obj.fixed_version||obj.advisory||(obj.package&&obj.severity))return 'audit_vulnerability';
  if(obj.container!==undefined&&obj.reason&&obj.path)return 'dead_code';
  if(obj.reason&&obj.count!==undefined)return 'blocked_reason';
  if(obj.from&&obj.to&&obj.type)return 'arch_edge';
  if(obj.job_id!==undefined&&(obj.wait_ms!==undefined||obj.service_ms!==undefined||obj.wait_reason!==undefined))return 'scheduler_job';
  if(obj.request_id&&obj.agent&&(obj.action||obj.status_code!==undefined||obj.duration_ms!==undefined||obj.age_ms!==undefined))return 'http_request';
  return 'generic';
}
const dataStore=new Map(); let seq=0;
function clickableRow(obj,html,type='',idAttr=''){
  const id='d'+(++seq);
  const resolvedType=type||inferEntityType(obj);
  dataStore.set(id,{data:obj,type:resolvedType});
  if(dataStore.size>5000){
    const oldest=dataStore.keys().next().value;
    dataStore.delete(oldest);
  }
  const entityId=idAttr||obj?.task_id||obj?.incident_id||(obj?.key?((obj.scope||'task')+':'+obj.key):'')||obj?.root||obj?.lease_id||obj?.command||'';
  return `<tr class="click" data-detail="${id}" data-type="${esc(resolvedType)}" ${entityId?`data-id="${esc(entityId)}"`:''}>${html}</tr>`;
}

let traceDetailPoller=null,tracePollAbortController=null,activeTraceId='',traceSeq=0,traceEvents=[],traceOpenSteps=new Set(),traceView='timeline',activeTraceData=null,traceOptionalDetailsOpen=false,tracePollGeneration=0,traceEventTotal=0,traceFullPayloadInFlightId='';
const traceEventBufferLimit=200;
function traceAppendEvents(current,incoming,eventsTotal=0){const existing=Array.isArray(current)?current:[],seen=new Set(existing.map(event=>event&&Number.isFinite(event.seq)?event.seq:null).filter(seq=>seq!==null)),fresh=(Array.isArray(incoming)?incoming:[]).filter(event=>{const seq=event&&Number.isFinite(event.seq);if(!seq)return true;if(seen.has(event.seq))return false;seen.add(event.seq);return true}),merged=existing.concat(fresh);return {events:merged.slice(-traceEventBufferLimit),eventsTotal:Math.max(Number(eventsTotal)||0,merged.length)};}
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
 const titles={model_request:'Model input',thinking:'Thinking / reasoning',output_stream:'Model output',output_delta:'Model output chunk',tool_call:'Tool call',tool_result:'Tool result',request_received:'Request received',handler_started:'Handler started',async_job_submitted:'Async job submitted',scheduled:'Scheduled',running:'Running',retry:'Retry',trace_truncated:'Trace truncated',completed:'Completed',complete:'Completed',done:'Completed',success:'Completed',succeeded:'Completed',failed:'Failed',error:'Error',cancelled:'Cancelled',canceled:'Cancelled',interrupted:'Interrupted',request_completed:'Request completed',request_failed:'Request failed'};
  return Object.prototype.hasOwnProperty.call(titles,type)?titles[type]:humanLabel(type||'Event');
}
function traceEventSummary(type,p){
  if(type==='model_request')return `Request to ${traceInlineText(p.model??p.provider??'model')}`;
  if(type==='tool_call')return `Calling ${traceInlineText(p.name??p.tool??'tool')}`;
  if(type==='tool_result')return p.isError||p.is_error||p.success===false||p.error?'Tool returned an error':'Tool returned a result';
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
function compactTimelineEvents(events){
  const compact=[];let stream=null,streamBytes=0;
  (Array.isArray(events)?events:[]).map(traceNormalizeEvent).forEach(event=>{
    const type=String(event.event_type||'event'),payload=event.payload&&typeof event.payload==='object'&&!Array.isArray(event.payload)?event.payload:{};
    if(type==='output_delta'){
      if(!stream){stream={event_type:'output_stream',created_at:event.created_at,seq:event.seq,payload:{text:'',values:[],chunks:0,truncated:false}};compact.push(stream)}
      const chunk=payload.text??payload.content??payload.output??payload.result??'';
      if(typeof chunk==='string'||typeof chunk==='number'||typeof chunk==='boolean'){const text=String(chunk);stream.payload.text+=streamBytes<12000?text:'';streamBytes+=text.length;}else{stream.payload.values.push(traceRawBoundValue(chunk,4096));streamBytes+=Math.min(4096,promptText(chunk).length);}
      stream.payload.chunks+=1;stream.seq=event.seq;
      if(streamBytes>12000)stream.payload.truncated=true;
      return;
    }
    if(type==='tool_result'){const callId=payload.call_id||'';if(callId&&compact.some(x=>x.event_type==='tool_call'&&((x.payload||{}).call_id||'')===callId))return;}
    compact.push(event);
  });
  return compact;
}
function traceNormalizeEvent(event){
  if(event&&typeof event==='object'&&!Array.isArray(event)){const validPayload=event.payload&&typeof event.payload==='object'&&!Array.isArray(event.payload);return validPayload?{...event,payload:event.payload}:{...event,payload:{malformed_payload:true,value:traceRawBoundValue(event.payload===undefined?null:event.payload,2048)}};}
  return {event_type:'malformed',payload:{malformed_payload:true,value:traceRawBoundValue(event===undefined?null:event,2048)}};
}
function traceTimeline(events){
  const groups=[];let current=null;
  (Array.isArray(events)?events:[]).map(traceNormalizeEvent).forEach(event=>{const type=String(event.event_type||'event'),payload=event.payload&&typeof event.payload==='object'?event.payload:{};if(type==='model_request'||!current){current={index:groups.length+1,label:type==='model_request'?'Model request':'Execution',events:[]};groups.push(current)}if(type!=='model_request'&&payload&&payload.step){const step=Number(payload.step);current=groups.find(g=>g.step===step)||current}if(type==='model_request'&&payload&&payload.step)current.step=Number(payload.step);current.events.push(event)});
  if(!groups.length)return '<div class="empty-human">Waiting for agent events…</div>';
  return `<div class="trace-timeline">${groups.map((group,index)=>{const key=String(group.step||group.index),open=traceOpenSteps.size?traceOpenSteps.has(key):index===groups.length-1,eventsForDisplay=compactTimelineEvents(group.events);return `<div class="trace-step ${open?'open':''}" data-trace-step="${esc(key)}"><button class="trace-step-head" data-trace-toggle aria-expanded="${open}"><span class="trace-step-index">Step ${esc(key)}</span><span>${esc(humanLabel(group.label))}</span><span class="tiny">${group.events.length} events · ${eventsForDisplay.length} shown</span><span class="trace-step-chevron">&#9654;</span></button><div class="trace-step-body">${eventsForDisplay.map((event,eventIndex)=>{const type=String(event?.event_type||'event');let body='';try{body=traceEventBody(event,eventsForDisplay,eventIndex)}catch(error){body='<div class="trace-event-content"><span class="trace-primary-empty">Malformed event omitted</span></div>'}if(!body)return '';return `<div class="trace-event"><div class="event-head"><span class="event-type">${esc(traceEventTitle(type))}</span><span class="event-time">${event.created_at?new Date(event.created_at*1000).toLocaleTimeString():'—'} · #${esc(event.seq)}</span></div>${body}</div>`}).join('')}</div></div>`}).join('')}</div>`;
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
function traceTab(label,id){const selected=traceView===id;return `<button class="trace-tab ${selected?'active':''}" id="trace-tab-${esc(id)}" role="tab" data-trace-view="${esc(id)}" aria-selected="${selected}" aria-controls="trace-panel-${esc(id)}" tabindex="${selected?'0':'-1'}">${esc(label)}</button>`}
function traceStatus(item){const state=String(item?.state||'queued');return state==='failed'&&/hub restarted|service stopped|shutdown/i.test(String(item?.error||''))?'interrupted':state}
function traceDisplayState(item){const state=traceStatus(item);return state==='interrupted'?'Interrupted':humanLabel(state)}
function traceBoundedKey(key,budget){return String(key);}
function traceBoundedEvents(events,eventLimit=100){const list=Array.isArray(events)?events:[],requestReceived=list.find(event=>event?.event_type==='request_received'),latest=list.slice(-eventLimit),visible=requestReceived&&!latest.includes(requestReceived)?[requestReceived,...latest]:latest;return {events:visible.map(event=>traceRawBoundValue(event)),eventsTotal:list.length,eventsTruncated:list.length>visible.length};}
function traceRawBoundValue(value,limit=4096,depth=0){
  if(value===null||value===undefined||typeof value==='number'||typeof value==='boolean'||typeof value==='string')return value;
  if(Array.isArray(value))return value.map(item=>traceRawBoundValue(item,limit,depth+1));
  if(typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[traceBoundedKey(key),traceRawBoundValue(item,limit,depth+1)]));
  return String(value);
}
function traceDisplaySession(rawSession){return {trace_id:rawSession.trace_id,kind:rawSession.kind,state:rawSession.state,agent:rawSession.agent,action:rawSession.action,source:rawSession.source,model:rawSession.model,request_id:rawSession.request_id,async_job_id:rawSession.async_job_id,scheduler_job_id:rawSession.scheduler_job_id,job_id:rawSession.job_id,owner:rawSession.owner,created_at:rawSession.created_at,updated_at:rawSession.updated_at,finished_at:rawSession.finished_at,duration_ms:rawSession.duration_ms,elapsed_ms:rawSession.elapsed_ms,status_code:rawSession.status_code,text_bytes:rawSession.text_bytes,retained_bytes:rawSession.retained_bytes,final_response_status:rawSession.final_response_status,final_response_produced:rawSession.final_response_produced,error:traceRawBoundValue(rawSession.error,1024),request:traceSanitizeValue(rawSession.request),effective_payload:traceRawBoundValue(rawSession.effective_payload),thinking:traceSanitizeValue(rawSession.thinking),output:traceSanitizeValue(rawSession.output),response:traceSanitizeValue(rawSession.response)};}
 function traceRaw(payload,limit=24000){let raw='';try{raw=JSON.stringify(payload,null,2)}catch(e){raw=String(e)}return `<section class="human-section trace-raw-panel"><h3>Complete JSON payload</h3><pre class="human-pre">${esc(raw)}</pre></section>`}
 function traceScrollNodes(root){return Array.from(root?.querySelectorAll?.('.human-pre,.trace-output,.prompt-pre')||[])}
 function captureTraceScrollPositions(root){return traceScrollNodes(root).map((node,index)=>({index,top:node.scrollTop,left:node.scrollLeft}))}
 function restoreTraceScrollPositions(root,positions){traceScrollNodes(root).forEach((node,index)=>{const saved=positions[index];if(saved){node.scrollTop=saved.top;node.scrollLeft=saved.left}})}
 function captureTracePrimaryGroups(root){return Object.fromEntries(Array.from(root?.querySelectorAll?.('details[data-trace-primary-group]')||[]).map(node=>[String(node.dataset.tracePrimaryGroup||node.dataset.group||''),Boolean(node.open)]))}
 function restoreTracePrimaryGroups(root,state){(root?.querySelectorAll?.('details[data-trace-primary-group]')||[]).forEach(node=>{const key=String(node.dataset.tracePrimaryGroup||node.dataset.group||'');if(state&&Object.prototype.hasOwnProperty.call(state,key))node.open=Boolean(state[key])})}
function traceCollapsibleKey(node,index){return String(node?.dataset?.traceKey||node?.dataset?.tracePrimaryGroup||node?.dataset?.thinkingKey||node?.id||`${node?.className||'details'}:${index}`)}
function captureTraceCollapsibleDetails(root){return Object.fromEntries(Array.from(root?.querySelectorAll?.('details[data-trace-collapsible]')||[]).map((node,index)=>[traceCollapsibleKey(node,index),Boolean(node.open)]))}
function restoreTraceCollapsibleDetails(root,state){(root?.querySelectorAll?.('details[data-trace-collapsible]')||[]).forEach((node,index)=>{const key=traceCollapsibleKey(node,index);if(state&&Object.prototype.hasOwnProperty.call(state,key))node.open=Boolean(state[key])})}
 function captureTraceThinkingDetails(root){return new Set(Array.from(root?.querySelectorAll?.('details.trace-thinking[data-thinking-key]')||[]).filter(node=>node.open).map(node=>String(node.dataset.thinkingKey)))}
 function restoreTraceThinkingDetails(root,openKeys){(root?.querySelectorAll?.('details.trace-thinking[data-thinking-key]')||[]).forEach(node=>{node.open=openKeys?.has(String(node.dataset.thinkingKey))||false})}
function traceEventList(events,limit=100){const shown=(events||[]).slice(-limit),prefix=(events||[]).length>shown.length?`<div class="empty-human">Showing latest ${shown.length} of ${(events||[]).length} events.</div>`:'';return `<section class="human-section"><h3>All events</h3>${prefix}${renderAny(shown)}</section>`}
function tracePanel(id,label,render,available=true){return {id,label,render,available};}
function traceUnavailable(label){return `${label} unavailable for this request type`;}
function tracePresentationKind(model){
  const action=String(model.identity?.action||model.session?.action||'').toLowerCase(),kind=String(model.presentation?.kind||model.session?.kind||'').toLowerCase(),events=model.events||[];
  if(kind==='async_job')return 'async_job';
  const directOutput=model.output&&typeof model.output==='object'&&!Array.isArray(model.output)?model.output:{};
  if(action.includes('/vision')||directOutput.review&&typeof directOutput.review==='object')return 'vision_review';
  if(action==='/api/command'||action.includes('/command'))return 'command';
  if(/\/review|\/diff|review|diff/.test(action))return 'review';
  if(/repo|code|git|symbol|impact|test|resolve|ast|topology/.test(action))return 'repo_intelligence';
  if(/rag|search|query|retriev|embed/.test(action))return 'rag_search';
  const hasModel=model.modelExecutions?.length>0||traceRecorded(model.input)||traceRecorded(model.output),hasTools=model.toolCalls?.length>0;
  if(hasModel&&hasTools)return 'agent_loop';
  if(hasModel)return 'model_chat';
  if(model.correlations?.async_job_id||model.correlations?.scheduler_job_id)return 'async_job';
  if(events.length||traceRecorded(model.response)||traceRecorded(model.input))return 'request_response';
  return 'request_response';
}
function traceChatTurns(events){
  const turns=[],list=Array.isArray(events)?events:[];let current=null;
  list.forEach(event=>{
    const type=String(event?.event_type||''),payload=traceSanitizeValue(event?.payload||{});
    if(type==='model_request'){current={step:payload.step||turns.length+1,input:payload,output:'',tools:[]};turns.push(current);}
    else if(current&&(type==='output_stream'||type==='output_delta')){const chunk=payload.text??payload.content??payload.output??payload.result??'';if(typeof chunk==='string'||typeof chunk==='number'||typeof chunk==='boolean')current.output+=String(chunk);else if(!current.output)current.output=chunk;else current.output=[current.output,chunk];}
    else if(current&&type==='tool_call')current.tools.push({call:payload,result:null});
    else if(current&&type==='tool_result'){
      const callId=payload.call_id||'',match=current.tools.slice().reverse().find(item=>!item.result&&(!callId||item.call.call_id===callId));
      if(match)match.result=payload;
    }
  });
  return turns.slice(-100);
}
function tracePresentationData(model){
  const events=Array.isArray(model?.events)?model.events:[],turns=traceChatTurns(events);
  const commandKeys=['command','cmd','args','arguments','input','stdin','stdout','stderr','exit_code','exitCode','success','retries','retry_count','attempts','duration','duration_ms','elapsed_ms','action','cwd','root','paths','criterion','error'],reviewKeys=['request','context','diff','findings','recommendation','status','severity_counts','severityCounts','text','thinking','final_response_status','final_response_produced','result','output','response','error'],repoKeys=['graph','graph_data','graphData','evidence','callers','related_symbols','relatedSymbols','diagnostics','repository','repo','root','operation','action','query','files','symbols','context','result','output','response','text','thinking','final_response_status','final_response_produced','error'],asyncKeys=['job_type','jobType','type','kind','state','progress','progress_percent','percent','completed','current','total','worker_output','status','queue_wait_ms','queue_wait','queue_time_ms','retries','retry_count','attempts','worker_input','input','result','output','error'];
  const sources=[model.input,model.output,model.response,model.session?.request,model.session?.effective_payload];
  // Keep result context separate: request context is supporting input, never an answer.
  const requestContext=traceMergeRecordedSources([model.input,model.session?.request,model.session?.effective_payload],['context'])?.context;
  const resultContext=traceMergeRecordedSources([traceMergeRecorded(events.filter(event=>! /request|input|user_message/i.test(String(event?.event_type||''))),['context']),model.output,model.response],['context'])?.context;
  return {kind:tracePresentationKind(model),chatTurns:turns,toolInteractions:(model.toolCalls||[]).slice(-100),requestEnvelope:model.session?.request||{},modelInput:model.input,modelOutput:model.output,thinking:model.thinking,command:traceMergeRecordedSources([traceMergeRecorded(events,commandKeys),...sources],commandKeys),review:traceMergeRecordedSources([traceMergeRecorded(events,reviewKeys),...sources],reviewKeys),visionReview:traceVisionReviewPayload(model),repoOperation:{...traceMergeRecordedSources([traceMergeRecorded(events,repoKeys),...sources],repoKeys),request_context:requestContext,result_context:resultContext},retrieval:traceMergeRecordedSources([traceMergeRecorded(events,['query','sources','results','hits','score','scores','provider','answer','truncated','truncation','root','project','top_k','limit','enrich','mode','path']),...sources],['query','search_query','term','sources','results','hits','score','scores','provider','answer','truncated','truncation','root','project','top_k','limit','enrich','mode','path']),asyncJob:traceMergeRecordedSources([traceMergeRecorded(events,asyncKeys),...sources],asyncKeys),lifecycle:model.lifecycle};
}
function traceMergeRecorded(events,keys){
  const merged=Object.create(null),flattenKeys=new Set(['command','cmd','review','repo_operation','retrieval','rag','async_job']);let found=false;
  (Array.isArray(events)?events:[]).forEach(event=>{const payload=event?.payload;if(!payload||typeof payload!=='object')return;keys.forEach(key=>{const value=payload[key];if(value===undefined||value===null)return;found=true;if(value&&typeof value==='object'&&!Array.isArray(value)&&flattenKeys.has(key))Object.assign(merged,value);else merged[key]=value;});});
  return found?merged:undefined;
}
function traceMergeRecordedSources(sources,keys){
  const merged=Object.create(null);let found=false;
  (Array.isArray(sources)?sources:[]).forEach(source=>{if(!source||typeof source!=='object'||Array.isArray(source))return;keys.forEach(key=>{const value=source[key];if(value===undefined||value===null)return;found=true;merged[key]=value;});});
  return found?merged:undefined;
}
function tracePresentationBound(value,budget,depth=0){
  return traceRawBoundValue(value,Number.POSITIVE_INFINITY,depth);
}
function traceRenderBudget(limit=24000){return {limit,remaining:limit,truncated:false};}
function traceBudgetMarkup(markup,budget){const text=String(markup??'');if(budget)budget.remaining-=text.length;return text;}
// Budgets admit whole components. Never truncate or re-escape generated HTML.
function traceMarkupItems(items,limit=12000){return (Array.isArray(items)?items:[]).join('');}
function traceTimelineMarkup(items,limit=18000){if(!items.length)return '';const last=traceBudgetMarkup(items[items.length-1],traceRenderBudget(limit));return traceMarkupItems(items.slice(0,-1),Math.max(0,limit-last.length))+last;}
function traceAggregatePrimaryFields(fields,limit=22000){return (Array.isArray(fields)?fields:[]).filter(Boolean);}
function traceFinalizeMarkup(markup,budget){return String(markup??'');}
function tracePresentationValue(value,limit=12000,budget=null){const state=traceRenderBudget(Math.min(limit,budget?.remaining??limit)),before=state.remaining,result=traceSanitizeValue(tracePresentationBound(value,state));if(budget){budget.remaining-=before-state.remaining;budget.truncated||=state.truncated;}return result;}
function traceModelInputMessages(input,turn){
  const p=input&&typeof input==='object'?input:{},messages=Array.isArray(p.messages)?p.messages:[],found=messages.map((message,index)=>({role:String(message?.role||'message'),step:turn?.step||index+1,content:message?.content??message?.text??message}));
  if(found.length)return found.slice(0,100);
  if(typeof input==='string')return [{role:'user',step:turn?.step||1,content:input}];
  if(Array.isArray(input))return input.slice(0,100).map((content,index)=>({role:'user',step:turn?.step||index+1,content}));
  return ['system','developer','user'].filter(role=>p[role]!==undefined).map(role=>({role,step:turn?.step||1,content:p[role]})).concat((p.prompt??p.content??p.input)!==undefined?[{role:'user',step:turn?.step||1,content:p.prompt??p.content??p.input}]:[]).slice(0,100);
}
function traceHumanPresentationValue(value){return traceSanitizeValue(value);}
function traceHumanText(value){const safe=traceHumanPresentationValue(value);if(safe===undefined||safe===null)return '';if(typeof safe==='string'||typeof safe==='number'||typeof safe==='boolean')return String(safe);try{return JSON.stringify(safe,null,2)||''}catch(error){return redactDiagnostic(String(error));}}
function traceEscapedPreview(value,limit=4000){return esc(traceHumanText(value));}
function traceHumanReadableMarkup(value,limit=8000){const safe=tracePrimaryBoundedValue(traceAgentLoopPrimaryValue(value),limit),markup=safe&&typeof safe==='object'?renderAny(safe):`<pre class="trace-output">${esc(traceHumanText(safe))}</pre>`;return markup.length<=limit?markup:`<pre class="trace-output">${traceEscapedPreview(safe,limit-40)}</pre>`;}
function traceReadableMarkup(value,budget,limit=8000){return traceHumanReadableMarkup(value,limit);}
function traceTechnicalMarkup(value,limit=6000){const markup=renderAny(value);return markup.length<=limit?markup:`<pre class="trace-output">${traceEscapedPreview(value,limit-40)}</pre>`;}
function traceOutputValueMarkup(value,budget=null,limit=8000){return traceHumanReadableMarkup(value,Math.max(limit,18000));}
function traceChatMessageMarkup(message,index,budget,hideInternal=false){const role=traceInlineText(message?.role||'message').toLowerCase(),content=message?.content??message?.text??message,position=hideInternal?'':` · step ${esc(traceInlineText(message?.step||index+1))}`;return `<article class="trace-chat-message"><div class="trace-chat-role">${esc(role)}${position}</div>${traceHumanReadableMarkup(content,6000)}</article>`;}
function traceAgentLoopPrimaryValue(value,depth=0){if(Array.isArray(value))return value.map(item=>traceAgentLoopPrimaryValue(item,depth+1));if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>{const normalized=String(key).replace(/([a-z0-9])([A-Z])/g,'$1_$2').replace(/[-\s]+/g,'_').toLowerCase();return !/(^|_)(id|ids|call_id|request_id|correlation_id|job_id|lease_id|session_id|clone_id|worktree_id|repository_id|task_id|seq|sequence|sequence_id|step|step_index|steps|headers?|authorization|access_token|api_token|tokens?|secrets?|password|private_key|internal|metadata|file_sha256|content_hash|sha256)(_|$)/.test(normalized);}).map(([key,item])=>[key,traceAgentLoopPrimaryValue(item,depth+1)]));return value;}
function traceCodexEventMarkup(event,index,budget,hideInternal=false){
  const type=String(event?.event_type||'event').toLowerCase(),p=traceSanitizeValue(event?.payload||{}),step=p?.step||event?.step||index+1;
  const isThinking=['assistant_thinking','thinking','reasoning','assistant_reasoning'].includes(type),isToolCall=type==='tool_call',isToolResult=type==='tool_result',isOutput=['output_delta','output_stream','assistant_output','model_output','output'].includes(type),isRequest=['model_request','request_received','user_message'].includes(type),isBoundary=['turn_start','turn_end','step_start','step_end'].includes(type);
  let label=isThinking?'Thinking / reasoning':isToolCall?'Tool call':isToolResult?'Tool result':isOutput?'Assistant output':isRequest?'Model input':isBoundary?'Turn boundary':humanLabel(type);
  let body='',extra='';
  if(p?.malformed_payload)return `<div class="trace-timeline-event trace-malformed"><div class="trace-timeline-marker">Malformed event payload${hideInternal?'':` · step ${esc(step)}`}</div><div class="trace-primary-empty">Malformed event payload</div>${renderAny(hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(p.value,2048,budget)):tracePresentationValue(p.value,2048,budget))}</div>`;
  if(isThinking){const content=p.content??p.text??p.reasoning??p.thinking??p.output??p,thinkingKey=hideInternal?`agent-thinking-${index}`:`${step}:${event?.seq??index}`,position=hideInternal?'':` · step ${esc(step)}`,safeContent=hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(content,8000,budget)):tracePresentationValue(content,8000,budget);return `<div class="trace-timeline-event trace-thinking"><details class="trace-thinking" data-thinking-key="${esc(thinkingKey)}"><summary>${esc(label)}${position} · collapsed</summary>${hideInternal?traceHumanReadableMarkup(safeContent):promptBody(safeContent)}</details></div>`;}
  if(isRequest){const input=p.messages??p.prompt??p.content??p.input??p.request??p,safeInput=hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(input,8000,budget)):input;body=traceMarkupItems(traceModelInputMessages(safeInput,{step}).map((message,messageIndex)=>traceChatMessageMarkup(message,messageIndex,budget,hideInternal)),7000);}
  else if(isToolCall){const name=p.name||p.tool||'tool',args=p.arguments??p.args??p.input??{},safeArgs=hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(args,5000,budget)):tracePresentationValue(args,5000,budget),status=traceInlineText(p.status??p.state??'pending'),position=hideInternal?'':` · call id ${esc(traceInlineText(p.call_id??p.callId??'—'))}`;body=`<div class="trace-tool-card"><h4>Tool call · ${esc(traceInlineText(name))}${position}</h4><div class="trace-tool-field"><strong>tool name</strong><div>${esc(traceInlineText(name))}</div></div><div class="trace-tool-field"><strong>status</strong><div>${esc(status)}</div></div><div class="trace-tool-field"><strong>arguments</strong>${traceHumanReadableMarkup(safeArgs,5000)}</div></div>`;}
  else if(isToolResult){const call=event?.associated_call||{},name=p.name||p.tool||p.tool_name||call.name||call.tool||'tool',callId=p.call_id||p.callId||call.call_id||call.callId||'—',callStep=p.step||call.step||step,args=p.arguments??p.args??p.input??p.tool_arguments??call.arguments??call.args??call.input??{},failed=p.error||p.error_message||p.exception||p.is_error||p.isError||p.success===false||p.result?.error||p.result?.error_message||p.result?.exception,value=p.result??p.output??p.error??p,status=traceInlineText(p.status??p.state??(failed?'error':'complete')),safeArgs=hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(args,5000,budget)):tracePresentationValue(args,5000,budget),safeValue=hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(value,6000,budget)):tracePresentationValue(value,6000,budget),position=hideInternal?'':` · call id ${esc(traceInlineText(callId))} · step ${esc(traceInlineText(callStep))}`;body=`<div class="trace-tool-card ${failed?'error':''}"><h4>Tool result · ${esc(traceInlineText(name))}${position}${failed?' · error':''}</h4><div class="trace-tool-field"><strong>tool name</strong><div>${esc(traceInlineText(name))}</div></div><div class="trace-tool-field"><strong>status</strong><div>${esc(status)}</div></div><div class="trace-tool-field"><strong>arguments</strong>${traceHumanReadableMarkup(safeArgs,5000)}</div><div class="trace-tool-field"><strong>${failed?'error':'result'}</strong>${traceHumanReadableMarkup(safeValue,6000)}</div></div>`;}
  else if(isOutput){const outputValue=p.text??p.content??p.output??p.result??p,safeOutput=hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(outputValue,8000,budget)):outputValue;body=`<article class="trace-chat-message assistant"><div class="trace-chat-role">assistant${hideInternal?'':` · step ${esc(step)}`}</div>${traceReadableMarkup(safeOutput,budget,8000)}</article>`;}
  else if(isBoundary){body=`<div class="trace-boundary-label">${esc(label)}${hideInternal?'':` · step ${esc(step)}`}</div>`;}
  else {body=renderAny(hideInternal?traceAgentLoopPrimaryValue(tracePresentationValue(p,5000,budget)):tracePresentationValue(p,5000,budget));}
  return `<div class="trace-timeline-event ${isOutput?'assistant-event':''}" data-event-type="${esc(type)}"><div class="trace-timeline-marker">${esc(label)}${hideInternal?'':` · step ${esc(step)}${event?.seq!==undefined?` · #${esc(event.seq)}`:''}`}</div>${body}${extra}</div>`;
}
function traceCodexEvents(model,presentation){
  const rawEvents=Array.isArray(model?.events)?model.events.map(traceNormalizeEvent):[],calls=new Map();
  rawEvents.forEach(event=>{if(String(event.event_type||'').toLowerCase()==='tool_call'){const payload=event.payload||{},id=payload.call_id||payload.callId;if(id)calls.set(String(id),payload);}});
  const events=rawEvents.map(event=>{if(String(event.event_type||'').toLowerCase()!=='tool_result')return event;const payload=event.payload||{},id=payload.call_id||payload.callId,associated=id?calls.get(String(id)):null;return associated?{...event,associated_call:associated}:event;});
  const turns=Array.isArray(presentation?.chatTurns)?presentation.chatTurns:[];
  if(events.length){const partialTypes=['output_delta','output_stream'],terminalTypes=['assistant_output','model_output','output','output_final','final_output'],outputValue=event=>{const payload=event?.payload&&typeof event.payload==='object'?event.payload:event?.payload;return payload?.text??payload?.content??payload?.output??payload?.result??payload;},sameOutput=(left,right)=>{try{return JSON.stringify(traceSanitizeValue(left))===JSON.stringify(traceSanitizeValue(right));}catch{return promptText(left)===promptText(right);}},finalOutput=traceRecorded(presentation?.modelOutput)?presentation.modelOutput:traceRecorded(model?.session?.output)?model.session.output:null,retained=events.slice(-100),streamed=retained.filter(event=>partialTypes.includes(String(event?.event_type||'').toLowerCase())).map(outputValue).filter(value=>value!==undefined&&value!==null).map(value=>typeof value==='string'?value:promptText(traceSanitizeValue(value))).join(''),hasEquivalentFinal=traceRecorded(finalOutput)&&(retained.some(event=>terminalTypes.includes(String(event?.event_type||'').toLowerCase())&&sameOutput(outputValue(event),finalOutput))||(streamed&&sameOutput(streamed,finalOutput)));if(traceRecorded(finalOutput)&&!hasEquivalentFinal){const visible=retained.slice(-99);visible.push({event_type:'assistant_output',payload:{content:traceRawBoundValue(finalOutput,8000)}});return visible;}return retained;}
  const fallback=[];turns.forEach(turn=>{if(turn.input)fallback.push({event_type:'model_request',payload:{step:turn.step,input:turn.input}});(turn.tools||[]).forEach(item=>{fallback.push({event_type:'tool_call',payload:{step:turn.step,...item.call}});if(item.result)fallback.push({event_type:'tool_result',payload:{step:turn.step,...item.result}})});if(traceRecorded(turn.output))fallback.push({event_type:'assistant_output',payload:{step:turn.step,content:turn.output}});});
  if(!fallback.length&&Array.isArray(model?.toolCalls))model.toolCalls.slice(-100).forEach(item=>{fallback.push({event_type:'tool_call',payload:item.call||item});if(item.result)fallback.push({event_type:'tool_result',payload:item.result});});
  if(!fallback.length&&traceRecorded(presentation?.modelInput))fallback.push({event_type:'model_request',payload:{input:presentation.modelInput}});
  if(!fallback.length&&traceRecorded(presentation?.modelOutput))fallback.push({event_type:'assistant_output',payload:{content:presentation.modelOutput}});
  return fallback;
}
function traceCodexTimeline(model,title='Model chat',renderBudget=null,full=false,materializedEvents=null){
  const budget=renderBudget||traceRenderBudget(),presentation=model.presentation||tracePresentationData(model),events=Array.isArray(materializedEvents)?materializedEvents:traceCodexEvents(model,presentation),modelName=traceInlineText(model.session?.model??model.actor?.model??'model not recorded');
  if(!events.length)return traceFinalizeMarkup(`<section class="trace-primary trace-chat-presentation"><div class="trace-primary-head"><h2>${esc(title)}</h2><span class="tiny">${esc(String(modelName))}</span></div><div class="trace-primary-empty">No model events captured</div></section>`,budget);
  const cards=traceTimelineMarkup(events.map((event,index)=>full?traceCodexEventMarkup(event,index,null,true):traceCodexEventMarkup(event,index,traceRenderBudget(6000))),18000),hasOutput=events.some(event=>['output_delta','output_stream','assistant_output','model_output','output'].includes(String(event?.event_type||'').toLowerCase())),outputState=traceCaptureState(presentation?.modelOutput,presentation?.finalResponseStatus??model.finalResponseStatus??model.session?.final_response_status??'');
  const emptyOutput=hasOutput||outputState==='produced'?'':`<div class="trace-primary-empty">Model output · ${outputState==='empty'?'Model returned an empty final response':outputState==='redacted'?'Final response is redacted':'No model output captured'}</div>`;
  return traceFinalizeMarkup(`<section class="trace-primary trace-chat-presentation trace-codex-timeline"><div class="trace-primary-head"><h2>${esc(title)}</h2><span class="tiny">${esc(String(modelName))} · ${events.length} events</span></div><div class="trace-tool-timeline trace-timeline-stream">${cards}${emptyOutput}</div></section>`,budget);
}
function traceToolResultData(result,budget=null){
  // Determine outcome before rendering can omit error fields to fit its budget.
  const failure=candidate=>candidate&&(candidate.error||candidate.error_message||candidate.exception||candidate.is_error||candidate.isError||candidate.success===false),error=Boolean(failure(result?.result)||failure(result)),value=tracePresentationValue(result||{},5000,budget);
  return {value,error};
}
function traceModelChatEventTypes(events){const useful=new Set(['model_request','assistant_thinking','thinking','reasoning','assistant_reasoning','tool_call','tool_result','output_delta','output_stream','assistant_output','model_output','output','output_final','final_output','turn_start','turn_end','step_start','step_end']);return (Array.isArray(events)?events:[]).filter(event=>{const type=String(event?.event_type||'').toLowerCase(),payload=event?.payload;return useful.has(type)||(payload&&typeof payload==='object'&&payload.malformed_payload)||(event&&payload!==null&&typeof payload!=='object');});}
function traceModelContextMarkup(input,budget){const source=input&&typeof input==='object'&&!Array.isArray(input)?input:{},details={};if(source.model!==undefined)details.model=source.model;if(source.stream!==undefined)details.stream=source.stream;if(source.options&&typeof source.options==='object')details.options=source.options;if(source.request&&typeof source.request==='object')details.request={path:source.request.path};if(source.headers||source.metadata||(source.request&&source.request.headers))details.security='Sensitive request metadata redacted';if(!Object.keys(details).length)return '';return `<details class="trace-optional-details trace-model-context" data-trace-key="model-context" data-trace-collapsible><summary>Model details · compact</summary><div class="trace-optional-body">${traceTechnicalMarkup(tracePresentationValue(details,4000,budget),4000)}</div></details>`;}
 function renderModelChatPresentation(model){
  const timelineContract='Model input Model output model name tool result trace-codex-timeline';
  const budget=traceRenderBudget(),presentation=traceSanitizeValue(model.presentation||{}),input=model.input??presentation.modelInput,output=model.output??presentation.modelOutput,thinking=model.thinking??presentation.thinking,finalStatus=model.finalResponseStatus??presentation.finalResponseStatus??model.session?.final_response_status??'',outputState=traceCaptureState(output,finalStatus||model.captureStates?.output),thinkingState=traceCaptureState(thinking,model.captureStates?.thinking),inputState=traceCaptureState(input,model.captureStates?.input),messages=traceModelInputMessages(input,null),promptMarkup=traceMarkupItems(messages.map((message,index)=>traceChatMessageMarkup(message,index,budget)),7000)||(traceMeaningfulValue(input)?traceHumanReadableMarkup(input,7000):''),responseMarkup=outputState==='produced'?traceReadableMarkup(output,budget,7000):`<div class="trace-primary-empty">${traceCaptureBadge(outputState,'Final response')}<div>${esc(outputState==='empty'?'Model returned an empty final response':outputState==='redacted'?'Final response is redacted':'Final response was not captured')}</div></div>`,thinkingMarkup=thinkingState==='produced'?`<details class="trace-optional-details trace-thinking-panel" data-trace-collapsible><summary>Thinking / reasoning · expandable</summary><div class="trace-optional-body">${traceReadableMarkup(thinking,budget,12000)}</div></details>`:'',copyDisabled=outputState!=='produced'?' disabled aria-disabled="true"':'',actions=`<div class="trace-presentation-actions">${traceCaptureBadge(outputState,'Final response')}<button type="button" class="btn" data-trace-copy-final${copyDisabled}>Copy final response</button><button type="button" class="btn" data-trace-expand-all>Expand all</button><button type="button" class="btn" data-trace-collapse-all>Collapse all</button></div>`,timelineEvents=traceModelChatEventTypes(traceCodexEvents(model,presentation));
  const toolRecords=[],toolById=new Map();
  timelineEvents.forEach(event=>{const type=String(event?.event_type||'').toLowerCase(),payload=event?.payload&&typeof event.payload==='object'?event.payload:{};if(type==='tool_call'){const record={call:payload,result:null};toolRecords.push(record);const id=payload?.call_id??payload?.callId;if(id)toolById.set(String(id),record);}else if(type==='tool_result'){const id=payload?.call_id??payload?.callId,record=id&&toolById.get(String(id));if(record)record.result=payload;else toolRecords.push({call:null,result:payload});}});
  const toolSummary=toolRecords.length?traceMarkupItems(toolRecords.slice(0,100).map((record,index)=>{const call=record.call||{},result=record.result||{},resultData=traceToolResultData(result,budget),failed=Boolean(resultData.error),name=call.name||call.tool||result.name||result.tool||'tool',status=failed?'error':result.status??result.state??(record.result?'complete':call.status??'pending'),summary=traceAgentLoopPrimaryValue(resultData.value?.result??resultData.value?.output??resultData.value?.error??'');return `<div class="trace-tool-summary-row ${failed?'error':''}"><strong>${esc(traceInlineText(name))}</strong><span>${esc(traceInlineText(status))}</span>${traceRecorded(summary)?`<span>${esc(traceInlineText(summary))}</span>`:''}</div>`}),6000):'<div class="trace-primary-empty">No tool calls captured</div>';
  const toolMarkup=`<section class="trace-tool-summary"><h3>Tool summary <span class="tiny">${toolRecords.length}</span></h3><div class="trace-tool-summary-list">${toolSummary}</div></section>`;
  const contextMarkup=traceModelContextMarkup(input,budget).replace('Model details · compact','Model context · compact');
  const inputObject=input&&typeof input==='object'&&!Array.isArray(input)?input:{};
  const requestEnvelope={};if(inputObject.model!==undefined)requestEnvelope.model=inputObject.model;if(inputObject.stream!==undefined)requestEnvelope.stream=inputObject.stream;if(inputObject.request&&typeof inputObject.request==='object')requestEnvelope.request={path:inputObject.request.path};if(Array.isArray(inputObject.messages))requestEnvelope.messages=inputObject.messages.length;if(inputObject.headers||inputObject.request?.headers)requestEnvelope.security='Sensitive request metadata redacted';
  const requestMarkup=Object.keys(requestEnvelope).length?`<details class="trace-optional-details trace-request-envelope" data-trace-key="request-envelope" data-trace-collapsible><summary>Request envelope</summary><div class="trace-optional-body">${renderAny(tracePresentationValue(requestEnvelope,4000,budget))}</div></details>`:'';
  const primary=`<section class="trace-primary trace-model-presentation"><div class="trace-primary-head"><h2>Prompt / response</h2><span class="tiny">what the model received and returned</span></div>${actions}<div class="trace-chat-columns trace-primary-grid"><article class="trace-primary-card input"><h3>Prompt</h3><div class="trace-primary-value">${promptMarkup||`<div class="trace-primary-empty">${inputState==='empty'?'Prompt is empty':'No prompt captured'}</div>`}</div></article><article class="trace-primary-card output"><h3>Response</h3><div class="trace-primary-value">${responseMarkup}</div></article></div>${toolMarkup}${thinkingMarkup}</section>`;
  const timeline=traceCodexTimeline({...model,events:timelineEvents,presentation:{...presentation,modelOutput:output,finalResponseStatus:finalStatus}},'Model chat',traceRenderBudget(),false,timelineEvents);
  return traceFinalizeMarkup(primary,budget)+requestMarkup+contextMarkup+`<details class="trace-optional-details trace-model-timeline" data-trace-key="model-timeline" data-trace-collapsible><summary>Execution timeline · ${timelineEvents.length} useful events</summary><div class="trace-optional-body">${timeline}</div></details>`;
 }
function renderAgentLoopPresentation(model){
  const timelineContract='trace-codex-timeline trace-tool-timeline tool call tool result traceRawBoundValue traceSanitizeValue';
  const budget=traceRenderBudget(),presentation=traceSanitizeValue(model.presentation||{}),safeModel={...model,presentation},rawEvents=traceCodexEvents({...model,presentation},presentation),events=rawEvents.map(event=>({...event,payload:tracePresentationValue(event?.payload??{},8000)})),lifecycle=safeModel.lifecycle&&typeof safeModel.lifecycle==='object'?safeModel.lifecycle:{},input=safeModel.input??presentation.modelInput,objective=presentation.objective??safeModel.objective??lifecycle.objective,result=safeModel.output??presentation.modelOutput,error=safeModel.errors??presentation.error;
  const eventFailure=events.some(event=>{const payload=event?.payload,nested=payload&&typeof payload==='object'?payload.result:null;return payload&&typeof payload==='object'&&(traceRecorded(payload.error)||traceRecorded(payload.error_message)||traceRecorded(payload.exception)||payload.is_error===true||payload.isError===true||payload.success===false||nested?.error||nested?.success===false);});
  const explicitFailure=traceRecorded(error)||safeModel.success===false||safeModel.output?.success===false||presentation.success===false||presentation.modelOutput?.success===false;
  const lifecycleText=traceInlineText(lifecycle.state??lifecycle.status??'').toLowerCase();
  const state=explicitFailure||eventFailure||/failed|failure|error/.test(lifecycleText)?'failed':/interrupted|cancelled|canceled/.test(lifecycleText)?'interrupted':/queued|pending|waiting/.test(lifecycleText)?'queued':/running|active|processing/.test(lifecycleText)?'running':lifecycleText||(events.length?'live':'empty');
  const primaryField=(label,value,emptyLabel)=>{const fieldBudget=traceRenderBudget(3200),valueState=traceCaptureState(value,''),safe=tracePresentationValue(traceAgentLoopPrimaryValue(value),3200,fieldBudget),hasValue=traceMeaningfulValue(safe),body=hasValue?traceHumanValue(safe,fieldBudget,3200):`<span class="trace-primary-empty">${esc(valueState==='empty'?`${label} empty`:emptyLabel)}</span>`;return `<section class="trace-summary-card trace-agent-field" data-field="${esc(String(label).toLowerCase().replace(/\s+/g,'-'))}"><h3>${esc(label)}</h3><div class="trace-summary-value">${body}</div></section>`;};
  const toolRecords=[],toolById=new Map();
  events.forEach(event=>{const type=String(event?.event_type||'').toLowerCase(),payload=event?.payload&&typeof event.payload==='object'?tracePresentationValue(event.payload,8000):{};if(type==='tool_call'){const record={call:payload,result:null};toolRecords.push(record);const id=payload?.call_id??payload?.callId;if(id)toolById.set(String(id),record);}else if(type==='tool_result'){const id=payload?.call_id??payload?.callId,record=id&&toolById.get(String(id));if(record)record.result=payload;else toolRecords.push({call:null,result:payload});}});
  const toolCards=toolRecords.length?traceMarkupItems(toolRecords.slice(0,100).map((record,index)=>{const call=record.call||{},resultPayload=record.result||{},resultData=traceToolResultData(resultPayload),failed=Boolean(resultData.error),name=call.name||call.tool||resultPayload.name||resultPayload.tool||'tool',status=resultPayload.status??resultPayload.state??(failed?'error':record.result?'complete':call.status??'pending'),summary=resultData.value?.result??resultData.value?.output??resultData.value?.error??'',summaryBudget=traceRenderBudget(4000),safeSummary=tracePresentationValue(traceAgentLoopPrimaryValue(summary),4000,summaryBudget);return `<article class="trace-tool-card ${failed?'error':''}" data-tool-index="${index+1}"><h4>Tool ${index+1} · ${esc(traceInlineText(name))}</h4><div class="trace-tool-field"><strong>status</strong><div>${esc(traceInlineText(status))}</div></div>${traceRecorded(safeSummary)?`<div class="trace-tool-field"><strong>${failed?'failure':'summary'}</strong>${traceHumanReadableMarkup(safeSummary)}</div>`:'<div class="trace-primary-empty">No result captured</div>'}</article>`}),6500):'';
  const rawPayloads=traceAgentLoopPrimaryValue(toolRecords.map(record=>({call:record.call,result:record.result})));
  const rawMarkup=toolRecords.length?`<details class="trace-secondary-details trace-agent-raw" data-trace-collapsible><summary>Raw tool payloads</summary><div class="trace-optional-body">${traceHumanReadableMarkup(tracePresentationValue(rawPayloads,12000),12000)}</div></details>`:'';
  const metadataMarkup=events.length?`<details class="trace-secondary-details trace-agent-metadata" data-trace-collapsible><summary>Full event metadata</summary><div class="trace-optional-body">${traceHumanReadableMarkup(tracePresentationValue(traceAgentLoopPrimaryValue(events),12000),12000)}</div></details>`:'';
  const correlationSource=safeModel.correlations&&typeof safeModel.correlations==='object'&&!Array.isArray(safeModel.correlations)?safeModel.correlations:{};
  const correlationUnsafe=key=>/(^|_)(id|ids|request_id|correlation_id|call_id|session_id|job_id|lease_id|seq|sequence|header|headers|authorization|token|secret|password|private_key)(_|$)/.test(String(key).replace(/([a-z])([A-Z])/g,'$1_$2').replace(/[-\s]+/g,'_').toLowerCase());
  const safeCorrelationEntries=Object.entries(correlationSource).filter(([key,value])=>!correlationUnsafe(key)&&traceMeaningfulValue(value,key));
  const correlationValue=safeCorrelationEntries.length?Object.fromEntries(safeCorrelationEntries):'Correlation details unavailable (internal identifiers redacted)';
  const correlationMarkup=Object.keys(correlationSource).length?`<details class="trace-secondary-details trace-agent-correlations" data-trace-collapsible><summary>Correlations</summary><div class="trace-optional-body">${primaryField('Correlation summary',correlationValue,'Correlation details unavailable')}</div></details>`:'';
  const timelineMarkup=events.length?`<details class="trace-secondary-details trace-agent-timeline" data-trace-collapsible><summary>Execution timeline</summary><div class="trace-optional-body">${traceCodexTimeline({...safeModel,events},'Agent loop',null,true,events)}</div></details>`:'';
  const emptyStateMarkup=events.length?'':`<section class="trace-agent-empty-state"><h3>Trace state</h3><div class="trace-primary-empty">No agent trace events captured</div></section>`;
  const toolMarkup=toolRecords.length?`<section class="trace-tool-summary"><h3>Tool summary <span class="tiny">${toolRecords.length}</span></h3><div class="trace-tool-timeline">${toolCards}</div></section>`:'';
  const primary=`<section class="trace-primary trace-agent-loop-presentation"><div class="trace-primary-head"><h2>Agent loop</h2><span class="tiny">${esc(state)}</span></div><div class="trace-agent-state"><strong>Lifecycle</strong><span>${esc(state)}</span></div>${primaryField('Objective',objective,'Objective not captured')}${primaryField('Input',input,'Input not captured')}${primaryField('Final result',result,'Final result not captured')}${primaryField('Failure summary',traceRecorded(error)?error:'No failures recorded','No failures recorded')}${emptyStateMarkup}${toolMarkup}${rawMarkup}${metadataMarkup}${correlationMarkup}${timelineMarkup}</section>`;
  return traceFinalizeMarkup(primary,budget);
}
function tracePresentationPayload(model,key){const presentation=model?.presentation&&typeof model.presentation==='object'?model.presentation:{},payload=presentation[key],fieldSets={command:['command','cmd','args','arguments','input','stdin','stdout','stderr','exit_code','exitCode','success','retries','retry_count','attempts','duration','duration_ms','elapsed_ms','action','cwd','root','paths','criterion','error'],review:['request','context','diff','findings','recommendation','status','severity_counts','severityCounts','error'],repoOperation:['request_context','result_context','graph','graph_data','graphData','evidence','callers','related_symbols','relatedSymbols','diagnostics','repository','repo','root','operation','action','query','files','symbols','context','result','output','response','error'],asyncJob:['job_type','jobType','type','kind','status','state','progress','progress_percent','percent','completed','current','total','queue_wait_ms','queue_wait','queue_time_ms','retries','retry_count','attempts','worker_input','worker_output','input','result','output','error'],retrieval:['query','search_query','term','sources','results','hits','score','scores','provider','answer','truncated','truncation','root','project','top_k','limit','enrich','mode','path']},keys=fieldSets[key];return keys?(traceMergeRecordedSources([payload,model?.input,model?.output,model?.response,model?.session?.request,model?.session?.effective_payload],keys)||{}):payload??{};}
function tracePresentationPick(value,keys,fallback){const source=value&&typeof value==='object'?value:{};for(const key of keys){if(traceRecorded(source[key]))return source[key];}return fallback;}
function tracePrimaryBoundedValue(value,limit=6000){return tracePresentationValue(traceAgentLoopPrimaryValue(value),limit);}
function tracePresentationField(label,value,empty,budget,options={}){const key=String(label||'').toLowerCase().replace(/\s+/g,'_'),safe=options.mode==='technical'?tracePresentationValue(value,6000,budget):options.mode==='primary'?tracePrimaryBoundedValue(value,options.limit||6000):traceHumanPresentationValue(value);if(options.mode==='technical')return `<div class="trace-presentation-field"><strong>${esc(label)}</strong>${traceRecorded(safe)?traceTechnicalMarkup(safe,6000):`<span class="trace-primary-empty">${esc(empty||`No ${label} captured`)}</span>`}</div>`;if(options.showEmpty&&!traceRecorded(safe))return `<div class="trace-presentation-field"><strong>${esc(label)}</strong><span class="trace-primary-empty">${esc(empty||`No ${label} captured`)}</span></div>`;if(!traceMeaningfulValue(safe,key))return '';if(/(^|_)(stdout|stderr|diff|prompt|output|response)$/.test(key))return traceCodeBlock(label,safe,budget,{key,bounded:options.mode==='primary'});if(Array.isArray(safe))return traceList(label,safe,budget);return traceSummaryCard(label,safe,budget,{key,full:true,bounded:options.mode==='primary'});}
function tracePrimarySection(title,subtitle,markup){const content=String(markup??'');if(!content.trim())return '';const existing=content.match(/^<section\b[^>]*>/),existingClasses=existing&&existing[0].match(/\bclass="([^"]*\btrace-primary\b[^"]*)"/);if(existing&&existingClasses){const classes=existingClasses[1].includes('trace-primary-section')?existingClasses[1]:`trace-primary-section ${existingClasses[1]}`;return content.replace(existing[0],existing[0].replace(existingClasses[0],`class="${esc(classes)}"`));}const heading=esc(traceHumanText(title)),sub=traceRecorded(subtitle)?`<span class="tiny">${esc(traceHumanText(subtitle))}</span>`:'';return `<section class="trace-primary-section"><div class="trace-primary-head"><h2>${heading}</h2>${sub}</div>${content}</section>`;}
function traceSecondaryDetails(title,markup,options={}){const content=String(markup??'');if(!content.trim())return '';const label=traceHumanText(options.group??title),id=traceRecorded(options.id)?` id="${esc(traceHumanText(options.id))}"`:'';const open=options.open===true?' open':'';return `<details class="trace-secondary-details trace-optional-details" data-trace-collapsible data-trace-primary-group="${esc(label)}"${id}${open}><summary>${esc(label)}</summary><div class="trace-optional-body">${content}</div></details>`;}
function traceAttentionSection(items,budget){const state=budget||traceRenderBudget(4000),values=(Array.isArray(items)?items:[items]).map(item=>tracePresentationValue(item,2000,state)).filter(item=>traceMeaningfulValue(item));if(!values.length)return '';return `<section class="trace-attention-section" role="status"><h3>Attention</h3><ul>${values.map(item=>`<li>${traceHumanValue(item,state)}</li>`).join('')}</ul></section>`;}
function tracePresentationShell(title,subtitle,primary,secondary,attention=''){return `${traceAttentionSection(attention,traceRenderBudget(4000))}${tracePrimarySection(title,subtitle,primary)}${traceSecondaryDetails('Technical details',secondary)}`;}
 function tracePresentationGroup(title,markup,kind){if(!markup)return '';const groupKey=String(kind||title);return `<details class="trace-primary-group" data-group="${esc(groupKey)}" data-trace-primary-group="${esc(groupKey)}" data-trace-collapsible open><summary><span>${esc(title)}</span><span class="tiny">Show details</span></summary><div class="trace-primary-group-body">${markup}</div></details>`;}
function tracePresentationColumns(title,left,right,budget,headerExtra='',leftTitle='Request details',rightTitle='Result details',aggregate=false){const rawLeft=left.filter(Boolean),rawRight=right.filter(Boolean),all=aggregate?traceAggregatePrimaryFields([...rawLeft,...rawRight]):[...rawLeft,...rawRight],leftMarkup=all.slice(0,rawLeft.length).join(''),rightMarkup=all.slice(rawLeft.length).join(''),groups=tracePresentationGroup(leftTitle,leftMarkup,'request')+tracePresentationGroup(rightTitle,rightMarkup,'result'),markup=`<section class="trace-primary trace-request-presentation"><div class="trace-primary-head"><h2>${esc(title)}</h2>${headerExtra}</div>${groups?`<div class="trace-primary-groups">${groups}</div>`:''}</section>`;return traceFinalizeMarkup(markup,budget);}
function renderTraceInputOutputPresentation(model){const budget=traceRenderBudget(),input=tracePresentationField('input',model.input,'No input captured',budget,{mode:'primary',showEmpty:true}),output=tracePresentationField('output',model.output,'No output captured',budget,{mode:'primary',showEmpty:true});return tracePresentationColumns('Input / output',[input],[output],budget,'','Input','Output',true);}
function traceReviewSeverityMarkup(findings,severityMap,budget){const counts={critical:0,high:0,medium:0,low:0},map=severityMap&&typeof severityMap==='object'&&!Array.isArray(severityMap)?severityMap:{};Object.keys(counts).forEach(level=>{const value=Number(map[level]);if(Number.isFinite(value))counts[level]=value;});const items=Array.isArray(findings)?findings:[];items.forEach(item=>{const severity=traceInlineText(item?.severity??item?.priority??'',120).toLowerCase();if(counts[severity]!==undefined&&!Number.isFinite(Number(map[severity])))counts[severity]+=1;});return `<div class="trace-severity-counts" aria-label="severity counts">${Object.entries(counts).map(([level,count])=>`<span class="trace-event-chip ${count?'trace-severity-active':''}">${esc(level)}: ${count}</span>`).join('')}</div>`;}
function traceProjectLabel(value){
  if(typeof value==='string'){const text=value.replace(/[\\/]+$/,'');if(!text)return '';const parts=text.split(/[\\/]/).filter(Boolean);return parts[parts.length-1]||text;}
  const source=value&&typeof value==='object'?value:{};
  for(const key of ['project','project_name','projectName','workspace_name','workspaceName','workspace','root','repo_root','repository','repo']){const candidate=source[key];if(typeof candidate==='string'&&candidate.trim())return traceProjectLabel(candidate);}
  for(const key of ['request','effective_payload','payload','input']){if(source[key]&&typeof source[key]==='object'){const nested=traceProjectLabel(source[key]);if(nested)return nested;}}
  return '';
}
function traceSearchText(value,limit=420){
  if(value===undefined||value===null)return '';
  if(typeof value==='string')return value.length>limit?value.slice(0,limit)+'…':value;
  if(typeof value==='number'||typeof value==='boolean')return String(value);
  const source=value&&typeof value==='object'?value:{};
  const directKeys=['text','content','snippet','summary','description','reason','message','detail'],directKey=directKeys.find(key=>source[key]!==undefined&&source[key]!==null&&source[key]!==''),parts=[];
  if(directKey)parts.push(traceSearchText(source[directKey],Math.max(40,Math.floor(limit/2))));
  const fields=['reason','status','shown','count','total','limit','budget','truncated'].filter(key=>key!==directKey&&source[key]!==undefined&&source[key]!==null&&source[key]!=='').map(key=>`${humanLabel(key)}: ${traceSearchText(source[key],Math.max(40,Math.floor(limit/3)))}`);
  return parts.concat(fields).join(' · ').slice(0,limit);
}
function traceMeaningfulValue(value,key=''){
  const name=String(key||'').replace(/([a-z0-9])([A-Z])/g,'$1_$2').toLowerCase();
  if(value===undefined||value===null||value==='')return false;
  if(!/(^|_)(stdout|stderr)$/i.test(name)&&typeof value==='string'&&/^(empty|none|null|n\/a|unknown)$/i.test(value.trim()))return false;
  if(/(^|_)(id|ids|lease_id|session_id|clone_id|worktree_id|repository_id|task_id|metadata|headers?)$/.test(name)||name.includes('internal')||name.includes('duplicate')||name.includes('authorization')||name.includes('token')||name.includes('secret')||name.includes('password'))return false;
  if(Array.isArray(value))return value.some(item=>traceMeaningfulValue(item));
  if(typeof value==='object')return Object.entries(value).some(([childKey,childValue])=>traceMeaningfulValue(childValue,childKey));
  return true;
}
function tracePrimaryMeaningfulValue(value,key=''){if(typeof value==='string'&&/^(empty|none|null|n\/a|unknown)$/i.test(value.trim()))return false;return traceMeaningfulValue(value,key);}
function traceHumanValue(value,budget,limit=4000){const safe=tracePrimaryBoundedValue(traceAgentLoopPrimaryValue(value),limit),markup=traceHumanValueBody(safe,budget,limit);return markup.length<=limit?markup:traceEscapedPreview(safe,limit);}
function traceHumanValueBody(value,budget,limit=4000){
  const val=traceHumanPresentationValue(value);
  if(val===undefined||val===null)return '';
  if(typeof val==='string'||typeof val==='number'||typeof val==='boolean'){
    return esc(String(val));
  }
  if(Array.isArray(val)){
    const items=val.filter(item=>traceMeaningfulValue(item));
    if(!items.length)return '';
    if(items.every(it=>typeof it==='string'||typeof it==='number'||typeof it==='boolean')){
      return items.map(it=>`<span class="trace-chip">${esc(String(it))}</span>`).join('');
    }
    return `<div class="trace-list-items">${items.map(it=>`<div>${traceHumanValueBody(it,budget,limit)}</div>`).join('')}</div>`;
  }
  if(typeof val==='object'){
    const entries=Object.entries(val).filter(([k,v])=>traceMeaningfulValue(v,k));
    if(!entries.length)return '';
    return entries.map(([k,v])=>`<div class="trace-obj-field"><strong class="trace-obj-key">${esc(k)}:</strong> <span class="trace-obj-val">${traceHumanValueBody(v,budget,limit)}</span></div>`).join('');
  }
  return esc(String(val));
}
function traceSummaryCard(title,value,budget,options={}){
  const val=options.mode==='technical'?tracePresentationValue(value,options.limit||4000,budget):options.bounded?tracePrimaryBoundedValue(value,options.limit||6000):traceHumanPresentationValue(value);
  if(!traceMeaningfulValue(val,options.key||title))return '';
  return `<section class="trace-summary-card ${esc(options.tone||'')}" data-field="${esc(options.key||title)}"><h3>${esc(title)}</h3><div class="trace-summary-value">${traceHumanValue(val,budget,options.limit||1800)}</div></section>`;
}
function traceCodeBlock(title,value,budget,options={}){
  const val=options.bounded?tracePrimaryBoundedValue(value,options.limit||6000):traceHumanPresentationValue(value);
  if(!tracePrimaryMeaningfulValue(val,options.key||title))return '';
  return `<section class="trace-code-card"><h3>${esc(title)}</h3><pre class="trace-output">${traceEscapedPreview(traceAgentLoopPrimaryValue(val),options.limit||4000)}</pre></section>`;
}
function traceList(title,items,budget,renderItem){
  const values=(Array.isArray(items)?items:[]).filter(item=>traceMeaningfulValue(item));
  if(!values.length)return '';
  const rendered=traceMarkupItems(values.map((item,index)=>renderItem?renderItem(item,index,budget):`<div class="trace-list-item">${traceHumanValue(item,budget,1200)}</div>`),4000);
  return `<section class="trace-list-card"><h3>${esc(title)} <span class="tiny">${values.length}</span></h3><div>${rendered}</div></section>`;
}
function renderCommandPresentation(model){
  const budget=traceRenderBudget();
  const presentation=model?.presentation&&typeof model.presentation==='object'?model.presentation:{};
  const rawCommand=presentation.command&&typeof presentation.command==='object'&&!Array.isArray(presentation.command)?presentation.command:{};
  const command=traceSanitizeValue(tracePresentationPayload(model,'command')||{}),pick=(keys,fallback='')=>tracePresentationPick(command,keys,fallback),bound=(value,limit=1800)=>tracePresentationValue(value,limit);
  const cmdVal=pick(['command','cmd'],''),argsVal=pick(['args','arguments'],''),inputVal=pick(['input','stdin'],''),exitCodeVal=pick(['exit_code','exitCode','code'],''),successVal=pick(['success'],model?.success),retriesVal=pick(['retries','retry_count','attempts'],''),durationVal=pick(['duration','duration_ms','elapsed_ms'],''),errorVal=pick(['error'],model?.error??model?.errors??'');
  const lifecycle=model?.lifecycle&&typeof model.lifecycle==='object'?model.lifecycle:{},lifecycleText=traceInlineText(lifecycle.state??lifecycle.status??'').toLowerCase(),failed=successVal===false||((typeof exitCodeVal==='number'||(typeof exitCodeVal==='string'&&exitCodeVal.trim()!==''))&&Number(exitCodeVal)!==0)||traceRecorded(errorVal)||/failed|failure|error/.test(lifecycleText),live=/queued|pending|running|active|processing|streaming|live|incomplete/.test(lifecycleText),commandHas=Object.entries(command).some(([key,value])=>traceMeaningfulValue(value,key)),state=failed?'failed':live?'live':!commandHas?'empty':successVal===true||(traceRecorded(exitCodeVal)&&String(exitCodeVal).trim()!==''&&Number(exitCodeVal)===0)?'success':'incomplete',stateLabel=state==='failed'?'Failed':state==='live'?'Live / incomplete':state==='success'?'Success':state==='empty'?'Not captured':'Incomplete';
  const stdout=pick(['stdout'],''),stderr=pick(['stderr'],''),inputSafe=bound(inputVal,1800),errorSafe=bound(errorVal,1800),argsSafe=bound(argsVal,3000),exitSafe=bound(exitCodeVal,200),durationSafe=bound(durationVal,300),stdoutPreview=traceRecorded(stdout)?traceCodeBlock('stdout',bound(stdout,1400),budget):'',stderrPreview=traceRecorded(stderr)?traceCodeBlock('stderr',bound(stderr,1400),budget):'',outputMarkup=stdoutPreview||stderrPreview?`${stdoutPreview}${stderrPreview}`:'<div class="trace-primary-empty">No output captured</div>';
  const cmdSummary=traceMeaningfulValue(cmdVal)?`<div class="trace-command-line"><code>${esc(traceInlineText(bound(cmdVal,800)))}</code></div>`:'<div class="trace-primary-empty">No command captured</div>',argsMarkup=Array.isArray(argsSafe)&&argsSafe.length?traceList('arguments',argsSafe,budget):traceMeaningfulValue(argsSafe)?traceSummaryCard('arguments',argsSafe,budget):'<div class="trace-primary-empty">No arguments captured</div>',stateMarkup=`<section class="trace-summary-card trace-command-state"><h3>exit state</h3><div class="trace-summary-value">${esc(stateLabel)}</div>${failed?'<div class="trace-primary-empty">Command failed</div>':''}${live?'<div class="trace-primary-empty">Command live / incomplete</div>':''}</section>`,failureMarkup=failed&&traceMeaningfulValue(errorSafe)?traceSummaryCard('failure',errorSafe,budget):'',top=`<section class="trace-summary-card trace-command-top"><h3>Command and arguments</h3>${cmdSummary}${argsMarkup}${stateMarkup}${failureMarkup}</section>`,left=[traceMeaningfulValue(inputSafe)?traceSummaryCard('input',inputSafe,budget):''],right=[outputMarkup,traceMeaningfulValue(exitSafe)?traceSummaryCard('exit code',exitSafe,budget):'',traceMeaningfulValue(durationSafe)?traceSummaryCard('duration',durationSafe,budget):''],details=[];
  if(state==='live')details.push('<div class="trace-primary-empty">Command is live or incomplete</div>');
  const cwd=rawCommand.cwd??command.cwd,paths=rawCommand.paths??command.paths,criterion=rawCommand.criterion??command.criterion;
  if(traceMeaningfulValue(cwd))details.push(traceSummaryCard('cwd',bound(cwd,4000),budget,{full:true}));
  if(traceMeaningfulValue(paths)){const pathsSafe=bound(paths,4000);details.push(Array.isArray(pathsSafe)?traceList('paths',pathsSafe,budget):traceSummaryCard('paths',pathsSafe,budget,{full:true}));}
  if(traceMeaningfulValue(retriesVal))details.push(traceSummaryCard('retries',bound(retriesVal,400),budget));
  if(traceMeaningfulValue(criterion))details.push(traceSummaryCard('criterion',bound(criterion,4000),budget,{full:true}));
  const rawSource=Object.keys(rawCommand).length?rawCommand:command,cleanRaw=(value,key='')=>{if(traceSensitiveField(key))return traceSanitizeValue(value);if(!tracePrimaryMeaningfulValue(value,key))return undefined;if(Array.isArray(value))return value.map(item=>cleanRaw(item)).filter(item=>item!==undefined);if(value&&typeof value==='object'){const result={};Object.entries(value).forEach(([childKey,childValue])=>{const cleaned=cleanRaw(childValue,childKey);if(cleaned!==undefined)result[childKey]=cleaned});return result;}return traceSanitizeValue(value)};
  const fullInput=traceRecorded(inputVal)?traceCodeBlock('Full input',traceRawBoundValue(cleanRaw(inputVal,'input'),16000),traceRenderBudget(18000),{limit:16000}):'';
  const fullFailure=traceRecorded(errorVal)?traceCodeBlock('Full failure',traceRawBoundValue(traceSanitizeValue(errorVal),16000),traceRenderBudget(18000),{limit:16000}):'';
  const fullStdout=traceRecorded(stdout)?traceCodeBlock('Full stdout',traceRawBoundValue(traceSanitizeValue(stdout),16000),traceRenderBudget(18000),{limit:16000}):'';
  const fullStderr=traceRecorded(stderr)?traceCodeBlock('Full stderr',traceRawBoundValue(traceSanitizeValue(stderr),16000),traceRenderBudget(18000),{limit:16000}):'';
  [fullInput,fullFailure,fullStdout,fullStderr].filter(Boolean).forEach(item=>details.push(item));
  const rawProjection=cleanRaw(rawSource)||{};
  if(Object.keys(rawProjection).length)details.push(`<section class="trace-code-card"><h3>Raw command payload</h3><pre class="trace-output">${traceEscapedPreview(traceRawBoundValue(rawProjection,12000),12000)}</pre></section>`);
  const secondary=details.length?traceSecondaryDetails('Command details',details.join('')):'';
  return traceFinalizeMarkup(`${top}${tracePresentationColumns('Command output',left,right,budget)}${secondary}`,budget);
}
function traceReviewFindingsMarkup(groups,total){
   if(!total)return '<div class="trace-primary-empty">No findings recorded</div>';
   let markup='';
   for(const [severity,items] of groups){const cards=items.map(item=>{const safe=tracePrimaryBoundedValue(traceAgentLoopPrimaryValue(item),2600),summary=safe&&typeof safe==='object'?{rule:safe.rule,title:safe.title,message:safe.message??safe.description??safe.text}:safe;return `<article class="trace-finding-item"><span class="trace-chip">${esc(humanLabel(severity))}</span><div>${traceHumanReadableMarkup(summary,1800)}</div></article>`;}).join('');if(cards)markup+=`<section class="trace-finding-group trace-list-card" data-severity="${esc(severity)}"><h3>${esc(humanLabel(severity))} findings <span class="tiny">${items.length}</span></h3>${cards}</section>`;}
   return markup;
}
function traceVisionReviewPayload(model){
  const parse=value=>{if(typeof value!=='string')return value;try{const parsed=JSON.parse(value);return parsed&&typeof parsed==='object'?parsed:null}catch{return null}};
  const output=parse(model?.output),response=parse(model?.response),sessionOutput=parse(model?.session?.output),sources=[output,response,sessionOutput,model?.session?.effective_payload,model?.presentation?.visionReview].filter(value=>value&&typeof value==='object');
  const nested=sources.flatMap(value=>[value.review,value.result,value.vision_review]).filter(value=>value&&typeof value==='object'&&!Array.isArray(value));
  const review=nested[0]||sources.find(value=>Array.isArray(value.findings)||value.summary||value.unknowns)||{};
  const pick=(keys,fallback='')=>{for(const source of [review,...sources])for(const key of keys)if(source?.[key]!==undefined&&source?.[key]!==null)return source[key];return fallback;};
  const refs={...(sources.find(value=>value.artifact_refs&&typeof value.artifact_refs==='object')?.artifact_refs||{}),...(sources.find(value=>value.artifacts&&typeof value.artifacts==='object')?.artifacts||{}),...(output?.coder_context?.artifact_refs||{})};if(output?.image_artifact_id||output?.screenshot_artifact_id)refs.screenshot=output.image_artifact_id||output.screenshot_artifact_id;if(output?.raw_output_artifact_id)refs.raw_output=output.raw_output_artifact_id;const capture=pick(['capture','capture_state','captureState'],{}),error=pick(['error'],{});
  return {summary:pick(['summary','text']),findings:Array.isArray(review.findings)?review.findings:[],unknowns:pick(['unknowns'],[]),recommended_checks:pick(['recommended_checks','recommendedChecks'],[]),provider:pick(['provider','source_provider'],model?.session?.provider||'local'),model:pick(['model'],model?.session?.model||'vision model'),source:pick(['source'],model?.session?.source||'upload'),status:pick(['status'],model?.lifecycle?.state||''),capture,artifacts:refs,raw_output_artifact_id:pick(['raw_output_artifact_id','rawOutputArtifactId']),raw_output:pick(['raw_output','response'],model?.response||''),error,error_code:pick(['error_code','errorCode'],''),permission_error:pick(['permission_error','permissionError'],''),viewport:pick(['viewport'],{}),page:pick(['page'],{})};
}
function traceVisionCaptureState(value,fallback='not_captured'){const source=value&&typeof value==='object'?value:{state:value};const state=String(source.state??source.status??source.capture_state??fallback).toLowerCase();if(state.includes('permission'))return 'not_captured';if(state.includes('redact'))return 'redacted';if(state.includes('empty'))return 'empty';if(['produced','captured','ok','success','complete','completed'].includes(state))return 'produced';return 'not_captured';}
function requestFrontendVisionRepair(findingId){const id=String(findingId||'').trim();if(!id)return;openFrontendVisionReviewModal({findingId:id,prompt:`Fix frontend finding ${id}`});window.dispatchEvent(new CustomEvent('local-ai-vision-repair',{detail:{finding_id:id}}));}
function renderVisionReviewPresentation(model){
  const budget=traceRenderBudget(),review=traceVisionReviewPayload(model),findings=Array.isArray(review.findings)?review.findings:[],captureState=traceVisionCaptureState(review.capture,review.source==='current_tab'?'not_captured':'produced'),permissionError=review.error_code==='permission_denied'||/permission/i.test(String(review.permission_error||review.error?.code||review.error||'')),summary=review.summary||'No visual summary captured';
  const provenance=`<div class="trace-vision-provenance"><span>model provenance: ${esc(traceInlineText(review.provider))}</span><span>${esc(traceInlineText(review.model))}</span><span>source: ${esc(traceInlineText(review.source))}</span>${traceCaptureBadge(captureState,'Current tab')}</div>`;
  const errorMarkup=permissionError?`<div class="trace-summary-card trace-vision-error" data-capture-error="permission_denied"><h3>Capture error</h3><div>Permission denied by current-tab bridge. Manual screenshot upload remains available.</div></div>`:(traceMeaningfulValue(review.error)?traceSummaryCard('error',review.error,budget):'');
  const findingMarkup=findings.length?findings.map((item,index)=>{const id=String(item?.finding_id??item?.id??`finding-${index+1}`),severity=String(item?.severity??'info'),problem=item?.problem??item?.observed??'Finding';const detail=[item?.observed&&traceSummaryCard('observed',item.observed,budget),item?.hypothesized&&traceSummaryCard('hypothesized',item.hypothesized,budget),item?.evidence&&traceList('evidence',item.evidence,budget),item?.fix_hint&&traceSummaryCard('fix hint',item.fix_hint,budget)].filter(Boolean).join('');return `<article class="trace-vision-finding ${esc(severity)}" data-finding-id="${esc(id)}"><div class="trace-vision-finding-head"><span class="trace-chip">${esc(severity)}</span><strong>${esc(id)}</strong><span>${esc(traceInlineText(problem))}</span></div><div class="tiny">confidence ${esc(item?.confidence??'—')} · category ${esc(item?.category??'—')}</div><div class="trace-vision-finding-actions"><button class="btn" type="button" data-repair-finding="${esc(id)}" onclick="requestFrontendVisionRepair(${escJs(id)})">Repair finding ${esc(id)}</button></div>${detail?`<details class="trace-optional-details"><summary>Finding evidence</summary><div class="trace-optional-body">${detail}</div></details>`:''}</article>`}).join(''):'<div class="trace-vision-empty">No findings captured.</div>';
  const artifact=(keys)=>{for(const key of keys){const value=review.artifacts?.[key]??review[key];if(traceRecorded(value))return value;}return '';};
  const evidence=(key,label,value,raw=false)=>{const safe=tracePresentationValue(value,raw?12000:6000,budget),body=traceRecorded(safe)?(key==='screenshot'&&typeof safe==='string'&&/^data:image\//.test(safe)?`<img src="${esc(safe)}" alt="Captured screenshot">`:raw?`<pre class="trace-output">${esc(traceInlineText(safe,12000))}</pre>`:renderAny(safe)):`<span class="trace-vision-empty">${esc(label)} unavailable</span>`;return `<details class="trace-optional-details trace-vision-evidence" data-vision-evidence="${esc(key)}"><summary>${esc(label)} · expandable</summary><div class="trace-optional-body">${body}</div></details>`;};
  const evidenceMarkup=[evidence('screenshot','Screenshot',artifact(['screenshot','screenshot_artifact_id'])),evidence('dom','DOM',artifact(['dom','dom_artifact_id'])),evidence('accessibility','Accessibility',artifact(['accessibility','accessibility_artifact_id','a11y_artifact_id'])),evidence('raw-output','Raw model output',review.raw_output||review.raw_output_artifact_id||model?.response,true)].join('');
  return traceFinalizeMarkup(`<section class="trace-primary trace-vision-review" data-vision-review><div class="trace-primary-head"><h2>Frontend vision review</h2><span class="tiny">summary first · ${findings.length} finding${findings.length===1?'':'s'}</span></div>${provenance}<section class="trace-summary-card trace-vision-summary"><h3>Summary</h3><div class="trace-summary-value">${esc(traceInlineText(summary,4000))}</div></section><section class="trace-list-card trace-vision-findings"><h3>Findings</h3>${findingMarkup}</section>${errorMarkup}${evidenceMarkup}</section>`,budget);
}
function renderReviewPresentation(model){
  const budget=traceRenderBudget();
  const presentation=model?.presentation&&typeof model.presentation==='object'?model.presentation:{};
  const rawReview=presentation.review&&typeof presentation.review==='object'&&!Array.isArray(presentation.review)?presentation.review:{};
  const review=traceSanitizeValue(tracePresentationPayload(model,'review')||{}),bound=(value,limit=1800)=>tracePresentationValue(value,limit),requestRaw=rawReview.request??review.request??'',target=rawReview.target??rawReview.target_path??(requestRaw&&typeof requestRaw==='object'?requestRaw.target??requestRaw.path??requestRaw.repository:'')??'',scope=rawReview.scope??rawReview.files??(requestRaw&&typeof requestRaw==='object'?requestRaw.scope??requestRaw.files:'')??'',findingsRaw=rawReview.findings??review.findings??review.text??model?.output??'',findings=Array.isArray(findingsRaw)?findingsRaw:traceMeaningfulValue(findingsRaw)?[findingsRaw]:[],status=review.status??rawReview.status??model?.lifecycle?.state??'',errorVal=review.error??rawReview.error??model?.error??model?.errors??'';
  const lifecycle=model?.lifecycle&&typeof model.lifecycle==='object'?model.lifecycle:{},lifecycleText=traceInlineText(lifecycle.state??lifecycle.status??'').toLowerCase(),failed=traceRecorded(errorVal)||review.success===false||rawReview.success===false||/failed|failure|error|blocked/.test(String(status).toLowerCase()),live=!failed&&/queued|pending|running|active|processing|streaming|live|incomplete/.test(lifecycleText||String(status).toLowerCase()),hasReview=traceRecorded(target)||traceRecorded(scope)||traceRecorded(requestRaw)||findings.length>0||traceRecorded(review.recommendation)||traceRecorded(status)||traceRecorded(errorVal),state=failed?'failed':live?'live':!hasReview?'empty':/complete|completed|done|success|succeeded|finished/.test(String(status).toLowerCase())?'complete':'incomplete',stateLabel=state==='failed'?'Review failed':state==='live'?'Review Live / incomplete':state==='empty'?'Review not captured':state==='complete'?'Complete':'Incomplete',displayStatus=failed?'Review failed':live?'Review Live / incomplete':traceRecorded(status)?traceInlineText(bound(status,600),180):stateLabel,targetSafe=bound(target,1800),scopeSafe=bound(scope,1800),requestSafe=bound(requestRaw,1800),recommendationSafe=bound(review.recommendation,1800),requestMarkup=traceMeaningfulValue(targetSafe)?traceSummaryCard('target',targetSafe,budget):traceMeaningfulValue(requestSafe)?traceSummaryCard('request',requestSafe,budget):'<div class="trace-primary-empty">Review target not captured</div>',scopeMarkup=traceMeaningfulValue(scopeSafe)?traceSummaryCard('scope',scopeSafe,budget):'',stateMarkup=`<section class="trace-summary-card trace-review-state"><h3>overall status</h3><div class="trace-summary-value">${esc(displayStatus)}</div>${failed?'<div class="trace-primary-empty">Review failed</div>':''}${live?'<div class="trace-primary-empty">Review Live / incomplete</div>':''}</section>`,severityMarkup=traceReviewSeverityMarkup(review.findings??findingsRaw,review.severity_counts??review.severityCounts,budget),groups=new Map();
  findings.forEach(item=>{const severity=traceInlineText(item?.severity??item?.priority??'other',120).toLowerCase()||'other';if(!groups.has(severity))groups.set(severity,[]);groups.get(severity).push(item);});
  const findingMarkup=traceReviewFindingsMarkup(groups,findings.length),failureMarkup=failed&&traceMeaningfulValue(errorVal)?traceSummaryCard('failure',bound(errorVal,1800),budget):'',recommendationMarkup=traceMeaningfulValue(recommendationSafe)?traceSummaryCard('recommendation',recommendationSafe,budget,{full:true}):'',findingMetadata=tracePresentationValue(findings.map(item=>{const safe=traceSanitizeValue(item);if(!safe||typeof safe!=='object')return bound(safe,1600);return Object.fromEntries([['severity',bound(safe.severity,300)],['rule',bound(safe.rule,500)],['title',bound(safe.title,500)],['message',bound(safe.message??safe.description??safe.text,4000)],['details',bound(safe.details,6000)]].filter(([,value])=>traceMeaningfulValue(value)));}),12000),primary=`<section class="trace-summary-card trace-review-top"><h3>Review target and scope</h3>${requestMarkup}${scopeMarkup}${stateMarkup}${severityMarkup}${findingMarkup}${recommendationMarkup}${failureMarkup}</section>`,details=[];
  if(traceMeaningfulValue(rawReview.diff??review.diff))details.push(traceCodeBlock('diff',traceRawBoundValue(traceSanitizeValue(rawReview.diff??review.diff),16000),traceRenderBudget(18000)));
  if(traceMeaningfulValue(rawReview.context??review.context))details.push(`<section class="trace-summary-card"><h3>context</h3>${traceHumanReadableMarkup(tracePresentationValue(rawReview.context??review.context,8000))}</section>`);
  if(findings.length){const findingMetadataMarkup=traceBudgetMarkup(traceHumanReadableMarkup(findingMetadata),traceRenderBudget(12000));details.push(`<section class="trace-summary-card"><h3>Full finding metadata</h3>${findingMetadataMarkup}</section>`);}
  if(traceRecorded(target))details.push(traceCodeBlock('Full target',traceRawBoundValue(traceSanitizeValue(target),12000),traceRenderBudget(14000)));
  if(traceRecorded(scope))details.push(traceCodeBlock('Full scope',traceRawBoundValue(traceSanitizeValue(scope),12000),traceRenderBudget(14000)));
  if(traceRecorded(review.recommendation))details.push(traceCodeBlock('Full recommendation',traceRawBoundValue(traceSanitizeValue(review.recommendation),12000),traceRenderBudget(14000)));
  if(traceRecorded(errorVal))details.push(traceCodeBlock('Full failure',traceRawBoundValue(traceSanitizeValue(errorVal),12000),traceRenderBudget(14000)));
  const rawSource=Object.keys(rawReview).length?rawReview:review;
  if(Object.keys(rawSource).length)details.push(`<section class="trace-code-card"><h3>Raw review metadata</h3><pre class="trace-output">${traceEscapedPreview(traceRawBoundValue(traceSanitizeValue(rawSource),12000),12000)}</pre></section>`);
  const secondary=details.length?traceSecondaryDetails('Review evidence',details.join('')):'';
  return traceFinalizeMarkup(`${primary}${secondary}`,budget);
}
function renderRepoIntelligencePresentation(model){
  const budget=traceRenderBudget(),presentation=model?.presentation&&typeof model.presentation==='object'?model.presentation:{},rawRepo=presentation.repoOperation&&typeof presentation.repoOperation==='object'&&!Array.isArray(presentation.repoOperation)?presentation.repoOperation:{},repo=traceSanitizeValue(tracePresentationPayload(model,'repoOperation')||{}),pick=(keys,fallback='')=>tracePresentationPick(repo,keys,fallback),repository=pick(['repository','repo'],''),root=pick(['root','repo_root','repository_root'],''),operation=pick(['operation','action'],model?.identity?.action||''),query=pick(['query','search_query','term'],''),files=pick(['files','changed_files','paths'],''),symbols=pick(['symbols','changed_symbols'],''),result=pick(['result','output','response','text','result_context'],model?.output??''),errors=pick(['errors','error'],model?.errors??model?.error??''),resultSummary=result&&typeof result==='object'&&!Array.isArray(result)?tracePresentationPick(result,['summary','message','text','matches','count','total'],result):result,bounded=(value,limit=5000)=>tracePresentationValue(value,limit,budget),listOrCard=(label,value)=>{const safe=bounded(value);return Array.isArray(safe)?traceList(label,safe,budget):traceSummaryCard(label,safe,budget,{full:true})};
  const left=[
    traceMeaningfulValue(repository)?traceSummaryCard('repository',bounded(repository,1800),budget):'',
    traceMeaningfulValue(root)?traceSummaryCard('root',bounded(root,2200),budget):'',
    traceMeaningfulValue(operation)?traceSummaryCard('operation',bounded(operation,1200),budget):'',
    traceMeaningfulValue(query)?traceSummaryCard('query',bounded(query,3000),budget):'',
    traceMeaningfulValue(files)?listOrCard('files',files):'',
    traceMeaningfulValue(symbols)?listOrCard('symbols',symbols):'',
    traceMeaningfulValue(errors)?traceSummaryCard('error',bounded(errors,3000),budget,{tone:'bad'}):''
  ];
  const right=[
    traceMeaningfulValue(resultSummary)?traceSummaryCard('result summary',bounded(resultSummary,6000),budget,{full:true}):'<div class="trace-primary-empty">No result summary captured</div>'
  ];
  const details=[],secondaryFields=[['request context',repo.request_context],['context',repo.result_context??repo.context],['graph',repo.graph??repo.graph_data??repo.graphData],['evidence',repo.evidence],['callers',repo.callers],['related symbols',repo.related_symbols??repo.relatedSymbols],['diagnostics',repo.diagnostics]];
  secondaryFields.forEach(([label,value])=>{if(!traceMeaningfulValue(value,label))return;const safe=tracePresentationValue(value,7000,budget);if(traceMeaningfulValue(safe,label))details.push(`<section class="trace-summary-card"><h3>${esc(label)}</h3>${traceHumanReadableMarkup(safe)}</section>`);});
  const rawSource=Object.keys(rawRepo).length?rawRepo:repo,cleanPayload=(value,key='')=>{const normalized=String(key||'').replace(/([a-z])([A-Z])/g,'$1_$2').toLowerCase();if(traceSensitiveField(key)||/^(evidence_id|file_sha256|content_hash|sha256)$/.test(normalized))return undefined;if(Array.isArray(value))return value.map(item=>cleanPayload(item)).filter(item=>item!==undefined);if(value&&typeof value==='object'){const cleaned={};Object.entries(value).forEach(([childKey,childValue])=>{const child=cleanPayload(childValue,childKey);if(child!==undefined)cleaned[childKey]=child});return cleaned;}return value;};
  if(Object.keys(rawSource).length){const raw=traceRawBoundValue(traceSanitizeValue(cleanPayload(rawSource)),12000);details.push(`<section class="trace-code-card"><h3>Full repository payload</h3><pre class="trace-output">${traceEscapedPreview(raw,12000)}</pre></section>`);}
  const secondary=details.length?traceSecondaryDetails('Repository evidence',details.join('')):'';
  return traceFinalizeMarkup(`${tracePresentationColumns('Repository intelligence',left,right,budget)}${secondary}`,budget);
}
function traceRagResultKey(item){
  const source=item&&typeof item==='object'?item:{},id=source.id??source.evidence_id??source.chunk_id;
  const identity=JSON.stringify(id!==undefined?['id',id]:[source.path??source.file??source.filename??'',source.start_line??source.startLine??'',source.end_line??source.endLine??'',source.source??source.provider??'',source.title??source.name??'',source.snippet??source.text??source.content??item]);
  let hash=2166136261,other=5381;for(let i=0;i<identity.length;i++){hash=Math.imul(hash^identity.charCodeAt(i),16777619);other=Math.imul(other,33)^identity.charCodeAt(i);}return 'rag-result:'+(hash>>>0).toString(16)+(other>>>0).toString(16);
}
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
  const request=safeModel.session?.request&&typeof safeModel.session.request==='object'?safeModel.session.request:{},method=request.method??safeModel.identity?.method??safeModel.session?.method,path=request.path??safeModel.identity?.path??safeModel.session?.path,action=safeModel.identity?.action??safeModel.session?.action,reqVal=traceRecorded(method)||traceRecorded(path)||traceRecorded(action)?{method,path,action}:undefined,statusVal=safeModel.lifecycle?.status_code??safeModel.session?.status_code??safeModel.session?.state??safeModel.lifecycle?.state,duration=safeModel.timing?.duration_ms??safeModel.timing?.elapsed_ms??safeModel.session?.duration_ms??safeModel.session?.elapsed_ms,requestBody=safeModel.input??request.body??request.payload??request.data,responseBody=safeModel.response??safeModel.output,outputBody=safeModel.response&&traceRecorded(safeModel.output)?safeModel.output:undefined,error=safeModel.errors,hasCore=traceRecorded(reqVal)||traceRecorded(requestBody)||traceRecorded(responseBody)||traceRecorded(error)||traceRecorded(safeModel.lifecycle?.status_code)||traceRecorded(safeModel.session?.state)||traceRecorded(duration);
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
  const timing={created_at:session.created_at,updated_at:session.updated_at,finished_at:session.finished_at,duration_ms:session.duration_ms,elapsed_ms:session.elapsed_ms};
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
  if(typeof value==='string')return value;
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
  const titleEl=$('tracePageTitle'),liveEl=$('tracePageLive');if(titleEl)titleEl.textContent=traceHumanTitle(model);
  if(liveEl){liveEl.textContent=d?.terminal?'finished':'● live · updating';liveEl.className='tiny '+(d?.terminal?'ok':'trace-running');}
  const state=traceStatus(s),stateClass=(state==='failed'||state==='error')?'bad':(state==='interrupted'?'warn':(d?.terminal?'ok':'warn'));
  const command=s.action||traceHumanTitle(model),project=model.project?` · ${model.project}`:'',timestamp=Number(s.created_at)>0?new Date(Number(s.created_at)*1000).toLocaleString():'nezaznamenané';
  const header=`<div class="trace-inspector-head"><div class="trace-header-title"><h1>${esc(command+project)}</h1><span class="badge ${stateClass}">${esc(state)}</span></div><div class="trace-header-meta"><span class="trace-header-time">${esc(timestamp)}</span>${d?.payload_truncated?'<span>Obsah zkrácen limitem trace úložiště</span>':''}</div></div>`;
  const primaryMarkup=`<section class="trace-primary"><div class="trace-primary-grid">${traceMainContent('Input','input',tracePrimaryInput(model.input))}${traceMainContent('Output','output',model.output)}</div></section>`;
  const historyControls=d?.has_older_events||d?.has_newer_events?`<div class="trace-header-meta">${d?.has_older_events?'<button type="button" class="btn" data-trace-event-page="older">Load older events</button>':''}${d?.has_newer_events?'<button type="button" class="btn" data-trace-event-page="newer">Load newer events</button>':''}</div>`:'';
  const panelMarkup=technicalPanels.map(panel=>{const selected=panel.id===traceView,content=selected?panel.render():'';return `<div id="trace-panel-${esc(panel.id)}" class="trace-view" role="tabpanel" aria-labelledby="trace-tab-${esc(panel.id)}"${selected?'':' hidden'}>${content}</div>`}).join('');
  const requestSettingsValue={...traceTechnicalSettings(model.input),...traceTechnicalSettings(s.request)};
  const requestSettings=Object.keys(requestSettingsValue).length?`<details class="trace-optional-details" data-trace-collapsible data-trace-key="request-settings"><summary>Command / project settings</summary><div class="trace-optional-body">${humanSection('Settings',traceSanitizeValue(requestSettingsValue))}</div></details>`:'';
  const detailPolicy='Tajné klíče a přístupové tokeny jsou redigované; běžný obsah zůstává viditelný.';
  const technical=`<details class="trace-optional-details" id="traceTechnicalDetails" data-trace-collapsible data-trace-key="technical"${traceOptionalDetailsOpen?' open':''}><summary>Nastavení a technické údaje · ${technicalPanels.length}</summary><div class="trace-optional-body"><p class="tiny muted">${detailPolicy}</p>${traceSummary(model,{})}${requestSettings}${historyControls}<nav class="trace-tabs" role="tablist" aria-label="Trace technical details">${technicalPanels.map(panel=>traceTab(panel.label,panel.id)).join('')}</nav>${panelMarkup}</div></details>`;
  if(body){body.className='trace-page-body';body.innerHTML=`<div class="human-shell">${header}${traceMetricRow(d?.metrics)}${primaryMarkup}${technical}</div>`;}
  const restore=()=>{restoreTraceCollapsibleDetails($('tracePageBody'),collapsibleState);restoreTraceThinkingDetails($('tracePageBody'),thinkingDetailsOpen);restoreTraceScrollPositions($('tracePageBody'),scrollPositions);const next=$('tracePageBody')?.closest('.trace-main');if(next){next.scrollTop=mainScrollTop;next.scrollLeft=mainScrollLeft}};
  if(window.requestAnimationFrame)window.requestAnimationFrame(restore);else restore();
 }
function setTraceView(view){if(!activeTraceData)return;const model=traceDisplayModel(activeTraceData);if(!model.panels.some(panel=>panel.available&&panel.id===view))return;traceView=view;renderTraceDetail(activeTraceData)}
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
function moveTraceTab(tab,key){
  const tabs=Array.from(document.querySelectorAll('#tracePageBody [role="tab"]'));
  const index=tabs.indexOf(tab);if(index<0)return;
  let nextIndex=index;
  if(key==='ArrowLeft')nextIndex=(index-1+tabs.length)%tabs.length;
  else if(key==='ArrowRight')nextIndex=(index+1)%tabs.length;
  else if(key==='Home')nextIndex=0;
  else if(key==='End')nextIndex=tabs.length-1;
  else return;
  const view=tabs[nextIndex]?.dataset.traceView;if(!view)return;
  setTraceView(view);requestAnimationFrame(()=>document.getElementById('trace-tab-'+view)?.focus());
}
async function openTrace(id){
  const pollTraceId=String(id||''),pollGeneration=++tracePollGeneration;activeTraceId=pollTraceId;traceSeq=0;traceEvents=[];traceEventTotal=0;traceOpenSteps=new Set();traceView='timeline';activeTraceData=null;traceOptionalDetailsOpen=false;
  renderTraceList(lastTraces);switchTab('traceInspector');
  if(traceDetailPoller){traceDetailPoller.stop();traceDetailPoller=null}
  let pollInFlight=false,lastTracePollSignature='',terminalPayloadRequested=false;
  const poll=async isCurrent=>{
    if(!activeTraceId||pollTraceId!==activeTraceId||pollGeneration!==tracePollGeneration||pollInFlight||!isCurrent())return false;
    pollInFlight=true;
    const controller=typeof AbortController==='function'?new AbortController():null;
    tracePollAbortController=controller;
    try{
      const sinceSeq=traceSeq,opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
      const r=await apiFetch('/api/debug-traces/'+encodeURIComponent(pollTraceId)+'?since_seq='+sinceSeq+'&limit=100&max_bytes=8388608',opts),d=await r.json();
      if(!isCurrent()||pollGeneration!==tracePollGeneration||pollTraceId!==activeTraceId)return false;
      if(d.cursor_reset){traceSeq=0;traceEvents=[];traceEventTotal=0;}
      if(d.success){
        const signature=JSON.stringify([d.state,d.terminal,d.next_seq,d.events_total,d.updated_at,d.error]);
        const changed=signature!==lastTracePollSignature;lastTracePollSignature=signature;
        traceSeq=traceFiniteSequence(d.next_seq,traceSeq);traceEventTotal=Math.max(traceEventTotal,traceSeq,Number(d.events_total||d.eventsTotal||0));const next=traceAppendEvents(traceEvents,d.events,traceEventTotal);traceEvents=next.events;traceEventTotal=next.eventsTotal;
        if(changed)renderTraceDetail({...d,events:traceEvents,events_total:traceEventTotal,has_older_events:traceEventTotal>traceEvents.length,events_before_seq:traceEvents[0]?.seq||0,has_newer_events:false});
        if(d.terminal&&!terminalPayloadRequested){
          terminalPayloadRequested=true;const requestedTraceId=pollTraceId,base={...d,events:traceEvents,events_total:traceEventTotal};
          fetchPrimaryTraceContent(requestedTraceId,base).then(full=>{if(activeTraceId!==requestedTraceId||pollGeneration!==tracePollGeneration)return;activeTraceData={...activeTraceData,...full,metrics:activeTraceData?.metrics};renderTraceDetail(activeTraceData);}).catch(error=>{if(activeTraceId===requestedTraceId){activeTraceData={...activeTraceData,full_payload_error:String(error?.message||error)};renderTraceDetail(activeTraceData);}});
          fetchTraceMetrics(requestedTraceId).then(metrics=>{if(activeTraceId!==requestedTraceId||pollGeneration!==tracePollGeneration||!metrics)return;activeTraceData={...activeTraceData,metrics};renderTraceDetail(activeTraceData);}).catch(()=>{});
        }
        if(d.terminal&&!d.has_more&&!d.events_has_more&&pollGeneration===tracePollGeneration&&pollTraceId===activeTraceId){traceDetailPoller?.stop();traceDetailPoller=null}
        return {changed};
      }else if(d.retryable){const lEl=$('tracePageLive');if(lEl){lEl.textContent='● live · retrying…';lEl.className='tiny trace-running';}return false;
      }else{openModal(d,'Trace error');traceDetailPoller?.stop();traceDetailPoller=null;return false}
    }catch(e){if(isCurrent()&&pollGeneration===tracePollGeneration&&pollTraceId===activeTraceId&&!controller?.signal.aborted){const lEl=$('tracePageLive');if(lEl)lEl.textContent='refresh failed: '+e.message;}return false;
    }finally{pollInFlight=false;if(tracePollAbortController===controller)tracePollAbortController=null}
  };
  traceDetailPoller=createDashboardStatusPoller(poll,{baseDelay:1000,maxDelay:30000});
  traceDetailPoller.start();
}
function openModal(obj,title='',entityType=''){
  if($('modalLive'))$('modalLive').textContent='';
  if(!$('modalBody'))return;
  const type=entityType||inferEntityType(obj);
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
  else if(type==='project')renderProjectModal(obj);
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

function renderTaskModal(t){
  const st=String(t.status||'planned').toLowerCase();
  const terminal=st==='completed'||st==='failed';
  const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
  const goal=t.contract?.goal||'No goal specified';
  const criteria=t.contract?.acceptance_criteria||[];
  activeTaskInspectorState={taskId:String(t.task_id||''),criteria:[...criteria],status:st};
  trajectoryTaskId=activeTaskInspectorState.taskId;trajectoryAfterSeq=0;trajectorySnapshotSeq=null;trajectoryHasMore=false;trajectoryGaps=[];trajectoryEvents=[];trajectoryLoading=false;trajectoryPageError='';trajectoryGeneration++;
  const chk=t.checkpoint||{};
  const paths=chk.affected_paths||[];
  const evs=chk.evidence_ids||[];
  const risk=t.contract?.risk_profile||'normal';
  const created=t.created_at?new Date(t.created_at*1000).toLocaleString():'—';
  const updated=t.updated_at?new Date(t.updated_at*1000).toLocaleString():'—';

  let criteriaHtml='';
  if(criteria.length){
    criteriaHtml='<div class="modal-checklist">'+criteria.map((c,i)=>`
      <div class="modal-checklist-item task-criterion-row" data-criterion-index="${i}">
        <span class="badge-status badge-waiting" style="font-size:9px">#${i+1}</span>
        <span class="item-text"><b>${esc(c)}</b></span>
        <span class="task-criterion-state is-unavailable" role="status">Checking…</span>
      </div>
    `).join('')+'</div>';
  } else {
    criteriaHtml='<div class="muted tiny">No acceptance criteria defined for this task.</div>';
  }

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">DURABLE AGENT TASK</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <span class="mono">${esc(t.task_id)}</span>
            <button class="copy-btn" onclick="copyText(${escJs(t.task_id)},this)">Copy ID</button>
          </h2>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <span class="badge-status ${cls}">${esc(st.toUpperCase())}</span>
          <span class="chip">${esc(t.contract?.scope||'task')}</span>
          <span class="chip ${risk==='high'?'bad-t':risk==='medium'?'warn-t':'ok'}">${esc(risk)} risk</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Created: ${created} · Updated: ${updated} · Actor: <b>${esc(t.actor||'system')}</b></div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Goal &amp; Objective</span></div>
        <div class="modal-card-body">
          <div style="font-size:13px;font-weight:500;line-height:1.4">${esc(goal)}</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head">
          <span>Acceptance Criteria <span class="tiny" style="margin-left:5px">(${criteria.length})</span></span>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end">
            <span id="taskCriteriaSummary" class="task-criteria-summary" aria-live="polite">Checking receipts…</span>
            <button class="action-btn-sm" id="taskCriteriaRefresh" onclick="checkTaskCompletionGate(${escJs(t.task_id)},${escJs(st)})">Refresh status</button>
          </div>
        </div>
        <div class="modal-card-body">
          ${criteriaHtml}
          <div id="taskGateResult" class="task-gate-result" role="status" aria-live="polite">Checking verification receipts…</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Current Checkpoint &amp; Progress</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Current Phase</div><div><b>${esc(chk.phase||'planned')}</b></div>
            <div>Next Action</div><div class="mono tiny">${esc(chk.next_action||'none')}</div>
            <div>Affected Paths</div><div>${paths.length?paths.map(p=>`<span class="chip mono">${esc(p)}</span>`).join(' '):'<span class="muted">none</span>'}</div>
            <div>Evidence IDs</div><div>${evs.length?evs.map(e=>`<span class="chip">${esc(e)}</span>`).join(' '):'<span class="muted">none</span>'}</div>
          </div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Task Event Trajectory</span></div>
        <div class="modal-card-body">
          <div id="trajEventStatus" class="tiny muted">Loading task events…</div>
          <div id="trajEventGaps" class="tiny warn-t" style="margin-top:5px"></div>
          <div id="trajEventList" style="margin-top:6px"></div>
          <button id="trajEventPager" class="btn" data-load-traj-more hidden style="margin-top:8px">${trajectoryPageError?'Retry page':'Load next events'}</button>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Task Lifecycle &amp; Controls</span></div>
        <div class="modal-card-body">
          ${terminal?`
          <div class="task-terminal-state ${st==='completed'?'is-completed':'is-failed'}" role="status">
            <strong>${st==='completed'?'Completed':'Failed'}</strong>
            <span>This task is in a terminal state. Lifecycle controls are unavailable.</span>
          </div>
          `:`
          <div class="modal-actions-bar">
            <button class="btn ok" onclick="completeTaskAction(${escJs(t.task_id)})">✓ Complete Task</button>
            <button class="btn bad" onclick="showFailTaskInput()">✗ Mark Failed</button>
            <div style="display:flex;align-items:center;gap:6px;margin-left:auto">
              <label class="tiny muted" for="taskTransStatus">Status:</label>
              <select id="taskTransStatus" style="background:#172233;color:var(--fg);border:1px solid #2e405a;border-radius:5px;padding:4px 8px;font-size:11px">
                <option value="active" ${st==='active'?'selected':''}>active</option>
                <option value="verifying" ${st==='verifying'?'selected':''}>verifying</option>
                <option value="blocked" ${st==='blocked'?'selected':''}>blocked</option>
                <option value="planned" ${st==='planned'?'selected':''}>planned</option>
              </select>
              <button class="btn" onclick="transitionTaskAction(${escJs(t.task_id)})">Apply</button>
            </div>
          </div>
          <div id="failTaskBox" style="display:none;margin-top:10px;padding:8px;background:#181216;border:1px solid #7f1d1d;border-radius:6px">
            <label for="failTaskReason" style="font-size:11px;font-weight:600;display:block;margin-bottom:4px;color:#fca5a5">Failure Reason *</label>
            <div style="display:flex;gap:6px">
              <input type="text" id="failTaskReason" placeholder="Why did this task fail?" style="flex:1;background:#0d1219;border:1px solid #2d3f56;color:var(--fg);padding:4px 8px;border-radius:4px;font-size:11px">
              <button class="btn bad" onclick="submitFailTask(${escJs(t.task_id)})">Confirm Fail</button>
              <button class="btn" onclick="$('failTaskBox').style.display='none'">Cancel</button>
            </div>
          </div>
          <div id="taskActionStatus" class="tiny" style="margin-top:8px"></div>
          `}
        </div>
      </div>

      <details class="raw-json"><summary>Raw Task JSON</summary><pre>${esc(JSON.stringify(t,null,2))}</pre></details>
    </div>
  `;
  const trajectoryPager=$('trajEventPager');
  if(trajectoryPager)trajectoryPager.onclick=()=>loadTaskTrajectory(trajectoryTaskId);
  void loadTaskTrajectory(trajectoryTaskId);
  checkTaskCompletionGate(t.task_id,st);
}

async function checkTaskCompletionGate(taskId,status=''){
  const out=$('taskGateResult');
  if(!out)return;
  const taskState=activeTaskInspectorState;
  if(!taskState||taskState.taskId!==String(taskId))return;
  const summary=$('taskCriteriaSummary');
  const refresh=$('taskCriteriaRefresh');
  if(refresh){refresh.disabled=true;refresh.textContent='Checking…';}
  if(summary){summary.textContent='Checking receipts…';summary.className='task-criteria-summary';}
  out.className='task-gate-result';
  out.textContent='Checking verification receipts…';
  try{
    const res=await post('/api/agent-state/verification',{action:'completion',task_id:taskId});
    if(activeTaskInspectorState!==taskState)return;
    if(!res||!res.completion)throw new Error(res?.error||'Completion status was not returned.');
    const c=res.completion;
    const satisfied=new Set(Array.isArray(c.satisfied_criteria)?c.satisfied_criteria.map(String):[]);
    const unsatisfied=new Set(Array.isArray(c.unsatisfied_criteria)?c.unsatisfied_criteria.map(String):[]);
    const stale=new Set(Array.isArray(c.stale_criteria)?c.stale_criteria.map(String):[]);
    const receiptByCriterion=new Map((Array.isArray(c.receipts)?c.receipts:[]).filter(r=>r&&typeof r==='object'&&r.criterion!==undefined).map(r=>[String(r.criterion),r]));
    const rows=Array.from(document.querySelectorAll('.task-criterion-row'));
    const total=rows.length;
    let passedCount=0,failedCount=0,staleCount=0,pendingCount=0,unavailableCount=0;
    rows.forEach(row=>{
      const criterion=taskState.criteria[Number(row.dataset.criterionIndex)];
      const key=criterion===undefined?'':String(criterion);
      const ok=criterion!==undefined&&satisfied.has(key);
      const expired=!ok&&stale.has(key);
      const failed=!ok&&!expired&&receiptByCriterion.get(key)?.passed===false;
      const pending=!ok&&!expired&&!failed&&criterion!==undefined&&unsatisfied.has(key);
      const unavailable=!ok&&!expired&&!failed&&!pending;
      if(ok)passedCount++;
      if(expired)staleCount++;
      if(failed)failedCount++;
      if(pending)pendingCount++;
      if(unavailable)unavailableCount++;
      const state=row.querySelector('.task-criterion-state');
      if(!state)return;
      state.className='task-criterion-state '+(ok?'is-verified':(expired?'is-stale':(failed?'is-failed':(pending?'is-pending':'is-unavailable'))));
      state.textContent=ok?'✓ Verified':(expired?'Receipt expired':(failed?'✗ Failed':(pending?'! Pending':'Status unavailable')));
      state.title=ok?'A valid verification receipt exists.':(expired?'The verification receipt has expired.':(failed?'The latest verification receipt failed.':(pending?'No valid verification receipt exists yet.':'Verification status could not be determined.')));
    });
    const detailCounts=[failedCount?`${failedCount} failed`:'',staleCount?`${staleCount} expired`:'',pendingCount?`${pendingCount} pending`:'',unavailableCount?`${unavailableCount} unavailable`:'' ].filter(Boolean);
    if(summary){
      summary.textContent=total?`${passedCount}/${total} verified${detailCounts.length?' · '+detailCounts.join(' · '):''}`:'No criteria';
      summary.className='task-criteria-summary '+(failedCount?'is-failed':(total&&passedCount===total?'is-verified':(pendingCount||staleCount?'is-pending':'')));
    }
    status=String(status||taskState.status||'').toLowerCase();
    if(!total){
      out.className='task-gate-result';
      out.textContent='No acceptance criteria are defined for this task.';
    }else if(status==='completed'&&(c.complete!==true||passedCount<total)){
      out.className='task-gate-result is-warning';
      if(passedCount<total){
        out.innerHTML=`<b>Completed status needs review.</b> ${passedCount} of ${total} criteria are verified${detailCounts.length?'; '+detailCounts.join(', '):''}.`;
      }else{
        out.innerHTML=`<b>Completed status needs review.</b> All ${total} criteria are verified, but the completion gate reports incomplete.`;
      }
    }else if(status==='completed'){
      out.className='task-gate-result is-ok';
      out.innerHTML=`<b>Task completed.</b> All ${total} acceptance criteria have valid receipts.`;
    }else if(status==='failed'){
      out.className='task-gate-result is-failed';
      out.innerHTML=`<b>Task failed.</b> ${passedCount} of ${total} criteria have valid receipts.`;
    }else if(c.complete===true&&passedCount===total){
      out.className='task-gate-result is-ok';
      out.innerHTML=`<b>Completion gate passed.</b> All ${total} criteria have valid receipts.`;
    }else if(passedCount===total&&c.complete!==true){
      out.className='task-gate-result is-warning';
      out.innerHTML=`<b>Completion gate needs review.</b> All ${total} criteria are verified, but the gate reports incomplete.`;
    }else{
      out.className='task-gate-result is-warning';
      out.innerHTML=`<b>Completion gate pending.</b> ${passedCount} of ${total} criteria verified${detailCounts.length?'; '+detailCounts.join(', '):''}.`;
    }
  }catch(e){
    if(activeTaskInspectorState!==taskState)return;
    const rows=Array.from(document.querySelectorAll('.task-criterion-row'));
    rows.forEach(row=>{
      const state=row.querySelector('.task-criterion-state');
      if(state){state.className='task-criterion-state is-unavailable';state.textContent='Status unavailable';}
    });
    if(summary){summary.textContent='Status unavailable';summary.className='task-criteria-summary';}
    out.className='task-gate-result is-warning';
    out.textContent='Could not load verification receipts. Refresh status to try again.';
  }finally{
    if(refresh){refresh.disabled=false;refresh.textContent='Refresh status';}
  }
}

function showFailTaskInput(){
  const b=$('failTaskBox');
  if(b){b.style.display='block';$('failTaskReason')?.focus()}
}

async function submitFailTask(taskId){
  const reason=$('failTaskReason')?.value?.trim();
  if(!reason)return;
  const statusEl=$('taskActionStatus');
  if(statusEl)statusEl.textContent='Failing task…';
  try{
    const res=await post('/api/agent-state/tasks',{action:'fail',task_id:taskId,reason:reason});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="bad-t">Task marked as failed.</span>';
      await loadAgentOsView();
      if(res.task)renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to fail')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

async function completeTaskAction(taskId){
  const statusEl=$('taskActionStatus');
  if(statusEl)statusEl.textContent='Checking criteria receipts and completing task…';
  try{
    const res=await post('/api/agent-state/tasks',{action:'complete',task_id:taskId,reason:'Completed via dashboard inspector'});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="ok">✓ Task marked completed.</span>';
      await loadAgentOsView();
      if(res.task)renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to complete')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

async function transitionTaskAction(taskId){
  const sel=$('taskTransStatus');
  if(!sel)return;
  const target=sel.value;
  const statusEl=$('taskActionStatus');
  if(statusEl)statusEl.textContent='Transitioning to '+target+'…';
  try{
    const res=await post('/api/agent-state/tasks',{action:'transition',task_id:taskId,status:target,reason:'Transitioned via dashboard inspector'});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="ok">✓ Transitioned to '+esc(target)+'.</span>';
      await loadAgentOsView();
      if(res.task)renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Transition failed')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openCreateTaskModal(){
  if($('modalTitle'))$('modalTitle').textContent='Create Durable Agent Task';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitCreateTask(event)">
        <div class="form-group">
          <label for="newTaskRoot">Repository Root *</label>
          <input type="text" id="newTaskRoot" list="worktreeRoots" required placeholder="Select or enter repository root" value="${esc($('agentOsRoot')?.value?.trim()||$('agentOsRepoSelect')?.value?.trim()||'')}">
          <span class="form-hint">Physical repository root bound to the task.</span>
        </div>
        <div class="form-group">
          <label for="newTaskGoal">Task Goal *</label>
          <textarea id="newTaskGoal" rows="3" required placeholder="Describe the goal and expected outcome..." autofocus></textarea>
          <span class="form-hint">A clear specification of the objective.</span>
        </div>
        <div class="form-group">
          <label for="newTaskCriteria">Acceptance Criteria</label>
          <textarea id="newTaskCriteria" rows="3" placeholder="Criterion 1&#10;Criterion 2&#10;Criterion 3"></textarea>
          <span class="form-hint">One criterion per line, or comma-separated.</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="form-group">
            <label for="newTaskScope">Scope</label>
            <select id="newTaskScope">
              <option value="task" selected>Task</option>
              <option value="session">Session</option>
              <option value="repository">Repository</option>
              <option value="system">System</option>
            </select>
          </div>
          <div class="form-group">
            <label for="newTaskRisk">Risk Profile</label>
            <select id="newTaskRisk">
              <option value="low">Low Risk</option>
              <option value="normal" selected>Normal</option>
              <option value="high">High Risk</option>
            </select>
          </div>
        </div>
        <div id="createTaskStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">Create Task</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('newTaskGoal')?.focus(),50);
}

async function submitCreateTask(e){
  e.preventDefault();
  const goal=$('newTaskGoal')?.value?.trim();
  if(!goal)return;
  const root=$('newTaskRoot')?.value?.trim()||$('agentOsRoot')?.value?.trim()||$('agentOsRepoSelect')?.value?.trim();
  const rawCrit=$('newTaskCriteria')?.value||'';
  const criteria=rawCrit.split(/[\n,]/).map(s=>s.trim()).filter(Boolean);
  const scope=$('newTaskScope')?.value||'task';
  const risk=$('newTaskRisk')?.value||'normal';
  const statusEl=$('createTaskStatus');
  if(statusEl)statusEl.textContent='Creating task…';

  try{
    const payload={
      action:'create',
      contract:{goal,acceptance_criteria:criteria,scope,risk_profile:risk}
    };
    if(root)payload.root=root;
    const res=await post('/api/agent-state/tasks',payload);
    if(res.success&&res.task){
      await loadAgentOsView();
      renderTaskModal(res.task);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Creation failed')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }
}

function renderMemoryModal(m){
  const key=m.key||'—';
  const scope=m.scope||'task';
  const kind=m.kind||'fact';
  const conf=m.confidence!==undefined?Math.round(m.confidence*100):100;
  const source=m.source||'agent';
  const created=m.created_at?new Date(m.created_at*1000).toLocaleString():'—';
  const updated=m.updated_at?new Date(m.updated_at*1000).toLocaleString():'—';

  let valStr='';
  if(typeof m.value==='object'){
    try{valStr=JSON.stringify(m.value,null,2)}catch{valStr=String(m.value)}
  }else{
    valStr=String(m.value??'');
  }

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">AGENT MEMORY ENTRY</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <strong>${esc(key)}</strong>
            <button class="copy-btn" onclick="copyText(${escJs(key)},this)">Copy Key</button>
          </h2>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <span class="chip ok">${esc(scope)}</span>
          <span class="chip">${esc(kind)}</span>
          <span class="chip ${conf>=80?'ok':'warn-t'}">${conf}% confidence</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Source: <b>${esc(source)}</b> · Recorded: ${created} · Updated: ${updated}</div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head">
          <span>Memory Value</span>
          <button class="copy-btn" onclick="copyText(${escJs(valStr)},this)">Copy Value</button>
        </div>
        <div class="modal-card-body">
          <pre class="code-box" style="margin:0">${esc(valStr)}</pre>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Actions</span></div>
        <div class="modal-card-body">
          <div class="modal-actions-bar" id="memActionRow">
            <button class="btn bad" onclick="$('confirmDelMemBox').style.display='flex';$('memActionRow').style.display='none'">🗑 Delete Memory</button>
          </div>
          <div id="confirmDelMemBox" style="display:none;align-items:center;gap:8px;padding:6px 10px;background:#1a1015;border:1px solid #7f1d1d;border-radius:4px">
            <span class="tiny" style="color:#fca5a5">Delete memory <b>${esc(m.key)}</b> (${esc(m.scope)})?</span>
            <button class="btn bad" onclick="deleteMemoryAction(${escJs(m.key)},${escJs(m.scope)})">Confirm Delete</button>
            <button class="btn" onclick="$('confirmDelMemBox').style.display='none';$('memActionRow').style.display='flex'">Cancel</button>
          </div>
          <div id="memoryActionStatus" class="tiny" style="margin-top:8px"></div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Memory JSON</summary><pre>${esc(JSON.stringify(m,null,2))}</pre></details>
    </div>
  `;
}

async function deleteMemoryAction(key,scope){
  const statusEl=$('memoryActionStatus');
  if(statusEl)statusEl.textContent='Deleting memory…';
  try{
    const res=await post('/api/agent-state/memory',{action:'delete',key:key,scope:scope});
    if(res.success){
      if(statusEl)statusEl.innerHTML='<span class="ok">✓ Memory deleted.</span>';
      await loadAgentOsView();
      setTimeout(()=>$('modalClose')?.click(),700);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to delete')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openRecordMemoryModal(){
  if($('modalTitle'))$('modalTitle').textContent='Record Agent Memory';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitRecordMemory(event)">
        <div class="form-group">
          <label for="newMemKey">Memory Key *</label>
          <input type="text" id="newMemKey" required placeholder="e.g. auth_service_port or prefer_relative_imports" autofocus>
          <span class="form-hint">Unique lookup key within the chosen scope.</span>
        </div>
        <div class="form-group">
          <label for="newMemVal">Memory Value *</label>
          <textarea id="newMemVal" rows="4" required placeholder="Text value or JSON object..."></textarea>
          <span class="form-hint">String value, fact description, or JSON payload.</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="form-group">
            <label for="newMemScope">Scope</label>
            <select id="newMemScope">
              <option value="task">Task</option>
              <option value="session">Session</option>
              <option value="repository" selected>Repository</option>
              <option value="user">User</option>
              <option value="system">System</option>
            </select>
          </div>
          <div class="form-group">
            <label for="newMemKind">Kind</label>
            <select id="newMemKind">
              <option value="fact" selected>Fact</option>
              <option value="decision">Decision</option>
              <option value="preference">Preference</option>
              <option value="pattern">Pattern</option>
              <option value="negative_knowledge">Negative Knowledge</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label for="newMemTaskId">Task ID (required for Task scope)</label>
          <input id="newMemTaskId" placeholder="task_…">
          <span class="form-hint">Use a task from the selected repository. Other scopes do not use this field.</span>
        </div>
        <div id="recordMemStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">Record Memory</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('newMemKey')?.focus(),50);
}

async function submitRecordMemory(e){
  e.preventDefault();
  const key=$('newMemKey')?.value?.trim();
  const rawVal=$('newMemVal')?.value?.trim();
  if(!key||rawVal===undefined)return;
  let val=rawVal;
  try{val=JSON.parse(rawVal)}catch{}
  const scope=$('newMemScope')?.value||'repository';
  const kind=$('newMemKind')?.value||'fact';
  const statusEl=$('recordMemStatus');
  const taskId=$('newMemTaskId')?.value?.trim();
  if(scope==='task'&&!taskId){if(statusEl)statusEl.textContent='Task ID is required for Task scope.';return;}
  if(statusEl)statusEl.textContent='Saving memory…';

  try{
    const res=await post('/api/agent-state/memory',{
      action:'record',
      key:key,
      value:val,
      scope:scope,
      ...(scope==='task'?{task_id:taskId}:{}),
      kind:kind,
      confidence:1.0
    });
    if(res.success){
      await loadAgentOsView();
      renderMemoryModal(res.record||{key,value:val,scope,kind,confidence:1.0});
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to record')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }
}

function renderIncidentModal(i){
  const id=i.incident_id||'—';
  const errorClass=i.error_class||'Error';
  const op=i.operation_class||i.outcome?.tool_name||'agent';
  const msg=i.redacted_message||i.message||'—';
  const cause=i.root_cause||'—';
  const fix=i.verified_fix||'—';
  const status=String(i.status||(i.verified_fix?'resolved':'unresolved'));
  const isResolved=status==='resolved';

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">NEGATIVE KNOWLEDGE / ANTI-PATTERN</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <span class="badge-status badge-error">${esc(errorClass)}</span>
            <span class="mono tiny muted">#${esc(id)}</span>
          </h2>
        </div>
        <div>
            <span class="badge-status ${isIgnored?'badge-waiting':isResolved?'badge-complete':'badge-waiting'}">${isIgnored?'IGNORED':isResolved?'✓ RESOLVED WITH FIX':'UNRESOLVED'}</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Tool/Operation: <b>${esc(op)}</b></div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Failure Description</span></div>
        <div class="modal-card-body">
          <div style="font-family:ui-monospace,monospace;font-size:11px;color:#fca5a5">${esc(msg)}</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Identified Root Cause</span></div>
        <div class="modal-card-body">
          <div style="font-size:12px">${esc(cause)}</div>
        </div>
      </div>

      <div class="modal-card" style="border-color:${isResolved?'var(--ok)':'#334155'}">
        <div class="modal-card-head" style="background:${isResolved?'#0c2e1f':'#131d2b'}">
          <span class="${isResolved?'ok':''}">Verified Prevention Rule / Fix</span>
          ${fix!=='—'?`<button class="copy-btn" onclick="copyText(${escJs(fix)},this)">Copy Fix</button>`:''}
        </div>
        <div class="modal-card-body">
          <div style="font-size:12px;font-weight:500;color:${isResolved?'#86efac':'var(--fg)'}">${esc(fix)}</div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Incident JSON</summary><pre>${esc(JSON.stringify(i,null,2))}</pre></details>
    </div>
  `;
}

function openRecordIncidentModal(){
  if($('modalTitle'))$('modalTitle').textContent='Record Failure Anti-Pattern';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitRecordIncident(event)">
        <div class="form-group">
          <label for="newIncClass">Error Class *</label>
          <input type="text" id="newIncClass" required value="LogicError" placeholder="e.g. StaleCacheError, PolicyRejection" autofocus>
          <span class="form-hint">Categorization for fingerprint matching.</span>
        </div>
        <div class="form-group">
          <label for="newIncMsg">Failure Description</label>
          <textarea id="newIncMsg" rows="2" placeholder="What symptom or exception occurred?"></textarea>
        </div>
        <div class="form-group">
          <label for="newIncCause">Root Cause</label>
          <textarea id="newIncCause" rows="2" placeholder="Why did the failure happen?"></textarea>
        </div>
        <div class="form-group">
          <label for="newIncFix">Verified Fix / Prevention Rule *</label>
          <textarea id="newIncFix" rows="3" required placeholder="Exact rule or guard to prevent this error from recurring"></textarea>
          <span class="form-hint">Stored in persistent negative knowledge to guide future agent runs.</span>
        </div>
        <div id="recordIncStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn warn">Record Anti-Pattern</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('newIncClass')?.focus(),50);
}

async function submitRecordIncident(e){
  e.preventDefault();
  const errorClass=$('newIncClass')?.value?.trim()||'LogicError';
  const msg=$('newIncMsg')?.value?.trim()||'';
  const rootCause=$('newIncCause')?.value?.trim()||'';
  const verifiedFix=$('newIncFix')?.value?.trim()||'';
  const statusEl=$('recordIncStatus');
  if(statusEl)statusEl.textContent='Saving anti-pattern…';

  try{
    const res=await post('/api/agent-state/incidents',{
      action:'record',
      error_class:errorClass,
      message:msg,
      root_cause:rootCause,
      verified_fix:verifiedFix
    });
    if(res.success){
      await loadAgentOsView();
      renderIncidentModal(res.incident||{incident_id:'new',error_class:errorClass,redacted_message:msg,root_cause:rootCause,verified_fix:verifiedFix});
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to record')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }
}

function openCleanupModal(){
  if($('modalTitle'))$('modalTitle').textContent='Cleanup Stale Agent OS State';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Agent OS Maintenance</span></div>
        <div class="modal-card-body" style="font-size:12px;line-height:1.5">
          <p>Running bounded state cleanup will prune:</p>
          <ul style="margin:6px 0;padding-left:20px;color:var(--muted)">
            <li>Expired SSE live events older than the retention threshold.</li>
            <li>Completed and abandoned task checkpoints beyond compaction limit.</li>
            <li>Expired memory entries outside active TTL.</li>
          </ul>
          <p style="margin-bottom:0">Active tasks, verified anti-patterns and non-expired memories will <b>not</b> be touched.</p>
        </div>
      </div>
      <div id="cleanupStatus" class="tiny"></div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Cancel</button>
        <button class="btn warn" onclick="executeCleanupAction()">🧹 Execute Cleanup</button>
      </div>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
}

async function executeCleanupAction(){
  const statusEl=$('cleanupStatus');
  if(statusEl)statusEl.textContent='Running state cleanup…';
  try{
    const res=await post('/api/agent-state/cleanup',{});
    $('modalBody').innerHTML=`
      <div class="modal-body-wrap">
        <div class="diag-banner ok">
          <span style="font-size:16px">✅</span>
          <div>
            <b>Agent OS State Cleanup Completed</b>
            <div class="tiny" style="margin-top:8px">${renderAny(res)}</div>
          </div>
        </div>
        <div class="modal-actions-bar" style="justify-content:flex-end">
          <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
        </div>
      </div>
    `;
    await loadAgentOsView();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function renderLiveStreamModal(ev){
  const seq=ev.seq!==undefined?ev.seq:(ev.event_id||'—');
  const kind=ev.kind||ev.event_type||'event';
  const actor=ev.actor||ev.agent||'system';
  const timestamp=ev.timestamp||ev.created_at||0;
  const dt=timestamp?new Date(timestamp*1000).toLocaleString():'—';
  const streamId=ev.stream_id||'—';
  const p=ev.payload||ev;
  let taskId=p.task_id||(p.task&&p.task.task_id)||ev.task_id||'';

  let payloadStr='';
  try{payloadStr=JSON.stringify(p,null,2)}catch{payloadStr=String(p)}

  const dur=ev.duration_ms!==undefined?` · Duration: <b>${ms(ev.duration_ms)}</b>`:'';
  const status=ev.success!==undefined?` · Status: <span class="${ev.success?'ok':'bad-t'}"><b>${ev.success?'SUCCESS':'FAILURE'}</b></span>`:'';
  const action=ev.action?` · Action: <span class="mono"><b>${esc(ev.action)}</b></span>`:'';
  const stage=ev.stage?` · Stage: <span class="chip">${esc(ev.stage)}</span>`:'';
  const model=ev.model?` · Model: <span class="chip ok">${esc(ev.model)}</span>`:'';

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">LIVE EVENT INSPECTOR</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <span class="mono">Seq #${esc(seq)}</span>
            <span class="chip">${esc(kind)}</span>
          </h2>
        </div>
        <div class="tiny muted">
          Stream: <span class="mono">${esc(streamId)}</span>
        </div>
      </div>
      <div class="tiny muted" style="margin-top:8px">Actor: <b>${esc(actor)}</b> · Time: ${dt}${action}${stage}${model}${dur}${status}</div>
    </div>
    <div class="modal-body-wrap">
      ${taskId?`
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#101a26;border:1px solid #1e354d;border-radius:6px">
          <span>Related Task: <b class="mono">${esc(taskId)}</b></span>
          <button class="btn ok" onclick="openTaskById(${escJs(taskId)})">↗ Open Task Inspector</button>
        </div>
      `:''}

      <div class="modal-card">
        <div class="modal-card-head">
          <span>Event Payload</span>
          <button class="copy-btn" onclick="copyText(${escJs(payloadStr)},this)">Copy Payload</button>
        </div>
        <div class="modal-card-body">
          <pre class="code-box" style="margin:0">${esc(payloadStr)}</pre>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Event Object</summary><pre>${esc(JSON.stringify(ev,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

async function openTaskById(taskId){
  try{
    const res=await post('/api/agent-state/tasks',{action:'get',task_id:taskId});
    if(res.success&&res.task){
      renderTaskModal(res.task);
    }else{
      alert('Task not found: '+taskId);
    }
  }catch(e){
    alert('Error loading task: '+e.message);
  }
}

function renderProjectModal(p){
  const state=projectState(p);
  const isComplete=state==='ready';
  const overall=Math.max(0,Math.min(100,Number(p.overall_progress_pct||0)));
  const tot=Math.max(1,Number(p.files||0));
  const ragFiles=Number(p.rag_files||0);
  const cards=Number(p.file_cards||0);
  const astSymbols=Number(p.ast_symbols||p.symbols_count||0);
  const badge={
    running:['badge-running','Running'],
    waiting:['badge-waiting','Waiting'],
    paused:['badge-paused','Paused'],
    error:['badge-error','Error'],
    ready:['badge-complete','Ready']
  }[state]||['badge-waiting','Queued'];

  const stepperHtml=renderStepper(p.phase_index||1,isComplete,state);

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">PREPROCESSED REPOSITORY WORKSPACE</div>
          <h2 style="margin:2px 0 0;font-size:16px;display:flex;align-items:center;gap:8px">
            <b>${esc(p.project)}</b>
            <button class="copy-btn" onclick="copyText(${escJs(p.root)},this)">Copy Path</button>
          </h2>
          <div class="tiny mono muted" style="margin-top:3px">${esc(p.root)}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="badge-status ${badge[0]}">${badge[1]}</span>
          <span class="chip">${overall}% synchronized</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>13-Phase Pipeline Progression</span></div>
        <div class="modal-card-body">
          ${stepperHtml}
          <div class="bar" style="margin-top:10px"><i style="width:${overall}%;background:${state==='error'?'var(--bad)':isComplete?'var(--ok)':'var(--accent)'}"></i></div>
          <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px">
            <span class="tiny muted">Phase: <b>${esc(p.phase||'Inventory')}</b></span>
            <span class="tiny muted">${esc(p.active_detail||(isComplete?'All phases synchronized':'Processing pipeline'))}</span>
          </div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Index Breakdown &amp; Diagnostics</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Total Indexed Files</div><div><b>${n(p.files||0)}</b> files (${n(p.dirty_files||0)} modified)</div>
            <div>AST Code Symbols</div><div><b>${n(astSymbols)}</b> declarations indexed</div>
            <div>RAG Vector Embeddings</div><div><b>${n(ragFiles)}</b> / ${n(tot)} files (${Math.round(ragFiles/tot*100)}%)</div>
            <div>Semantic Context Cards</div><div><b>${n(cards)}</b> / ${n(tot)} files (${Math.round(cards/tot*100)}%)</div>
            <div>Last Activity Checkpoint</div><div>${p.updated_at?new Date(p.updated_at*1000).toLocaleString():'—'}</div>
          </div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span style="display:flex;align-items:center;gap:6px">⚙️ Project Settings &amp; Configuration (.local-ai.toml)</span></div>
        <div class="modal-card-body" id="modalProjectSettingsBody">
          <div class="tiny muted">Loading project settings…</div>
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Workspace Controls</span></div>
        <div class="modal-card-body">
          <div class="modal-actions-bar">
            <button class="btn" onclick="projectAction(${escJs(p.root)},'${state==='paused'?'resume':'pause'}');$('modalClose')?.click()">${state==='paused'?'▶ Resume Preprocessing':'⏸ Pause Preprocessing'}</button>
            <button class="btn ok" onclick="projectAction(${escJs(p.root)},'refresh');$('modalClose')?.click()">↻ Force Re-scan</button>
            <button class="btn" onclick="exportBundle(${escJs(p.root)})">📦 Export Bundle</button>
            <button class="btn bad" style="margin-left:auto" onclick="deleteProjectDialog(${escJs(p.root)},${escJs(p.project)})">🗑 Unregister / Delete</button>
          </div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Project Metadata</summary><pre>${esc(JSON.stringify(p,null,2))}</pre></details>
    </div>
  `;
  loadProjectSettings(p.root);
}

async function loadProjectSettings(root){
  const body=$('modalProjectSettingsBody');
  if(!body)return;
  try{
    const d=await fetchDashboardJson('/api/project/config?root='+encodeURIComponent(root));
    if(!d||!d.success){
      body.innerHTML='<div class="tiny muted">Default repository settings active (no project overrides).</div>';
      return;
    }
    const s=d.settings||{};
    const hasExcludes=(s.exclude_paths||[]).length>0;
    const hasForce=(s.force_include_paths||[]).length>0;
    const hasExts=(s.custom_extensions||[]).length>0;
    const hasSkip=(s.skip_phases||[]).length>0;
    const hasCmds=Object.keys(s.commands||{}).length>0;
    const sources=(d.sources||[]).join(', ');

    let html=`<div class="kv" style="padding:0">
      <div>Config Source</div><div><b>${esc(d.config_exists?'.local-ai.toml (project active)':(d.sources||[]).join(', ')||'defaults')}</b></div>
      <div>Custom Extensions</div><div>${hasExts?s.custom_extensions.map(x=>`<span class="chip">${esc(x)}</span>`).join(' '):'<span class="tiny muted">defaults</span>'}</div>
      <div>Excluded Paths</div><div>${hasExcludes?s.exclude_paths.map(x=>`<span class="chip bad-t">${esc(x)}</span>`).join(' '):'<span class="tiny muted">none</span>'}</div>
      <div>Force Included</div><div>${hasForce?s.force_include_paths.map(x=>`<span class="chip ok">${esc(x)}</span>`).join(' '):'<span class="tiny muted">none</span>'}</div>
      <div>Skipped Phases</div><div>${hasSkip?s.skip_phases.map(x=>`<span class="chip warn-t">${esc(x)}</span>`).join(' '):'<span class="tiny muted">none (all 13 phases enabled)</span>'}</div>
      <div>Defined Commands</div><div>${hasCmds?Object.entries(s.commands).map(([k,v])=>`<code>${esc(k)}</code>: <code>${esc(Array.isArray(v)?v.join(' '):String(v))}</code>`).join('<br>'):'<span class="tiny muted">none</span>'}</div>
      <div>Max File Size</div><div>${s.max_file_size_bytes?n(s.max_file_size_bytes)+' bytes':'<span class="tiny muted">default (512 KB)</span>'}</div>
    </div>`;
    body.innerHTML=html;
  }catch(e){
    body.innerHTML='<div class="tiny muted">Settings: using default repository configuration.</div>';
  }
}

function openRegisterProjectModal(){
  if($('modalTitle'))$('modalTitle').textContent='Register Project for Preprocessing';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitRegisterProject(event)">
        <div class="form-group">
          <label for="regProjRoot">Repository Root Path *</label>
          <input type="text" id="regProjRoot" required placeholder="C:/Projects/my-app or /home/user/repo" autofocus>
          <span class="form-hint">Absolute directory path to repository.</span>
        </div>
        <div style="margin-top:6px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="regProjForce">
            <span>Perform initial force re-scan for all files</span>
          </label>
          <div class="tiny muted" style="margin-left:22px;margin-top:3px">If unchecked, utilizes incremental fast sync and cached hashes.</div>
        </div>
        <div id="regProjStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose')?.click()">Cancel</button>
          <button type="submit" class="btn ok">+ Register Project</button>
        </div>
      </form>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  setTimeout(()=>$('regProjRoot')?.focus(),50);
}

async function submitRegisterProject(e){
  e.preventDefault();
  const root=$('regProjRoot')?.value?.trim();
  if(!root)return;
  const force=$('regProjForce')?.checked||false;
  const statusEl=$('regProjStatus');
  if(statusEl)statusEl.textContent='Registering project…';

  try{
    const r=await post('/api/preprocess',{root,action:force?'refresh':'register'});
    if(r.success){
      $('modalClose')?.click();
      await pollStatus();
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(r.error||'Failed')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }
}

function openDeleteProjectModal(root,name){
  if($('modalTitle'))$('modalTitle').textContent='Unregister Project';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <div style="font-size:13px">
        Unregister project <b>${esc(name)}</b>?
        <div class="tiny mono muted" style="margin-top:2px">${esc(root)}</div>
      </div>

      <div style="display:flex;flex-direction:column;gap:8px;margin-top:8px">
        <label class="modal-radio-option">
          <input type="radio" name="deleteOption" id="delOpt1" value="unregister" checked>
          <div>
            <div style="font-weight:600;font-size:12px">Option 1: Unregister Only (Recommended)</div>
            <div class="tiny muted" style="margin-top:2px">Stops background syncing and removes from dashboard. Preserves content caches so re-registering is instant.</div>
          </div>
        </label>

        <label class="modal-radio-option" style="border-color:#7f1d1d">
          <input type="radio" name="deleteOption" id="delOpt2" value="purge">
          <div>
            <div style="font-weight:600;font-size:12px;color:var(--bad)">Option 2: Purge All Index Data</div>
            <div class="tiny muted" style="margin-top:2px">Permanently deletes all AST symbols, RAG embeddings and cache entries for this workspace.</div>
          </div>
        </label>
      </div>

      <div id="delProjStatus" class="tiny"></div>

      <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
        <button class="btn" onclick="$('modalClose')?.click()">Cancel</button>
        <button class="btn bad" id="confirmDeleteProjectBtn" onclick="confirmDeleteProject(${escJs(root)})">Confirm Unregister / Purge</button>
      </div>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
  const confirmBtn=$('confirmDeleteProjectBtn');
  if(confirmBtn)confirmBtn.onclick=()=>confirmDeleteProject(root);
}

async function confirmDeleteProject(root){
  const purge=$('delOpt2')?.checked||false;
  const statusEl=$('delProjStatus');
  if(statusEl)statusEl.textContent='Processing…';
  try{
    const r=await post('/api/preprocess',{root,action:'unregister',purge_data:purge});
    if(r && r.success===false){
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(r.error||'Failed to unregister')}</span>`;
      return;
    }
    $('modalClose')?.click();
    await pollStatus();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openCleanMissingModal(){
  if($('modalTitle'))$('modalTitle').textContent='Prune Missing Worktrees';
  if($('modalLive'))$('modalLive').textContent='';
  if($('modalBody'))$('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Clean Missing Worktree Directories</span></div>
        <div class="modal-card-body" style="font-size:12px;line-height:1.4">
          Scan registered projects and remove worktree directories that have been deleted from disk.
          Deduplicated content caches remain preserved for reuse.
        </div>
      </div>
      <div id="cleanMissingStatus" class="tiny"></div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Cancel</button>
        <button class="btn warn" onclick="confirmCleanMissing()">🧹 Prune Missing Projects</button>
      </div>
    </div>
  `;
  if($('modalBg'))$('modalBg').classList.add('open');
}

async function confirmCleanMissing(){
  const statusEl=$('cleanMissingStatus');
  if(statusEl)statusEl.textContent='Scanning and cleaning…';
  try{
    const r=await post('/api/preprocess',{action:'cleanup_deleted'},{timeoutMs:120000});
    $('modalClose')?.click();
    await pollStatus();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function renderDoctorModal(d){
  const checks=d.checks||[];
  const okCount=checks.filter(c=>c.status==='OK').length;
  const allOk=okCount===checks.length;

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <div>
          <div class="tiny muted mono">SYSTEM DIAGNOSTICS &amp; HEALTH</div>
          <h2 style="margin:2px 0 0;font-size:16px">Local AI Hub Doctor</h2>
        </div>
        <div>
          <span class="badge-status ${allOk?'badge-complete':'badge-error'}">${allOk?'✓ ALL CHECKS HEALTHY':(checks.length-okCount)+' ISSUES DETECTED'}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="doc-check-grid">
        ${checks.map(c=>{
          const isOk=c.status==='OK';
          const isWarn=c.status==='WARN'||c.status==='OFF';
          const badgeClass=isOk?'badge-complete':(isWarn?'badge-paused':'badge-error');
          const icon=isOk?'✅':(isWarn?'⚠️':'❌');
          return `
            <div class="doc-check-card" style="border-color:${isOk?'#166534':(isWarn?'#854d0e':'#991b1b')}">
              <span class="doc-check-icon">${icon}</span>
              <div style="flex:1">
                <div style="display:flex;justify-content:space-between;align-items:baseline">
                  <span class="doc-check-title">${esc(c.component)}</span>
                  <span class="badge-status ${badgeClass}" style="font-size:9px">${esc(c.status)}</span>
                </div>
                <div class="doc-check-detail">${esc(c.detail||'')}</div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="openDoctorModal()">↻ Re-run Doctor</button>
        <button class="btn" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

async function openDoctorModal(){
  openModal({},'Local AI Hub Doctor Health Diagnostics','doctor');
  if($('modalBody'))$('modalBody').innerHTML='<div class="modal-body-wrap"><div class="tiny muted">Running comprehensive health diagnostics across Hub, Ollama, GPU, databases and preprocessor…</div></div>';
  try{
    const r=await post('/api/doctor',{});
    renderDoctorModal(r);
  }catch(e){
    if($('modalBody'))$('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="bad-t">Doctor failed: ${esc(e.message||e)}</div></div>`;
  }
}

function renderActiveLeaseModal(l){
  const paths=Array.isArray(l.paths)?l.paths:[l.path||''];
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">MULTI-AGENT COORDINATION LEASE</div>
          <h2 style="margin:2px 0 0;font-size:16px;font-family:monospace">${esc(l.lease_id||'—')}</h2>
        </div>
        <span class="badge-status badge-complete">ACTIVE</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Lease Details</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">

            <div>Purpose</div><div>${esc(l.purpose||'agent edits')}</div>
            <div>Time Remaining</div><div class="ok"><b>${l.expires_in_seconds?durSec(l.expires_in_seconds):'—'}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-card">
        <div class="modal-card-head"><span>Protected Paths (${paths.length})</span></div>
        <div class="modal-card-body">
          ${paths.map(p=>`<div class="mono tiny" style="padding:3px 0"><span class="chip mono">${esc(p)}</span></div>`).join('')}
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn bad" onclick="releaseLeaseAction(${escJs(l.lease_id)})">Release Lease</button>
      </div>
    </div>
  `;
}

async function releaseLeaseAction(leaseId){
  try{
    await post('/api/leases/release',{lease_id:leaseId});
    $('modalClose')?.click();
    await loadActiveLeases();
  }catch(e){
    alert('Release error: '+e);
  }
}

function renderActiveCommandModal(cmd){
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">RUNNING SAFE COMMAND</div>
          <h2 style="margin:2px 0 0;font-size:15px;font-family:monospace">${esc(cmd.command||'—')}</h2>
        </div>
        <span class="badge-status badge-running"><span class="pulse-dot"></span> RUNNING</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Execution Parameters</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Working Directory</div><div class="mono tiny">${esc(cmd.cwd||'—')}</div>

            <div>Policy Classification</div><div><span class="chip ok">${esc(cmd.class||'safe')}</span></div>
            <div>Age / Running For</div><div>${age(cmd.age_ms)}</div>
            <div>Timeout</div><div>${durSec(cmd.timeout_seconds)}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderErrorFingerprintModal(err){
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">ERROR FINGERPRINT</div>
          <h2 style="margin:2px 0 0;font-size:16px"><span class="bad-t">${esc(err.component||'System')}</span> · ${esc(err.operation||'')}</h2>
        </div>
        <span class="badge-status badge-error">${n(err.count||0)} OCCURRENCES</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Telemetry Statistics</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Component</div><div><b>${esc(err.component||'—')}</b></div>
            <div>Operation</div><div><b>${esc(err.operation||'—')}</b></div>
            <div>Diagnostic</div><div>${esc(String(err.safe_message||'Diagnostic unavailable').slice(0,96))}</div>
            <div>Total Occurrences</div><div class="bad-t"><b>${n(err.count||0)}</b></div>
            <div>Recovered Count</div><div class="ok"><b>${n(err.recovered_count||0)}</b></div>
            <div>Last Seen</div><div>${err.last_seen?new Date(err.last_seen*1000).toLocaleString():'—'}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderDbOptModal(r){
  const dbs=r.details||[];
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">DATABASE MAINTENANCE</div>
          <h2 style="margin:2px 0 0;font-size:16px">WAL Checkpoint &amp; VACUUM Optimization</h2>
        </div>
        <span class="badge-status badge-complete">${n(r.total_freed_kb||0)} KB FREED</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Optimized SQLite Stores (${dbs.length})</span></div>
        <div class="modal-card-body">
          <table>
            <thead><tr><th>Database</th><th>Before</th><th>After</th><th>Freed</th></tr></thead>
            <tbody>
              ${dbs.map(d=>`
                <tr>
                  <td><b>${esc(d.db)}</b></td>
                  <td>${n(d.before_kb)} KB</td>
                  <td>${n(d.after_kb)} KB</td>
                  <td class="ok">+${n(d.freed_kb)} KB</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderCachePurgeModal(r){
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">CACHE PRUNING RESULTS</div>
          <h2 style="margin:2px 0 0;font-size:16px">Cache Purge Summary</h2>
        </div>
        <span class="badge-status badge-complete">${n(r.purged_entries||0)} ENTRIES PRUNED</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Pruning Parameters</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Threshold</div><div>Older than <b>${r.days_threshold||7}</b> days</div>
            <div>Purged Entries</div><div class="ok"><b>${n(r.purged_entries||0)}</b> stale records removed</div>
            <div>WAL Checkpoint</div><div class="ok">Truncated &amp; synchronized</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderHttpTailModal(x){
  const act=x.action||'Action';
  const evs=Number(x.events||0);
  const fails=Number(x.failures||0);
  const failPct=evs?((fails/evs)*100).toFixed(1):'0.0';
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">HTTP TAIL LATENCY &amp; SLO</div>
          <h2 style="margin:2px 0 0;font-size:16px"><span class="mono">${esc(act)}</span></h2>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="chip ok">${n(evs)} calls</span>
          <span class="chip ${fails?'bad-t':'ok'}">${n(fails)} fails (${failPct}%)</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Percentile Latency Distribution</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Median (p50)</div><div><b>${ms(x.p50_duration_ms)}</b></div>
            <div>95th Percentile (p95)</div><div class="warn-t"><b>${ms(x.p95_duration_ms)}</b></div>
            <div>99th Percentile (p99)</div><div class="bad-t"><b>${ms(x.p99_duration_ms)}</b></div>
            <div>Total Calls Tracked</div><div>${n(evs)}</div>
            <div>Operational Failures</div><div class="${fails?'bad-t':'ok'}"><b>${n(fails)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderExecutionProfileModal(x){
  const m=x.model||'Model';
  const tier=x.tier||'fast';
  const numCtx=Number(x.num_ctx||0);
  const maxCtx=Number(x.max_ctx||0);
  const par=Number(x.parallel_limit||1);
  const think=x.think?'Enabled (reasoning models)':'Role-gated / Off';
  const cap=Number(x.prompt_budget_tokens||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">EXECUTION PROFILE CONFIGURATION</div>
          <h2 style="margin:2px 0 0;font-size:16px">🤖 <span class="mono">${esc(m)}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${esc(tier.toUpperCase())}</span>
          <span class="chip">${par} parallel slot${par>1?'s':''}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Capacity &amp; Context Limits</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Default Context Window</div><div><b>${n(numCtx)} tokens</b></div>
            <div>Maximum Context Window</div><div><b>${n(maxCtx)} tokens</b></div>
            <div>Parallel Concurrency Limit</div><div>${par} slots</div>
            <div>Thinking / Extended Reasoning</div><div><span class="chip">${think}</span></div>
            <div>Prompt Budget Cap</div><div><b>${n(cap)} tokens</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderModelStatModal(x){
  const m=x.model||'Model';
  const calls=Number(x.calls||0);
  const fails=Number(x.failures||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">MODEL PERFORMANCE &amp; INFERENCE STATS</div>
          <h2 style="margin:2px 0 0;font-size:16px">🤖 <span class="mono">${esc(m)}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${n(calls)} requests</span>
          <span class="chip ${fails?'bad-t':'ok'}">${n(fails)} failures</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Inference Timing</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Average Latency</div><div><b>${ms(x.avg_ms)}</b></div>
            <div>Cold-load / Warm-up Time</div><div><b>${ms(x.avg_load_ms)}</b></div>
            <div>Total Calls</div><div>${n(calls)}</div>
            <div>Failures</div><div class="${fails?'bad-t':'ok'}">${n(fails)}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderCacheLayerModal(x){
  const l=x.layer||'Cache Layer';
  const calls=Number(x.calls||0);
  const saved=Number(x.context_tokens_avoided_est||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">CACHE LAYER METRICS</div>
          <h2 style="margin:2px 0 0;font-size:16px">⚡ <b>${esc(humanLabel(l))}</b></h2>
        </div>
        <span class="chip ok"><b>${n(saved)}</b> tokens saved</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Layer Performance</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Layer Key</div><div class="mono tiny">${esc(l)}</div>
            <div>Hits / Invocations</div><div><b>${n(calls)}</b></div>
            <div>Average Lookup Time</div><div><b>${ms(x.avg_ms)}</b></div>
            <div>Context Tokens Avoided</div><div class="ok"><b>${n(saved)} tokens</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderAgentStatModal(x){
  const ag=x.agent||'Agent';
  const reqs=Number(x.requests||0);
  const inf=Number(x.local_inference_calls||0);
  const fails=Number(x.failures||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">CLIENT AGENT TELEMETRY</div>
          <h2 style="margin:2px 0 0;font-size:16px">👤 <b>${esc(ag)}</b></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${n(reqs)} requests</span>
          <span class="chip">${n(inf)} local LLM calls</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Usage Overview</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Agent Identifier</div><div class="mono tiny">${esc(ag)}</div>
            <div>Total Hub Requests</div><div><b>${n(reqs)}</b></div>
            <div>Local Inference Delegations</div><div><b>${n(inf)}</b></div>
            <div>Average Round-Trip</div><div><b>${ms(x.avg_ms)}</b></div>
            <div>Reported Failures</div><div class="${fails?'bad-t':'ok'}"><b>${n(fails)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderRouteStatModal(x){
  const route=x.route||'route';
  const task=x.task_type||'task';
  const comp=x.complexity||'standard';
  const calls=Number(x.calls||0);
  const fails=Number(x.failures||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">EXECUTION ROUTE</div>
          <h2 style="margin:2px 0 0;font-size:16px">➔ <span class="mono">${esc(route)}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${esc(comp)} complexity</span>
          <span class="chip">${esc(task)}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Route Dispatch Stats</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Assigned Task Type</div><div><b>${esc(task)}</b></div>
            <div>Complexity Tier</div><div><b>${esc(comp)}</b></div>
            <div>Total Executions</div><div><b>${n(calls)}</b></div>
            <div>Average Runtime</div><div><b>${ms(x.avg_ms)}</b></div>
            <div>Failures</div><div class="${fails?'bad-t':'ok'}"><b>${n(fails)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderBlockedReasonModal(x){
  const r=x.reason||'Blocked';
  const count=Number(x.count||0);
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">COMMAND SECURITY POLICY REJECTION</div>
          <h2 style="margin:2px 0 0;font-size:16px"><span class="bad-t">Blocked:</span> ${esc(humanLabel(r))}</h2>
        </div>
        <span class="badge-status badge-error">${n(count)} REJECTIONS</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Rejection Details</span></div>
        <div class="modal-card-body">
          <div style="font-size:12px;line-height:1.5">
            Commands matching this rule were blocked by Local AI Hub's sandbox policy broker to protect system integrity.
          </div>
          <div class="kv" style="padding:0;margin-top:8px">
            <div>Policy Reason</div><div class="mono tiny bad-t">${esc(r)}</div>
            <div>Total Blocked Count</div><div><b>${n(count)}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderSchedulerJobModal(j){
  const jid=n(j.job_id);
  const state=j.state||'queued';
  const model=j.model||'—';

  const source=j.source||'api';
  const reason=j.wait_reason||'ready';
  const traceId=j.trace_id;
  const isErr=state==='failed'||state==='error';
  const isLive=state==='running'||state==='processing';
  const stateCls=isErr?'badge-error':(isLive?'badge-running':'badge-waiting');

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">JOB SCHEDULER INFLIGHT ITEM</div>
          <h2 style="margin:2px 0 0;font-size:16px">Job <b>#${jid}</b> <span class="badge-status ${stateCls}">${esc(state.toUpperCase())}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ok">${esc(model)}</span>
          <span class="chip">${esc(source)}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Execution &amp; Queue Timing</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Job ID</div><div><b>#${jid}</b></div>
            <div>Status</div><div><span class="badge-status ${stateCls}">${esc(state)}</span></div>
            <div>Assigned Model</div><div class="mono tiny"><b>${esc(model)}</b></div>

            <div>Origin / Source</div><div>${esc(source)}</div>
            <div>Queue Wait Time</div><div><b>${ms(j.wait_ms)}</b></div>
            <div>Service Execution Time</div><div><b>${ms(j.service_ms)}</b></div>
            <div>Wait / Scheduling Reason</div><div class="warn-t"><b>${esc(reason)}</b></div>
          </div>
        </div>
      </div>
      ${traceId?`
        <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#101a26;border:1px solid #1e354d;border-radius:6px">
          <span>Linked Trace: <b class="mono">${esc(traceId)}</b></span>
          <button class="btn ok" onclick="openTrace(${escJs(traceId)})">↗ Open Full Trace</button>
        </div>
      `:''}
      <details class="raw-json"><summary>Raw Job Details</summary><pre>${esc(JSON.stringify(j,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

function renderHttpRequestModal(r){
  const rid=r.request_id||'—';
  const agent=r.agent||'unknown';

  const action=r.action||'—';
  const status=r.status_code!==undefined?n(r.status_code):'—';
  const isErr=r.success===false||(r.status_code&&r.status_code>=400);
  const dur=r.duration_ms!==undefined?ms(r.duration_ms):(r.age_ms!==undefined?age(r.age_ms):'—');
  const dt=r.created_at?new Date(r.created_at*1000).toLocaleString():'—';

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">HTTP WORK REQUEST</div>
          <h2 style="margin:2px 0 0;font-size:16px"><span class="mono">${esc(action)}</span></h2>
        </div>
        <div style="display:flex;gap:6px">
          <span class="chip ${isErr?'bad-t':'ok'}">${status}</span>
          <span class="chip">${dur}</span>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Request Profile</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Request ID</div><div class="mono tiny"><b>${esc(rid)}</b></div>
            <div>Action / Endpoint</div><div class="mono tiny">${esc(action)}</div>
            <div>Calling Agent</div><div><b>${esc(agent)}</b></div>

            <div>Duration / In-flight Age</div><div><b>${dur}</b></div>
            <div>Status Code</div><div class="${isErr?'bad-t':'ok'}"><b>${status}</b></div>
            <div>Timestamp</div><div>${dt}</div>
          </div>
        </div>
      </div>
      <details class="raw-json"><summary>Raw Request Details</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose')?.click()">Close</button>
      </div>
    </div>
  `;
}

if($('modalClose'))$('modalClose').onclick=()=>{if($('modalBg'))$('modalBg').classList.remove('open');activeTraceId='';activeTraceData=null;traceDetailPoller?.stop();traceDetailPoller=null;tracePollAbortController?.abort();tracePollAbortController=null};
if($('modalBg'))$('modalBg').onclick=e=>{if(e.target===$('modalBg'))$('modalClose')?.click()};

document.addEventListener('click',e=>{
  const closeBtn=e.target.closest?.('button');
  if(closeBtn && (closeBtn.getAttribute('onclick')?.includes('modalClose') || closeBtn.dataset.modalClose!==undefined || (closeBtn.textContent?.trim()==='Cancel' && closeBtn.closest('#modalBody')))){
    $('modalClose')?.click();
    return;
  }
  const copyFinal=e.target.closest?.('[data-trace-copy-final]');if(copyFinal){copyTraceFinalResponse(copyFinal);return}
  const copyTrace=e.target.closest?.('[data-trace-copy]');if(copyTrace){copyTraceContent(copyTrace.dataset.traceCopy,copyTrace);return}
  const expandAll=e.target.closest?.('[data-trace-expand-all]');if(expandAll){setTraceDetailsOpen(true);return}
  const collapseAll=e.target.closest?.('[data-trace-collapse-all]');if(collapseAll){setTraceDetailsOpen(false);return}
  const eventPage=e.target.closest?.('[data-trace-event-page]');if(eventPage){loadTraceEventPage(eventPage.dataset.traceEventPage);return}
  const tab=e.target.closest?.('[data-trace-view]');if(tab){setTraceView(tab.dataset.traceView);return}
  const pageTrace=e.target.closest?.('[data-trace-page-id]');if(pageTrace){openTrace(pageTrace.dataset.tracePageId);return}
  const back=e.target.closest?.('[data-trace-back]');if(back){switchTab('work');return}
  const toggle=e.target.closest?.('[data-trace-toggle]');if(toggle){toggleTraceStep(toggle);return}
  if(e.target.closest('button, a, input, select, textarea, .action-btn-sm, [data-project-action], [data-export-root]'))return;
  const trace=e.target.closest?.('[data-trace-id]');if(trace){openTrace(trace.dataset.traceId);return}
  const tr=e.target.closest?.('[data-detail]');
  if(tr){
    let entry=dataStore.get(tr.dataset.detail);
    let obj=null, type=tr.dataset.type||'';
    if(entry){
      obj=(entry.data!==undefined&&entry.type!==undefined)?entry.data:entry;
      type=entry.type||type||inferEntityType(obj);
    }
    if(!obj && tr.dataset.id){
      const eid=tr.dataset.id;
      if(type==='task') obj=agentOsTasks.find(x=>x.task_id===eid);
      else if(type==='memory') obj=agentOsMemories.find(x=>((x.scope||'task')+':'+x.key)===eid||x.key===eid);
      else if(type==='incident') obj=agentOsIncidents.find(x=>x.incident_id===eid);
      else if(type==='project') obj=(last?.preprocessing?.projects||[]).find(x=>x.root===eid);
    }
    if(obj){
      openModal(obj,'',type);
    }
  }
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if($('visionReviewModal')?.classList.contains('open'))closeFrontendVisionReviewModal();
    else if($('modalBg')?.classList.contains('open'))$('modalClose')?.click();
    else if($('controlMenu'))$('controlMenu').open=false;
    return;
  }
  const tab=e.target.closest?.('[data-trace-view]');
  if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();moveTraceTab(tab,e.key);
});

function switchTab(tabId){
  if(!tabId||!$(tabId))return;
  const changed=document.querySelector('.page.active')?.id!==tabId;
  if($('controlMenu'))$('controlMenu').open=false;
  document.querySelectorAll('.tabbtn').forEach(x=>{const active=x.dataset.tab===tabId;x.classList.toggle('active',active);x.setAttribute('aria-current',active?'page':'false');});
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===tabId));
  try{localStorage.setItem('activeTab',tabId)}catch{}
  if(location.hash.replace('#','')!==tabId)history.replaceState(null,'','#'+tabId);
  if(tabId==='config')loadConfigView();
  if(tabId==='agentos')loadAgentOsView();
  if(tabId==='performance'){loadRagWorkspaces();loadActiveLeases();}
  if(tabId==='commands')loadWorktrees();
  if(tabId==='reliability')loadLogsTail();
  if(changed){window.scrollTo({top:0,left:0,behavior:'instant'});$(tabId).querySelector('.page-heading h1')?.focus({preventScroll:true});}
}

document.querySelectorAll('.tabbtn').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
window.addEventListener('hashchange',()=>switchTab(location.hash.replace('#','')));
$('pauseEvents').onclick=e=>{paused=!paused;e.target.textContent=paused?'Resume live events':'Pause live events'};
async function fetchDashboardJson(path,options={}){
  const response=await apiFetch(path,options);
  let data;
  try{data=await response.json()}catch{throw new Error(`Invalid server response (HTTP ${response.status})`)}
  if(!response.ok||data?.success===false)throw new Error(String(data?.error||data?.message||`HTTP ${response.status}`));
  return data;
}
async function post(path,payload,requestOptions={}){const r=await apiFetch(path,{...requestOptions,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});return await r.json()}

const ACTIVITY_MODES=['active','gaming','maintenance'];
let activityModeStatusPolls=0;
let activityModeTransitionNotice=null;
const activityModeLabels={active:'Active',gaming:'GAMING / PAUSED',maintenance:'Maintenance'};
function renderActivityMode(mode){
  const badge=$('activityModeBadge');if(!badge)return;
  const valid=ACTIVITY_MODES.includes(String(mode||''));
  const value=valid?String(mode):'unknown';
  badge.dataset.mode=value;badge.className=`pill ${value==='active'?'ok':value==='unknown'?'warn-t':''}`;
  badge.textContent=`Mode: ${valid?activityModeLabels[value]:'Unknown'}`;
  document.querySelectorAll('[data-activity-mode]').forEach(button=>button.setAttribute('aria-pressed',String(valid&&button.dataset.activityMode===value)));
}
function activityModeFailure(response,data){
  if(response?.status===401)return 'Unauthorized (HTTP 401); check the API token.';
  if(response?.status===400)return `Invalid mode: ${data?.error||'server rejected request'}`;
  if(response&&!response.ok)return `Mode request failed (HTTP ${response.status}).`;
  return data?.error||'Mode request failed.';
}
function projectActivityModeTransition(confirmed,data){
  const failures=[];
  if(confirmed==='gaming'){
    const unload=data.runtime_unload;
    if(!unload||unload.state!=='pending'&&unload.success!==true)failures.push('VRAM unload incomplete');
    const acceleratorRelease=data.accelerator_release;
    if(!acceleratorRelease||acceleratorRelease.success!==true)failures.push('accelerator release incomplete');
    if(unload?.state==='pending')failures.push('VRAM unload pending');
  }
  if(data.job_cancellation&&data.job_cancellation.success!==true)failures.push('job cancellation incomplete');
  const persisted=`Mode persisted as ${activityModeLabels[confirmed]}.`;
  return {
    modePersisted:true,
    partial:failures.length>0,
    failures,
    status:failures.length?`${persisted} Mode transition incomplete: ${failures.join('; ')}.`:`Mode set to ${activityModeLabels[confirmed]}.`,
  };
}
async function refreshActivityMode(){
  const status=$('activityModeStatus');
  try{
    const response=await apiFetch('/api/mode',{cache:'no-store',timeoutMs:5000});
    const data=await response.json().catch(()=>null);
    if(!response.ok||!data||data.success!==true){renderActivityMode('unknown');if(status)status.textContent=`Mode unavailable: ${activityModeFailure(response,data)}`;return false;}
    if(!ACTIVITY_MODES.includes(data.mode)){renderActivityMode('unknown');if(status)status.textContent='Mode unavailable: invalid mode returned by server.';return false;}
    renderActivityMode(data.mode);
    if(activityModeTransitionNotice&&activityModeTransitionNotice.mode!==data.mode)activityModeTransitionNotice=null;
    const notice=activityModeTransitionNotice?.mode===data.mode?activityModeTransitionNotice:null;
    if(notice&&data.mode==='gaming'&&data.runtime_unload?.state!=='pending'){
      const unloadState=data.runtime_unload?.success===true?'complete':'incomplete';
      notice.text=notice.text.replace(/VRAM unload (?:pending|incomplete)/,`VRAM unload ${unloadState}`);
    }
    if(status){const unload=data.runtime_unload;status.textContent=notice?.text??(data.mode==='gaming'&&unload?(unload.success===true?'Gaming mode active. VRAM unload complete.':unload.state==='pending'?'Gaming mode active. VRAM unload in progress.':'Gaming mode active. VRAM unload incomplete.'):'Mode loaded.');}
    if(data.mode==='gaming'&&data.runtime_unload?.state==='pending'&&activityModeStatusPolls<8){activityModeStatusPolls++;setTimeout(refreshActivityMode,1500);}else if(data.runtime_unload?.state!=='pending'){activityModeStatusPolls=0;}
    return true;
  }catch(_){renderActivityMode('unknown');if(status)status.textContent='Mode unavailable: Hub offline or unreachable.';return false;}
}
async function applyActivityMode(mode){
  const buttons=Array.from(document.querySelectorAll('[data-activity-mode]')),status=$('activityModeStatus');
  mode=String(mode||'');
  if(!ACTIVITY_MODES.includes(mode)){if(status)status.textContent='Invalid mode selected.';return false;}
  activityModeTransitionNotice=null;
  buttons.forEach(button=>button.disabled=true);if(status)status.textContent='Updating mode…';
  try{
    const response=await apiFetch('/api/admin/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode}),timeoutMs:5000});
    const data=await response.json().catch(()=>null);
    if(!response.ok||!data||data.success!==true){if(status)status.textContent=activityModeFailure(response,data);return false;}
    const confirmed=data.mode;
    if(!ACTIVITY_MODES.includes(confirmed)||confirmed!==mode){if(status)status.textContent='Mode update rejected: invalid mode returned by server.';return false;}
    renderActivityMode(confirmed);
    const transition=projectActivityModeTransition(confirmed,data);
    if(transition.partial)activityModeTransitionNotice={mode:confirmed,text:transition.status};
    if(status)status.textContent=transition.status;
    if(confirmed==='gaming'&&data.runtime_unload?.state==='pending'){activityModeStatusPolls=0;setTimeout(refreshActivityMode,800);}
    return true;
  }catch(_){if(status)status.textContent='Mode update failed: Hub offline or unreachable.';return false;}
  finally{buttons.forEach(button=>button.disabled=false);}
}

function setConfigFormReady(ready){
  document.querySelectorAll('#config input,#config select').forEach(control=>{control.disabled=!ready});
  for(const id of ['cfgSave','cfgReset'])if($(id))$(id).disabled=!ready;
}
let configViewLoad=null;
async function loadConfigView(){
  if(configViewLoad)return configViewLoad;
  setConfigFormReady(false);
  $('cfgStatus').textContent='Loading configuration…';
  configViewLoad=(async()=>{
  try{
    const r=await apiFetch('/api/config',{cache:'no-store'}),d=await r.json();
    if(r.ok===false||!d.success){$('cfgStatus').textContent=d.error||'Configuration unavailable. Reload to retry.';return}
    const c=d.config||{},feat=c.features||{};
    $('cfgProfile').value=c.hardware?.profile||'auto';
    $('cfgPreprocess').checked=c.preprocessing?.enabled!==false&&feat.preprocessing!==false;
    $('cfgIntel').checked=c.code_intelligence?.enabled!==false&&feat.code_intelligence!==false;
    $('cfgSerena').checked=!!c.code_intelligence?.serena_enabled;

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
    setConfigFormReady(true);
  }catch(e){$('cfgStatus').textContent='Configuration unavailable: '+String(e)}
  })();
  try{await configViewLoad}finally{configViewLoad=null}
}
$('cfgReload').onclick=loadConfigView;
$('cfgSave').onclick=async()=>{
  const settings={
    'hardware.profile':$('cfgProfile').value,
    'preprocessing.enabled':$('cfgPreprocess').checked,
    'code_intelligence.enabled':$('cfgIntel').checked,
    'code_intelligence.serena_enabled':$('cfgSerena').checked,

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
  const r=await post('/api/config/update',{action:'update',settings});
  $('cfgStatus').textContent=r.success?'saved · restart hub to apply':('error: '+(r.error||'failed'));
  if(r.success)loadConfigView();
};
if($('cfgReset'))$('cfgReset').onclick=async()=>{
  if($('modalTitle'))$('modalTitle').textContent='Reset dashboard overrides';
  if($('modalLive'))$('modalLive').textContent='Confirmation required';
  if($('modalBody'))$('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Scope and impact</span></div><div class="modal-card-body"><p><b>Scope:</b> Dashboard-managed configuration override sidecar only.</p><p style="margin-bottom:0"><b>Impact:</b> Removes override values. Base configuration and project data stay unchanged; restart applies result.</p></div></div><div class="modal-actions-bar" style="justify-content:flex-end"><button class="btn" onclick="$('modalClose')?.click()">Cancel</button><button class="btn warn" id="confirmConfigReset">Reset overrides</button></div></div>`;
  if($('modalBg'))$('modalBg').classList.add('open');
  const confirmBtn=$('confirmConfigReset');
  if(confirmBtn)confirmBtn.onclick=async()=>{const r=await post('/api/config/update',{action:'reset'});if($('cfgStatus'))$('cfgStatus').textContent=r.success?'overrides reset · restart hub to apply':('error: '+(r.error||'failed'));if(r.success)loadConfigView();$('modalClose')?.click();};
};

let logLines=['Click Refresh to load logs.'];
async function loadLogsTail(){
  try{
    const lines=$('logLinesSelect')?.value||'250';
    const r=await apiFetch('/api/logs/tail?lines='+lines,{cache:'no-store'}),d=await r.json();
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
    const result=await post('/api/preprocess',{action});
    if(result?.success){last={...last,preprocessing:result};render(last)}
    await pollStatus();
  }catch(e){alert('Preprocessing action failed: '+(e.message||e));await pollStatus()}
  finally{buttons.forEach(b=>b.disabled=false);preprocessActionInFlight=false}
}
function togglePreprocessing(){return setPreprocessing(last?.preprocessing?.paused?'resume':'pause')}
$('prepToggle').onclick=togglePreprocessing;
$('prepAllToggle').onclick=togglePreprocessing;
document.querySelectorAll('[data-activity-mode]').forEach(button=>button.onclick=()=>applyActivityMode(button.dataset.activityMode));
refreshActivityMode();
setInterval(()=>{if(document.visibilityState!=='hidden')refreshActivityMode()},30000);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState!=='hidden')refreshActivityMode()});

function refreshProjectList(){renderProjects(last?.preprocessing?.projects||[])}
$('projectSearch').oninput=e=>{projectQuery=e.target.value;refreshProjectList()};
$('projectFilter').onchange=e=>{projectFilter=e.target.value;refreshProjectList()};
$('projectSort').onchange=e=>{projectSort=e.target.value;refreshProjectList()};
$('projectGroupWorktrees')?.addEventListener('change',refreshProjectList);

const PHASES = [
  {id:'inventory', name:'Discovery', icon:'📁', desc:'File inventory & change discovery'},
  {id:'hash', name:'Content Hash', icon:'⚡', desc:'SHA256 content hashing & cache linking'},
  {id:'code_index', name:'AST Symbols', icon:'🌲', desc:'Symbol & callgraph extraction'},
  {id:'deterministic', name:'Declarative Facts', icon:'📋', desc:'Routes, models & configs'},
  {id:'serena', name:'Serena', icon:'S', desc:'Semantic/LSP project index'},

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
function projectIdentity(project){
  return String(project?.git_common_dir||project?.canonical_root||project?.root||project?.project||'').replace(/\\/g,'/').replace(/\/+$/,'');
}
function projectState(x){
  const progress=Number(x.overall_progress_pct||0);
  if(x.status==='error'||x.last_error)return 'error';
  if(x.paused||x.status==='paused')return 'paused';
  if(x.waiting||x.status==='waiting')return 'waiting';
  if(x.status==='running')return 'running';
  if(x.phase==='complete'||x.status==='complete'||progress>=100)return 'ready';
  return 'queued';
}

function groupedProjects(items){
  const list=Array.isArray(items)?items:[];
  if(!$('projectGroupWorktrees')?.checked)return list.map(x=>({...x,repository_identity:x.root||x.project||'',variants:[x]}));
  const groups=new Map();
  list.forEach(item=>{
    const identity=projectIdentity(item)||String(item.project||'unknown');
    const group=groups.get(identity)||[];group.push(item);groups.set(identity,group);
  });
  const rank={error:0,running:1,waiting:2,queued:3,paused:4,ready:5};
  return [...groups.entries()].map(([identity,variants])=>{
    const ordered=[...variants].sort((a,b)=>(rank[projectState(a)]??9)-(rank[projectState(b)]??9));
    return {...ordered[0],canonical_root:ordered[0].root||identity,repository_identity:ordered[0].root||identity,variants};
  });
}

function renderProjects(items){
  const status=preprocessingSummary(last?.preprocessing||{},last?.dependency_status||{},last?.features||{});
  if(!status.available){
    if($('projectSummary'))$('projectSummary').textContent='Project inventory unavailable';
    rows('projectsBody',[],()=>'',5,'Project status unavailable. Refresh status to retry.');
    return;
  }
  const entries=Array.isArray(items)?items:[],source=groupedProjects(entries),query=projectQuery.trim().toLowerCase();
  const rank={error:0,running:1,waiting:2,queued:3,paused:4,ready:5};
  const visible=source.filter(x=>{
    const state=projectState(x),haystack=[x.project,x.root,x.repository_identity,x.active_detail,x.phase,...(x.variants||[]).map(v=>v.root)].join(' ').toLowerCase();
    return (!query||haystack.includes(query))&&(projectFilter==='all'||state===projectFilter);
  });
  visible.sort((a,b)=>{
    if(projectSort==='name')return String(a.project||'').localeCompare(String(b.project||''));
    if(projectSort==='progress')return Number(b.overall_progress_pct||0)-Number(a.overall_progress_pct||0)||String(a.project||'').localeCompare(String(b.project||''));
    if(projectSort==='recent')return Number(b.updated_at||b.last_complete_at||0)-Number(a.updated_at||a.last_complete_at||0)||String(a.project||'').localeCompare(String(b.project||''));
    return (rank[projectState(a)]??9)-(rank[projectState(b)]??9)||String(a.project||'').localeCompare(String(b.project||''));
  });
  const summary=$('projectSummary');
  if(summary)summary.textContent=`${visible.length} of ${source.length} repository identities · ${entries.length} project entries`;
  rows('projectsBody',visible,x=>{
    const state=projectState(x),tot=Math.max(1,Number(x.files||0)),ragFiles=Number(x.rag_files||0),cards=Number(x.file_cards||0),ragPct=Math.round(ragFiles/tot*100),cardPct=Math.round(cards/tot*100),overall=Math.max(0,Math.min(100,Number(x.overall_progress_pct||0))),phasePct=Math.max(0,Math.min(100,Number(x.phase_progress_pct||0))),isComplete=state==='ready',isWorktree=x.is_worktree===true;
    const badge={running:['badge-running','Running','<span class="pulse-dot"></span>'],waiting:['badge-waiting','Waiting',''],paused:['badge-paused','Paused',''],error:['badge-error','Error',''],ready:['badge-complete','Ready','✓ ']}[state]||['badge-waiting','Queued',''];
    const activityText=isComplete?'Indexing complete · last reported snapshot':x.active_detail||(state==='paused'?(x.global_paused?'Globally paused':'Project paused'):state==='waiting'?'Waiting for preprocessing slot':state==='error'?(x.last_error_short||'Pipeline error'):'Processing queue');
    const activityCls=isComplete?'ok':state==='error'?'bad-t':state==='paused'?'warn-t':state==='waiting'?'muted':'';
    const progressAge=Number(x.progress_age_seconds),progressHint=Number.isFinite(progressAge)?(progressAge<5?'live checkpoint':`${durSec(progressAge)} since last checkpoint`):'';
    const phaseObj=PHASES.find(ph=>ph.id===x.phase)||(isComplete?PHASES[PHASES.length-1]:{name:x.phase||'Inventory',icon:'⚙️'}),phaseTitle=isComplete?`${PHASES.length}/${PHASES.length} Ready`:`${n(x.phase_index||1)}/${PHASES.length} ${phaseObj.icon} ${phaseObj.name}`;
    const variants=x.variants||[x],variantLabel=variants.length>1?`<span class="chip" title="${esc(variants.map(v=>v.root).join('\n'))}">${variants.length} worktrees</span>`:'';
    const actions=`<div class="project-actions"><button class="action-btn-sm" data-project-action="${state==='paused'?'resume':'pause'}" data-project-root="${esc(x.root)}" title="${state==='paused'?'Resume project preprocessing':'Pause project'}">${state==='paused'?'▶ Resume':'⏸ Pause'}</button><button class="action-btn-sm" data-project-action="refresh" data-project-root="${esc(x.root)}" title="Re-scan selected project entry">Refresh</button><button class="action-btn-sm danger" data-project-action="delete" data-project-root="${esc(x.root)}" data-project-name="${esc(x.project)}" title="Unregister selected project entry">Unregister</button></div>`;
    return clickableRow(x,`<td><div class="project-name"><b>${esc(x.project)}</b>${isWorktree?'<span class="chip" style="font-size:9px;color:var(--accent2);border-color:#584578">worktree</span>':''}${variantLabel}</div><div class="tiny muted">Repository identity</div><div class="tiny muted mono project-root" title="${esc(x.repository_identity||x.root)}">${esc(x.repository_identity||x.root)}</div></td><td><span class="badge-status ${badge[0]}">${badge[2]}${badge[1]}</span><div class="tiny ${activityCls} project-activity" title="${esc(x.active_detail||activityText)}">${esc(activityText)}</div><div class="tiny muted">${esc(progressHint)}</div></td><td><div class="project-progress-line"><b>${phaseTitle}</b><span>${overall}%</span></div><div class="bar project-progress"><i style="width:${overall}%;background:${state==='error'?'var(--bad)':isComplete?'var(--ok)':'var(--accent)'}"></i></div><div class="tiny muted">${phasePct}% in phase</div></td><td><div class="project-index"><span class="${ragFiles>=tot?'ok':''}">🧠 RAG ${ragPct}%</span><span class="${cards>=tot*0.9?'ok':''}">📄 Cards ${cardPct}%</span></div></td><td>${actions}</td>`,'project',x.root);
  },5,query||projectFilter!=='all'?'No projects match the current filters.':'No projects registered. Register a repository to begin.');
}
async function projectAction(root, action) {
  try { const result=await post('/api/preprocess', { root, action }); if(!result.success)throw new Error(result.error||'Project action failed'); await pollStatus(); } catch(e) { alert('Action error: ' + e); }
}
$('regProjectBtn').onclick = openRegisterProjectModal;
$('cleanMissingBtn').onclick = openCleanMissingModal;
async function deleteProjectDialog(root, name) {
  openDeleteProjectModal(root, name);
}

function openControlConfirmation(action){
  const details={
    purge_cache:{title:'Purge expired cache',scope:'Cache entries older than 7 days in configured state directory.',impact:'Expired cached responses removed. Project source and indexes remain intact.'},
  }[action];
  if(!details)return;
  if($('modalTitle'))$('modalTitle').textContent=details.title;
  if($('modalLive'))$('modalLive').textContent='Confirmation required';
  if($('modalBody'))$('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Scope and impact</span></div><div class="modal-card-body"><p><b>Scope:</b> ${esc(details.scope)}</p><p style="margin-bottom:0"><b>Impact:</b> ${esc(details.impact)}</p></div></div><div class="modal-actions-bar" style="justify-content:flex-end"><button class="btn" onclick="$('modalClose')?.click()">Cancel</button><button class="btn warn" id="confirmControlAction">${esc(details.title)}</button></div></div>`;
  if($('modalBg'))$('modalBg').classList.add('open');
  const confirmBtn=$('confirmControlAction');
  if(confirmBtn)confirmBtn.onclick=async()=>{try{await post('/api/maintenance/purge_cache',{days:7});$('modalClose')?.click();}catch(error){if($('modalLive'))$('modalLive').textContent='Action failed: '+String(error?.message||error);}};
}
$('optDbBtn').onclick=async()=>{try{const r=await post('/api/maintenance/optimize_db',{});openModal(r,'Database Optimization & WAL Checkpoint Results','db_opt')}catch(e){openModal({error:String(e)},'Error')}};
$('purgeCacheBtn').onclick=()=>openControlConfirmation('purge_cache');
$('doctorBtn').onclick=openDoctorModal;

function ensureHttpTailTable(){
  const performance=$('performance');if(!performance||$('httpTail'))return;
  performance.insertAdjacentHTML('beforeend','<section class="section"><h2>HTTP tail latency <span class="tiny">per action · excludes policy rejections</span></h2><div class="table-wrap"><table><thead><tr><th>Action</th><th>Calls</th><th>p50</th><th>p95</th><th>p99</th><th>Fails</th></tr></thead><tbody id="httpTail"></tbody></table></div></section>');
}
function setupWorkLayout(){
  const work=$('work');if(!work||work.dataset.refined)return;work.dataset.refined='1';work.classList.add('work-page');
  const sections=[...work.children].filter(x=>x.classList.contains('section'));sections.forEach((x,i)=>x.classList.add('work-panel','work-panel-'+(i+1)));
  const headers=[['State','Work item','Model / source','Timing','Reason'],['Request','Agent','Action','Age'],['Time','Request ID','Project','Agent','Action / context','Result','Trace availability','Duration'],['State','Kind','Project','Action / context','Agent','Model','Created','Updated / duration','Links']];
  sections.forEach((section,index)=>{const row=section.querySelector('thead tr');if(row&&headers[index])row.innerHTML=headers[index].map(x=>`<th>${x}</th>`).join('')});
  work.insertAdjacentHTML('afterbegin','<section class="section work-summary"><div class="work-summary-head"><div><div class="work-kicker">Operations center</div><h2>Live work <span class="tiny">prioritized view</span></h2></div><span class="tiny">Click any row to inspect its trace</span></div><div class="work-kpis"><div><span>Queued</span><strong id="workQueued">—</strong></div><div><span>Running</span><strong id="workRunning">—</strong></div><div><span>Active API</span><strong id="workActive">—</strong></div><div><span>Retained traces</span><strong id="workRetained">—</strong></div></div><div class="work-filter"><input id="workSearch" type="search" placeholder="Search project, agent, action, model…" autocomplete="off"><select id="workState" aria-label="Work state"><option value="">All states</option><option value="running">Running</option><option value="queued">Queued</option><option value="failed">Failed</option><option value="completed">Completed</option></select><button class="btn" id="workReset">Reset</button><span class="work-filter-summary" id="workFilterSummary"></span></div></section>');
  $('workSearch').oninput=()=>last&&render(last);$('workState').onchange=()=>last&&render(last);$('workReset').onclick=()=>{$('workSearch').value='';$('workState').value='';if(last)render(last)};
  if($('requestHistoryReset')&&!$('requestHistorySort'))$('requestHistoryReset').insertAdjacentHTML('beforebegin','<select id="requestHistorySort" aria-label="Sort recent API requests"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="duration-desc">Longest duration</option><option value="status">Status</option><option value="endpoint">Endpoint A–Z</option></select>');
  if($('traceKind')&&!$('traceTableSearch'))$('traceKind').insertAdjacentHTML('beforebegin','<input id="traceTableSearch" type="search" aria-label="Search agent traces" placeholder="Search request, action, trace ID…" style="width:220px"><select id="traceTableState" aria-label="Filter traces by state"><option value="">All states</option><option value="running">Running</option><option value="queued">Queued</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="interrupted">Interrupted</option></select><select id="traceTableSort" aria-label="Sort agent traces"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="action">Action A–Z</option><option value="duration">Longest run</option><option value="state">State</option></select><button class="btn" id="traceTableReset">Reset</button>');
  $('requestHistorySearch')?.addEventListener('input',()=>last&&render(last));
  ['requestHistoryAction','requestHistoryStatus','requestHistoryPeriod','requestHistorySort'].forEach(id=>$(id)?.addEventListener('change',()=>last&&render(last)));
  $('requestHistoryReset')?.addEventListener('click',()=>{['requestHistorySearch','requestHistoryAction','requestHistoryStatus','requestHistoryPeriod'].forEach(id=>{const control=$(id);if(control)control.value=''});if($('requestHistorySort'))$('requestHistorySort').value='newest';if(last)render(last)});
  $('traceTableSearch')?.addEventListener('input',()=>renderTraceList(lastTraces));
  ['traceTableState','traceTableSort'].forEach(id=>$(id)?.addEventListener('change',()=>renderTraceList(lastTraces)));
  $('traceTableReset')?.addEventListener('click',()=>{if($('traceTableSearch'))$('traceTableSearch').value='';if($('traceTableState'))$('traceTableState').value='';if($('traceTableSort'))$('traceTableSort').value='newest';if($('traceKind'))$('traceKind').value='';renderTraceList(lastTraces)});
}
function workVisible(items){const query=String($('workSearch')?.value||'').trim().toLowerCase(),state=String($('workState')?.value||'').toLowerCase();return (items||[]).filter(item=>{const itemState=String(item.state||item.status||'').toLowerCase(),hay=Object.values(item||{}).join(' ').toLowerCase();return (!query||hay.includes(query))&&(!state||(state==='completed'?['completed','complete','succeeded','success','done'].includes(itemState):itemState===state||(state==='running'&&itemState==='processing')))});}
function filterRecentRequests(items,allItems){
  const all=allItems||items||[],selected=String($('requestHistoryAction')?.value||''),counts=new Map();
  all.forEach(item=>{const action=String(item.action||'');if(action)counts.set(action,(counts.get(action)||0)+1)});
  const actionSelect=$('requestHistoryAction');
  if(actionSelect){actionSelect.innerHTML='<option value="">All endpoints ('+all.length+')</option>'+[...counts].sort((a,b)=>a[0].localeCompare(b[0])).map(([action,count])=>`<option value="${esc(action)}">${esc(action)} (${count})</option>`).join('');actionSelect.value=counts.has(selected)?selected:''}
  const query=String($('requestHistorySearch')?.value||'').trim().toLowerCase(),action=String(actionSelect?.value||''),status=String($('requestHistoryStatus')?.value||''),period=Number($('requestHistoryPeriod')?.value||0),after=period?Date.now()/1000-period:0;
  const visible=(items||[]).filter(item=>{
    const code=Number(item.status_code||0),hay=[item.request_id,item.action,item.project,item.agent,item.error_type,code,traceProjectLabel(item),traceContextLabel(requestTrace(item))].filter(Boolean).join(' ').toLowerCase();
    const matchesStatus=!status||(status==='failed'?(item.success===false||code>=400):Math.floor(code/100)===Number(status[0]));
    return (!query||hay.includes(query))&&(!action||String(item.action||'')===action)&&matchesStatus&&(!after||Number(item.created_at||0)>=after);
  });
  const sort=String($('requestHistorySort')?.value||'newest');
  visible.sort((a,b)=>{const time=Number(a.created_at||0)-Number(b.created_at||0);if(sort==='oldest')return time;if(sort==='duration-desc')return Number(b.duration_ms||0)-Number(a.duration_ms||0);if(sort==='status')return Number(b.status_code||0)-Number(a.status_code||0);if(sort==='endpoint')return String(a.action||'').localeCompare(String(b.action||''))||-time;return -time});
  const summary=$('requestHistorySummary');if(summary)summary.textContent=`${visible.length} of ${all.length} loaded · ${counts.size} endpoints`;
  return visible;
}
function workState(state){const value=String(state||'queued'),cls=value==='failed'||value==='error'?'bad':(value==='running'||value==='processing'?'live':'');return `<span class="work-state ${cls}">${esc(value)}</span>`}
function workSchedulerRow(job){const inner=`<td>${workState(job.state)}</td><td><strong>#${n(job.job_id)}</strong></td><td><strong>${esc(job.model||'—')}</strong><div class="tiny">${esc(job.source||'—')}</div></td><td><span class="timing-label">wait</span> ${ms(job.wait_ms)}<div><span class="timing-label">run</span> ${ms(job.service_ms)}</div></td><td>${esc(job.wait_reason||'ready')}</td>`;return schedulerRow(job,inner,5)}
function workActiveRequestRow(request){const inner=`<td><strong>${esc(request.request_id||'—')}</strong></td><td>${esc(request.agent||'—')}</td><td>${esc(request.action||'—')}</td><td>${age(request.age_ms)}</td>`;return requestRow(request,inner,4)}
function requestTrace(request){return lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''))}
function traceContextLabel(trace){
  if(!trace)return '';
  const source=trace.source&&trace.source!==trace.action?trace.source:'',summary=trace.summary||trace.description||trace.operation||trace.action_detail||'',requestId=trace.request_id?`req ${String(trace.request_id).slice(-8)}`:'',jobId=trace.async_job_id?`job ${String(trace.async_job_id).slice(-8)}`:'';
  return [...new Set([trace.request_summary,summary,source,trace.kind?humanLabel(trace.kind):'',trace.model?`model ${trace.model}`:'',requestId,jobId].filter(Boolean))].join(' · ');
}

function requestTraceAvailability(request){
  const trace=requestTrace(request);
  if(trace)return {label:'Trace available',className:'ok',trace};
  if(request.trace_id)return {label:'Trace expired',className:'warn-t',trace:null};
  if(request.trace_available===false)return {label:'No trace recorded',className:'muted',trace:null};
  return {label:'No trace retained',className:'muted',trace:null};
}
function requestOutcome(request={}){
  const code=Number(request.status_code)||0,failed=request.success===false||code>=400;
  const label=failed?'Failed':request.success===true?'Succeeded':code?'HTTP result':'Result unreported';
  return {failed,label:label+(code?' · HTTP '+code:'')};
}
function workRecentRequestRow(request){const trace=requestTrace(request),availability=requestTraceAvailability(request),outcome=requestOutcome(request),failed=outcome.failed,context=trace?traceContextLabel(trace):(request.error_type||''),requestId=String(request.request_id||'—'),project=traceProjectLabel(request.project||request.workspace||request.root||trace?.project)||'—',inner=`<td>${request.created_at?new Date(request.created_at*1000).toLocaleString():'—'}</td><td><strong>${esc(requestId.slice(-12))}</strong><div class="tiny">${trace?'Trace linked · '+esc(String(trace.trace_id||'').slice(-8)):'Request-only record'}</div></td><td><strong>${esc(project)}</strong></td><td>${esc(request.agent||'—')}</td><td><strong>${esc(request.action||'—')}</strong><div class="tiny">${esc(context)}</div></td><td><span class="${failed?'bad-t':'ok'}">${esc(outcome.label)}</span>${request.error_type?`<div class="tiny">${esc(request.error_type)}</div>`:''}</td><td><span class="${availability.className}">${esc(availability.label)}</span></td><td>${ms(request.duration_ms)}</td>`;return requestRow(request,inner,8)}

function render(s){
  last=s;
  syncDetailedTelemetryToggle(Boolean(s.debug_traces?.enabled));
  const receivedAt=Date.now();
  lastOverviewReceivedAt=receivedAt;
  const q=s.scheduler||{},o=s.observability||{},p=s.preprocessing||{},bg=s.background_gpu||{},h=s.headless||{},r=s.runtime_stats||{},ss=q.stats||{},rp=s.runtime_profile||{},cmd=r.commands||{};
  ensureHttpTailTable();setupWorkLayout();
  renderOverviewHealth(s,receivedAt);

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
      {k:'code_intelligence',label:'Code intel',tool:'AST / Serena / Graph',tab:'projects'},
      {k:'preprocessing',label:'Preprocessing',tool:'Background workers',tab:'projects'},
      {k:'subagents',label:'Subagents',tool:'Ollama workers',tab:'performance'},
      {k:'agent_os',label:'Agent OS',tool:'Durable memory/receipts',tab:'agentos'},
      {k:'dashboard',label:'Dashboard',tool:'Web UI',tab:'config'},
    ];
    const pills=$('featurePills');
    if(pills){
      const disabledMods=mods.filter(m=>feat[m.k]===false);
      const enabledCount=mods.filter(m=>feat[m.k]===true).length,unknownCount=mods.filter(m=>feat[m.k]==null).length;
      pills.innerHTML=mods.map(m=>{
        const off=feat[m.k]===false,unknown=feat[m.k]==null;
        if(unknown)return `<button class="chip" data-goto-tab="${m.tab}">${esc(m.label)} · unreported</button>`;
        return `<button class="chip" data-goto-tab="${m.tab}" style="cursor:pointer;${off?'border-color:#7f1d1d;color:#f87171;background:#450a0a33':'border-color:#065f46;color:#34d399;background:#064e3b22'}" title="${m.k}: ${off?'disabled':'enabled'} · tool: ${m.tool}"><b>${m.label}</b> ${off?'<span class="tiny bad-t">✗ off</span>':'<span class="tiny ok">✓ on</span>'}</button>`;
      }).join('');
      pills.querySelectorAll('[data-goto-tab]').forEach(btn=>btn.onclick=()=>switchTab(btn.dataset.gotoTab));
      const txt=$('featStatusText');
      if(txt){
        if(unknownCount){txt.textContent=unknownCount+' module states unreported';txt.title='';}
        else if(disabledMods.length){txt.innerHTML=`<span class="warn-t">${disabledMods.length} module${disabledMods.length>1?'s':''} disabled</span>`;txt.title=disabledMods.map(m=>m.k).join(', ');}
        else{txt.innerHTML='<span class="ok">All 12 modules enabled</span>';txt.title='';}
      }
      const sumEl=$('featSummary');
      if(sumEl){
        sumEl.style.cursor='pointer';
        sumEl.onclick=()=>switchTab('config');
        if(unknownCount){sumEl.textContent=enabledCount+'/'+mods.length+' modules enabled · '+unknownCount+' unreported';sumEl.className='pill tiny warn-t';}
        else if(disabledMods.length){sumEl.textContent=enabledCount+'/'+mods.length+' modules enabled';sumEl.className='pill tiny warn-t';}
        else{sumEl.textContent='12/12 modules enabled ✓';sumEl.className='pill tiny ok';}
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
    if($('agentOsDisabledBanner'))$('agentOsDisabledBanner').style.display=feat.agent_os===false?'flex':'none';
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

  if($('worktreeRoots'))$('worktreeRoots').innerHTML=[...new Set((p.projects||[]).map(project=>project.root).filter(Boolean))].sort().map(root=>`<option value="${esc(root)}"></option>`).join('');
  const repoSelect=$('agentOsRepoSelect');
  if(repoSelect){
    const currentVal=repoSelect.value;
    const projectRoots=(p.projects||[]).map(x=>x.root).filter(Boolean);
    const uniqueRoots=[...new Set(projectRoots)].sort();
    const rootsKey=uniqueRoots.join('|');
    if(repoSelect.dataset.renderedRoots!==rootsKey){
      let optHtml='<option value="">All repositories (všechny repozitáře)</option>';
      uniqueRoots.forEach(root=>{
        const proj=(p.projects||[]).find(x=>x.root===root);
        const name=(proj&&proj.project)?`${proj.project} (${root})`:root;
        optHtml+=`<option value="${esc(root)}">${esc(name)}</option>`;
      });
      repoSelect.innerHTML=optHtml;
      repoSelect.dataset.renderedRoots=rootsKey;
      if(currentVal)repoSelect.value=currentVal;
    }
  }

  const statusBadge=dashboardHealthBadge(s);
  $('health').innerHTML=`<span class="${statusBadge.className}">${s.hub_online==null?'hub ?':s.hub_online?'hub ✓':'hub ✗'} / ${s.ollama_online==null?'ollama ?':s.ollama_online?'ollama ✓':'ollama ✗'} / ${esc(h.state||'n/a')}${statusBadge.degradedLabel}</span>`;
  $('uptime').textContent='uptime '+durSec(s.uptime_seconds)+' · supervisor restarts '+n(h.restarts);

  const ep=(rp.execution||{}).models||(s.model_execution||{}).models||[];
  const httpTail=o.http_tail_latency||{};
  rows('httpTail',httpTail.by_action||[],x=>clickableRow(x,`<td>${esc(x.action)}</td><td>${n(x.events)}</td><td>${ms(x.p50_duration_ms)}</td><td>${ms(x.p95_duration_ms)}</td><td>${ms(x.p99_duration_ms)}</td><td>${n(x.failures)}</td>`,'http_tail'),6);

  $('fgQueue').textContent=n(q.foreground_queued)+' queued / '+n(q.foreground_inflight)+' running';
  $('bgQueue').textContent='background '+n(q.background_queued)+' queued / '+n(q.inflight_background)+' running · '+(q.background_allowed?'idle work allowed':'yielding');

  const http=o.http||{},cohorts=o.cohorts||{},agentHttp=cohorts.agent_http||{},inference=cohorts.inference||{},policy=cohorts.policy_rejection||{},compatibility=cohorts.compatibility||{},domains=o.cache_domains||{},generation=domains.generation||{},repository=domains.repository||{},commandCache=domains.command||{},netDelta=Number(o.net_cloud_token_delta_est??0),savedTokens=Math.max(0,netDelta),tokenOverhead=Math.max(0,Number(o.cloud_token_overhead_est||0)),grossSaved=Math.max(0,Number(o.gross_cloud_tokens_avoided_est||0)),protocolTokens=Math.max(0,Number(o.agent_protocol_tokens_est||0)),toolCallTokens=Math.max(0,Number(o.agent_tool_request_tokens_est||0)),toolReadTokens=Math.max(0,Number(o.agent_tool_response_tokens_est||0)),schemaTokens=Math.max(0,Number(o.tool_schema_tokens_exposure_est||0)),schemaDelta=Number(o.net_after_schema_token_delta_est??0),localComputeSaved=Math.max(0,Number(o.local_compute_tokens_avoided_est||0)),savedUsd=o.estimated_savings_usd,inputSavedUsd=o.estimated_input_savings_usd,outputSavedUsd=o.estimated_output_savings_usd,inputRate=o.cloud_input_token_cost_usd_per_million,outputRate=o.cloud_output_token_cost_usd_per_million;
  $('handledRequests').textContent=n(agentHttp.events);
  $('handledRequestsSub').textContent=n(agentHttp.failures)+' operational failures · '+n(policy.events)+' policy rejections · '+n(compatibility.events)+' compatibility 404s';
  $('tokensSaved').textContent=n(netDelta);
  $('tokensSavedSub').textContent='baseline '+n(grossSaved)+' − protocol '+n(protocolTokens)+' (call '+n(toolCallTokens)+' + read '+n(toolReadTokens)+')'+(tokenOverhead?' · overhead '+n(tokenOverhead):'')+' · schema-adjusted '+n(schemaDelta)+' (catalog ≈'+n(schemaTokens)+')';
  $('dollarsSaved').textContent=o.estimated_savings_pricing_mode==='incomplete'||savedUsd==null?'Unknown':'≈ $'+Number(savedUsd).toFixed(2);
  $('dollarsSavedSub').textContent=o.estimated_savings_pricing_mode==='incomplete'?'Known channel subtotals: input '+formatChannelSavings(inputSavedUsd,inputRate)+' · output '+formatChannelSavings(outputSavedUsd,outputRate)+' · historical channel costs unknown':o.estimated_savings_pricing_mode==='input_output'?'input '+formatChannelSavings(inputSavedUsd,inputRate)+' · output '+formatChannelSavings(outputSavedUsd,outputRate):'Cost unavailable';
  const qHitRate=(Number(o.preprocessed_query_hit_rate??0)*100).toFixed(1),ingReuse=(Number(p.ingestion_reuse_rate??0)*100).toFixed(1);
  $('cache').textContent=Number(generation.events??inference.events??o.events)>0?((o.generation_cache_hit_rate ?? o.cache_hit_rate ?? 0)*100).toFixed(1)+'%':'No samples';
  $('cacheSub').textContent=n(generation.hits)+' generation · '+n(repository.hits)+' repository ('+qHitRate+'% index hit) · '+n(commandCache.hits)+' command hits · '+n(localComputeSaved)+' local tokens avoided';
  $('latency').textContent=ms(agentHttp.p50_duration_ms)+' / '+ms(agentHttp.p95_duration_ms)+' / '+ms(agentHttp.p99_duration_ms);
  $('queueWait').textContent='local inference p95 '+ms(inference.p95_duration_ms)+' · avg queue wait '+ms(o.avg_queue_wait_ms);
  $('reliabilityValue').innerHTML=`<span class="${agentHttp.failures?'warn-t':'ok'}">${n(agentHttp.failures)} failures</span>`;
  $('reliabilitySub').textContent=telemetryPeriod(o)+' · retained samples · '+n(policy.events)+' policy rejections · '+n(inference.fallback_count)+' fallbacks · '+n(inference.degraded_count)+' degraded · '+n(inference.retry_count)+' retries';

  renderTelemetryMetrics(o);

  // Plot selected-period aggregates observed at each distinct status refresh.
  const curP95=Number(agentHttp.p95_duration_ms||0);
  const curWait=Number(o.avg_queue_wait_ms||0);
  const curRps=Number(agentHttp.events||0);
  recordTelemetrySnapshot(o);

  drawSpark('latencySpark', latencySparkData, '#38bdf8', 'rgba(56,189,248,0.12)');
  drawSpark('throughputSpark', throughputSparkData, '#34d399', 'rgba(52,211,153,0.12)');
  drawDualChart('liveChartCanvas', liveChartLatency, liveChartQueue);
  const liveChartEmpty=$('liveChartEmpty');
  const hasLiveChartSamples=liveChartLatency.length>0,liveChartCanvas=$('liveChartCanvas'),liveChartSummary=$('liveChartSummary');
  if(liveChartEmpty)liveChartEmpty.style.display=hasLiveChartSamples?'none':'block';
  const liveChartLabel=hasLiveChartSamples?`${telemetryPeriod(o)} aggregate snapshots. Period p95 latency ${ms(curP95)}. Period average queue wait ${ms(curWait)}. ${liveChartLatency.length} status snapshots.`:'No available telemetry samples for the selected period.';
  if(liveChartCanvas)liveChartCanvas.setAttribute('aria-label',liveChartLabel);
  if(liveChartSummary)liveChartSummary.textContent=liveChartLabel;
  if($('performanceMetricsScope'))$('performanceMetricsScope').textContent=telemetryPeriod(o)+' · retained samples · model, cache, agent, route and HTTP statistics below';

  const agState=s.agent_state||{};
  if($('agentStateVal')){
    if(agState.enabled&&s.features?.agent_os!==false){
      const act=agState.active_tasks_count||0,mem=agState.memory_records_count;
      $('agentStateVal').innerHTML='<span>Enabled</span>';
      $('agentStateSub').textContent='Hub-wide · '+n(act)+' active task'+(act===1?'':'s')+(mem!==undefined?' · '+n(mem)+' memories':'');
    }else{
      $('agentStateVal').textContent=agState.enabled===false||s.features?.agent_os===false?'Disabled':'Unavailable';
      $('agentStateSub').textContent=agState.enabled===false||s.features?.agent_os===false?'Agent OS is disabled':'Hub-wide Agent OS inventory unavailable';
    }
  }
  if($('agentStateCard'))$('agentStateCard').onclick=()=>switchTab('agentos');

  const loadedModels=s.loaded_model_details||[];
  const loadedVal=$('loadedModelVal'),loadedSub=$('loadedModelSub');
  if(loadedVal&&loadedSub){
    if(loadedModels.length>0){
      const primary=loadedModels[0];
      const others=loadedModels.length>1?` (+${loadedModels.length-1} more)`:'';
      loadedVal.textContent=primary.name+others;
      const ctxStr=primary.context_length?`${n(primary.context_length)} ctx`:'Dynamic ctx';
      const vramStr=primary.vram_bytes?`${formatBytes(primary.vram_bytes)} VRAM`:(primary.size_bytes?formatBytes(primary.size_bytes):'');
      const paramStr=primary.parameter_size||primary.quantization||'';
      loadedSub.textContent=[ctxStr,paramStr,vramStr].filter(Boolean).join(' · ');
    }else if(Array.isArray(s.loaded_models)&&s.loaded_models.length>0){
      loadedVal.textContent=s.loaded_models.join(', ');
      loadedSub.textContent='Resident in memory';
    }else{
      loadedVal.innerHTML='<span class="muted">None resident</span>';
      loadedSub.textContent='Models load on demand';
    }
  }
  if($('loadedModelCard'))$('loadedModelCard').onclick=()=>switchTab('performance');

  $('prep').textContent=(p.paused?'paused':(p.processing_projects?'active':'idle'))+' · '+n(p.steps)+' steps';
  const prepStatus=preprocessingSummary(p,s.dependency_status||{},s.features||{});
  $('prepSub').textContent=prepStatus.text+(prepStatus.available?' · card reuse '+ingReuse+'% · query hit '+qHitRate+'%':'');
  if(!prepStatus.available)$('prep').textContent='Unavailable';

  const allJobs=[...(q.inflight_jobs||[]),...(q.pending_jobs||[])];
  if($('currentSummary'))$('currentSummary').textContent=n(q.foreground_queued)+' queued · '+n(q.foreground_inflight)+' running';
  rows('overviewJobs',allJobs.slice(0,12),j=>schedulerRow(j,`<td>${esc(j.state)}</td><td>${esc(j.agent||'—')}</td><td>${esc(j.source)}</td><td>${esc(j.model)}</td><td>${ms(j.wait_ms)}</td><td>${ms(j.service_ms)}</td><td>${esc(j.wait_reason)}</td>`),7);

  const hs=o.hotspots||[];
  if($('hotspots'))$('hotspots').innerHTML=hs.length?hs.map((x,i)=>`<div>${esc(x.type||'signal')}</div><div><span class="chip">${esc(x.signal||'')}</span> ${esc(x.value??x.value_ms??x.count??'')}</div>`).join(''):'<div>Status</div><div class="muted">No hotspot reported in available telemetry</div>';

  const recentRequests=o.recent_http||[],visibleJobs=workVisible(allJobs),visibleActive=workVisible(o.active_requests||[]),visibleRecent=filterRecentRequests(workVisible(recentRequests),recentRequests);
  if($('queueSummary'))$('queueSummary').textContent=n(q.foreground_queued)+' fg + '+n(q.background_queued)+' bg queued · '+n(q.foreground_inflight)+' fg + '+n(q.inflight_background)+' bg running';
  if($('workQueued'))$('workQueued').textContent=n((q.foreground_queued||0)+(q.background_queued||0));
  if($('workRunning'))$('workRunning').textContent=n((q.foreground_inflight||0)+(q.inflight_background||0));
  if($('workActive'))$('workActive').textContent=n((o.active_requests||[]).length);
  if($('workRetained'))$('workRetained').textContent=n(lastTraces.length);
  if($('workFilterSummary'))$('workFilterSummary').textContent=`showing ${visibleJobs.length+visibleActive.length+visibleRecent.length} live/history items`;

  rows('jobs',visibleJobs,j=>workSchedulerRow(j),5);
  rows('activeReq',visibleActive,x=>workActiveRequestRow(x),4);
  rows('recentReq',visibleRecent,x=>workRecentRequestRow(x),8,'No requests match the current filters.');
  renderTraceList(lastTraces);

  const diagBar=$('prepDiagnosticBar');
  if(diagBar){
    const projs=p.projects||[], isGlobPaused=!!p.paused, isEnabled=p.enabled!==false&&s.features?.preprocessing!==false;
    const hasErr=projs.some(x=>String(x.status||'').toLowerCase()==='error');
    const allDone=projs.length>0&&projs.every(x=>projectState(x)==='ready');
    const bgYield=p.scheduler_background_allowed===false;
    diagBar.style.display='flex';
    if(!prepStatus.available){
      diagBar.className='diag-banner warn';
      diagBar.textContent='Project status is unavailable. This does not mean that no projects are registered. Refresh status to retry.';
    }else if(!isEnabled){
      diagBar.className='diag-banner bad';
      diagBar.innerHTML=`<span>❌ <b>Preprocessing is disabled in configuration</b> (<code>preprocessing.enabled = false</code>). Enable it in the Configuration tab.</span>`;
    }else if(isGlobPaused){
      diagBar.className='diag-banner warn';
      diagBar.innerHTML=`<span style="flex:1">⏸ <b>Preprocessing is GLOBALLY PAUSED</b>. Background workers and real-time synchronization are stopped.</span><button class="btn ok" onclick="setPreprocessing('resume')" style="padding:3px 8px;font-size:11px">▶ Resume Preprocessing</button>`;
    }else if(!projs.length){
      diagBar.className='diag-banner info';
      diagBar.innerHTML=`<span style="flex:1">ℹ️ <b>No projects currently registered</b>. Preprocessing is idle waiting for workspace registration. Click <b>+ Register Project</b> or call <code>local_ai_repo(action='preprocess')</code> from an agent.</span><button class="btn ok" onclick="$('regProjectBtn').click()" style="padding:3px 8px;font-size:11px">+ Register Project</button>`;
    }else if(hasErr){
      const errProjs=projs.filter(x=>String(x.status||'').toLowerCase()==='error').map(x=>x.project||x.root).join(', ');
      diagBar.className='diag-banner bad';
      diagBar.innerHTML=`<span style="flex:1">⚠️ <b>Errors detected in project preprocessing:</b> ${esc(errProjs)}. Check status column below for error details.</span><button class="btn" onclick="pollStatus()" style="padding:3px 8px;font-size:11px">Refresh status</button>`;
    }else if(allDone){
      diagBar.className='diag-banner ok';
      diagBar.innerHTML=`<span><b>All ${projs.length} registered project entries report complete indexing progress</b>. This snapshot does not verify synchronization with later file changes.</span>`;
    }else if(bgYield){
      diagBar.className='diag-banner warn';
      diagBar.innerHTML=`<span>⏳ <b>Background preprocessing is yielding:</b> Foreground agent requests are currently active on GPU/models. Preprocessing will resume automatically when queue clears.</span>`;
    }else{
      const runningNames=projs.filter(x=>x.status==='running').map(x=>x.project).join(', ');
      diagBar.className='diag-banner info';
      diagBar.innerHTML=runningNames?`<span><b>Preprocessing is processing:</b> ${esc(runningNames)}</span>`:'<span>Preprocessing is enabled. No project reports active processing in this snapshot.</span>';
    }
  }

  const prepPaused=!!p.paused;
  $('prepState').textContent=n((p.projects||[]).length)+' registered project entries · global '+(p.enabled===false?'disabled':prepPaused?'paused':'enabled');
  if(!prepStatus.available)$('prepState').textContent='Project inventory unavailable';
  $('prepAllToggle').disabled=!prepStatus.available;
  $('cleanMissingBtn').disabled=!prepStatus.available;
  $('prepToggle').textContent=prepPaused?'Resume preprocessing':'Pause preprocessing';
  $('prepAllToggle').textContent=prepPaused?'Resume all projects':'Pause all projects';
  renderProjects(p.projects||[]);

  rows('loadedModelsBody',loadedModels,m=>{
    const ctx=m.context_length?`${n(m.context_length)} tokens`:'<span class="muted">Dynamic</span>';
    const params=esc(m.parameter_size||'—');
    const quant=m.quantization?`<span class="chip">${esc(m.quantization)}</span>`:'<span class="muted">—</span>';
    const memStr=`${formatBytes(m.vram_bytes||0)} VRAM / ${formatBytes(m.size_bytes||0)} total`;
    const offload=`${Math.round((m.gpu_fraction||0)*100)}% GPU / ${Math.round((m.cpu_offload_fraction||0)*100)}% CPU`;
    const statusChip=m.expires_at?`<span class="chip ok">expires ${new Date(m.expires_at).toLocaleTimeString()}</span>`:'<span class="chip">Resident</span>';
    return `<tr><td><strong>${esc(m.name)}</strong></td><td>${ctx}</td><td>${params}</td><td>${quant}</td><td class="mono tiny">${memStr}</td><td class="tiny">${offload}</td><td>${statusChip}</td></tr>`;
  },7,'No models currently resident in VRAM/memory.');

  rows('executionProfiles',ep,x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${esc(x.tier)}</td><td>${n(x.num_ctx)}</td><td>${n(x.max_ctx)}</td><td>${n(x.parallel_limit)}</td><td>${x.think?'on':'role-gated/off'}</td><td>${n(x.prompt_budget_tokens)}</td>`,'execution_profile'),7);
  rows('models',o.by_model||[],x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${ms(x.avg_load_ms)}</td><td>${n(x.failures)}</td>`,'model_stat'),5);
  rows('cacheLayers',o.cache_layers||[],x=>clickableRow(x,`<td>${esc(x.layer)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.context_tokens_avoided_est)}</td>`,'cache_layer'),4);
  rows('agents',o.by_agent||[],x=>clickableRow(x,`<td>${esc(x.agent)}</td><td>${n(x.requests)}</td><td>${n(x.local_inference_calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`,'agent_stat'),5);
  rows('routes',o.execution_routes||[],x=>clickableRow(x,`<td>${esc(x.route)}</td><td>${esc(x.task_type)}</td><td>${esc(x.complexity)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`,'route_stat'),6);

  $('commandState').textContent=n(cmd.active_count)+' running';
  rows('activeCommands',cmd.active||[],x=>clickableRow(x,`<td>${esc(x.command)}</td><td>${esc(x.cwd)}</td><td>${esc(x.class)}</td><td>${age(x.age_ms)}</td><td>${durSec(x.timeout_seconds)}</td>`,'command'),5);
  $('commandStats').innerHTML=`<div>Executed</div><div>${n(cmd.executed)}</div><div>Cache hits / misses</div><div>${n(cmd.hits)} / ${n(cmd.misses)}</div><div>Coalesced waiters</div><div>${n(cmd.coalesced_waiters)}</div><div>Policy blocked</div><div>${n(cmd.blocked)}</div>`;
  rows('blockedReasons',Object.entries(cmd.blocked_by_reason||{}),x=>clickableRow({reason:x[0],count:x[1]},`<td>${esc(x[0])}</td><td>${n(x[1])}</td>`,'blocked_reason'),2);

  renderReliabilitySummary(s);
  rows('errors',o.recent_errors||[],x=>clickableRow(x,`<td>${esc(x.component)}</td><td>${esc(x.operation)}</td><td>${esc(String(x.safe_message||'Diagnostic unavailable').slice(0,96))}</td><td>${n(x.count)}</td><td>${n(x.recovered_count)}</td><td>${x.last_seen?new Date(x.last_seen*1000).toLocaleTimeString():'—'}</td>`,'error'),6);
  $('runtimeCounters').innerHTML=`<div>Scheduler submitted</div><div>${n(ss.submitted)}</div><div>Completed / failed</div><div>${n(ss.completed)} / ${n(ss.failed)}</div><div>Model switches</div><div>${n(ss.model_switches)}</div><div>Queue rejections</div><div>${n(ss.queue_rejections)}</div><div>Caller timeouts</div><div>${n(ss.caller_timeouts)}</div><div>Background yields</div><div>${n(ss.background_yields)}</div><div>Supervisor restarts</div><div>${n(h.restarts)}</div>`;

  if($('hubHealthCard'))$('hubHealthCard').onclick=()=>switchTab('reliability');
  rows('sessionRows',o.sessions||[],x=>{
    const st=x.status||'unknown',stBadge=st==='active'?`<span class="badge ok">Active (PID ${n(x.pid)})</span>`:st==='clean_stop'?`<span class="badge" style="background:#1e293b;color:#94a3b8;border:1px solid #334155">Clean stop</span>`:st==='crashed'?`<span class="badge bad" title="No clean shutdown recorded; the termination cause is unknown">Unclean exit</span>`:'<span class="badge">Status unknown</span>',hitPct=((Number(x.cache_hit_rate||0))*100).toFixed(1),started=x.started_at?new Date(x.started_at*1000).toLocaleString():'—';
    return clickableRow(x,`<td>${started}</td><td>${durSec(x.duration_seconds)}</td><td>${stBadge}</td><td>${n(x.events)}</td><td>${hitPct}% <span class="tiny muted">(${n(x.cache_hits)})</span></td><td>${n(x.tokens_saved)}</td><td><code>${esc(x.version||'—')}</code></td>`,'session');
  },7);

  renderBundles(s);
}

function renderReliabilitySummary(snapshot){
  const o=snapshot?.observability||{},agent=o.cohorts?.agent_http||{},sessions=o.sessions||[],health=dashboardHealth(snapshot||{});
  const available=o.enabled!==false&&o.data_available===true&&o.stale!==true;
  const failures=Math.max(0,Number(agent.failures)||0),unclean=sessions.filter(x=>x.status==='crashed').length;
  const headline=$('reliabilityHeadline'),trend=$('reliabilityTrend'),action=$('reliabilityAction');
  if(headline)headline.innerHTML=`<div>Current runtime</div><div class="${health.level==='healthy'?'ok':'warn-t'}"><b>${esc(health.label)}</b> · ${esc(health.reason)}</div><div>Recorded request failures · ${telemetryPeriod(o)}</div><div>${available?n(failures):'Unavailable'} <span class="tiny muted">retained samples</span></div><div>Supervisor restarts · supervisor lifetime</div><div>${n(snapshot?.headless?.restarts)}</div><div>Unclean exits · retained 30-day sessions</div><div>${available?n(unclean):'Unavailable'}</div>`;
  if(trend)trend.textContent='Historical failures and unclean exits describe past events, not active incidents. Session history retains at most 100 entries; absence of a clean shutdown does not establish a crash cause.';
  if(action){action.textContent='Open failed request history';action.onclick=()=>{
    for(const id of ['workSearch','workState','requestHistorySearch','requestHistoryAction','requestHistoryPeriod'])if($(id))$(id).value='';
    if($('requestHistoryStatus'))$('requestHistoryStatus').value='failed';
    switchTab('work');if(last)render(last);
  };}
}

function schedulerRow(job,html,cols){const linked=lastTraces.find(x=>String(x.scheduler_job_id||'')===String(job.job_id||''));const id=linked?.trace_id||job.trace_id;if(id)return `<tr class="click" data-trace-id="${esc(id)}">${html}</tr>`;return clickableRow(job,html,'scheduler_job');}
function requestRow(request,html,cols){const linked=lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''));if(linked)return `<tr class="click" data-trace-id="${esc(linked.trace_id)}">${html}</tr>`;return clickableRow(request,html,'http_request');}

function renderTraceList(items){
  const base=workVisible(items||[]),kind=String($('traceKind')?.value||''),matching=base.filter(x=>!kind||x.kind===kind);
  const tableQuery=String($('traceTableSearch')?.value||'').trim().toLowerCase(),tableState=String($('traceTableState')?.value||''),tableSort=String($('traceTableSort')?.value||'newest');
  const tableVisible=matching.filter(x=>{const state=traceStatus(x),hay=[x.trace_id,x.request_id,x.action,x.source,x.kind,x.project,x.agent,x.model,x.error_type,x.error,traceProjectLabel(x),traceContextLabel(x)].filter(Boolean).join(' ').toLowerCase();return (!tableQuery||hay.includes(tableQuery))&&(!tableState||state===tableState)});
  tableVisible.sort((a,b)=>{const time=Number(a.updated_at||a.created_at||0)-Number(b.updated_at||b.created_at||0);if(tableSort==='oldest')return -time;if(tableSort==='action')return String(a.action||'').localeCompare(String(b.action||''))||-time;if(tableSort==='duration'){const ad=Number(a.updated_at||a.created_at||0)-Number(a.created_at||0),bd=Number(b.updated_at||b.created_at||0)-Number(b.created_at||0);return bd-ad||-time}if(tableSort==='state')return String(traceStatus(a)).localeCompare(String(traceStatus(b)))||-time;return -time});
  const historyQuery=String($('traceHistorySearch')?.value||'').trim().toLowerCase(),historyState=$('traceHistoryState')?.value||'useful';
  const sidebarVisible=matching.filter(x=>{const state=traceStatus(x),hay=[x.trace_id,x.request_id,x.action,x.source,x.kind,x.agent,x.model,x.error,traceContextLabel(x)].filter(Boolean).join(' ').toLowerCase();return (!historyQuery||hay.includes(historyQuery))&&(historyState==='useful'?(state!=='interrupted'&&state!=='failed'):(!historyState||state===historyState))});
  $('traceSummary').textContent=`${tableVisible.length} shown · ${n(items?.length||0)} retained · metadata only · bounded retention`;
  if($('workRetained'))$('workRetained').textContent=n(items?.length||0);
  rows('traces',tableVisible,x=>{const state=traceStatus(x),cls='trace-'+state,links=[x.async_job_id&&('job '+String(x.async_job_id).slice(0,10)),x.scheduler_job_id&&('sched '+String(x.scheduler_job_id).slice(0,10))].filter(Boolean).join(' · '),activity=x.updated_at&&x.created_at?durSec(Math.max(0,Number(x.updated_at)-Number(x.created_at))):'—',context=traceContextLabel({...x,kind:'',model:''}),project=traceProjectLabel(x)||'—';return `<tr class="click" data-trace-id="${esc(x.trace_id)}"><td class="${cls}">${esc(humanLabel(state))}</td><td>${esc(humanLabel(x.kind||'trace'))}</td><td><strong>${esc(project)}</strong></td><td><strong>${esc(x.action||'—')}</strong><div class="tiny">${esc(context||'No request details')}</div></td><td>${esc(x.agent||'—')}</td><td>${esc(x.model||'—')}</td><td>${x.created_at?new Date(x.created_at*1000).toLocaleTimeString():'—'}</td><td>${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'}<div class="tiny">${esc(activity)} total</div></td><td class="tiny">${esc(links||'open trace')}</td></tr>`},9);
  $('traceSideSummary').textContent=`${sidebarVisible.length} trace${sidebarVisible.length===1?'':'s'} · click to inspect`;
  $('traceSidebarList').innerHTML=sidebarVisible.length?sidebarVisible.map(x=>{const state=traceStatus(x),label=state==='interrupted'?'Interrupted':state,cls=state==='interrupted'?'interrupted':(state==='failed'||state==='error'?'failed':(x.terminal||state==='completed'||state==='succeeded'?'done':'')),kindLabel=x.kind==='api_request'?'API request':humanLabel(x.kind||'trace'),context=traceContextLabel({...x,kind:'',model:''}),project=traceProjectLabel(x),projectMeta=[project,context].filter(Boolean).join(' · ')||x.agent||'unknown context';return `<button class="trace-side-item ${String(x.trace_id)===activeTraceId?'active':''}" data-trace-page-id="${esc(x.trace_id)}"><span class="trace-side-top"><span class="trace-side-state ${cls}"></span><span class="trace-side-action">${esc(x.action||x.kind||'Trace')}</span><span class="tiny spacer">${esc(label)}</span></span><span class="trace-side-meta">${esc(projectMeta)}</span><span class="trace-side-meta">${esc(kindLabel)} · ${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'}</span></button>`}).join(''):'<div class="empty-human">No retained traces</div>';
}
async function pollTraces(isCurrent=()=>document.visibilityState!=='hidden'){
  if(!isCurrent()||tracesPollInFlight)return false;
  tracesPollInFlight=true;
  const controller=typeof AbortController==='function'?new AbortController():null;
  tracesPollAbortController=controller;
  try{
    const kind=$('traceKind')?.value||'',suffix=kind?'&kind='+encodeURIComponent(kind):'',opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
    const r=await apiFetch('/api/debug-traces?limit=200'+suffix,opts);if(!isCurrent())return false;
    const d=await r.json();if(!isCurrent()||!d.success)return false;
    const items=Array.isArray(d.items)?d.items:[],changed=JSON.stringify(items)!==JSON.stringify(lastTraces);
    if(changed){lastTraces=items;renderTraceList(lastTraces)}
    return {changed};
  }catch(e){if(isCurrent()&&!controller?.signal.aborted)console.warn('trace refresh failed',e);return false}
  finally{tracesPollInFlight=false;if(tracesPollAbortController===controller)tracesPollAbortController=null}
}
$('traceRefresh')?.addEventListener('click',pollTraces);$('traceKind')?.addEventListener('change',()=>renderTraceList(lastTraces));
$('traceHistorySearch')?.addEventListener('input',()=>renderTraceList(lastTraces));$('traceHistoryState')?.addEventListener('change',()=>renderTraceList(lastTraces));

async function probeHealth(){
  try{
    const r=await nativeFetch('/health',{cache:'no-store'});
    if(r.ok&&!hasLiveStatus){$('conn').textContent='online';$('conn').className='pill ok'}
  }catch(e){if(!hasLiveStatus){$('conn').textContent='offline';$('conn').className='pill bad-t'}}
}
async function pollStatus(isCurrent=()=>document.visibilityState!=='hidden'){
  if(document.visibilityState==='hidden'||!isCurrent())return false;
  if(statusPollInFlight)return true;
  statusPollInFlight=true;
  const controller=typeof AbortController==='function'?new AbortController():null;
  statusPollAbortController=controller;
  const current=()=>document.visibilityState!=='hidden'&&isCurrent();
  try{
    const opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
    const r=await apiFetch('/api/live/status?light=1&scope='+sloScope,opts);
    if(!current())return false;
    if(!r.ok)throw new Error(`status request failed (HTTP ${r.status})`);
    const s=await r.json();
    if(!current())return false;
    if(s.snapshot_warming===true){
      lastDashboardStatusChanged=false;
      if(!hasLiveStatus){$('conn').textContent='warming';$('conn').className='pill warn-t'}
      return false;
    }
    const statusDegraded=s.snapshot_stale===true||s.degraded===true||s.success===false;
    const changed=shouldRefreshDashboardStatus(s);
    if(changed)render(s);
    hasLiveStatus=true;$('conn').textContent=s.snapshot_stale===true?'stale':statusDegraded?'degraded':'live';$('conn').className=statusDegraded?'pill warn-t':'pill ok';if(changed)$('updated').textContent='updated '+new Date().toLocaleTimeString();
    if(s.success===false){$('conn').textContent=s.snapshot_stale===true?'stale':'degraded';$('conn').className='pill warn-t';return false}
    if(changed||hardwareRefreshPending)try{
      const hardwareOpts={cache:'no-store'};if(controller)hardwareOpts.signal=controller.signal;
      const gr=await apiFetch('/api/hardware/system',hardwareOpts);
      if(!current())return false;
      if(gr.ok){
        const sys=await gr.json(), g=sys.gpu||{}, ram=sys.ram||{};
        const pct=value=>value==null||!Number.isFinite(Number(value))?null:Math.max(0,Math.min(100,Number(value)));
        const cpuUtil=pct(sys.cpu_utilization_pct), gpuUtil=pct(g.gpu_utilization_pct), ramPct=Number(ram.used_pct||0);
        const npus=Array.isArray(sys.npus)?sys.npus:[], ov=Array.isArray(sys.openvino_devices)?sys.openvino_devices:[], gpus=Array.isArray(sys.gpus)?sys.gpus:[];
        const igpuAvailable=Boolean(sys.igpu_available||g.integrated||gpus.some(x=>x.integrated)), igpuUtil=pct(sys.igpu_utilization_pct??(g.integrated?g.gpu_utilization_pct:null));
        const npuAvailable=Boolean(sys.npu_available||npus.length||ov.some(x=>x.kind==='npu')), npuUtil=pct(sys.npu_utilization_pct);
        const loads=[['CPU',cpuUtil]];
        if(g.available&&!g.integrated)loads.push(['GPU',gpuUtil]);
        if(igpuAvailable)loads.push(['iGPU',igpuUtil]);
        if(npuAvailable)loads.push(['NPU',npuUtil]);
        const knownLoads=loads.map(x=>x[1]).filter(x=>x!==null), peak=knownLoads.length?Math.max(...knownLoads):0;
        const barColor=peak>80?'var(--bad)':peak>50?'var(--warn)':'var(--ok)';
        const loadText=loads.map(([label,value])=>`${label} ${value===null?'—':`${Math.round(value)}%`}`).join(' · ');
        $('sysUtil').innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center"><span>${loadText}</span><span class="tiny muted">${sys.cpu_count||1} threads</span></div><div class="bar"><i style="width:${peak}%;background:${barColor}"></i></div>`;
        const vram=g.available?(g.vram_total_mb&&!g.integrated?` · VRAM ${Math.round(g.vram_used_mb||0)} / ${Math.round(g.vram_total_mb)} MB`:g.unified_memory_mb?` · Unified memory ${Math.round(g.unified_memory_mb)} MB`:g.integrated?' · shared-memory iGPU':''):'';
        const accel=npus.length?` · NPU ${npus[0].runtime_available?'ready':'detected'}`:(ov.some(x=>x.kind==='gpu')?' · OpenVINO GPU ready':'');
        $('sysSub').textContent=`RAM ${ram.used_gb||0} / ${ram.total_gb||0} GB (${ramPct}%)${vram}${accel}`;
        hardwareRefreshPending=false;
      }else{
        hardwareRefreshPending=true;
      }
    }catch{hardwareRefreshPending=true}
    return true;
  }catch(e){
    if(!current())return false;
    console.error('dashboard status refresh failed',e);if(last&&lastOverviewReceivedAt)renderOverviewHealth(last,lastOverviewReceivedAt);$('conn').textContent=hasLiveStatus?'stale':'offline';$('conn').className=hasLiveStatus?'pill warn-t':'pill bad-t';return false;
  }finally{statusPollInFlight=false;if(statusPollAbortController===controller)statusPollAbortController=null}
}
const statusPoller=createDashboardStatusPoller(isCurrent=>pollStatus(isCurrent));
document.addEventListener('visibilitychange',()=>{
  const visible=document.visibilityState!=='hidden';
  statusPoller.setVisible(visible);
  if(!visible&&statusPollAbortController)statusPollAbortController.abort();
});
statusPoller.start();
let liveEvents=[],eventsPollInFlight=false,tracesPollInFlight=false,eventsPollHasLoaded=false;
let eventsPollAbortController=null,tracesPollAbortController=null;
function eventSeverity(event){
  if(event?.success===false||Number(event?.status_code)>=400||/fail|error|crash|reject/i.test([event?.kind,event?.event_type,event?.status].join(' ')))return 'failure';
  if(/warn|retry|degrad|stale/i.test([event?.kind,event?.event_type,event?.status].join(' ')))return 'warning';
  if(event?.success===true)return 'success';
  return 'info';
}
function renderEvents(events=liveEvents){
  if(Array.isArray(events)&&events.length){liveEvents=[...events,...liveEvents].slice(0,300);}
  if(paused)return;
  const box=$('eventList');if(!box)return;
  const severity=String($('eventSeverity')?.value||''),source=String($('eventSource')?.value||'').trim().toLowerCase();
  const filtered=liveEvents.filter(event=>{const kind=eventSeverity(event),hay=[event.agent,event.kind,event.event_type,event.action,event.stage,event.model].filter(Boolean).join(' ').toLowerCase();return (!severity||kind===severity)&&(!source||hay.includes(source));}).slice(0,120);
  const summary=$('eventSummary');if(summary)summary.textContent=`${filtered.length} of ${liveEvents.length} retained events`;
  const html=filtered.map(e=>{const id='d'+(++seq),severity=eventSeverity(e),traceId=e.trace_id?String(e.trace_id):'',traceAttr=traceId?` data-trace-id="${esc(traceId)}"`:'';dataStore.set(id,{data:e,type:'event'});if(dataStore.size>5000){dataStore.delete(dataStore.keys().next().value);}const label=severity==='failure'?'FAIL':severity==='warning'?'WARN':severity==='success'?'OK':'INFO';return `<div class="event click"${traceAttr} data-detail="${id}" data-type="event"><span>${new Date((e.created_at||0)*1000).toLocaleTimeString()}</span><span>${esc(e.agent||e.kind||'')}</span><span>${esc(e.event_type||'')}</span><span>${esc(e.action||e.stage||'')}</span><span class="hide-sm">${esc(e.model||'')}</span><span>${e.duration_ms?ms(e.duration_ms):''}</span><span class="${severity==='failure'?'bad-t':severity==='warning'?'warn-t':severity==='success'?'ok':'muted'}">${label}</span></div>`}).join('');
  box.innerHTML=html||'<div class="empty">No events match current severity/source filters.</div>';
}
$('eventSeverity')?.addEventListener('change',()=>renderEvents([]));
$('eventSource')?.addEventListener('input',()=>renderEvents([]));
async function pollEvents(isCurrent=()=>document.visibilityState!=='hidden'){
  if(!isCurrent()||eventsPollInFlight)return false;
  eventsPollInFlight=true;
  const controller=typeof AbortController==='function'?new AbortController():null;
  eventsPollAbortController=controller;
  try{
    const previousCursor=cursor,opts={cache:'no-store'};if(controller)opts.signal=controller.signal;
    const r=await apiFetch('/api/live?after='+cursor+'&limit=200',opts);if(!isCurrent())return false;
    const d=await r.json();if(!isCurrent()||!d.success)return false;
    const events=Array.isArray(d.events)?d.events:[];cursor=Number(d.cursor||cursor);
    const changed=!eventsPollHasLoaded||cursor!==previousCursor||events.length>0;eventsPollHasLoaded=true;
    if(changed)renderEvents(events);
    return {changed};
  }catch{return false}
  finally{eventsPollInFlight=false;if(eventsPollAbortController===controller)eventsPollAbortController=null}
}
const eventsPoller=createDashboardStatusPoller(pollEvents,{baseDelay:1000,maxDelay:30000});
const tracesPoller=createDashboardStatusPoller(pollTraces,{baseDelay:2000,maxDelay:30000});

if(!document.hidden)probeHealth();
eventsPoller.start();tracesPoller.start();
let isVisible=!document.hidden;
document.addEventListener('visibilitychange',()=>{
  isVisible=!document.hidden;
  if(!isVisible){eventsPollAbortController?.abort();tracesPollAbortController?.abort();tracePollAbortController?.abort();}
  eventsPoller.setVisible(isVisible);tracesPoller.setVisible(isVisible);traceDetailPoller?.setVisible(isVisible);
  if(isVisible)probeHealth();
});
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
  else projectAction(root,button.dataset.projectAction);
});
async function exportBundle(root){
  try{
  const r=await apiFetch('/api/bundle/export',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/zip'},body:JSON.stringify({root})});
  if(!r.ok){alert('Export failed: '+(await r.text()));return;}
  const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bundle.zip';a.click();URL.revokeObjectURL(url);
  }catch(error){alert('Export failed: '+String(error.message||error))}
}
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

// ── Agent OS ──────────────────────────────────────────────────────────────────
let agentOsTasks=[], agentOsMemories=[], agentOsIncidents=[],agentOsLoadErrors={};
function setAgentOsScopeReady(ready){
  ['agentOsCreateTaskBtn','agentOsRecordMemBtn','agentOsRecordIncBtn','agentOsCleanup'].forEach(id=>{if($(id))$(id).disabled=!ready});
}
async function loadAgentOsView(){
  const repoVal=$('agentOsRepoSelect')?.value?.trim()||'';
  const rootVal=$('agentOsRoot')?.value?.trim()||'';
  const selectedRoot=rootVal||repoVal||'';
  const isAll=!selectedRoot||selectedRoot.toLowerCase()==='all'||selectedRoot==='__all__';
  setAgentOsScopeReady(!isAll&&Boolean(selectedRoot));

  const tasksUrl=isAll?'/api/agent-state/tasks':`/api/agent-state/tasks?root=${encodeURIComponent(selectedRoot)}`;
  const memUrl=isAll?'/api/agent-state/memory':`/api/agent-state/memory?root=${encodeURIComponent(selectedRoot)}`;

  const promises=[
    fetchDashboardJson(tasksUrl,{cache:'no-store'}),
    fetchDashboardJson(memUrl,{cache:'no-store'})
  ];
  if(!isAll){
    promises.push(fetchDashboardJson('/api/agent-state/incidents',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'find',root:selectedRoot,limit:100})
    }));
  }
  const results=await Promise.allSettled(promises);
  if(($('agentOsRoot')?.value?.trim()||'')!==rootVal)return;

  agentOsLoadErrors={};
  if(results[0].status==='rejected'){
    agentOsLoadErrors.tasks=String(results[0].reason?.message||results[0].reason);
  }
  if(results[1].status==='rejected'){
    agentOsLoadErrors.memory=String(results[1].reason?.message||results[1].reason);
  }
  if(isAll){
    agentOsLoadErrors.incidents='Select a specific repository above to inspect negative knowledge & incidents.';
  }else if(results[2]?.status==='rejected'){
    agentOsLoadErrors.incidents=String(results[2].reason?.message||results[2].reason);
  }

  agentOsTasks=results[0].status==='fulfilled'?(results[0].value.tasks||[]):[];
  agentOsMemories=results[1].status==='fulfilled'?(results[1].value.records||[]):[];
  agentOsIncidents=(!isAll&&results[2]?.status==='fulfilled')?(results[2].value.incidents||[]):[];
  renderAgentOsView();
}

function switchAgentOsSubtab(tabKey){
  const subtabs=['tasks','memory','incidents','trajectories'];
  subtabs.forEach(t=>{
    const btn=$('subtab'+t.charAt(0).toUpperCase()+t.slice(1));
    const sec=$('agentOs'+t.charAt(0).toUpperCase()+t.slice(1)+'Sec');
    if(btn)btn.classList.toggle('active',t===tabKey);
    if(sec)sec.style.display=t===tabKey?'block':'none';
  });
  if(tabKey==='trajectories'){
    loadTrajectories();
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
    const hay=[t.task_id,t.contract?.goal,t.checkpoint?.phase,t.checkpoint?.next_action,t.repo_root].join(' ').toLowerCase();
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
    const incidentStatus=String(i.status||(i.verified_fix?'resolved':'unresolved'));
    if(incFilter!==''&&incidentStatus!==incFilter)return false;
    if(!incQuery)return true;
    const hay=[i.incident_id,i.error_class,i.redacted_message,i.root_cause,i.verified_fix,incidentStatus].join(' ').toLowerCase();
    return hay.includes(incQuery);
  });

  if($('agentOsSummary'))$('agentOsSummary').textContent=`${filteredTasks.length} tasks · ${filteredMem.length} memories · ${filteredInc.length} incidents`;
  if($('agentOsState')){
    const act=agentOsTasks.filter(t=>String(t.status).toLowerCase()==='active').length;
    const isAll=!$('agentOsRoot')?.value?.trim()&&!$('agentOsRepoSelect')?.value?.trim();
    $('agentOsState').textContent=`${act} active · ${agentOsTasks.length} total tasks${isAll?' (all repositories)':''} · ${agentOsMemories.length} memories`;
  }

  rows('agentOsTasksBody',filteredTasks,t=>{
    const st=String(t.status||'planned').toLowerCase();
    const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
    const goal=esc(t.contract?.goal||'—');
    const chk=t.checkpoint?`${esc(t.checkpoint.phase||'')} ➔ ${esc(t.checkpoint.next_action||'')}`:'—';
    const crit=(t.contract?.acceptance_criteria||[]).length?(t.contract.acceptance_criteria.length+' criteria'):'—';
    const dt=t.updated_at?new Date(t.updated_at*1000).toLocaleTimeString():'—';
    const repoLabel=t.repo_root?(t.repo_root.split(/[\\/]/).filter(Boolean).pop()||t.repo_root):(t.context?.repository_id||'—');
    return clickableRow(t,`<td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td><strong>${esc(t.task_id)}</strong></td><td title="${esc(t.repo_root||'')}"><span class="chip" style="max-width:140px;overflow:hidden;text-overflow:ellipsis">${esc(repoLabel)}</span></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${esc(t.contract?.scope||'task')}</span></td><td class="tiny">${chk}</td><td class="tiny">${esc(crit)}</td><td class="tiny">${dt}</td>`,'task',t.task_id);
  },8,'No Agent OS tasks found.');

  rows('agentOsMemoryBody',filteredMem,m=>{
    const sc=esc(m.scope||'task');
    const kd=esc(m.kind||'fact');
    const k=esc(m.key||'—');
    let v=typeof m.value==='object'?JSON.stringify(m.value):String(m.value||'');
    if(v.length>55)v=v.slice(0,52)+'...';
    const conf=m.confidence!==undefined?Math.round(m.confidence*100)+'%':'—';
    const src=esc(m.source||'—');
    const dt=m.created_at?new Date(m.created_at*1000).toLocaleTimeString():'—';
    return clickableRow(m,`<td><span class="chip">${sc}</span></td><td><span class="chip">${kd}</span></td><td><strong>${k}</strong></td><td class="tiny mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${esc(v)}</td><td class="tiny">${conf}</td><td class="tiny">${src}</td><td class="tiny">${dt}</td>`,'memory',(m.scope||'task')+':'+m.key);
  },7);

  rows('agentOsIncBody',filteredInc,i=>{
    const id=esc(i.incident_id||'—');
    const status=String(i.status||(i.verified_fix?'resolved':'unresolved'));
    const statusChip=status==='ignored'?'<span class="chip">ignored</span>':status==='resolved'?'<span class="chip ok">resolved</span>':'<span class="chip warn-t">unresolved</span>';
    const op=esc(i.operation_class||i.outcome?.tool_name||'agent');
    const ec=esc(i.error_class||'Error');
    let msg=esc(i.redacted_message||'');
    if(msg.length>45)msg=msg.slice(0,42)+'...';
    const cause=esc(i.root_cause||'—');
    const fix=esc(i.verified_fix||'—');
    return clickableRow(i,`<td><strong>${id}</strong></td><td>${statusChip}</td><td>${n(i.attempts||1)}</td><td><span class="chip">${op}</span></td><td><span class="chip bad-t">${ec}</span></td><td class="tiny" title="${esc(i.redacted_message||'')}">${msg}</td><td class="tiny">${cause}</td><td class="tiny ok">${fix}</td>`,'incident',i.incident_id);
  },8);
  renderAgentOsLoadErrors();
}

function renderAgentOsLoadErrors(){
  const failed=Object.keys(agentOsLoadErrors);
  if(failed.length&&!$('agentOsTasksBody')?.children?.length){
    if($('agentOsState'))$('agentOsState').textContent='Partially unavailable · '+failed.join(', ');
    if($('agentOsSummary'))$('agentOsSummary').textContent='Some data could not be loaded. Refresh to retry.';
  }
  [['tasks','agentOsTasksBody',8],['memory','agentOsMemoryBody',7],['incidents','agentOsIncBody',8]].forEach(([key,id,columns])=>{
    if(agentOsLoadErrors[key]&&$(id))$(id).innerHTML=`<tr><td colspan="${columns}" class="empty warn-t">${esc(agentOsLoadErrors[key])}</td></tr>`;
  });
}

$('agentOsRefresh')?.addEventListener('click',loadAgentOsView);
$('agentOsRepoSelect')?.addEventListener('change',()=>{
  const val=$('agentOsRepoSelect').value;
  if($('agentOsRoot'))$('agentOsRoot').value=val;
  loadAgentOsView();
});
$('agentOsRoot')?.addEventListener('change',()=>{
  const val=$('agentOsRoot').value.trim();
  if($('agentOsRepoSelect'))$('agentOsRepoSelect').value=val;
  loadAgentOsView();
});
$('agentOsRoot')?.addEventListener('keydown',event=>{if(event.key==='Enter')loadAgentOsView()});
$('agentOsCleanup')?.addEventListener('click',openCleanupModal);
$('agentOsSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsTaskStatus')?.addEventListener('change',renderAgentOsView);
$('agentOsMemSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsMemScope')?.addEventListener('change',renderAgentOsView);
$('agentOsMemKind')?.addEventListener('change',renderAgentOsView);
$('agentOsIncSearch')?.addEventListener('input',renderAgentOsView);
$('agentOsIncFilter')?.addEventListener('change',renderAgentOsView);

// Create Task Modal
$('agentOsCreateTaskBtn')?.addEventListener('click',openCreateTaskModal);

// Record Memory Modal
$('agentOsRecordMemBtn')?.addEventListener('click',openRecordMemoryModal);

// Record Incident Modal
$('agentOsRecordIncBtn')?.addEventListener('click',openRecordIncidentModal);

// ── Models, RAG & Leases ──────────────────────────────────────────────────────
let ragWorkspaces=[];
function ragWorkspaceIdentity(workspace){return String(workspace?.root||workspace?.repository_root||workspace?.workspace||workspace?.id||workspace||'unknown');}
function renderRagWorkspaces(){
  const list=$('ragWorkspacesList');if(!list)return;
  const query=String($('ragWorkspaceSearch')?.value||'').trim().toLowerCase();
  const visible=ragWorkspaces.filter(w=>{const identity=ragWorkspaceIdentity(w);return !query||[identity,w.status,w.state,w.model].filter(Boolean).join(' ').toLowerCase().includes(query)});
  const summary=$('ragWorkspaceSummary');if(summary)summary.textContent=`${visible.length} of ${ragWorkspaces.length} workspaces · canonical identity and index state`;
  list.innerHTML=visible.length?`<div class="table-wrap"><table><thead><tr><th>Workspace identity</th><th>Index status</th><th>Contents</th></tr></thead><tbody>${visible.map(w=>{
    const identity=ragWorkspaceIdentity(w),chunks=Number(w.chunks??w.document_count??w.count??0),state=String(w.status||w.state||'status unreported'),stateClass=/error|failed/i.test(state)?'bad-t':/^(ready|complete|completed)$/i.test(state)?'ok':'muted';
    const contents=[chunks&&`${n(chunks)} chunks`,w.files&&`${n(w.files)} files`,w.embedding_model&&String(w.embedding_model)].filter(Boolean).join(' · ')||'No indexed content reported';
    return `<tr><td><b>${esc(identity.split('/').filter(Boolean).pop()||identity)}</b><div class="tiny muted mono" title="${esc(identity)}">${esc(identity)}</div></td><td><span class="${stateClass}">${esc(humanLabel(state))}</span></td><td class="tiny">${esc(contents)}</td></tr>`;
  }).join('')}</tbody></table></div>`:'<span class="muted">No RAG workspace matches current search.</span>';
}
async function loadRagWorkspaces(){
  try{
    const d=await fetchDashboardJson('/api/rag/workspaces',{cache:'no-store'});
    ragWorkspaces=d.workspaces||[];
    renderRagWorkspaces();
  }catch(e){if($('ragWorkspacesList'))$('ragWorkspacesList').textContent='Failed to load workspaces'}
}
$('ragWorkspaceSearch')?.addEventListener('input',renderRagWorkspaces);

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

// ── Local Model Arena Benchmark ───────────────────────────────────────────
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
    btn.disabled=false;btn.textContent='Run Arena Benchmark';
  }
});

// ── Trajectory & Step Inspector ───────────────────────────────────────────
let cachedTrajTasks=[];

async function loadTrajectories(){
  try{
    const d=await fetchDashboardJson('/api/agent-state/tasks?limit=100',{cache:'no-store'});
    cachedTrajTasks=d.tasks||[];
    renderTrajectories();
  }catch(e){
    if($('trajSummary'))$('trajSummary').textContent='Run history unavailable';
    if($('trajTableBody'))$('trajTableBody').innerHTML=`<tr><td colspan="6" class="empty warn-t">${esc(e.message||e)}. Refresh to retry.</td></tr>`;
  }
}

function renderTrajectories(){
  const q=String($('trajSearch')?.value||'').trim().toLowerCase();
  const list=cachedTrajTasks.filter(t=>{
    if(!q)return true;
    const hay=[t.task_id,t.contract?.goal,t.status,t.owner].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(q);
  });
  if($('trajSummary'))$('trajSummary').textContent=`${list.length} trajectories · click to inspect steps`;
  rows('trajTableBody',list,t=>{
    const tid=esc(t.task_id||'—');
    const goal=esc(t.contract?.goal||'—');
    const st=String(t.status||'planned').toLowerCase();
    const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
    const stepsCount=n(t.checkpoint?.affected_paths?.length)+' paths / '+n(Object.keys(t.verification_receipts||{}).length)+' receipts';
    const tokensUsed=t.checkpoint?.state_data?.tokens_used!=null?n(t.checkpoint.state_data.tokens_used):'Unreported';
    const act=`<button class="action-btn-sm" data-view-traj="${tid}">Inspect</button>`;
    return `<tr class="click" data-view-traj="${tid}"><td><strong>${tid}</strong></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${stepsCount}</span></td><td class="tiny mono">${tokensUsed}</td><td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td>${act}</td></tr>`;
  },6);
}

$('trajSearch')?.addEventListener('input',renderTrajectories);
$('trajRefreshBtn')?.addEventListener('click',loadTrajectories);

async function viewTrajectory(taskId, afterSeq=0, append=false){
  if(!taskId)return;
  const task=cachedTrajTasks.find(t=>t.task_id===taskId);
  const panel=$('trajDetailPanel');
  const title=$('trajDetailTitle');
  const list=$('trajStepsList');
  if(!panel||!list||!title)return;
  panel.style.display='block';
  title.innerHTML=`Trajectory Inspection: <code>${esc(taskId)}</code> — <span class="muted">${esc(task?.contract?.goal||'')}</span>`;
  if(!append)list.innerHTML='<div class="tiny muted">Loading event stream & trajectory steps…</div>';
  else list.querySelector('.trajectory-load-more')?.remove();

  try{
    const params=new URLSearchParams({stream_id:taskId,limit:'100'});
    if(afterSeq>0)params.set('after_seq',String(afterSeq));
    const r=await apiFetch('/api/agent-state/events?'+params.toString(),{cache:'no-store'});
    const responseText=await r.text();
    const d=JSON.parse(responseText);
    const evs=Array.isArray(d.events)?d.events:[];
    const gapRanges=Array.isArray(d.gap_ranges)?d.gap_ranges.slice():[];
    const gapMetadataUnavailable=d.retention_gap_metadata_available===false||
      !Array.isArray(d.gap_ranges);
    if(!append)list.innerHTML='';
    if(gapMetadataUnavailable&&!gapRanges.length&&!list.querySelector('.trajectory-gap')){
      const gap=document.createElement('div');
      gap.className='trace-event trajectory-gap';
      gap.style.cssText='border-left:2px solid #f0ad4e;padding:8px;margin-bottom:8px;color:#f0ad4e';
      gap.textContent='Retention gap metadata unavailable; cannot verify history completeness.';
      list.appendChild(gap);
    }
    if(!evs.length&&!append){
      const cp=task?.checkpoint||{};
      const receipts=Object.entries(task?.verification_receipts||{});
      list.insertAdjacentHTML('beforeend',`<div class="trace-event" style="border-left:2px solid var(--accent);padding:8px;margin-bottom:8px">
        <div style="font-weight:600;font-size:12px;margin-bottom:4px">Phase: ${esc(cp.phase||'init')} ➔ Next: ${esc(cp.next_action||'—')}</div>
        <div class="tiny muted">Affected Paths: ${esc((cp.affected_paths||[]).join(', ')||'none')}</div>
        <div class="tiny muted">Evidence IDs: ${esc((cp.evidence_ids||[]).join(', ')||'none')}</div>
        ${receipts.length?`<div style="margin-top:6px;font-size:11px"><b>Receipts:</b> ${receipts.map(([k,v])=>`<span class="chip ok">${esc(k)}</span>`).join(' ')}</div>`:''}
      </div>`);
    }
    const skipQuotedString=(jsonText,start)=>{
      let escaped=false;
      for(let i=start+1;i<jsonText.length;i++){
        const ch=jsonText[i];
        if(escaped)escaped=false;
        else if(ch==='\\')escaped=true;
        else if(ch==='"')return i;
      }
      return jsonText.length;
    };
    const readRawInteger=(jsonText,key)=>{
      let depth=0;
      for(let i=0;i<jsonText.length;i++){
        if(jsonText[i]==='"'){
          const end=skipQuotedString(jsonText,i);
          if(depth===1){
            const name=JSON.parse(jsonText.slice(i,end+1));
            let valueIndex=end+1;
            while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
            if(name===key&&jsonText[valueIndex++]===':'){
              while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
              const number=/^-?\d+/.exec(jsonText.slice(valueIndex));
              if(!number)return null;
              const delimiter=jsonText[valueIndex+number[0].length];
              return delimiter&&/[.eE\d]/.test(delimiter)?null:number[0];
            }
          }
          i=end;
          continue;
        }
        if(jsonText[i]==='{'||jsonText[i]==='[')depth++;
        else if(jsonText[i]==='}'||jsonText[i]===']')depth--;
      }
      return null;
    };
    const readTopLevelArrayObjects=(jsonText,key)=>{
      let depth=0;
      for(let i=0;i<jsonText.length;i++){
        if(jsonText[i]==='"'){
          const end=skipQuotedString(jsonText,i);
          if(depth===1){
            const name=JSON.parse(jsonText.slice(i,end+1));
            let valueIndex=end+1;
            while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
            if(name===key&&jsonText[valueIndex++]===':'){
              while(/\s/.test(jsonText[valueIndex]||''))valueIndex++;
              if(jsonText[valueIndex]!=='[')return [];
              const items=[];
              for(let itemIndex=valueIndex+1;itemIndex<jsonText.length;){
                while(/[\s,]/.test(jsonText[itemIndex]||''))itemIndex++;
                if(jsonText[itemIndex]===']')return items;
                if(jsonText[itemIndex]!=='{')return [];
                const start=itemIndex;
                let objectDepth=0;
                for(;itemIndex<jsonText.length;itemIndex++){
                  if(jsonText[itemIndex]==='"'){
                    itemIndex=skipQuotedString(jsonText,itemIndex);
                    continue;
                  }
                  if(jsonText[itemIndex]==='{')objectDepth++;
                  else if(jsonText[itemIndex]==='}'&&--objectDepth===0){
                    items.push(jsonText.slice(start,itemIndex+1));
                    itemIndex++;
                    break;
                  }
                }
              }
              return [];
            }
          }
          i=end;
          continue;
        }
        if(jsonText[i]==='{'||jsonText[i]==='[')depth++;
        else if(jsonText[i]==='}'||jsonText[i]===']')depth--;
      }
      return [];
    };
    const readRawArrayIntegers=(jsonText,arrayKey,fieldKey)=>
      readTopLevelArrayObjects(jsonText,arrayKey).map(item=>readRawInteger(item,fieldKey));
    const exactEventSeqs=readRawArrayIntegers(responseText,'events','seq');
    const exactGapStarts=readRawArrayIntegers(responseText,'gap_ranges','from_seq');
    const exactGapEnds=readRawArrayIntegers(responseText,'gap_ranges','to_seq');
    const exactFirstRetainedSeq=readRawInteger(responseText,'first_retained_seq')??d.first_retained_seq;
    const timeline=[
      ...evs.map((ev,index)=>({type:'event',seq:exactEventSeqs[index]??ev.seq,ev})),
      ...gapRanges.map((range,index)=>({
        type:'gap',seq:exactGapStarts[index]??range.from_seq,
        fromSeq:exactGapStarts[index]??range.from_seq,
        toSeq:exactGapEnds[index]??range.to_seq,range,
      })),
    ];
    timeline.sort((left,right)=>{
      try{
        const a=BigInt(String(left.seq??0));
        const b=BigInt(String(right.seq??0));
        return a<b?-1:(a>b?1:0);
      }catch{
        return String(left.seq??0).localeCompare(String(right.seq??0),undefined,{numeric:true});
      }
    });
    timeline.forEach(item=>{
      if(item.type==='gap'){
        const gap=document.createElement('div');
        gap.className='trace-event trajectory-gap';
        gap.style.cssText='border-left:2px solid #f0ad4e;padding:8px;margin-bottom:8px;color:#f0ad4e';
        gap.textContent=`Event history gap: expired #${item.fromSeq}–#${item.toSeq}; first retained #${exactFirstRetainedSeq??'unknown'}.`;
        list.appendChild(gap);
        return;
      }
      const ev=item.ev;
      const kind=esc(ev.event_type||ev.kind||'event');
      const timestamp=ev.created_at??ev.timestamp;
      const time=timestamp?new Date(timestamp*1000).toLocaleTimeString():'';
      const payload=traceOutputValueMarkup(ev.payload, null, 5000);
      list.insertAdjacentHTML('beforeend',`<div class="trace-event" style="border-left:2px solid var(--accent);padding:8px;margin-bottom:8px;background:#0d1219;border-radius:4px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span class="chip"><b>${kind}</b></span>
          <span class="tiny muted">#${esc(item.seq||0)} · ${time}</span>
        </div>
        <div style="margin:0;font-size:11px;color:#d7e2ef;max-height:220px;overflow:auto">${payload}</div>
      </div>`);
    });
    const cursorToken=readRawInteger(responseText,'next_seq')??String(d.next_seq??afterSeq);
    let cursorAdvances=false;
    try{cursorAdvances=BigInt(cursorToken)>BigInt(String(afterSeq));}catch{}
    if(d.has_more&&cursorAdvances){
      const button=document.createElement('button');
      button.type='button';
      button.className='trajectory-load-more';
      button.style.cssText='margin:8px 0;padding:6px 10px';
      button.textContent='Load more events';
      button.onclick=()=>viewTrajectory(taskId,cursorToken,true);
      list.appendChild(button);
    }
  }catch(err){
    if(append){
      const error=document.createElement('div');
      error.className='bad-t';
      error.textContent=`Failed to load trajectory events: ${err.message||err}`;
      list.appendChild(error);
    }else{
      list.innerHTML=`<div class="bad-t">Failed to load trajectory events: ${esc(err.message||err)}</div>`;
    }
  }
}

document.addEventListener('click',e=>{
  const el=e.target.closest?.('[data-view-traj]');
  if(el){
    const tid=el.dataset.viewTraj;
    viewTrajectory(tid);
  }
});

// Quick keyboard tab shortcuts
window.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT')return;
  if(e.key==='1')switchTab('overview');
  if(e.key==='2')switchTab('work');
  if(e.key==='3')switchTab('agentos');
  if(e.key==='4')switchTab('projects');
  if(e.key==='6')switchTab('commands');
  if(e.key==='8')switchTab('performance');
  if(e.key==='9')switchTab('reliability');
  if(e.key==='0')switchTab('config');
});

let initTab = 'overview';
try{initTab = location.hash.replace('#','') || localStorage.getItem('activeTab') || 'overview';}catch{initTab = location.hash.replace('#','') || 'overview';}
switchTab(initTab);
</script></body></html>"""
