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
.section.rag-narrow{width:min(100%, 960px);max-width:960px;margin:12px auto 0}
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
    <span class="tiny spacer">Agent debug traces · bounded prompt/output retention</span>
    <span id="featSummary" class="pill tiny"></span>
    <details id="controlMenu" class="control-menu">
      <summary>Controls</summary>
      <div class="control-popover">
        <div class="token"><input type="password" id="apiToken" autocomplete="off" placeholder="API token (remote only)"><button class="btn" id="saveToken">Set token</button></div>
        <div class="tiny muted">Diagnostics</div>
        <button class="btn ok" id="optDbBtn">Optimize databases</button>
        <button class="btn" id="doctorBtn">Run diagnostics</button>
        <button class="btn" id="pauseEvents">Pause event display</button>
        <div class="tiny muted">Runtime control</div>
        <button class="btn warn" id="prepToggle">Pause preprocessing</button>
        <button class="btn" id="restartHub" data-control-action="restart_hub">Restart hub service</button>
        <div class="tiny muted">Destructive maintenance</div>
        <button class="btn warn" id="purgeCacheBtn" data-control-action="purge_cache">Purge expired cache</button>
        <button class="btn bad" id="stopService" data-control-action="stop_service">Stop hub service</button>
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
  <section id="overviewHealthSummary" class="section" style="margin-bottom:12px;padding:14px;border-left:4px solid var(--accent)">
    <div class="label">Operational summary</div>
    <div class="value primary-metric" id="overviewHealthLevel">Loading runtime health…</div>
    <div class="sub" id="overviewHealthEvidence">Waiting for live status.</div>
    <div class="tiny muted" id="overviewFreshness">Timestamp unavailable</div>
    <button type="button" class="btn" id="overviewHealthAction" style="margin-top:10px">Open details</button>
    <div id="overviewAnnouncement" aria-live="polite" aria-atomic="true" style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0"></div>
  </section>
  <div class="dash-group">
    <div class="group-title"><span>Host &amp; System Health</span><span class="tiny muted">Core runtime state, capacity and supervisory control</span></div>
    <div class="grid grid-3">
      <div class="card" id="hubHealthCard" style="cursor:pointer" title="Click to open Reliability &amp; Restart history"><div class="label" style="display:flex;justify-content:space-between"><span>Hub health</span><span>↗</span></div><div class="value primary-metric" id="health">…</div><div class="sub" id="uptime"></div></div>
      <div class="card system-card"><div class="label">Host Hardware</div><div class="value" id="sysUtil">…</div><div class="sub" id="sysSub"></div></div>
      <div class="card" id="agentStateCard" style="cursor:pointer" title="Click to open Agent OS inspector"><div class="label" style="display:flex;justify-content:space-between"><span>Agent OS State</span><span>↗</span></div><div class="value primary-metric" id="agentStateVal">…</div><div class="sub" id="agentStateSub"></div></div>
    </div>
  </div>

  <div class="dash-group">
    <div class="group-title"><span>Performance &amp; Token Efficiency</span><span class="tiny muted">Net cloud avoidance after agent tool-call/read overhead, local compute reuse and tail latency</span></div>
    <div class="grid grid-6">
      <div class="card"><div class="label">Requests handled</div><div class="value primary-metric" id="handledRequests">…</div><div class="sub" id="handledRequestsSub"></div><canvas id="throughputSpark" class="spark-canvas" width="160" height="30"></canvas></div>
      <div class="card"><div class="label">Net cloud token delta</div><div class="value primary-metric" id="tokensSaved">…</div><div class="sub" id="tokensSavedSub"></div></div>
      <div class="card"><div class="label">Estimated savings</div><div class="value primary-metric" id="dollarsSaved">…</div><div class="sub" id="dollarsSavedSub"></div></div>
      <div class="card"><div class="label">Generation cache hit rate</div><div class="value primary-metric" id="cache">…</div><div class="sub" id="cacheSub"></div></div>
      <div class="card"><div class="label">Latency p50 / p95 / p99</div><div class="value" id="latency">…</div><div class="sub" id="queueWait"></div><canvas id="latencySpark" class="spark-canvas" width="160" height="30"></canvas></div>
      <div class="card"><div class="label">Reliability</div><div class="value primary-metric" id="reliabilityValue">…</div><div class="sub" id="reliabilitySub"></div></div>
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
  <section class="section"><h2>Live scheduler work <span class="tiny" id="queueSummary">Current queue only; not request history.</span></h2><div class="table-wrap"><table><thead><tr><th>State</th><th>Job</th><th>Agent/tenant</th><th>Source</th><th>Model</th><th>Priority</th><th>Wait</th><th>Processing</th><th>Reason</th></tr></thead><tbody id="jobs"></tbody></table></div></section>
  <section class="section"><h2>Active API requests <span class="tiny">monitoring endpoints excluded</span></h2><div class="table-wrap"><table><thead><tr><th>Request</th><th>Agent</th><th>Tenant</th><th>Action</th><th>Age</th></tr></thead><tbody id="activeReq"></tbody></table></div></section>
  <section class="section"><h2>Request history — Recent API requests <span class="tiny">Persisted API telemetry; distinct from scheduler work and Agent OS task runs.</span></h2><div class="request-filter"><input id="requestHistorySearch" type="search" placeholder="Search request ID, route, agent, tenant, error…" autocomplete="off"><select id="requestHistoryAction" aria-label="Filter by endpoint"><option value="">All endpoints</option></select><select id="requestHistoryStatus" aria-label="Filter by status"><option value="">All results</option><option value="failed">Failed</option><option value="2xx">2xx</option><option value="4xx">4xx</option><option value="5xx">5xx</option></select><select id="requestHistoryPeriod" aria-label="Filter by time"><option value="">All loaded</option><option value="3600">Last hour</option><option value="86400">Last 24 hours</option><option value="604800">Last 7 days</option><option value="2592000">Last 30 days</option></select><button class="btn" id="requestHistoryReset">Reset</button><span class="tiny request-summary" id="requestHistorySummary">0 requests</span></div><div class="table-wrap"><table><thead><tr><th>Time</th><th>Request</th><th>Agent</th><th>Tenant</th><th>Action</th><th>Status</th><th>Trace availability</th><th>Duration</th></tr></thead><tbody id="recentReq"></tbody></table></div></section>
</div>

<div id="agentos" class="page">
  <div id="agentOsDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Agent OS feature is disabled in configuration</b> (<code>features.agent_os = false</code>). Durable task tracking and memory are inactive.</div>
  <section class="section">
    <h2><span style="display:flex;align-items:center;gap:8px">Agent Operating System <span class="tiny" id="agentOsState">0 active · 0 total tasks · 0 memories</span></span><div style="display:flex;gap:6px;align-items:center"><button class="btn ok" id="agentOsRefresh" style="padding:4px 10px;font-size:11px">↻ Refresh</button><button class="btn warn" id="agentOsCleanup" style="padding:4px 10px;font-size:11px">🧹 Cleanup stale state</button></div></h2>
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
        <select id="agentOsIncFilter" aria-label="Incident status"><option value="">All incidents</option><option value="unresolved">Unresolved</option><option value="resolved">Resolved with fix</option><option value="ignored">Ignored</option></select>
        <button class="btn warn" id="agentOsRecordIncBtn" style="padding:5px 9px">+ Record Anti-Pattern</button>
      </div>
      <div class="table-wrap"><table><thead><tr><th>Incident ID</th><th>Status</th><th>Attempts</th><th>Operation</th><th>Error Class</th><th>Redacted Message</th><th>Root Cause</th><th>Verified Fix</th></tr></thead><tbody id="agentOsIncBody"></tbody></table></div>
    </section>
  </div>

  <div id="agentOsTrajectoriesSec" style="display:none">
    <section class="section">
      <div class="project-toolbar">
        <input id="trajSearch" type="search" placeholder="Search task runs..." autocomplete="off">
        <button class="btn ok" id="trajRefreshBtn" style="padding:5px 9px">↻ Refresh Run History</button>
        <span class="tiny project-summary" id="trajSummary">Durable Agent OS tasks, checkpoints, and verification receipts — no HTTP request history.</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Task</th><th>Goal</th><th>Steps</th><th>Tokens Used</th><th>State</th><th>Actions</th></tr></thead>
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
      <div class="trace-toolbar"><span class="tiny">Inspect request events, model prompts, tool calls, and outputs.</span><select id="traceKind"><option value="">All kinds</option><option value="api_request">API requests</option><option value="async_job">Async jobs</option></select><button class="btn" id="traceRefresh" style="padding:4px 8px;font-size:11px">Refresh</button></div>
      <div class="table-wrap"><table><thead><tr><th>State</th><th>Kind</th><th>Action</th><th>Agent / tenant</th><th>Model</th><th>Created</th><th>Updated</th><th>Links</th></tr></thead><tbody id="traces"></tbody></table></div>
    </section>
  </div>
</div>


<div id="projects" class="page">
  <div id="prepDiagnosticBar" class="diag-banner info" style="display:none"></div>
  <section class="section">
    <h2><span style="display:flex;align-items:center;gap:8px">Projects <span class="tiny" id="prepState">0 registered projects · global running</span></span><div style="display:flex;gap:6px;align-items:center"><button class="btn warn" id="prepAllToggle" style="padding:4px 10px;font-size:11px">Pause all projects</button><button class="btn ok" id="regProjectBtn" style="padding:4px 10px;font-size:11px">+ Register</button><button class="btn warn" id="cleanMissingBtn" style="padding:4px 10px;font-size:11px">🧹 Clean missing</button></div></h2>
    <div class="project-toolbar"><input id="projectSearch" type="search" placeholder="Search repository identity, project, or worktree…" autocomplete="off"><select id="projectFilter" aria-label="Project status"><option value="all">All states</option><option value="running">Running</option><option value="waiting">Waiting</option><option value="error">Error</option><option value="paused">Paused</option><option value="ready">Ready</option></select><label class="tiny"><input id="projectGroupWorktrees" type="checkbox" checked> Group worktrees</label><select id="projectSort" aria-label="Project sort"><option value="priority">Operational priority</option><option value="name">Name</option><option value="progress">Progress</option><option value="recent">Recent activity</option></select><span class="tiny project-summary" id="projectSummary">0 of 0 projects</span></div>
    <div class="table-wrap"><table class="project-table"><thead><tr><th>Project</th><th>State &amp; activity</th><th>Phase &amp; progress</th><th>Indexes</th><th>Actions</th></tr></thead><tbody id="projectsBody"></tbody></table></div>
  </section>
</div>

<div id="commands" class="page">
  <div id="cmdDisabledBanner" class="diag-banner bad" style="display:none">⚠️ <b>Commands feature is disabled in configuration</b> (<code>features.commands = false</code>). Command classification and execution are blocked.</div>
  <section class="section"><h2>Running commands <span class="tiny" id="commandState">0 running</span></h2><div class="table-wrap"><table><thead><tr><th>Command</th><th>CWD</th><th>Tenant</th><th>Class</th><th>Age</th><th>Timeout</th></tr></thead><tbody id="activeCommands"></tbody></table></div></section>
  <div class="split"><section class="section"><h2>Command broker statistics</h2><div id="commandStats" class="kv"></div></section><section class="section"><h2>Blocked by policy</h2><div class="table-wrap"><table><thead><tr><th>Reason</th><th>Count</th></tr></thead><tbody id="blockedReasons"></tbody></table></div></section></div>
  <section class="section" style="margin-top:12px">
    <h2>Active Git Worktrees &amp; Subagent Sandboxes <span class="tiny" id="worktreeSummary">0 worktrees</span></h2>
    <div style="padding:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input id="worktreeRoot" placeholder="Repository root" style="flex:1;min-width:220px;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 8px">
      <button class="btn ok" id="refreshWorktreesBtn">↻ Refresh Worktrees</button>
      <button class="btn warn" id="pruneWorktreesBtn">🧹 Prune Stale Worktrees</button>
      <span class="tiny muted">Isolated worktrees prevent concurrent file write collisions</span>
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
  <section class="section">
    <h2>Live Telemetry Waves <span class="tiny">p95 latency (ms) &amp; queue wait (ms) · HTML5 Canvas</span></h2>
    <div style="padding:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:11px">
        <span><span class="chip" style="border-color:#38bdf8;color:#38bdf8">● Latency p95</span> <span class="chip" style="border-color:#34d399;color:#34d399">● Queue Wait</span></span>
        <span class="tiny muted">30 rolling sample ticks</span>
      </div>
      <canvas id="liveChartCanvas" role="img" aria-label="Live telemetry graph. Waiting for samples." width="800" height="150" style="width:100%;height:150px;background:#080c13;border-radius:6px;border:1px solid #1e293b;display:block"></canvas>
      <div id="liveChartEmpty" class="tiny muted" style="display:none;padding-top:8px">No latency or queue samples yet.</div>
      <div id="liveChartSummary" class="tiny muted" style="padding-top:8px">Waiting for telemetry samples.</div>
    </div>
  </section>

  <div style="margin-top:12px">
    <section class="section rag-narrow">
      <h2>RAG Vector Workspaces <span class="tiny">Persistent semantic code index</span></h2>
      <div style="padding:12px"><div class="project-toolbar"><input id="ragWorkspaceSearch" type="search" placeholder="Search RAG workspaces…" autocomplete="off"><span class="tiny" id="ragWorkspaceSummary">Workspace identity and index status.</span></div><div id="ragWorkspacesList"><div class="tiny muted">Loading RAG workspaces…</div></div></div>
    </section>
  </div>

  <section class="section" style="margin-top:12px">
    <h2>Local Model Arena <span class="tiny">Side-by-side prompt testbed comparing fast tier vs smart tier</span></h2>
    <div style="padding:12px">
      <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
        <input type="text" id="arenaPromptInput" placeholder="Test prompt (e.g. Write a Python function with LRU cache to solve knapsack problem)..." style="flex:1;min-width:320px;background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:8px 12px;font-size:12px">
        <button class="btn ok" id="arenaRunBtn">Run Arena Benchmark</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
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

  <section class="section" style="margin-top:12px"><h2>Execution profiles <span class="tiny">configured capacity; context packing remains adaptive</span></h2>
<div class="table-wrap"><table><thead><tr><th>Model</th><th>Tier</th><th>Context</th><th>Max</th><th>Parallel</th><th>Thinking</th><th>Prompt cap</th></tr></thead><tbody id="executionProfiles"></tbody></table></div></section>
  <div class="split"><section class="section"><h2>Model statistics</h2><div class="table-wrap"><table><thead><tr><th>Model</th><th>Calls</th><th>Avg</th><th>Load</th><th>Fails</th></tr></thead><tbody id="models"></tbody></table></div></section><section class="section"><h2>Cache layers</h2><div class="table-wrap"><table><thead><tr><th>Layer</th><th>Calls</th><th>Avg</th><th>Context tokens avoided</th></tr></thead><tbody id="cacheLayers"></tbody></table></div></section></div>
  <div class="split"><section class="section"><h2>Agents</h2><div class="table-wrap"><table><thead><tr><th>Agent</th><th>Requests</th><th>Local AI</th><th>Avg</th><th>Fails</th></tr></thead><tbody id="agents"></tbody></table></div></section><section class="section"><h2>Execution routes</h2><div class="table-wrap"><table><thead><tr><th>Route</th><th>Task</th><th>Complexity</th><th>Calls</th><th>Avg</th><th>Fails</th></tr></thead><tbody id="routes"></tbody></table></div></section></div>
  <section class="section"><h2>HTTP tail latency <span class="tiny">per action · excludes policy rejections</span></h2><div class="table-wrap"><table><thead><tr><th>Action</th><th>Calls</th><th>p50</th><th>p95</th><th>p99</th><th>Fails</th></tr></thead><tbody id="httpTail"></tbody></table></div></section>
  <section class="section"><h2>Active Multi-Agent File Leases <span class="tiny">Prevents conflicting agent edits</span></h2><div class="table-wrap"><table><thead><tr><th>Lease ID</th><th>Paths</th><th>Tenant</th><th>Purpose</th><th>Expires</th><th>Actions</th></tr></thead><tbody id="activeLeasesBody"></tbody></table></div></section>
</div>

<div id="reliability" class="page">
  <section class="section" id="reliabilitySummary"><h2>Operational severity <span class="tiny">Aggregates current failures, restart history, and request health.</span></h2><div id="reliabilityHeadline" class="kv"></div><div class="tiny muted" id="reliabilityTrend">Failure trend unavailable until telemetry arrives.</div><button class="btn" id="reliabilityAction">Open affected requests</button></section>
  <div class="split">
    <section class="section"><h2>Recent error fingerprints</h2><div class="table-wrap"><table><thead><tr><th>Component</th><th>Operation</th><th>Count</th><th>Recovered</th><th>Last seen</th></tr></thead><tbody id="errors"></tbody></table></div></section>
    <section class="section"><h2>Runtime / scheduler counters</h2><div id="runtimeCounters" class="kv"></div></section>
  </div>
  <section class="section">
    <h2>Process session &amp; restart history <span class="tiny">last 30 days · crash detection &amp; session token economics</span></h2>
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
    <h2><span>Operational log tail</span><div style="display:flex;gap:6px;align-items:center"><input type="text" id="logFilterInput" placeholder="Filter logs…" style="background:#0d141c;color:var(--fg);border:1px solid #334355;border-radius:5px;padding:3px 7px;font-size:11px;width:150px"><select id="logLinesSelect" style="background:#0d141c;color:var(--fg);border:1px solid #334355;border-radius:5px;padding:3px 6px;font-size:11px"><option value="100">100 lines</option><option value="250" selected>250 lines</option><option value="500">500 lines</option></select><button class="btn" id="loadLogs" style="padding:3px 8px">Refresh</button><button class="btn" id="copyLogsBtn" style="padding:3px 8px">Copy</button></div></h2>
    <pre id="logTail" style="margin:0;padding:12px;white-space:pre-wrap;max-height:420px;overflow:auto;background:#0d1219;color:#c9d6e4;font-size:11px">Click Refresh to load logs.</pre>
  </section>
</div>

<div id="config" class="page">
  <section class="section">
    <h2>Runtime configuration <span class="tiny">safe override sidecar · restart required after save</span></h2>
    <div style="padding:14px">
      <div class="dash-group"><div class="group-title">Hardware &amp; Engine</div><div class="kv" style="padding:0;margin-bottom:12px"><div>Hardware profile</div><div><select id="cfgProfile" style="background:#172233;color:var(--fg);border:1px solid #2e405a;border-radius:6px;padding:6px 10px"><option>auto</option><option>cpu</option><option>integrated</option><option>low</option><option>balanced</option><option>high</option><option>max</option></select></div></div></div>
      <div class="dash-group"><div class="group-title">Core MCP Tools</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px"><label><input type="checkbox" id="cfgFeatStatus"> status (local_ai_status)</label><label><input type="checkbox" id="cfgFeatRepo"> repo (local_ai_repo)</label><label><input type="checkbox" id="cfgFeatTasks"> tasks (local_ai_task &amp; Ollama)</label><label><input type="checkbox" id="cfgFeatRag"> rag (local_ai_rag)</label><label><input type="checkbox" id="cfgFeatCommands"> commands (local_ai_command)</label><label><input type="checkbox" id="cfgFeatCoord"> coord (local_ai_coord)</label><label><input type="checkbox" id="cfgFeatArtifacts"> artifacts (local_ai_artifact)</label></div></div>
      <div class="dash-group"><div class="group-title">Code Intelligence &amp; Indexing</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px"><label><input type="checkbox" id="cfgPreprocess"> Preprocessing enabled</label><label><input type="checkbox" id="cfgIntel"> Managed code intelligence</label><label><input type="checkbox" id="cfgSerena"> Serena backend</label><label><input type="checkbox" id="cfgCodegraph"> CodeGraphContext backend</label></div></div>
      <div class="dash-group"><div class="group-title">Advanced Subsystems</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-bottom:12px"><label><input type="checkbox" id="cfgFeatSubagents"> Subagents (Ollama workers)</label><label><input type="checkbox" id="cfgFeatAgentOs"> Agent OS (durable memory/receipts)</label><label><input type="checkbox" id="cfgFeatDashboard"> Web Dashboard</label></div></div>
      <div class="tiny muted" style="margin:4px 0 7px">Scope and impact: saves only dashboard-managed overrides. Restart applies changes; reset removes only those overrides.</div><div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:6px"><button class="btn ok" id="cfgSave">Save overrides (restart required)</button><button class="btn" id="cfgReload">Reload view</button><button class="btn warn" id="cfgReset">Reset dashboard overrides</button><span class="tiny" id="cfgStatus"></span></div>
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
        <div><h3 style="font-size:12px;margin:0 0 8px">Export Bundle</h3><table><thead><tr><th>Repository identity</th><th>Bundle readiness</th><th>Index contents</th><th>Action</th></tr></thead><tbody id="bundleExportTable"></tbody></table></div>
        <div><h3 style="font-size:12px;margin:0 0 8px">Import Bundle</h3><div style="display:flex;flex-direction:column;gap:8px"><input type="file" id="bundleFile" accept=".zip,application/zip" style="color:var(--fg);font-size:12px"><input type="text" id="bundleTargetRoot" placeholder="Optional target repository root" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px"><button class="btn" id="bundleImport">Import selected ZIP</button><div id="bundleImportStatus" class="tiny muted"></div></div></div>
      </div>
    </div>
  </section>
</div>

<div id="events" class="page"><section class="section"><h2>Live activity <span class="tiny">RAM ring buffer · display pause does not pause runtime</span></h2><div class="project-toolbar"><select id="eventSeverity" aria-label="Event severity"><option value="">All severities</option><option value="failure">Failures</option><option value="warning">Warnings</option><option value="success">Successful</option></select><input id="eventSource" type="search" placeholder="Event source, agent, action…" aria-label="Event source"><span class="tiny" id="eventSummary">No events received.</span></div><div id="eventList" class="events"></div></section></div>

<div id="modalBg" class="modal-bg"><div class="modal"><div class="modal-head"><strong id="modalTitle">Details</strong><span id="modalLive" class="tiny" style="margin-left:10px"></span><button class="btn spacer" id="modalClose">Close</button></div><div id="modalBody"></div></div></div>

<script>
let cursor=0,paused=false,last=null,lastTraces=[],lastOverviewAnnouncement='',lastOverviewReceivedAt=0;
const latencySparkData=[], throughputSparkData=[], liveChartLatency=[], liveChartQueue=[];

const traceStyles=document.createElement('style');
traceStyles.textContent='.trace-inspector-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:12px;background:linear-gradient(135deg,#172535,#11171e);border:1px solid #33485f;border-radius:8px}.trace-kicker{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}.trace-inspector-head strong{font-size:15px;display:block;overflow-wrap:anywhere}.trace-metrics{display:flex;gap:7px;flex-wrap:wrap;padding:8px 0 2px;color:var(--muted);font-size:10px}.trace-metrics span{border:1px solid #2b3948;border-radius:999px;padding:3px 7px}.trace-tabs{display:flex;gap:5px;overflow:auto;padding:10px 0 2px;border-bottom:1px solid var(--line)}.trace-tab{background:transparent;color:var(--muted);border:0;border-bottom:2px solid transparent;padding:7px 9px;cursor:pointer;white-space:nowrap;font-size:11px}.trace-tab:hover,.trace-tab.active{color:var(--fg);border-bottom-color:var(--accent)}.trace-view{min-height:80px}.tool-pair{display:grid;gap:6px}.tool-part{border-left:3px solid #6d86a8;background:#0d141c;padding:8px;border-radius:4px}.tool-result{border-left-color:var(--ok)}.tool-label{color:var(--accent);font-weight:700;font-size:11px;margin-bottom:6px}.tool-label .tiny{margin-left:7px;color:var(--fg);font-weight:400}.tool-pending{color:var(--warn);font-size:11px;padding:7px 0}.trace-raw-panel pre{margin:0}';
document.head.append(traceStyles);

const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), escJs=v=>esc(JSON.stringify(v));
const n=v=>Number(v||0).toLocaleString(), ms=v=>{v=Number(v||0);return v>=1000?(v/1000).toFixed(v>=10000?1:2)+' s':Math.round(v)+' ms'}, durSec=s=>{s=Number(s||0);if(s<60)return Math.round(s)+'s';if(s<3600)return Math.floor(s/60)+'m '+Math.round(s%60)+'s';if(s<86400)return Math.floor(s/3600)+'h '+Math.floor((s%3600)/60)+'m';return Math.floor(s/86400)+'d '+Math.floor((s%86400)/3600)+'h'}, age=msv=>durSec(Number(msv||0)/1000);

function dashboardHealth(snapshot={}){
  const current=snapshot.current||snapshot.live||snapshot.headless||snapshot;
  const observability=snapshot.observability||{},cohorts=observability.cohorts||{},agentHttp=cohorts.agent_http||{},policy=cohorts.policy_rejection||{},inference=cohorts.inference||{};
  const status=String(current.health||current.status||current.service_status||'').toLowerCase();
  const count=value=>Math.max(0,Number(value)||0);
  const openIssues=count(current.open_incidents??current.active_errors??current.blocked_requests??0),agentFailures=count(agentHttp.failures),policyRejections=count(policy.events),degradedCount=count(inference.degraded_count),retryCount=count(inference.retry_count),restarts=count(current.restarts??snapshot.headless?.restarts),hubOnline=snapshot.hub_online??current.hub_online,ollamaOnline=snapshot.ollama_online??current.ollama_online,heartbeatStale=current.heartbeat_stale===true||snapshot.heartbeat_stale===true;
  const signals=[];
  if(agentFailures)signals.push(`${agentFailures} agent HTTP failure${agentFailures===1?'':'s'}`);
  if(policyRejections)signals.push(`${policyRejections} policy rejection${policyRejections===1?'':'s'}`);
  if(degradedCount)signals.push(`${degradedCount} degraded inference${degradedCount===1?'':'s'}`);
  if(retryCount)signals.push(`${retryCount} retr${retryCount===1?'y':'ies'}`);
  if(restarts)signals.push(`${restarts} supervisor restart${restarts===1?'':'s'}`);
  const actionTab=openIssues||count(current.blocked_requests)?'work':'reliability';
  const actionLabel=actionTab==='work'?'Open queue and requests':'Open reliability details';
  if(hubOnline===false||heartbeatStale||['degraded','down','offline','unavailable','crashed','stopped','stale'].includes(status)||current.degraded===true){
    const reason=hubOnline===false?'Hub is offline.':heartbeatStale||status==='stale'?'Runtime heartbeat is stale.':signals.length?`Current runtime is degraded: ${signals.join(', ')}.`:'Current runtime reports an unavailable service.';
    return {level:'degraded',label:'Degraded',reason,actionTab,actionLabel};
  }
  if(ollamaOnline===false)signals.push('Ollama is offline');
  if(['attention','warning','warn','partial'].includes(status)||openIssues||signals.length){
    const reason=openIssues?`Current runtime has ${openIssues} open issue${openIssues===1?'':'s'}${signals.length?`; ${signals.join(', ')}`:''}.`:signals.length?`Current runtime needs attention: ${signals.join(', ')}.`:'Current runtime reports a warning state.';
    return {level:'attention',label:'Needs attention',reason,actionTab,actionLabel};
  }
  return {level:'healthy',label:'Healthy',reason:'Current runtime reports no active issue.',actionTab:'reliability',actionLabel:'Open reliability details'};
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
  const health=dashboardHealth(snapshot);
  const timestamp=snapshot.updated_at??snapshot.generated_at??snapshot.timestamp??snapshot.observability?.updated_at??runtime.updated_at;
  let freshness=dashboardFreshness(timestamp,now);
  if(freshness.state==='unknown'&&Number.isFinite(Number(receivedAt)))freshness=dashboardFreshness(receivedAt,now);
  const level=$('overviewHealthLevel'),evidence=$('overviewHealthEvidence'),freshnessEl=$('overviewFreshness'),action=$('overviewHealthAction'),summary=$('overviewHealthSummary'),announcement=$('overviewAnnouncement');
  if(!level||!evidence||!freshnessEl||!action||!summary)return;
  const label=health.level==='attention'?'Needs attention':health.label;
  const target=health.actionTab||'reliability';
  const targetLabel=health.actionLabel||'Open reliability details';
  const stateText=current.health||current.status||current.service_status||'unreported';
  const activeRequests=Array.isArray(snapshot.observability?.active_requests)?snapshot.observability.active_requests.length:0;
  const evidenceText=`${health.reason} Runtime state: ${stateText}. ${activeRequests} active API request${activeRequests===1?'':'s'}.`;
  level.textContent=label;
  level.className='value primary-metric '+(health.level==='healthy'?'ok':health.level==='attention'?'warn-t':'bad-t');
  evidence.textContent=evidenceText;
  freshnessEl.textContent=freshness.ageMs===null?freshness.label:`${freshness.label} · updated ${age(freshness.ageMs)} ago`;
  freshnessEl.className='tiny '+(freshness.state==='stale'?'warn-t':'muted');
  summary.style.borderLeftColor=health.level==='healthy'?'var(--ok)':health.level==='attention'?'var(--warn)':'var(--bad)';
  action.textContent=targetLabel;
  action.onclick=()=>switchTab(target);
  const announcementText=`${label}. ${freshness.label}.`;
  if(announcement&&announcementText!==lastOverviewAnnouncement){announcement.textContent=announcementText;lastOverviewAnnouncement=announcementText;}
}

function redactDiagnostic(value){
  const maskPath=path=>{
    const parts=path.replace(/\\/g,'/').split('/').filter(Boolean);
    return parts.length?`${/^[a-z]:/i.test(parts[0])?parts[0]+'/':'/'}…/${parts.at(-1)}`:'<path>';
  };
  return String(value??'')
    .replace(/\b(Bearer\s+)[^\s,;]+/gi,'$1<redacted>')
    .replace(/((?:["'](?:api[_-]?key|token|secret|password|authorization)["'])\s*:\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)/gi,'$1"<redacted>"')
    .replace(/\b((?:api[_-]?key|token|secret|password|authorization)\b\s*(?:=|:)\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi,'$1<redacted>')
    .replace(/(^|\s)((?:--(?:api[-_]?key|token|secret|password)|-(?:k|t))(?:\s+|=))(?:"[^"]*"|'[^']*'|\S+)/gi,'$1$2<redacted>')
    .replace(/[A-Za-z]:[\\/](?:[^\s"'`\\/]+[\\/])*[^\s"'`\\/]*/g,maskPath)
    .replace(/(?<![:\w])\/(?:[^\s"'`/]+\/)+[^\s"'`/]+/g,maskPath);
}

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
workPageStyles.textContent='.work-page{display:grid!important;grid-template-columns:minmax(0,1.55fr) minmax(320px,.9fr);gap:12px;align-items:start}.work-page>.work-summary{grid-column:1/-1}.work-panel{min-width:0}.work-panel-1{grid-column:1;grid-row:2}.work-panel-2{grid-column:2;grid-row:2}.work-panel-3{grid-column:1;grid-row:3}.work-panel-4{grid-column:2;grid-row:3}.work-summary{padding:14px!important}.work-summary-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.work-kicker{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}.work-summary h2{margin:0}.work-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}.work-kpis>div{background:#0d141c;border:1px solid #2b3948;border-radius:7px;padding:9px 10px}.work-kpis span{display:block;color:var(--muted);font-size:10px}.work-kpis strong{display:block;font-size:18px;margin-top:3px}.work-panel h2{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.work-panel .table-wrap{max-height:390px;overflow:auto}.work-panel table{width:100%;table-layout:fixed}.work-panel th{position:sticky;top:0;z-index:1;background:#151d26}.work-panel td{vertical-align:top;overflow-wrap:anywhere}.work-panel-1 th:nth-child(1){width:13%}.work-panel-1 th:nth-child(2){width:20%}.work-panel-1 th:nth-child(3){width:24%}.work-panel-1 th:nth-child(4){width:17%}.work-panel-1 th:nth-child(5){width:26%}.work-panel-2 th:nth-child(1){width:27%}.work-panel-2 th:nth-child(2){width:30%}.work-panel-2 th:nth-child(3){width:27%}.work-panel-2 th:nth-child(4){width:16%}.work-panel-3 th:nth-child(1){width:12%}.work-panel-3 th:nth-child(2){width:14%}.work-panel-3 th:nth-child(3){width:9%}.work-panel-3 th:nth-child(4){width:14%}.work-panel-3 th:nth-child(5){width:31%}.work-panel-3 th:nth-child(6){width:10%}.work-panel-3 th:nth-child(7){width:10%}.work-panel-3 td{white-space:normal;overflow-wrap:anywhere;word-break:break-word}.work-panel-4 th:nth-child(1){width:13%}.work-panel-4 th:nth-child(2){width:22%}.work-panel-4 th:nth-child(3){width:22%}.work-panel-4 th:nth-child(4){width:18%}.work-panel-4 th:nth-child(5){width:15%}.work-panel-4 th:nth-child(6){width:10%}.work-state{display:inline-block;border:1px solid #3b4b5e;border-radius:999px;padding:3px 7px;color:var(--muted);font-size:10px;white-space:nowrap}.work-state.live{border-color:#4f8edb;color:var(--accent)}.work-state.bad{border-color:#a64c4c;color:var(--bad)}.timing-label{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.04em}.work-panel-4 .tiny{line-height:1.35}@media(max-width:1050px){.work-page{grid-template-columns:1fr}.work-page>.work-summary,.work-panel-1,.work-panel-2,.work-panel-3,.work-panel-4{grid-column:1;grid-row:auto}.work-panel .table-wrap{max-height:320px}}@media(max-width:620px){.work-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.work-summary-head{display:block}.work-summary-head>.tiny{display:block;margin-top:6px}.work-panel table{table-layout:auto;min-width:650px}.work-panel .table-wrap{overflow:auto}}';
document.head.append(workPageStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-side-state.interrupted{background:var(--warn)}.trace-interrupted{color:var(--warn)}.work-page{display:none!important}.work-page.active{display:grid!important}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.work-page.active .work-panel-4{grid-column:1/-1!important;grid-row:3!important}.work-page.active .work-panel-4 .table-wrap{max-height:460px}.work-page.active .work-panel-3{grid-column:1/-1!important;grid-row:4!important}</style>');

const workFilterStyles=document.createElement('style');
workFilterStyles.textContent='.work-filter{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}.work-filter input,.work-filter select{background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:7px 9px;font:inherit;font-size:11px}.work-filter input{flex:1;min-width:220px}.work-filter select{min-width:125px}.work-filter .btn{padding:6px 9px;font-size:11px}.work-filter-summary{color:var(--muted);font-size:10px}';
document.head.append(workFilterStyles);
document.head.insertAdjacentHTML('beforeend','<style>.trace-sidebar-controls{display:flex;gap:6px;padding:8px 8px 2px}.trace-sidebar-controls input,.trace-sidebar-controls select{min-width:0;width:100%;background:#0d141c;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:6px 7px;font:inherit;font-size:10px}.trace-sidebar-controls select{width:116px;flex:0 0 116px}</style>');
document.head.insertAdjacentHTML('beforeend','<style>.trace-main,.trace-step-body,.trace-event,.human-section{min-width:0}.prompt-meta{display:flex;gap:5px;flex-wrap:wrap;padding:7px 8px;border-bottom:1px solid #202a35}.prompt-chip{border:1px solid #394758;border-radius:999px;padding:2px 7px;color:var(--muted);font-size:9px}.prompt-chip strong{color:var(--fg)}.prompt-messages{display:grid;gap:6px;padding:7px}.prompt-card{border:1px solid #2d3d4e;border-left:3px solid #5b8def;border-radius:6px;overflow:hidden}.prompt-card.role-system{border-left-color:#a78bfa}.prompt-card.role-user{border-left-color:#38bdf8}.prompt-card.role-assistant{border-left-color:#4ade80}.prompt-card-head{display:flex;align-items:center;gap:7px;padding:6px 8px;background:#151d26;color:var(--fg);font-size:10px;font-weight:700}.prompt-card-head .tiny{margin-left:auto}.prompt-pre{margin:0;padding:7px 8px;background:#0d1219;color:#d7e2ef;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.3;font-size:11px;max-height:150px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}.prompt-context{margin:0 8px 8px;border:1px solid #334355;border-radius:5px;background:#111923}.prompt-context summary{cursor:pointer;padding:6px 8px;color:var(--muted);font-size:9px}.prompt-context .prompt-pre{max-height:180px;border-top:1px solid #273544}.prompt-fallback{padding:8px}</style>');

const nativeFetch=window.fetch.bind(window);
function getSavedToken(){
  try{return localStorage.getItem('apiToken')||sessionStorage.getItem('localAiHubToken')||'';}catch{return '';}
}
function saveToken(val){
  apiToken=val.trim();
  try{localStorage.setItem('apiToken',apiToken);sessionStorage.setItem('localAiHubToken',apiToken);}catch{}
}
let apiToken=getSavedToken();
if($('apiToken')) $('apiToken').value=apiToken;

function setupTraceInspector(){
  if($('traceInspector'))return;
  document.body.insertAdjacentHTML('beforeend','<div id="traceInspector" class="page trace-page"><div class="trace-layout"><aside class="trace-sidebar"><div class="trace-sidebar-head"><button class="btn" data-trace-back>← Queue & requests</button><strong>Agent trace history</strong><span class="tiny" id="traceSideSummary">Select a run to inspect</span></div><div id="traceSidebarList" class="trace-sidebar-list"></div></aside><main class="trace-main"><div class="trace-main-head"><div><h1 id="tracePageTitle">Select an agent trace</h1><span id="tracePageLive" class="tiny"></span></div><button class="btn spacer" data-trace-back>Back</button></div><div id="tracePageBody" class="trace-select-empty">Choose a trace from the left.</div></main></div></div>');
}
setupTraceInspector();
if($('traceSidebarList')&&!$('traceHistorySearch')){$('traceSidebarList').insertAdjacentHTML('beforebegin','<div class="trace-sidebar-controls"><input id="traceHistorySearch" type="search" placeholder="Search history…" autocomplete="off"><select id="traceHistoryState" aria-label="History state"><option value="useful">Live + completed</option><option value="">All history</option><option value="interrupted">Interrupted</option><option value="failed">Failed</option></select></div>')}

let statusPollInFlight=false,hasLiveStatus=false;
let sloScope=$('sloScope')?$('sloScope').value:'1h';
if($('sloScope')) $('sloScope').onchange=()=>{sloScope=$('sloScope').value;pollStatus()};
if($('saveToken')) $('saveToken').onclick=()=>{if($('apiToken'))saveToken($('apiToken').value);pollStatus()};

async function apiFetch(path,opts={}){
  opts={...opts};const h=new Headers(opts.headers||{});if(apiToken)h.set('X-LocalAI-Token',apiToken);opts.headers=h;
  let r=await nativeFetch(path,opts);
  if(r.status===401&&!apiToken){
    const entered=prompt('Local AI Hub API token');
    if(entered){saveToken(entered);if($('apiToken'))$('apiToken').value=apiToken;h.set('X-LocalAI-Token',apiToken);r=await nativeFetch(path,{...opts,headers:h})}
  }
  return r;
}
const rows=(id,items,fn,cols)=>{$(id).innerHTML=(items&&items.length)?items.map(fn).join(''):`<tr><td colspan="${cols}" class="muted">none</td></tr>`};
function copyText(text, btn){
  try{navigator.clipboard.writeText(String(text))}catch{}
  if(btn){
    const oldText=btn.textContent;
    btn.textContent='Copied!';
    setTimeout(()=>{btn.textContent=oldText},1500);
  }
}
async function checkTaskCriterion(taskId,criterion,btn){
  const oldText=btn.textContent;
  btn.disabled=true;
  btn.textContent='Checking…';
  try{
    const res=await post('/api/agent-state/verification',{action:'completion',task_id:taskId});
    const c=res.completion||{};
    const passed=(c.passed_criteria||[]).includes(criterion);
    if(passed){
      btn.className='action-btn-sm ok';
      btn.textContent='✓ Verified';
    }else{
      btn.className='action-btn-sm warn-t';
      btn.textContent='Pending';
    }
  }catch(e){
    btn.textContent='Error';
  }finally{
    btn.disabled=false;
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

function renderSecretFindingModal(s){
  const rule=s.rule||s.secret_type||'Secret';
  const desc=s.description||rule;
  const isMock=s.is_test||s.is_placeholder;
  const file=s.file||'—';
  const line=s.line||0;
  const match=s.match||s.redacted_secret||'***';
  const entropy=s.entropy!==undefined?s.entropy:'—';
  const snippet=s.redacted_snippet||match;
  const sev=isMock?'LOW':(s.severity||'HIGH');
  const badgeCls=isMock?'badge-waiting':(sev==='CRITICAL'?'badge-error':'badge-running');

  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <div>
          <div class="tiny muted mono">SECURITY AUDIT · CREDENTIAL SCANNER</div>
          <h2 style="margin:2px 0 0;font-size:16px">🔑 <b>${esc(desc)}</b></h2>
        </div>
        <span class="badge-status ${badgeCls}">${isMock?'🧪 TEST SUITE MOCK':(sev+' LEAK')}</span>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Finding Details</span></div>
        <div class="modal-card-body">
          <div class="kv" style="padding:0">
            <div>Rule Key</div><div class="mono">${esc(rule)}</div>
            <div>File Location</div><div class="mono tiny">${esc(file)}:${n(line)}</div>
            <div>Masked Match</div><div class="mono bad-t">${esc(match)}</div>
            <div>Shannon Entropy</div><div><span class="chip">${esc(entropy)}</span> <span class="tiny muted">(>3.5 indicates true random cryptographic entropy)</span></div>
            <div>Classification</div><div><b>${isMock?'<span class="warn-t">Unit Test Fixture (Safe)</span>':'<span class="bad-t">Live Production Credential Leak (Action Required)</span>'}</b></div>
          </div>
        </div>
      </div>
      <div class="modal-card">
        <div class="modal-card-head"><span>Source Snippet</span></div>
        <div class="modal-card-body">
          <pre class="code-box" style="margin:0">${esc(snippet)}</pre>
        </div>
      </div>
      ${!isMock?`
      <div class="diag-banner bad">
        <span>⚠️</span>
        <div>
          <b>Recommended Immediate Actions:</b>
          <ol style="margin:4px 0 0;padding-left:18px;font-size:11px">
            <li>Revoke or rotate this credential in provider dashboard immediately.</li>
            <li>Purge credential from git history using <code>git-filter-repo</code> or BFG.</li>
            <li>Move secrets to environment variables (e.g. <code>.env</code> in <code>.gitignore</code>).</li>
          </ol>
        </div>
      </div>
      `:''}
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

function ansiToHtml(text){
  if(!text)return '';
  const colors={
    '30':'#6e7681','31':'#f85149','32':'#3fb950','33':'#d29922','34':'#58a6ff','35':'#bc8cff','36':'#39c5cf','37':'#f0f6fc',
    '90':'#8b949e','91':'#ff7b72','92':'#56d364','93':'#e3b341','94':'#79c0ff','95':'#d2a8ff','96':'#56d4dd','97':'#ffffff'
  };
  let out='',open=false;
  const escaped=text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const parts=escaped.split(/\u001b\[([0-9;]*)m/);
  for(let i=0;i<parts.length;i++){
    if(i%2===1){
      const code=parts[i];
      if(open){out+='</span>';open=false;}
      if(code!=='0'&&code!==''){
        const c=colors[code];
        if(c){out+=`<span style="color:${c}">`;open=true;}
        else if(code==='1'){out+='<span style="font-weight:bold">';open=true;}
      }
    }else{
      out+=parts[i];
    }
  }
  if(open)out+='</span>';
  return out;
}

function renderCmdResult(res){
  const outEl=$('cmdOutput'),paneEl=$('cmdTermPane'),metaEl=$('cmdExecMeta');
  if(outEl)outEl.textContent=JSON.stringify(res,null,2);
  let termContent='';
  if(res?.stdout)termContent+=res.stdout;
  if(res?.stderr)termContent+=(termContent?'\n':'')+res.stderr;
  if(!termContent&&res?.output)termContent=res.output;
  if(!termContent&&res?.error)termContent='Error: '+res.error;
  if(paneEl)paneEl.innerHTML=ansiToHtml(termContent)||'<span class="muted">(no output)</span>';
  if(metaEl){
    const ec=res?.exit_code??res?.exitCode??res?.result?.exit_code;
    const dur=res?.duration_ms??res?.duration??res?.result?.duration_ms;
    const ok=ec===0;
    metaEl.innerHTML=`${ec!==undefined?`<span class="pill tiny ${ok?'ok':'bad'}">exit: ${ec}</span>`:''} ${dur?`<span class="pill tiny">${Math.round(dur)}ms</span>`:''}`;
  }
}

if($('cmdTermViewBtn'))$('cmdTermViewBtn').onclick=()=>{
  $('cmdTermPane').style.display='block';
  $('cmdOutput').style.display='none';
  $('cmdTermViewBtn').classList.add('active');
  $('cmdJsonViewBtn').classList.remove('active');
};
if($('cmdJsonViewBtn'))$('cmdJsonViewBtn').onclick=()=>{
  $('cmdTermPane').style.display='none';
  $('cmdOutput').style.display='block';
  $('cmdJsonViewBtn').classList.add('active');
  $('cmdTermViewBtn').classList.remove('active');
};

if($('cmdClassify'))$('cmdClassify').onclick=async()=>{
  const command=$('cmdInput').value.trim();
  if(!command)return;
  const res=await post('/api/command',{action:'classify',command});
  renderCmdResult(res);
};

if($('cmdRun'))$('cmdRun').onclick=async()=>{
  const command=$('cmdInput').value.trim(),cwd=$('cmdRoot').value.trim();
  if(!command||!cwd){
    renderCmdResult({error:'Repository root and command are required.'});
    return;
  }
  const c=await post('/api/command',{action:'classify',command});
  if(!c?.classification?.allowed){
    renderCmdResult(c);
    return;
  }
  if(!confirm('Run this '+c.classification.class+' command?\n\n'+command))return;
  $('cmdRun').disabled=true;
  try{
    const res=await post('/api/command',{action:'run',command,cwd,force:true});
    renderCmdResult(res);
  } finally {
    $('cmdRun').disabled=false;
    pollStatus();
  }
};

async function openGitDiffModal(defaultRoot,defaultPath,defaultStaged){
  const root=defaultRoot||$('cmdRoot')?.value?.trim()||'.';
  const path=defaultPath||'';
  const staged=!!defaultStaged;
  $('modalTitle').textContent='Visual Git Diff';
  $('modalLive').innerHTML='';
  $('modalBody').innerHTML=`
    <div style="padding:8px 12px;background:#131d2b;border-bottom:1px solid #2e405a;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input id="diffModalRoot" value="${esc(root)}" placeholder="Repo root" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:4px 8px;font-size:11px;min-width:180px">
      <input id="diffModalPath" value="${esc(path)}" placeholder="File path (optional)" style="background:#19232d;color:var(--fg);border:1px solid #394758;border-radius:6px;padding:4px 8px;font-size:11px;min-width:180px">
      <label style="font-size:11px;color:var(--fg);display:inline-flex;align-items:center;gap:4px">
        <input type="checkbox" id="diffModalStaged" ${staged?'checked':''}> Staged only
      </label>
      <button class="btn ok tiny" id="diffModalRefresh">↻ Refresh Diff</button>
      <button class="btn tiny" id="diffModalStageBtn" title="Stage current path or all (git add)">📥 Stage</button>
      <button class="btn warn tiny" id="diffModalUnstageBtn" title="Unstage changes (git reset)">↩ Unstage</button>
      <span id="diffModalStats" style="margin-left:auto;display:flex;gap:6px;align-items:center"></span>
    </div>
    <div id="diffModalContainer" style="padding:12px;max-height:550px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px">
      <div class="muted">Loading diff…</div>
    </div>
  `;
  $('modalBg').classList.add('open');

  async function loadDiff(){
    const r=$('diffModalRoot')?.value?.trim()||'.';
    const p=$('diffModalPath')?.value?.trim()||'';
    const s=$('diffModalStaged')?.checked;
    const container=$('diffModalContainer');
    const statsEl=$('diffModalStats');
    if(!container)return;
    container.innerHTML='<div class="muted">Loading diff…</div>';
    try{
      const res=await apiFetch('/api/git/diff?root='+encodeURIComponent(r)+'&path='+encodeURIComponent(p)+'&staged='+(s?'true':'false')+'&max_lines=1000');
      const data=await res.json();
      if(!data.success){
        container.innerHTML=`<div class="bad-t">Error: ${esc(data.error||'Failed to load git diff')}</div>`;
        return;
      }
      const stats=data.stats||{};
      if(statsEl){
        statsEl.innerHTML=`
          <span class="pill ok tiny">+${stats.insertions||0}</span>
          <span class="pill bad tiny">-${stats.deletions||0}</span>
          <span class="pill tiny">${stats.files_changed||0} files</span>
        `;
      }
      if(!data.raw_diff||!data.raw_diff.trim()){
        container.innerHTML='<div class="muted" style="text-align:center;padding:30px">No changes detected (clean working tree).</div>';
        return;
      }
      const lines=data.raw_diff.split('\n');
      let html='<div style="background:#0d1117;border-radius:6px;border:1px solid #30363d;overflow:hidden">';
      for(let line of lines){
        let style='padding:1px 8px;white-space:pre-wrap;line-height:1.45;';
        if(line.startsWith('+++')||line.startsWith('---')){
          style+='background:#161b22;color:#8b949e;font-weight:bold;';
        }else if(line.startsWith('@@')){
          style+='background:#162031;color:#58a6ff;font-weight:bold;';
        }else if(line.startsWith('+')){
          style+='background:rgba(46,160,67,0.15);color:#3fb950;';
        }else if(line.startsWith('-')){
          style+='background:rgba(248,81,73,0.15);color:#f85149;';
        }else if(line.startsWith('diff --git')){
          style+='background:#21262d;color:#f0f6fc;font-weight:bold;margin-top:8px;border-top:1px solid #30363d;';
        }else{
          style+='color:#c9d1d9;';
        }
        html+=`<div style="${style}">${esc(line)||' '}</div>`;
      }
      html+='</div>';
      container.innerHTML=html;
    }catch(err){
      if(container)container.innerHTML=`<div class="bad-t">Error: ${esc(String(err))}</div>`;
    }
  }

  const refBtn=$('diffModalRefresh');
  const stgCh=$('diffModalStaged');
  const stageBtn=$('diffModalStageBtn');
  const unstageBtn=$('diffModalUnstageBtn');
  if(refBtn)refBtn.onclick=loadDiff;
  if(stgCh)stgCh.onchange=loadDiff;
  if(stageBtn)stageBtn.onclick=async()=>{
    const r=$('diffModalRoot')?.value?.trim()||'.';
    const p=$('diffModalPath')?.value?.trim()||'';
    const cmd='git add '+(p?`"${p}"`:'.');
    await post('/api/command',{action:'run',command:cmd,cwd:r,force:true});
    await loadDiff();
  };
  if(unstageBtn)unstageBtn.onclick=async()=>{
    const r=$('diffModalRoot')?.value?.trim()||'.';
    const p=$('diffModalPath')?.value?.trim()||'';
    const cmd='git reset HEAD -- '+(p?`"${p}"`:'.');
    await post('/api/command',{action:'run',command:cmd,cwd:r,force:true});
    await loadDiff();
  };
  loadDiff();
}

if($('cmdGitDiffBtn'))$('cmdGitDiffBtn').onclick=()=>openGitDiffModal($('cmdRoot')?.value?.trim());

if($('intelRediscover'))$('intelRediscover').onclick=async()=>{$('intelControlStatus').textContent='working…';const r=await post('/api/code-intelligence/control',{action:'rediscover'});$('intelControlStatus').textContent=r.success?'rediscovery complete':'error: '+(r.error||'failed');pollStatus()};
if($('intelReset'))$('intelReset').onclick=async()=>{if(!confirm('Reset all managed Serena/CodeGraph MCP sessions?'))return;$('intelControlStatus').textContent='working…';const r=await post('/api/code-intelligence/control',{action:'reset',backend:'all'});$('intelControlStatus').textContent=r.success?'sessions reset':'error: '+(r.error||'failed');pollStatus()};

async function loadArchGraph(){
  try{
    const r=await apiFetch('/api/cross_project_graph',{cache:'no-store'});
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
  rows('archEdgesTable',edges,e=>clickableRow(e,`<td>${esc(e.from?.split('/').pop()||e.from)}</td><td>${esc(e.to?.split('/').pop()||e.to)}</td><td><span class="chip">${esc(e.type)}</span></td><td>${esc(e.label)}</td>`,'arch_edge'),4);
  drawArch(svg,nodes,edges,W,H);
  runSimulation(svg,nodes,edges,W,H);
}

function drawArch(svg,nodes,edges,W,H){
  svg.innerHTML='';
  const defs=document.createElementNS('http://www.w3.org/2000/svg','defs');
  const marker=document.createElementNS('http://www.w3.org/2000/svg','marker');
  marker.setAttribute('id','arr');marker.setAttribute('markerWidth','6');marker.setAttribute('markerHeight','4');marker.setAttribute('refX','6');marker.setAttribute('refY','2');marker.setAttribute('orient','auto');
  const mp=document.createElementNS('http://www.w3.org/2000/svg','polygon');mp.setAttribute('points','0 0, 6 2, 0 4');mp.setAttribute('fill','#4a6080');marker.appendChild(mp);defs.appendChild(marker);

  const markerRed=document.createElementNS('http://www.w3.org/2000/svg','marker');
  markerRed.setAttribute('id','arr-red');markerRed.setAttribute('markerWidth','6');markerRed.setAttribute('markerHeight','4');markerRed.setAttribute('refX','6');markerRed.setAttribute('refY','2');markerRed.setAttribute('orient','auto');
  const mpRed=document.createElementNS('http://www.w3.org/2000/svg','polygon');mpRed.setAttribute('points','0 0, 6 2, 0 4');mpRed.setAttribute('fill','#f87171');markerRed.appendChild(mpRed);defs.appendChild(markerRed);
  svg.appendChild(defs);

  const viewport=document.createElementNS('http://www.w3.org/2000/svg','g');
  viewport.setAttribute('id','archViewport');
  viewport.setAttribute('transform',`translate(${archPan.x},${archPan.y}) scale(${archZoom})`);
  svg.appendChild(viewport);

  const adj={};
  edges.forEach(e=>{ (adj[e.from]=adj[e.from]||[]).push(e.to); });
  const cycleEdges=new Set();
  function findCycles(curr, visited, pathStack){
    visited.add(curr);
    pathStack.push(curr);
    for(const nxt of (adj[curr]||[])){
      const idx = pathStack.indexOf(nxt);
      if(idx !== -1){
        for(let k=idx; k<pathStack.length-1; k++){
          cycleEdges.add(`${pathStack[k]}->${pathStack[k+1]}`);
        }
        cycleEdges.add(`${pathStack[pathStack.length-1]}->${nxt}`);
      } else if(!visited.has(nxt)){
        findCycles(nxt, visited, pathStack);
      }
    }
    pathStack.pop();
  }
  const vis=new Set();
  nodes.forEach(n=>{ if(!vis.has(n.root)) findCycles(n.root, vis, []); });

  const nodeIdx=Object.fromEntries(nodes.map((n,i)=>[n.root,i]));
  edges.forEach(e=>{
    const s=nodes[nodeIdx[e.from]],t=nodes[nodeIdx[e.to]];
    if(!s||!t)return;
    const isCycle = cycleEdges.has(`${e.from}->${e.to}`);
    const line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('class','arch-edge');line.setAttribute('x1',s.x);line.setAttribute('y1',s.y);line.setAttribute('x2',t.x);line.setAttribute('y2',t.y);
    line.setAttribute('stroke',isCycle ? '#f87171' : (e.type==='shared_route'?'#7b5fff':'#3a5572'));
    line.setAttribute('stroke-width',isCycle ? '2.5' : '1.5');
    if(isCycle) line.setAttribute('stroke-dasharray','4 2');
    line.setAttribute('marker-end',isCycle ? 'url(#arr-red)' : 'url(#arr)');
    viewport.appendChild(line);
  });
  nodes.forEach((nd,i)=>{
    const matches = !archFilter || (nd.root||'').toLowerCase().includes(archFilter) || (nd.label||'').toLowerCase().includes(archFilter);
    const g=document.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('transform',`translate(${nd.x},${nd.y})`);
    g.style.opacity = matches ? '1.0' : '0.25';
    const circ=document.createElementNS('http://www.w3.org/2000/svg','circle');
    circ.setAttribute('r','26');circ.setAttribute('fill','#1a2d40');
    circ.setAttribute('stroke',matches && archFilter ? '#fbbf24' : '#5380a8');
    circ.setAttribute('stroke-width',matches && archFilter ? '2.5' : '1.5');
    circ.style.cursor='pointer';
    const lbl=document.createElementNS('http://www.w3.org/2000/svg','text');
    lbl.setAttribute('text-anchor','middle');lbl.setAttribute('dy','4');lbl.setAttribute('fill','#c5d4e5');lbl.setAttribute('font-size','10');lbl.style.pointerEvents='none';
    lbl.textContent=(nd.root||'').split(/[\\/]/).pop()?.slice(0,12)||'?';
    g.appendChild(circ);g.appendChild(lbl);
    let moved=false;
    g.addEventListener('mousedown',ev=>{ev.preventDefault();moved=false;archDragging={node:nd,svg,dx:(ev.clientX/archZoom)-nd.x,dy:(ev.clientY/archZoom)-nd.y,setMoved:()=>{moved=true}}});
    circ.addEventListener('click',ev=>{if(!moved)openArchNodeModal(nd)});
    viewport.appendChild(g);
  });
  svg.addEventListener('mousemove',ev=>{
    if(!archDragging)return;
    archDragging.setMoved?.();
    archDragging.node.x=(ev.clientX/archZoom)-archDragging.dx;
    archDragging.node.y=(ev.clientY/archZoom)-archDragging.dy;
    updateArchPositions(svg,nodes,edges);
  });
  svg.addEventListener('mouseup',()=>{archDragging=null});
}

function updateArchPositions(svg,nodes,edges){
  const vp=$('archViewport')||svg;
  const lines=vp.querySelectorAll('.arch-edge');const nodeIdx=Object.fromEntries(nodes.map((n,i)=>[n.root,i]));
  lines.forEach((l,i)=>{const e=edges[i];if(!e)return;const s=nodes[nodeIdx[e.from]],t=nodes[nodeIdx[e.to]];if(!s||!t)return;l.setAttribute('x1',s.x);l.setAttribute('y1',s.y);l.setAttribute('x2',t.x);l.setAttribute('y2',t.y)});
  const gs=vp.querySelectorAll('g');nodes.forEach((nd,i)=>{if(gs[i])gs[i].setAttribute('transform',`translate(${nd.x},${nd.y})`)});
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
$('archZoomIn')?.addEventListener('click', () => {
  archZoom = Math.min(3.0, archZoom * 1.25);
  const vp = $('archViewport');
  if (vp) vp.setAttribute('transform', `translate(${archPan.x},${archPan.y}) scale(${archZoom})`);
});
$('archZoomOut')?.addEventListener('click', () => {
  archZoom = Math.max(0.3, archZoom / 1.25);
  const vp = $('archViewport');
  if (vp) vp.setAttribute('transform', `translate(${archPan.x},${archPan.y}) scale(${archZoom})`);
});
$('archZoomReset')?.addEventListener('click', () => {
  archZoom = 1.0; archPan = {x: 0, y: 0};
  const vp = $('archViewport');
  if (vp) vp.setAttribute('transform', `translate(0,0) scale(1)`);
});
$('archFilterInput')?.addEventListener('input', (ev) => {
  archFilter = (ev.target.value || '').trim().toLowerCase();
  const svg = $('archSvg');
  if (archNodes && archEdges && svg) drawArch(svg, archNodes, archEdges, svg.clientWidth||800, svg.clientHeight||520);
});

$('symbolGraphBtn')?.addEventListener('click',async()=>{
  const sym=$('symbolInput')?.value?.trim();
  try{
    const r=await apiFetch('/api/symbol_callgraph?symbol='+encodeURIComponent(sym||''),{cache:'no-store'});
    if(!r.ok)return;
    const d=await r.json();
    if(d.nodes&&d.nodes.length){
      archData={nodes:d.nodes.map(n=>({root:n.id,label:n.label})),edges:d.edges.map(e=>({from:e.from,to:e.to,type:e.type,label:e.type}))};
      renderArchGraph();
    }else{alert('No callgraph nodes found for symbol: '+sym)}
  }catch(e){console.warn(e)}
});

function showScanReady(secId, label){
  const el=$(secId);
  if(el){el.style.display='block';el.scrollIntoView({behavior:'smooth',block:'start'})}
  const status=$('archScanStatus');
  if(status){
    status.style.display='inline-flex';
    status.textContent=`✓ ${label} (click to jump ↓)`;
    status.onclick=()=>$(secId)?.scrollIntoView({behavior:'smooth',block:'start'});
  }
}

function setScanPending(label){
  const status=$('archScanStatus');
  if(status){
    status.style.display='inline-flex';
    status.textContent=`⏳ ${label}…`;
    status.onclick=null;
  }
}

$('deadCodeBtn')?.addEventListener('click',async()=>{
  $('deadCodeBtn').disabled=true;$('deadCodeBtn').textContent='Scanning…';setScanPending('Scanning dead code');
  try{
    const r=await apiFetch('/api/dead_code',{cache:'no-store'});
    const d=await r.json();
    $('deadCodeSec').style.display='block';
    $('deadCodeSummary').textContent=n(d.dead_symbols_count||0)+' potentially unused symbols';
    rows('deadCodeTable',d.dead_symbols||[],s=>clickableRow(s,`<td><b>${esc(s.name)}</b></td><td><span class="chip">${esc(s.kind)}</span></td><td>${esc(s.path)}</td><td>${n(s.line)}</td><td>${esc(s.container||'—')}</td><td class="muted">${esc(s.reason)}</td>`,'dead_code'),6);
    showScanReady('deadCodeSec','Dead Code ('+n(d.dead_symbols_count||0)+')');
  }catch(e){alert('Dead code scan failed: '+e.message)}
  finally{$('deadCodeBtn').disabled=false;$('deadCodeBtn').textContent='Scan Dead Code'}
});
$('auditDepsBtn')?.addEventListener('click',async()=>{
  $('auditDepsBtn').disabled=true;$('auditDepsBtn').textContent='Auditing…';setScanPending('Auditing dependencies');
  try{
    const r=await apiFetch('/api/audit_dependencies',{cache:'no-store'});
    const d=await r.json();
    $('auditSec').style.display='block';
    $('auditSummary').textContent=`Score ${d.security_score||'A'} · ${n(d.total_dependencies||0)} packages · ${n(d.vulnerability_count||0)} advisories`;
    rows('auditTable',d.vulnerabilities||[],v=>clickableRow(v,`<td><b>${esc(v.package)}</b></td><td><span class="chip ${v.severity==='HIGH'?'bad-t':'warn-t'}">${esc(v.severity)}</span></td><td>${esc(v.installed_version)}</td><td class="ok">${esc(v.fixed_version)}</td><td>${esc(v.advisory)}</td><td class="muted">${esc(v.manifest_path)}</td>`,'audit_vulnerability'),6);
    showScanReady('auditSec','Security Audit ('+n(d.vulnerability_count||0)+' advisories)');
  }catch(e){alert('Security audit failed: '+e.message)}
  finally{$('auditDepsBtn').disabled=false;$('auditDepsBtn').textContent='Audit Security'}
});

$('circDepsBtn')?.addEventListener('click',async()=>{
  $('circDepsBtn').disabled=true;$('circDepsBtn').textContent='Checking…';setScanPending('Checking circular deps');
  try{
    const r=await post('/api/repo/circular_dependencies',{root:'.'});
    $('circDepsSec').style.display='block';
    const cycles=r.cycles||[];
    $('circDepsSummary').textContent=n(cycles.length)+' circular cycle(s) detected';
    rows('circDepsTable',cycles,(c,i)=>clickableRow({cycle:c},`<td><b>#${i+1}</b></td><td><span class="chip">${esc(r.language||'python')}</span></td><td class="mono">${esc(Array.isArray(c)?c.join(' ➔ '):String(c))}</td><td>${n(Array.isArray(c)?c.length:1)}</td>`,'circ_dep'),4);
    if(archNodes&&archEdges&&$('archSvg')){
      drawArch($('archSvg'),archNodes,archEdges,$('archSvg').clientWidth||800,$('archSvg').clientHeight||520);
    }
    showScanReady('circDepsSec','Circular Deps ('+n(cycles.length)+')');
  }catch(e){alert('Circular dependency scan failed: '+e.message)}
  finally{$('circDepsBtn').disabled=false;$('circDepsBtn').textContent='Circular Deps'}
});

$('complexityBtn')?.addEventListener('click',async()=>{
  $('complexityBtn').disabled=true;$('complexityBtn').textContent='Analyzing…';setScanPending('Analyzing complexity');
  try{
    const r=await post('/api/repo/complexity',{root:'.'});
    $('complexitySec').style.display='block';
    const funcs=r.functions||[];
    $('complexitySummary').textContent=`Total ${n(r.total_functions||funcs.length)} functions · High risk: ${n(r.high_risk_count||0)}`;
    rows('complexityTable',funcs,f=>{
      const riskCls=f.risk==='high'?'bad-t':f.risk==='medium'?'warn-t':'ok';
      return clickableRow(f,`<td><b>${esc(f.name)}</b></td><td class="muted">${esc(f.file)}:${n(f.line)}</td><td>${n(f.cyclomatic_complexity)}</td><td>${n(f.cognitive_complexity)}</td><td><span class="chip ${riskCls}">${esc(f.risk||'low')}</span></td>`,'complexity');
    },5);
    showScanReady('complexitySec','Complexity ('+n(funcs.length)+' funcs)');
  }catch(e){alert('Complexity analysis failed: '+e.message)}
  finally{$('complexityBtn').disabled=false;$('complexityBtn').textContent='Code Complexity'}
});

$('apiSpecBtn')?.addEventListener('click',async()=>{
  $('apiSpecBtn').disabled=true;$('apiSpecBtn').textContent='Extracting…';setScanPending('Extracting API spec');
  try{
    const r=await post('/api/repo/api_spec',{root:'.'});
    $('apiSpecSec').style.display='block';
    const routes=r.routes||[];
    $('apiSpecSummary').textContent=`${n(routes.length)} endpoints detected · Framework: ${esc(r.framework||'auto')}`;
    rows('apiSpecTable',routes,rt=>clickableRow(rt,`<td><b>${esc(rt.path)}</b></td><td><span class="chip ok">${esc((rt.methods||['GET']).join(','))}</span></td><td class="mono">${esc(rt.handler||'—')}</td><td>${esc(rt.framework||'—')}</td><td class="tiny muted">${esc(rt.doc||'—')}</td>`,'api_route'),5);
    showScanReady('apiSpecSec','API Spec ('+n(routes.length)+' routes)');
  }catch(e){alert('API Spec extraction failed: '+e.message)}
  finally{$('apiSpecBtn').disabled=false;$('apiSpecBtn').textContent='API Spec'}
});

$('migrationDriftBtn')?.addEventListener('click',async()=>{
  $('migrationDriftBtn').disabled=true;$('migrationDriftBtn').textContent='Checking…';setScanPending('Checking migration drift');
  try{
    const r=await post('/api/repo/migration_drift',{root:'.'});
    $('migrationDriftSec').style.display='block';
    const drift=r.drift||{};
    const tables=Object.keys(drift);
    $('migrationDriftSummary').textContent=r.in_sync?'Database and code models are fully in sync ✓':`${n(tables.length)} drift table(s) found`;
    rows('migrationDriftTable',tables,t=>{
      const item=drift[t]||{};
      return clickableRow(item,`<td><b>${esc(t)}</b></td><td><span class="chip ${r.in_sync?'ok':'warn-t'}">${r.in_sync?'SYNC':'DRIFT'}</span></td><td class="bad-t">${esc((item.missing_in_db||[]).join(', ')||'—')}</td><td class="bad-t">${esc((item.missing_in_code||[]).join(', ')||'—')}</td><td class="warn-t">${esc(JSON.stringify(item.type_mismatches||{})||'—')}</td>`,'migration_drift');
    },5);
    showScanReady('migrationDriftSec','Migration Drift ('+n(tables.length)+' tables)');
  }catch(e){alert('Migration drift check failed: '+e.message)}
  finally{$('migrationDriftBtn').disabled=false;$('migrationDriftBtn').textContent='Migration Drift'}
});

let secretScanCache=[];

function renderSecretScanTable(){
  const hideTests=$('secretScanHideTests')?.checked??true;
  const filtered=hideTests?secretScanCache.filter(s=>!s.is_test&&!s.is_placeholder):secretScanCache;
  rows('secretScanTable',filtered,s=>{
    const isMock=s.is_test||s.is_placeholder;
    const sevChip=isMock
      ?'<span class="chip" style="color:#94a3b8;border-color:#475569">TEST / MOCK</span>'
      :(s.severity==='CRITICAL'?'<span class="chip bad-t">CRITICAL</span>':'<span class="chip warn-t">HIGH</span>');
    const matchVal=s.match||s.redacted_secret||s.redacted_snippet||'***';
    const entropyVal=s.entropy!==undefined?s.entropy:'—';
    return clickableRow(s,`<td><b>${esc(s.rule||s.secret_type||'secret')}</b></td><td class="muted">${esc(s.description||s.rule||'—')}</td><td class="mono tiny">${esc(s.file)}:${n(s.line)}</td><td class="mono bad-t">${esc(matchVal)}</td><td><span class="mono tiny">${esc(entropyVal)}</span></td><td>${sevChip}</td>`,'secret_finding');
  },6);
}
$('secretScanHideTests')?.addEventListener('change',renderSecretScanTable);

$('secretScanBtn')?.addEventListener('click',async()=>{
  $('secretScanBtn').disabled=true;$('secretScanBtn').textContent='Scanning…';setScanPending('Scanning secrets');
  try{
    const r=await post('/api/repo/secret_scan',{root:'.'});
    $('secretScanSec').style.display='block';
    secretScanCache=r.findings||[];
    const realLeaks=r.real_leaks_count!==undefined?r.real_leaks_count:secretScanCache.filter(s=>!s.is_test&&!s.is_placeholder).length;
    const testLeaks=r.test_findings_count!==undefined?r.test_findings_count:secretScanCache.filter(s=>s.is_test||s.is_placeholder).length;
    if(realLeaks>0){
      $('secretScanSummary').innerHTML=`<span class="bad-t">⚠️ ${n(realLeaks)} active credential leak(s) detected!</span> <span class="tiny muted">(${n(testLeaks)} test suite fixtures)</span>`;
    }else if(testLeaks>0){
      $('secretScanSummary').innerHTML=`<span class="ok">✓ Production code clean</span> <span class="tiny muted">(${n(testLeaks)} mock/test fixtures found)</span>`;
    }else{
      $('secretScanSummary').innerHTML=`<span class="ok">Clean — 0 leaked credentials found ✓</span>`;
    }
    renderSecretScanTable();
    showScanReady('secretScanSec',realLeaks>0?`Secrets (${realLeaks} leaks!)`:'Secrets (Clean ✓)');
  }catch(e){alert('Secret scan failed: '+e.message)}
  finally{$('secretScanBtn').disabled=false;$('secretScanBtn').textContent='Scan Secrets'}
});

// ── Bundles ────────────────────────────────────────────────────────────────────

function connectAgentOsStream(){
  if(sseSource){
    try{ sseSource.close(); }catch(e){}
    sseSource=null;
  }
  const badge=$('sseStreamBadge');
  if(badge){ badge.className='badge-status badge-waiting'; badge.textContent='Connecting…'; }
  const token=getSavedToken()||apiToken;
  const url='/api/agent-state/events/stream'+(token?'?token='+encodeURIComponent(token):'');
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
    return clickableRow(ev, `<td><strong>${seq}</strong></td><td class="tiny">${dt}</td><td class="tiny mono">${stream}</td><td><span class="badge-status ${kindBadge}">${kind}</span></td><td class="tiny">${actor}</td><td class="tiny mono" title="${esc(typeof ev.payload==='object'?JSON.stringify(ev.payload,null,2):payloadStr)}">${esc(payloadStr)}</td>`, 'event');
  }, 6);
}

$('sseReconnectBtn')?.addEventListener('click', connectAgentOsStream);
$('sseClearBtn')?.addEventListener('click', () => {
  sseEvents = [];
  renderLiveStreamTable();
});
$('sseKindFilter')?.addEventListener('change', renderLiveStreamTable);

async function loadInstalledModels(){
  const list=$('installedModelsList');
  if(!list)return;
  try{
    const r=await apiFetch('/api/models/manage',{cache:'no-store'});
    const d=await r.json();
    if(!d.success){
      const r2=await apiFetch('/api/models',{cache:'no-store'});
      const d2=await r2.json();
      const models=d2.data||[];
      list.innerHTML=models.length?models.map(m=>`<span class="chip ok">🤖 <b>${esc(m.id)}</b></span>`).join(' '):'<span class="muted">No models detected via Ollama</span>';
      return;
    }
    const models=d.models||[];
    const runningMap=new Map((d.running||[]).map(x=>[x.name,x]));
    if(!models.length){
      list.innerHTML='<span class="muted">No installed Ollama models found.</span>';
      return;
    }
    let html='<table style="width:100%;margin:0"><thead><tr><th>Model Name</th><th>Size</th><th>VRAM Status</th><th>Action</th></tr></thead><tbody>';
    for(const m of models){
      const name=m.name;
      const sizeMb=m.size?Math.round(m.size/(1024*1024))+' MB':'—';
      const isRun=runningMap.has(name);
      const vramInfo=isRun?`<span class="pill ok tiny">Active in VRAM (${Math.round((runningMap.get(name).size_vram||0)/(1024*1024))} MB)</span>`:'<span class="muted tiny">Idle</span>';
      html+=`<tr><td><strong>${esc(name)}</strong></td><td class="tiny">${sizeMb}</td><td>${vramInfo}</td><td><button class="btn bad tiny" onclick="deleteOllamaModel(${escJs(name)})">Delete</button></td></tr>`;
    }
    html+='</tbody></table>';
    list.innerHTML=html;
  }catch(e){
    list.textContent='Failed to load models';
  }
}

async function pullOllamaModel(){
  const input=$('modelPullName');
  const name=input?.value?.trim();
  const st=$('modelManageStatus');
  if(!name){alert('Enter a model name, e.g. qwen2.5-coder:3b');return;}
  if(st)st.innerHTML=`<span class="warn-t">Pulling model ${esc(name)} in background…</span>`;
  try{
    const res=await post('/api/models/manage',{action:'pull',model:name});
    if(st)st.innerHTML=res.success?`<span class="ok">✓ Pulling ${esc(name)} started</span>`:`<span class="bad-t">Error: ${esc(res.error)}</span>`;
    setTimeout(loadInstalledModels,3000);
  }catch(err){
    if(st)st.innerHTML=`<span class="bad-t">Error: ${esc(String(err))}</span>`;
  }
}

async function deleteOllamaModel(name){
  if(!confirm(`Delete model ${name}?`))return;
  const st=$('modelManageStatus');
  try{
    const res=await post('/api/models/manage',{action:'delete',model:name});
    if(st)st.innerHTML=res.success?`<span class="ok">✓ Deleted ${esc(name)}</span>`:`<span class="bad-t">Error: ${esc(res.error)}</span>`;
    loadInstalledModels();
  }catch(err){
    if(st)st.innerHTML=`<span class="bad-t">Error: ${esc(String(err))}</span>`;
  }
}

function setDbPreset(preset){
  const sel=$('dbSelect');
  const input=$('dbQueryInput');
  if(!sel||!input)return;
  if(preset==='tasks'){
    sel.value='agent_state';
    input.value='SELECT id, role, status, scope_root, retry_count, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 50';
  }else if(preset==='events'){
    sel.value='agent_state';
    input.value='SELECT id, task_id, event_type, actor, timestamp FROM events ORDER BY id DESC LIMIT 50';
  }else if(preset==='memory'){
    sel.value='agent_state';
    input.value='SELECT id, task_id, key, scope, updated_at, substr(value, 1, 100) as preview FROM agent_memory ORDER BY updated_at DESC LIMIT 50';
  }else if(preset==='relations'){
    sel.value='agent_state';
    input.value='SELECT source_entity, relation, target_entity, weight, updated_at FROM agent_entity_relations ORDER BY weight DESC LIMIT 50';
  }else if(preset==='cache'){
    sel.value='cache';
    input.value='SELECT key, created_at, expires_at FROM cache_entries ORDER BY created_at DESC LIMIT 50';
  }
}

async function runDbQuery(){
  const db=$('dbSelect')?.value||'agent_state';
  const query=$('dbQueryInput')?.value?.trim();
  const status=$('dbQueryStatus');
  const thead=$('dbResultsHead');
  const tbody=$('dbResultsBody');
  if(!query){if(status)status.textContent='Please enter a query';return;}
  if(status)status.innerHTML='<span class="muted">Running query…</span>';
  try{
    const res=await post('/api/db/query',{database:db,query:query});
    if(!res.success){
      if(status)status.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Query failed')}</span>`;
      return;
    }
    const cols=res.columns||[];
    const rows=res.rows||[];
    if(status)status.innerHTML=`<span class="ok">✓ Returned ${rows.length} row(s) in ${res.duration_ms||0} ms ${res.truncated?'(truncated at 200 rows)':''}</span>`;
    if(!cols.length){
      if(thead)thead.innerHTML='';
      if(tbody)tbody.innerHTML='<tr><td class="muted" style="padding:10px">Query returned no columns.</td></tr>';
      return;
    }
    if(thead)thead.innerHTML='<tr>'+cols.map(c=>`<th>${esc(c)}</th>`).join('')+'</tr>';
    if(tbody){
      tbody.innerHTML=rows.map(r=>{
        return '<tr>'+cols.map(c=>{
          const v=Array.isArray(r)?r[cols.indexOf(c)]:r[c];
          return `<td class="tiny mono" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(v)}">${esc(v===null?'NULL':(typeof v==='object'?JSON.stringify(v):v))}</td>`;
        }).join('')+'</tr>';
      }).join('');
    }
  }catch(err){
    if(status)status.innerHTML=`<span class="bad-t">Error: ${esc(String(err))}</span>`;
  }
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

let traceTimer=null,activeTraceId='',traceSeq=0,traceEvents=[],traceOpenSteps=new Set(),traceView='timeline',activeTraceData=null,traceRevealRedactedDetails=false;
const humanLabel=k=>String(k||'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()).replace(/\bApi\b/g,'API').replace(/\bId\b/g,'ID').replace(/\bUrl\b/g,'URL').replace(/\bHttp\b/g,'HTTP');

function renderAny(value){
  if(value===null||value===undefined)return '<span class="muted">—</span>';
  if(typeof value==='string'){return value.length>180?`<pre class="human-pre">${esc(value)}</pre>`:`<span class="human-value">${esc(value)||'<span class="muted">empty</span>'}</span>`}
  if(typeof value==='number'||typeof value==='boolean')return `<span class="human-value">${esc(String(value))}</span>`;
  if(Array.isArray(value))return value.length?`<div class="human-list">${value.map((v,i)=>`<div class="human-item"><div class="tiny muted">${i+1}</div>${renderAny(v)}</div>`).join('')}</div>`:'<div class="empty-human">empty list</div>';
  if(typeof value==='object'){const entries=Object.entries(value);return entries.length?`<div class="human-grid">${entries.map(([k,v])=>`<div>${esc(humanLabel(k))}</div><div>${renderAny(v)}</div>`).join('')}</div>`:'<div class="empty-human">empty object</div>'}
  return `<span class="human-value">${esc(String(value))}</span>`;
}
function traceSensitiveField(key){return /(api[_-]?key|authorization|token|secret|password|passwd|credential)/i.test(String(key||''));}
function traceSanitizeValue(value,seen=new WeakSet(),reveal=traceRevealRedactedDetails){
  if(value===null||value===undefined||typeof value==='number'||typeof value==='boolean')return value;
  if(typeof value==='string')return reveal?value:redactDiagnostic(value);
  if(Array.isArray(value))return value.map(item=>traceSanitizeValue(item,seen,reveal));
  if(typeof value==='object'){
    if(seen.has(value))return '<cycle omitted>';
    seen.add(value);
    return Object.fromEntries(Object.entries(value).map(([key,item])=>[reveal?key:redactDiagnostic(key),!reveal&&traceSensitiveField(key)?'<redacted>':traceSanitizeValue(item,seen,reveal)]));
  }
  return reveal?String(value):redactDiagnostic(String(value));
}
function traceRecorded(value){
  if(value===null||value===undefined)return false;
  if(typeof value==='string')return value.trim().length>0;
  if(Array.isArray(value))return value.length>0;
  return typeof value!=='object'||Object.keys(value).length>0;
}
function traceFirstRecorded(events,keys){
  for(const event of events||[]){
    const payload=event?.payload;
    if(!payload||typeof payload!=='object')continue;
    for(const key of keys){if(traceRecorded(payload[key]))return payload[key];}
  }
  return undefined;
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
const traceInputFields=new Set(['input','input_text','input_data','user_input','arguments','args','prompt','messages','query','query_params','request','request_data','request_body','request_payload','body','form_data','headers','parameters','payload','method','path','url','endpoint']);
const traceOutputFields=new Set(['output','output_text','output_data','generated_text','response_text','response_body','result','result_data','response','content','text','answer','completion','stdout','stderr','return_value','items']);
const traceProcessFields=new Set(['state','status','stage','phase','progress','progress_percent','percent','step','step_index','current_step','total_steps','completed_steps','attempt','attempts','attempt_number','max_attempts','retry_count','retry_delay_ms','duration','duration_ms','duration_ns','elapsed','elapsed_ms','queue_time_ms','queue_wait_ms','started_at','finished_at','error','error_type','error_message','exception','failure','retry_after','delivery','background','chunks','truncated','status_code']);
function traceEventTitle(type){
  const titles={model_request:'Model input',output_stream:'Model output',output_delta:'Model output chunk',tool_call:'Tool call',tool_result:'Tool result',request_received:'Request received',handler_started:'Handler started',async_job_submitted:'Async job submitted',scheduled:'Scheduled',running:'Running',retry:'Retry',trace_truncated:'Trace truncated',completed:'Completed',complete:'Completed',done:'Completed',success:'Completed',succeeded:'Completed',failed:'Failed',error:'Error',cancelled:'Cancelled',canceled:'Cancelled',interrupted:'Interrupted',request_completed:'Request completed',request_failed:'Request failed'};
  return Object.prototype.hasOwnProperty.call(titles,type)?titles[type]:humanLabel(type||'Event');
}
function traceEventSummary(type,p){
  if(type==='model_request')return `Request to ${p.model||p.provider||'model'}`;
  if(type==='tool_call')return `Calling ${p.name||p.tool||'tool'}`;
  if(type==='tool_result')return p.isError||p.is_error||p.success===false||p.error?'Tool returned an error':'Tool returned a result';
  if(type==='output_stream')return `${n(p.chunks||0)} output chunks${p.truncated?' · truncated':''}`;
  if(type==='output_delta')return 'Output content received';
  if(type==='scheduled')return `Queued${p.model?` · ${p.model}`:''}`;
  if(type==='running')return `Started${p.action?` · ${p.action}`:''}`;
  if(type==='retry')return `Retry${p.attempts?` · attempt ${p.attempts}`:''}`;
  if(type==='request_received')return `${p.method||'Request'}${p.path?` · ${p.path}`:''}`;
  if(type==='handler_started')return `Processing${p.action?` · ${p.action}`:''}`;
  if(type==='async_job_submitted')return 'Background job submitted';
  if(type==='trace_truncated')return 'Some trace data was omitted';
  if(/^(complete|completed|done|success|succeeded|finished)$/i.test(type))return 'Operation completed';
  if(/^(failed|error|request_failed)$/i.test(type))return String(p.error||p.error_message||p.message||'Operation failed').slice(0,160);
  for(const key of ['summary','message','action','name','tool','path','model','job_id','request_id']){
    const value=p[key];if((typeof value==='string'&&value.trim())||typeof value==='number')return String(value).slice(0,160);
  }
  return `${traceEventTitle(type)} event`;
}
function traceEventStatus(type,p,result){
  const r=result||{},raw=String(p.state||p.status||r.state||r.status||'').trim(),eventState=`${type} ${raw}`;
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
  const type=String(event.event_type||'event'),p=traceSanitizeValue(event.payload||{});let pairedResult=null,input='',output='',statusResult=null,groups;
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
    output=`<pre class="trace-output">${esc(p.text||'')}${p.truncated?'…':''}</pre>`;groups=traceEventGroups(p,['text']);
  }else if(type==='output_delta'){
    output=`<pre class="trace-output">${esc(p.text||'')}</pre>`;groups=traceEventGroups(p,['text']);
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
  return `<div class="trace-timeline">${groups.map((group,index)=>{const key=String(group.step||group.index),open=traceOpenSteps.size?traceOpenSteps.has(key):index===groups.length-1,eventsForDisplay=compactTimelineEvents(group.events);return `<div class="trace-step ${open?'open':''}" data-trace-step="${esc(key)}"><button class="trace-step-head" data-trace-toggle aria-expanded="${open}"><span class="trace-step-index">Step ${esc(key)}</span><span>${esc(humanLabel(group.label))}</span><span class="tiny">${group.events.length} events · ${eventsForDisplay.length} shown</span><span class="trace-step-chevron">▶</span></button><div class="trace-step-body">${eventsForDisplay.map((event,eventIndex)=>{const type=String(event.event_type||'event'),body=traceEventBody(event,eventsForDisplay,eventIndex);if(!body)return '';return `<div class="trace-event"><div class="event-head"><span class="event-type">${esc(traceEventTitle(type))}</span><span class="event-time">${event.created_at?new Date(event.created_at*1000).toLocaleTimeString():'—'} · #${esc(event.seq)}</span></div>${body}</div>`}).join('')}</div></div>`}).join('')}</div>`;
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
function traceBoundedEvents(events,eventLimit=100){const list=Array.isArray(events)?events:[],requestReceived=list.find(event=>event?.event_type==='request_received'),latest=list.slice(-eventLimit),visible=requestReceived&&!latest.includes(requestReceived)?[requestReceived,...latest]:latest;return {events:visible.map(event=>traceRawBoundValue(event,2048)),eventsTotal:list.length,eventsTruncated:list.length>visible.length};}
function traceRawBoundValue(value,limit=4096,depth=0){
  if(value===null||value===undefined||typeof value==='number'||typeof value==='boolean')return value;
  if(typeof value==='string')return value.length>limit?value.slice(0,limit)+'… truncated':value;
  if(depth>=4)return '<nested value truncated>';
  if(Array.isArray(value))return value.slice(0,50).map(item=>traceRawBoundValue(item,Math.max(128,Math.floor(limit/50)),depth+1));
  if(typeof value==='object'){const entries=Object.entries(value).slice(0,50),childLimit=Math.max(128,Math.floor(limit/Math.max(entries.length,1)));return Object.fromEntries(entries.map(([key,item])=>[key,traceRawBoundValue(item,childLimit,depth+1)]));}
  return String(value).slice(0,limit);
}
function traceDisplaySession(rawSession){return {trace_id:rawSession.trace_id,kind:rawSession.kind,state:rawSession.state,tenant:rawSession.tenant,agent:rawSession.agent,action:rawSession.action,source:rawSession.source,model:rawSession.model,request_id:rawSession.request_id,async_job_id:rawSession.async_job_id,scheduler_job_id:rawSession.scheduler_job_id,job_id:rawSession.job_id,owner:rawSession.owner,created_at:rawSession.created_at,updated_at:rawSession.updated_at,finished_at:rawSession.finished_at,duration_ms:rawSession.duration_ms,elapsed_ms:rawSession.elapsed_ms,status_code:rawSession.status_code,text_bytes:rawSession.text_bytes,retained_bytes:rawSession.retained_bytes,error:traceRawBoundValue(rawSession.error,1024),request:traceRawBoundValue(rawSession.request),effective_payload:traceRawBoundValue(rawSession.effective_payload),output:traceRawBoundValue(rawSession.output),response:traceRawBoundValue(rawSession.response)};}
function traceRawProjection(detail,eventLimit=100){
  const rawSession=detail?.session||{},eventProjection=traceBoundedEvents(detail?.events,eventLimit),session=traceDisplaySession(rawSession);
  return {session,effective_payload:traceRawBoundValue(rawSession.effective_payload),request:traceRawBoundValue(rawSession.request),output:traceRawBoundValue(rawSession.output),response:traceRawBoundValue(rawSession.response),events:eventProjection.events,events_total:eventProjection.eventsTotal,events_truncated:eventProjection.eventsTruncated};
}
function traceRaw(payload,limit=24000){let raw='';try{raw=JSON.stringify(traceSanitizeValue(payload),null,2)}catch(e){raw=redactDiagnostic(String(e))}const truncated=raw.length>limit;if(truncated)raw=raw.slice(0,limit)+'\n… raw output truncated';return `<section class="human-section trace-raw-panel"><h3>Raw JSON (redacted${truncated?' · truncated':''})</h3><pre class="human-pre">${esc(raw)}</pre></section>`}
function traceEventList(events,limit=100){const shown=(events||[]).slice(-limit),prefix=(events||[]).length>shown.length?`<div class="empty-human">Showing latest ${shown.length} of ${(events||[]).length} events.</div>`:'';return `<section class="human-section"><h3>All events</h3>${prefix}${renderAny(shown)}</section>`}
function tracePanel(id,label,render,available=true){return {id,label,render,available};}
function traceUnavailable(label){return `${label} unavailable for this request type`;}
function traceDisplayModel(detail){
  const rawSession=detail?.session||{},rawEvents=Array.isArray(detail?.events)?detail.events:[];
  const rawEventProjection=traceBoundedEvents(rawEvents),session=traceSanitizeValue(traceDisplaySession(rawSession)),events=traceSanitizeValue(rawEventProjection.events);
  const requestReceived=events.find(event=>event?.event_type==='request_received');
  const requestPayload=requestReceived?.payload&&typeof requestReceived.payload==='object'?requestReceived.payload:{};
  const redactedTraceId=traceRevealRedactedDetails?String(rawSession.trace_id||''):redactDiagnostic(rawSession.trace_id||'');
  const effectivePayload=session.effective_payload;
  const input=traceRecorded(session.request)?session.request:traceRecorded(effectivePayload)?effectivePayload:traceFirstRecorded(events,['request','request_body','request_payload','body','input','payload']);
  const output=traceRecorded(session.output)?session.output:traceFirstRecorded(events,['output','output_text','generated_text','text']);
  const response=traceRecorded(session.response)?session.response:traceFirstRecorded(events,['response','response_body','result']);
  const eventErrors=events.filter(event=>traceRecorded(event?.payload?.error)||traceRecorded(event?.payload?.error_message)||event?.payload?.success===false).map(event=>event.payload);
  const errors=traceRecorded(session.error)?[session.error,...eventErrors]:eventErrors;
  const modelExecutions=events.filter(event=>event?.event_type==='model_request'||event?.event_type==='output_stream'||event?.event_type==='output_delta');
  const toolCalls=events.filter(event=>event?.event_type==='tool_call'||event?.event_type==='tool_result');
  const timing={created_at:session.created_at,updated_at:session.updated_at,finished_at:session.finished_at,duration_ms:session.duration_ms,elapsed_ms:session.elapsed_ms};
  const identity={trace_id:redactedTraceId||session.trace_id,kind:session.kind,action:session.action,source:session.source,method:session.method||requestPayload.method,path:session.path||requestPayload.path||requestPayload.url||requestPayload.endpoint,request_id:session.request_id||requestPayload.request_id};
  const lifecycle={state:traceDisplayState(session),terminal:Boolean(detail?.terminal),status_code:session.status_code};
  const actor={agent:session.agent,tenant:session.tenant,owner:session.owner};
  const correlations={request_id:session.request_id||requestPayload.request_id,async_job_id:session.async_job_id||requestPayload.async_job_id,scheduler_job_id:session.scheduler_job_id||requestPayload.scheduler_job_id,job_id:session.job_id||requestPayload.job_id};
  const retainedBytes=Number(session.text_bytes||session.retained_bytes||0);
  const availability={
    input:traceRecorded(input),output:traceRecorded(output),response:traceRecorded(response),errors:errors.length>0,
    events:events.length>0,modelExecutions:modelExecutions.length>0,toolCalls:toolCalls.length>0,
  };
  const eventsTotal=rawEventProjection.eventsTotal,eventsTruncated=rawEventProjection.eventsTruncated,model={identity,lifecycle,timing,actor,correlations,retainedBytes,input,output,response,errors,events,eventsTotal,eventsTruncated,modelExecutions,toolCalls,effectivePayload,availability,session};
  model.panels=[
    tracePanel('summary','Summary',()=>'',true),
    tracePanel('input','Input',()=>humanSection('Input',input),availability.input),
    tracePanel('output','Output',()=>humanSection('Output',output),availability.output),
    tracePanel('response','Response',()=>humanSection('Response',response),availability.response),
    tracePanel('errors','Errors',()=>humanSection('Errors',errors),availability.errors),
    tracePanel('timeline','Timeline',()=>traceTimeline(events.slice(-100)),availability.events),
    tracePanel('model','Model execution',()=>traceTimeline(modelExecutions.slice(-100)),availability.modelExecutions),
    tracePanel('agent_context','Agent context',()=>humanSection('Agent context',effectivePayload),traceRecorded(effectivePayload)),
    tracePanel('tools','Tool calls',()=>humanSection('Tool calls',toolCalls.slice(-100)),availability.toolCalls),
    tracePanel('events','Events',()=>traceEventList(events),availability.events),
    tracePanel('raw','Raw',()=>traceRaw(traceRawProjection(detail)),true),
  ];
  return model;
}
function traceAvailability(model,unavailableCopy={}){
  const labels=[['input','Input'],['output','Output'],['response','Response'],['errors','Error details'],['events','Events'],['modelExecutions','Model execution'],['toolCalls','Tool calls']];
  return `<section class="human-section"><h3>Trace data availability</h3><div class="human-list">${labels.map(([key,label])=>`<div class="human-item">${model.availability[key]?`<span class="ok">${esc(label)} recorded</span>`:`<span class="muted">${esc(unavailableCopy[key]||traceUnavailable(label))}</span>`}</div>`).join('')}</div></section>`;
}
function traceSummary(model,unavailableCopy){
  const summary={identity:model.identity,lifecycle:model.lifecycle,timing:model.timing,actor:model.actor,correlations:model.correlations,retained_bytes:model.retainedBytes};
  return `<section class="human-section"><h3>Universal request summary</h3>${renderAny(summary)}</section>${traceAvailability(model,unavailableCopy)}`;
}
function renderTraceDetail(d){
  activeTraceData=d;const unavailableCopy={input:'Input unavailable for this request type',output:'Output unavailable for this request type',response:'Response unavailable for this request type'},model=traceDisplayModel(d),s=traceSanitizeValue(model.session),events=model.events;
  if(!model.panels.some(panel=>panel.available&&panel.id===traceView))traceView='summary';
  $('tracePageTitle').textContent=String(s.action||s.source||'Trace');$('tracePageLive').textContent=d?.terminal?'terminal · retained':'● live · auto-refresh';$('tracePageLive').className='tiny '+(d?.terminal?'ok':'trace-running');
  const state=model.lifecycle.state,displayState=traceStatus(s),stateClass=(displayState==='failed'||displayState==='error')?'bad':(displayState==='interrupted'?'warn':(d?.terminal?'ok':'warn'));
  const revealLabel=traceRevealRedactedDetails?'Hide unredacted details':'Reveal redacted details',revealState=traceRevealRedactedDetails?'Unredacted trace details shown locally.':'Trace details are redacted by default.';
  const header=`<div class="trace-inspector-head"><div><div class="trace-kicker">Request trace · Universal inspector</div><strong>${esc(s.action||s.source||'Trace')}</strong><div class="tiny">${esc(s.agent||'unknown actor')} · ${esc(s.model||'model not recorded')}</div></div><span class="badge ${stateClass}">${esc(state)}</span></div><div class="trace-metrics"><span>${model.eventsTotal} events${model.eventsTruncated?' · latest retained view':''}</span><span>${esc(s.tenant||'no tenant')}</span><span>${model.retainedBytes} bytes retained</span><button type="button" class="btn" data-trace-reveal aria-pressed="${traceRevealRedactedDetails}" aria-describedby="trace-reveal-status">${esc(revealLabel)}</button><span id="trace-reveal-status" class="tiny" aria-live="polite">${esc(revealState)}</span></div>`;
  const panels=model.panels.filter(panel=>panel.available),universalSummary=traceSummary(model,unavailableCopy),panelMarkup=panels.map(panel=>{const selected=panel.id===traceView,content=selected?(panel.id==='summary'?'<div class="empty-human">Summary shown above.</div>':panel.render()):'';return `<div id="trace-panel-${esc(panel.id)}" class="trace-view" role="tabpanel" aria-labelledby="trace-tab-${esc(panel.id)}"${selected?'':' hidden'}>${content}</div>`}).join('');
  // Universal request summary and Trace data availability are always rendered before tabs.
  $('tracePageBody').className='trace-page-body';$('tracePageBody').innerHTML=`<div class="human-shell">${header}${universalSummary}<nav class="trace-tabs" role="tablist" aria-label="Trace views">${panels.map(panel=>traceTab(panel.label,panel.id)).join('')}</nav>${panelMarkup}</div>`;
}
function setTraceView(view){if(!activeTraceData)return;const model=traceDisplayModel(activeTraceData);if(!model.panels.some(panel=>panel.available&&panel.id===view))return;traceView=view;renderTraceDetail(activeTraceData)}
function toggleTraceReveal(){if(!activeTraceData)return;traceRevealRedactedDetails=!traceRevealRedactedDetails;renderTraceDetail(activeTraceData)}
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
  activeTraceId=String(id||'');traceSeq=0;traceEvents=[];traceOpenSteps=new Set();traceView='summary';activeTraceData=null;traceRevealRedactedDetails=false;
  renderTraceList(lastTraces);switchTab('traceInspector');
  if(traceTimer)clearInterval(traceTimer);
  const poll=async()=>{
    if(!activeTraceId)return;
    try{
      const r=await apiFetch('/api/debug-traces/'+encodeURIComponent(activeTraceId)+'?since_seq='+traceSeq,{cache:'no-store'}),d=await r.json();
      if(d.success){
        traceSeq=Number(d.next_seq||traceSeq);traceEvents=traceEvents.concat(d.events||[]);renderTraceDetail({...d,events:traceEvents});
        if(d.terminal){clearInterval(traceTimer);traceTimer=null}
      }else{openModal(d,'Trace error');clearInterval(traceTimer);traceTimer=null}
    }catch(e){$('tracePageLive').textContent='refresh failed: '+e.message}
  };
  await poll();traceTimer=setInterval(poll,1000);
}
function openModal(obj,title='',entityType=''){
  $('modalLive').textContent='';
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
  $('modalTitle').textContent=defaultTitle;
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
  $('modalBg').classList.add('open');
  if($('modalBody'))$('modalBody').scrollTop=0;
}

let activeTaskInspectorState=null;

function renderTaskModal(t){
  const st=String(t.status||'planned').toLowerCase();
  const terminal=st==='completed'||st==='failed';
  const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
  const goal=t.contract?.goal||'No goal specified';
  const criteria=t.contract?.acceptance_criteria||[];
  activeTaskInspectorState={taskId:String(t.task_id||''),criteria:[...criteria],status:st};
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
  $('modalTitle').textContent='Create Durable Agent Task';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
    <div class="modal-body-wrap">
      <form class="modal-form" onsubmit="submitCreateTask(event)">
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
          <button type="button" class="btn" onclick="$('modalClose').click()">Cancel</button>
          <button type="submit" class="btn ok">Create Task</button>
        </div>
      </form>
    </div>
  `;
  $('modalBg').classList.add('open');
  setTimeout(()=>$('newTaskGoal')?.focus(),50);
}

async function submitCreateTask(e){
  e.preventDefault();
  const goal=$('newTaskGoal')?.value?.trim();
  if(!goal)return;
  const rawCrit=$('newTaskCriteria')?.value||'';
  const criteria=rawCrit.split(/[\n,]/).map(s=>s.trim()).filter(Boolean);
  const scope=$('newTaskScope')?.value||'task';
  const risk=$('newTaskRisk')?.value||'normal';
  const statusEl=$('createTaskStatus');
  if(statusEl)statusEl.textContent='Creating task…';

  try{
    const res=await post('/api/agent-state/tasks',{
      action:'create',
      goal:goal,
      acceptance_criteria:criteria,
      scope:scope,
      risk_profile:risk
    });
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
      setTimeout(()=>$('modalClose').click(),700);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed to delete')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openRecordMemoryModal(){
  $('modalTitle').textContent='Record Agent Memory';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
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
              <option value="task" selected>Task</option>
              <option value="session">Session</option>
              <option value="repository">Repository</option>
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
        <div id="recordMemStatus" class="tiny"></div>
        <div class="modal-actions-bar" style="justify-content:flex-end;margin-top:10px">
          <button type="button" class="btn" onclick="$('modalClose').click()">Cancel</button>
          <button type="submit" class="btn ok">Record Memory</button>
        </div>
      </form>
    </div>
  `;
  $('modalBg').classList.add('open');
  setTimeout(()=>$('newMemKey')?.focus(),50);
}

async function submitRecordMemory(e){
  e.preventDefault();
  const key=$('newMemKey')?.value?.trim();
  const rawVal=$('newMemVal')?.value?.trim();
  if(!key||rawVal===undefined)return;
  let val=rawVal;
  try{val=JSON.parse(rawVal)}catch{}
  const scope=$('newMemScope')?.value||'task';
  const kind=$('newMemKind')?.value||'fact';
  const statusEl=$('recordMemStatus');
  if(statusEl)statusEl.textContent='Saving memory…';

  try{
    const res=await post('/api/agent-state/memory',{
      action:'record',
      key:key,
      value:val,
      scope:scope,
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
  const op=i.outcome?.tool_name||'agent';
  const msg=i.redacted_message||i.message||'—';
  const cause=i.root_cause||'—';
  const fix=i.verified_fix||'—';
  const status=String(i.status||(i.ignored?'ignored':i.resolved?'resolved':'unresolved'));
  const isIgnored=status==='ignored';
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

      ${!isResolved?`
        <div class="modal-card">
          <div class="modal-card-head"><span>Resolve Anti-Pattern</span></div>
          <div class="modal-card-body">
            <div style="display:flex;gap:8px">
              <input type="text" id="resolveFixInput" placeholder="Enter verified fix or prevention rule..." style="flex:1;background:#131d2b;color:var(--fg);border:1px solid #2d3f56;border-radius:6px;padding:6px 10px;font-size:11px">
              <button class="btn ok" onclick="resolveIncidentAction(${escJs(id)})">Mark Resolved</button>
            </div>
            <div id="resolveIncStatus" class="tiny" style="margin-top:6px"></div>
          </div>
        </div>
      `:''}

      <div class="modal-card">
        <div class="modal-card-head"><span>${isIgnored?'Ignored anti-pattern':'Suppress repeated anti-pattern'}</span></div>
        <div class="modal-card-body" style="display:flex;justify-content:space-between;align-items:center;gap:10px">
          <span class="tiny muted">${isIgnored?'Restore this incident to normal tracking.':'Hide this repeated incident from future negative-knowledge prompts.'}</span>
          <button class="btn ${isIgnored?'':'warn'}" onclick="setIncidentIgnoredAction(${escJs(id)},${!isIgnored})">${isIgnored?'Restore':'Ignore'}</button>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Incident JSON</summary><pre>${esc(JSON.stringify(i,null,2))}</pre></details>
    </div>
  `;
}

async function resolveIncidentAction(id){
  const fix=$('resolveFixInput')?.value?.trim();
  if(!fix)return;
  const statusEl=$('resolveIncStatus');
  if(statusEl)statusEl.textContent='Saving fix…';
  try{
    const res=await post('/api/agent-state/incidents',{action:'resolve',incident_id:id,verified_fix:fix});
    if(res.success){
      await loadAgentOsView();
      if(res.incident)renderIncidentModal(res.incident);
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(res.error||'Failed')}</span>`;
    }
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openRecordIncidentModal(){
  $('modalTitle').textContent='Record Failure Anti-Pattern';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
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
          <button type="button" class="btn" onclick="$('modalClose').click()">Cancel</button>
          <button type="submit" class="btn warn">Record Anti-Pattern</button>
        </div>
      </form>
    </div>
  `;
  $('modalBg').classList.add('open');
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
  $('modalTitle').textContent='Cleanup Stale Agent OS State';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
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
        <button class="btn" onclick="$('modalClose').click()">Cancel</button>
        <button class="btn warn" onclick="executeCleanupAction()">🧹 Execute Cleanup</button>
      </div>
    </div>
  `;
  $('modalBg').classList.add('open');
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
            <div class="tiny" style="margin-top:3px">${esc(JSON.stringify(res))}</div>
          </div>
        </div>
        <div class="modal-actions-bar" style="justify-content:flex-end">
          <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
  const streamId=ev.stream_id||(ev.tenant?('tenant: '+ev.tenant):'—');
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
          Stream / Tenant: <span class="mono">${esc(streamId)}</span>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <div class="modal-card-head"><span>Workspace Controls</span></div>
        <div class="modal-card-body">
          <div class="modal-actions-bar">
            <button class="btn" onclick="projectAction(${escJs(p.root)},'${state==='paused'?'resume':'pause'}');$('modalClose').click()">${state==='paused'?'▶ Resume Preprocessing':'⏸ Pause Preprocessing'}</button>
            <button class="btn ok" onclick="projectAction(${escJs(p.root)},'refresh');$('modalClose').click()">↻ Force Re-scan</button>
            <button class="btn" onclick="exportBundle(${escJs(p.root)})">📦 Export Bundle</button>
            <button class="btn bad" style="margin-left:auto" onclick="deleteProjectDialog(${escJs(p.root)},${escJs(p.project)})">🗑 Unregister / Delete</button>
          </div>
        </div>
      </div>

      <details class="raw-json"><summary>Raw Project Metadata</summary><pre>${esc(JSON.stringify(p,null,2))}</pre></details>
    </div>
  `;
}

function openRegisterProjectModal(){
  $('modalTitle').textContent='Register Project for Preprocessing';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
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
          <button type="button" class="btn" onclick="$('modalClose').click()">Cancel</button>
          <button type="submit" class="btn ok">+ Register Project</button>
        </div>
      </form>
    </div>
  `;
  $('modalBg').classList.add('open');
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
      $('modalClose').click();
      await pollStatus();
    }else{
      if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(r.error||'Failed')}</span>`;
    }
  }catch(err){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(err.message||err)}</span>`;
  }
}

function openDeleteProjectModal(root,name){
  $('modalTitle').textContent='Unregister Project';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
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
        <button class="btn" onclick="$('modalClose').click()">Cancel</button>
        <button class="btn bad" id="confirmDeleteProjectBtn" onclick="confirmDeleteProject(${escJs(root)})">Confirm Unregister / Purge</button>
      </div>
    </div>
  `;
  $('modalBg').classList.add('open');
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
    $('modalClose').click();
    await pollStatus();
  }catch(e){
    if(statusEl)statusEl.innerHTML=`<span class="bad-t">Error: ${esc(e.message||e)}</span>`;
  }
}

function openCleanMissingModal(){
  $('modalTitle').textContent='Prune Missing Worktrees';
  $('modalLive').textContent='';
  $('modalBody').innerHTML=`
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
        <button class="btn" onclick="$('modalClose').click()">Cancel</button>
        <button class="btn warn" onclick="confirmCleanMissing()">🧹 Prune Missing Projects</button>
      </div>
    </div>
  `;
  $('modalBg').classList.add('open');
}

async function confirmCleanMissing(){
  const statusEl=$('cleanMissingStatus');
  if(statusEl)statusEl.textContent='Scanning and cleaning…';
  try{
    const r=await post('/api/preprocess',{action:'cleanup_deleted'});
    $('modalClose').click();
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
        <button class="btn" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

async function openDoctorModal(){
  openModal({},'Local AI Hub Doctor Health Diagnostics','doctor');
  $('modalBody').innerHTML='<div class="modal-body-wrap"><div class="tiny muted">Running comprehensive health diagnostics across Hub, Ollama, GPU, databases and preprocessor…</div></div>';
  try{
    const r=await post('/api/doctor',{});
    renderDoctorModal(r);
  }catch(e){
    $('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="bad-t">Doctor failed: ${esc(e.message||e)}</div></div>`;
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
            <div>Tenant</div><div><b>${esc(l.tenant||'—')}</b></div>
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
    $('modalClose').click();
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
            <div>Tenant</div><div><b>${esc(cmd.tenant||'—')}</b></div>
            <div>Policy Classification</div><div><span class="chip ok">${esc(cmd.class||'safe')}</span></div>
            <div>Age / Running For</div><div>${age(cmd.age_ms)}</div>
            <div>Timeout</div><div>${durSec(cmd.timeout_seconds)}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose').click()">Close</button>
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
            <div>Total Occurrences</div><div class="bad-t"><b>${n(err.count||0)}</b></div>
            <div>Recovered Count</div><div class="ok"><b>${n(err.recovered_count||0)}</b></div>
            <div>Last Seen</div><div>${err.last_seen?new Date(err.last_seen*1000).toLocaleString():'—'}</div>
          </div>
        </div>
      </div>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

function openArchNodeModal(nd){
  const root=nd.root||nd.id||'';
  const label=nd.label||root.split(/[\\/]/).pop()||'Project';
  const outEdges=(archEdges||[]).filter(e=>e.from===root);
  const inEdges=(archEdges||[]).filter(e=>e.to===root);

  openModal({},'Project Architecture Node: '+label,'arch_node');
  $('modalBody').innerHTML=`
    <div class="modal-hero">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="tiny muted mono">ARCHITECTURE GRAPH NODE</div>
          <h2 style="margin:2px 0 0;font-size:16px"><b>${esc(label)}</b></h2>
          <div class="tiny mono muted">${esc(root)}</div>
        </div>
      </div>
    </div>
    <div class="modal-body-wrap">
      <div class="modal-card">
        <div class="modal-card-head"><span>Dependencies (Outgoing Connections: ${outEdges.length})</span></div>
        <div class="modal-card-body">
          ${outEdges.length?outEdges.map(e=>`<div style="padding:4px 0">➔ <b>${esc(e.to.split(/[\\/]/).pop())}</b> <span class="chip">${esc(e.type)}</span> <span class="tiny muted">${esc(e.label)}</span></div>`).join(''):'<div class="muted tiny">No outgoing dependencies.</div>'}
        </div>
      </div>

      <div class="modal-card">
        <div class="modal-card-head"><span>Dependents (Incoming Connections: ${inEdges.length})</span></div>
        <div class="modal-card-body">
          ${inEdges.length?inEdges.map(e=>`<div style="padding:4px 0">⬅ <b>${esc(e.from.split(/[\\/]/).pop())}</b> <span class="chip">${esc(e.type)}</span> <span class="tiny muted">${esc(e.label)}</span></div>`).join(''):'<div class="muted tiny">No incoming dependents.</div>'}
        </div>
      </div>

      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="switchTab('projects');$('modalClose').click()">📁 Open in Projects</button>
        <button class="btn" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

function renderSchedulerJobModal(j){
  const jid=n(j.job_id);
  const state=j.state||'queued';
  const model=j.model||'—';
  const tenant=j.tenant||'default';
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
            <div>Tenant / Namespace</div><div>${esc(tenant)}</div>
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
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

function renderHttpRequestModal(r){
  const rid=r.request_id||'—';
  const agent=r.agent||'unknown';
  const tenant=r.tenant||'default';
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
            <div>Tenant</div><div>${esc(tenant)}</div>
            <div>Duration / In-flight Age</div><div><b>${dur}</b></div>
            <div>Status Code</div><div class="${isErr?'bad-t':'ok'}"><b>${status}</b></div>
            <div>Timestamp</div><div>${dt}</div>
          </div>
        </div>
      </div>
      <details class="raw-json"><summary>Raw Request Details</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>
      <div class="modal-actions-bar" style="justify-content:flex-end">
        <button class="btn ok" onclick="$('modalClose').click()">Close</button>
      </div>
    </div>
  `;
}

$('modalClose').onclick=()=>{$('modalBg').classList.remove('open');activeTraceId='';activeTraceData=null;if(traceTimer)clearInterval(traceTimer);traceTimer=null};
$('modalBg').onclick=e=>{if(e.target===$('modalBg'))$('modalClose').click()};

document.addEventListener('click',e=>{
  const closeBtn=e.target.closest?.('button');
  if(closeBtn && (closeBtn.getAttribute('onclick')?.includes('modalClose') || closeBtn.dataset.modalClose!==undefined || (closeBtn.textContent?.trim()==='Cancel' && closeBtn.closest('#modalBody')))){
    $('modalClose').click();
    return;
  }
  const reveal=e.target.closest?.('[data-trace-reveal]');if(reveal){toggleTraceReveal();return}
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
  const tab=e.target.closest?.('[data-trace-view]');
  if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();moveTraceTab(tab,e.key);
});

function switchTab(tabId){
  if(!tabId||!$(tabId))return;
  document.querySelectorAll('.tabbtn').forEach(x=>x.classList.toggle('active',x.dataset.tab===tabId));
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===tabId));
  try{localStorage.setItem('activeTab',tabId)}catch{}
  if(location.hash.replace('#','')!==tabId)history.replaceState(null,'','#'+tabId);
  if(tabId==='config')loadConfigView();
  if(tabId==='agentos')loadAgentOsView();
  if(tabId==='performance'){loadRagWorkspaces();loadActiveLeases();}
  if(tabId==='commands')loadWorktrees();
}

document.querySelectorAll('.tabbtn').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
window.addEventListener('hashchange',()=>switchTab(location.hash.replace('#','')));
$('pauseEvents').onclick=e=>{paused=!paused;e.target.textContent=paused?'Resume events':'Pause events'};
async function post(path,payload){const r=await apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});return await r.json()}

async function loadConfigView(){
  try{
    const r=await apiFetch('/api/config',{cache:'no-store'}),d=await r.json();
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
  const r=await post('/api/config/update',{action:'update',settings});
  $('cfgStatus').textContent=r.success?'saved · restart hub to apply':('error: '+(r.error||'failed'));
  if(r.success)loadConfigView();
};
$('cfgReset').onclick=async()=>{
  $('modalTitle').textContent='Reset dashboard overrides';
  $('modalLive').textContent='Confirmation required';
  $('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Scope and impact</span></div><div class="modal-card-body"><p><b>Scope:</b> Dashboard-managed configuration override sidecar only.</p><p style="margin-bottom:0"><b>Impact:</b> Removes override values. Base configuration and project data stay unchanged; restart applies result.</p></div></div><div class="modal-actions-bar" style="justify-content:flex-end"><button class="btn" onclick="$('modalClose').click()">Cancel</button><button class="btn warn" id="confirmConfigReset">Reset overrides</button></div></div>`;
  $('modalBg').classList.add('open');
  $('confirmConfigReset').onclick=async()=>{const r=await post('/api/config/update',{action:'reset'});$('cfgStatus').textContent=r.success?'overrides reset · restart hub to apply':('error: '+(r.error||'failed'));if(r.success)loadConfigView();$('modalClose').click();};
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
function projectIdentity(project){
  const root=String(project?.canonical_root||project?.root||project?.project||'').replace(/\\/g,'/').replace(/\/+$/,'');
  const worktreeAt=root.toLowerCase().indexOf('/.worktrees/');
  if(worktreeAt>=0)return root.slice(0,worktreeAt)||root;
  const gitWorktreeAt=root.toLowerCase().indexOf('/worktrees/');
  return gitWorktreeAt>=0?root.slice(0,gitWorktreeAt)||root:root;
}
function projectState(x){
  const progress=Number(x.overall_progress_pct||0);
  if(x.phase==='complete'||x.status==='complete'||progress>=100)return 'ready';
  if(x.paused||x.status==='paused')return 'paused';
  if(x.status==='error'||x.last_error)return 'error';
  if(x.waiting||x.status==='waiting')return 'waiting';
  if(x.status==='running')return 'running';
  return 'queued';
}

function groupedProjects(items){
  const list=Array.isArray(items)?items:[];
  if(!$('projectGroupWorktrees')?.checked)return list.map(x=>({...x,repository_identity:projectIdentity(x),variants:[x]}));
  const groups=new Map();
  list.forEach(item=>{
    const identity=projectIdentity(item)||String(item.project||'unknown');
    const group=groups.get(identity)||[];group.push(item);groups.set(identity,group);
  });
  const rank={error:0,running:1,waiting:2,queued:3,paused:4,ready:5};
  return [...groups.entries()].map(([identity,variants])=>{
    const ordered=[...variants].sort((a,b)=>(rank[projectState(a)]??9)-(rank[projectState(b)]??9));
    return {...ordered[0],canonical_root:identity,repository_identity:identity,variants};
  });
}

function renderProjects(items){
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
    const state=projectState(x),tot=Math.max(1,Number(x.files||0)),ragFiles=Number(x.rag_files||0),cards=Number(x.file_cards||0),ragPct=Math.round(ragFiles/tot*100),cardPct=Math.round(cards/tot*100),overall=Math.max(0,Math.min(100,Number(x.overall_progress_pct||0))),phasePct=Math.max(0,Math.min(100,Number(x.phase_progress_pct||0))),isComplete=state==='ready',isWorktree=(x.root||'').toLowerCase().includes('worktree');
    const badge={running:['badge-running','Running','<span class="pulse-dot"></span>'],waiting:['badge-waiting','Waiting',''],paused:['badge-paused','Paused',''],error:['badge-error','Error',''],ready:['badge-complete','Ready','✓ ']}[state]||['badge-waiting','Queued',''];
    const activityText=x.active_detail||(isComplete?'100% synchronized · real-time sync':state==='paused'?(x.global_paused?'Globally paused':'Project paused'):state==='waiting'?'Waiting for preprocessing slot':state==='error'?(x.last_error_short||'Pipeline error'):'Processing queue');
    const activityCls=isComplete?'ok':state==='error'?'bad-t':state==='paused'?'warn-t':state==='waiting'?'muted':'';
    const progressAge=Number(x.progress_age_seconds),progressHint=Number.isFinite(progressAge)?(progressAge<5?'live checkpoint':`${durSec(progressAge)} since last checkpoint`):'';
    const phaseObj=PHASES.find(ph=>ph.id===x.phase)||(isComplete?PHASES[PHASES.length-1]:{name:x.phase||'Inventory',icon:'⚙️'}),phaseTitle=isComplete?`${PHASES.length}/${PHASES.length} Ready`:`${n(x.phase_index||1)}/${PHASES.length} ${phaseObj.icon} ${phaseObj.name}`;
    const variants=x.variants||[x],variantLabel=variants.length>1?`<span class="chip" title="${esc(variants.map(v=>v.root).join('\n'))}">${variants.length} worktrees</span>`:'';
    const actions=`<div class="project-actions"><button class="action-btn-sm" data-project-action="${state==='paused'?'resume':'pause'}" data-project-root="${esc(x.root)}" title="${state==='paused'?'Resume project preprocessing':'Pause project'}">${state==='paused'?'▶ Resume':'⏸ Pause'}</button><button class="action-btn-sm" data-project-action="refresh" data-project-root="${esc(x.root)}" title="Re-scan selected project entry">Refresh</button><button class="action-btn-sm danger" data-project-action="delete" data-project-root="${esc(x.root)}" data-project-name="${esc(x.project)}" title="Unregister selected project entry">Unregister</button></div>`;
    return clickableRow(x,`<td><div class="project-name"><b>${esc(x.project)}</b>${isWorktree?'<span class="chip" style="font-size:9px;color:var(--accent2);border-color:#584578">worktree</span>':''}${variantLabel}</div><div class="tiny muted">Repository identity</div><div class="tiny muted mono project-root" title="${esc(x.repository_identity||x.root)}">${esc(x.repository_identity||x.root)}</div></td><td><span class="badge-status ${badge[0]}">${badge[2]}${badge[1]}</span><div class="tiny ${activityCls} project-activity" title="${esc(x.active_detail||activityText)}">${esc(activityText)}</div><div class="tiny muted">${esc(progressHint)}</div></td><td><div class="project-progress-line"><b>${phaseTitle}</b><span>${overall}%</span></div><div class="bar project-progress"><i style="width:${overall}%;background:${state==='error'?'var(--bad)':isComplete?'var(--ok)':'var(--accent)'}"></i></div><div class="tiny muted">${phasePct}% in phase</div></td><td><div class="project-index"><span class="${ragFiles>=tot?'ok':''}">🧠 RAG ${ragPct}%</span><span class="${cards>=tot*0.9?'ok':''}">📄 Cards ${cardPct}%</span></div></td><td>${actions}</td>`,'project',x.root);
  },5);
}
async function projectAction(root, action) {
  try { await post('/api/preprocess', { root, action }); await pollStatus(); } catch(e) { alert('Action error: ' + e); }
}
$('regProjectBtn').onclick = openRegisterProjectModal;
$('cleanMissingBtn').onclick = openCleanMissingModal;
async function deleteProjectDialog(root, name) {
  openDeleteProjectModal(root, name);
}

function openControlConfirmation(action){
  const details={
    restart_hub:{title:'Restart hub service',scope:'Local AI Hub process; active API requests may interrupt and recover from journal/cache.',impact:'Service briefly unavailable. No project indexes, models, or configuration are deleted.'},
    stop_service:{title:'Stop hub service',scope:'Local AI Hub service on this host.',impact:'Service becomes unavailable until manually started. Active requests stop.'},
    purge_cache:{title:'Purge expired cache',scope:'Cache entries older than 7 days in configured state directory.',impact:'Expired cached responses removed. Project source and indexes remain intact.'},
  }[action];
  if(!details)return;
  $('modalTitle').textContent=details.title;
  $('modalLive').textContent='Confirmation required';
  $('modalBody').innerHTML=`<div class="modal-body-wrap"><div class="modal-card"><div class="modal-card-head"><span>Scope and impact</span></div><div class="modal-card-body"><p><b>Scope:</b> ${esc(details.scope)}</p><p style="margin-bottom:0"><b>Impact:</b> ${esc(details.impact)}</p></div></div><div class="modal-actions-bar" style="justify-content:flex-end"><button class="btn" onclick="$('modalClose').click()">Cancel</button><button class="btn ${action==='stop_service'?'bad':action==='purge_cache'?'warn':''}" id="confirmControlAction">${esc(details.title)}</button></div></div>`;
  $('modalBg').classList.add('open');
  $('confirmControlAction').onclick=async()=>{try{if(action==='purge_cache')await post('/api/maintenance/purge_cache',{days:7});else await post('/api/control',{action});if(action==='stop_service'){$('conn').textContent='stopping';$('conn').className='pill warn-t';}$('modalClose').click();}catch(error){$('modalLive').textContent='Action failed: '+String(error?.message||error);}};
}
$('restartHub').onclick=()=>openControlConfirmation('restart_hub');
$('stopService').onclick=()=>openControlConfirmation('stop_service');
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
  const headers=[['State','Work item','Model / source','Timing','Reason'],['Request','Agent / tenant','Action','Age'],['Time','Request ID','Agent','Tenant','Action / context','Result','Trace availability','Duration'],['State','Kind','Action / context','Agent / tenant','Model','Created','Updated / duration','Links']];
  sections.forEach((section,index)=>{const row=section.querySelector('thead tr');if(row&&headers[index])row.innerHTML=headers[index].map(x=>`<th>${x}</th>`).join('')});
  work.insertAdjacentHTML('afterbegin','<section class="section work-summary"><div class="work-summary-head"><div><div class="work-kicker">Operations center</div><h2>Live work <span class="tiny">prioritized view</span></h2></div><span class="tiny">Click any row to inspect its trace</span></div><div class="work-kpis"><div><span>Queued</span><strong id="workQueued">—</strong></div><div><span>Running</span><strong id="workRunning">—</strong></div><div><span>Active API</span><strong id="workActive">—</strong></div><div><span>Retained traces</span><strong id="workRetained">—</strong></div></div><div class="work-filter"><input id="workSearch" type="search" placeholder="Search agent, tenant, action, model…" autocomplete="off"><select id="workState" aria-label="Work state"><option value="">All states</option><option value="running">Running</option><option value="queued">Queued</option><option value="failed">Failed</option><option value="completed">Completed</option></select><button class="btn" id="workReset">Reset</button><span class="work-filter-summary" id="workFilterSummary"></span></div></section>');
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
    const code=Number(item.status_code||0),hay=[item.request_id,item.action,item.agent,item.tenant,item.error_type,code,traceContextLabel(requestTrace(item))].filter(Boolean).join(' ').toLowerCase();
    const matchesStatus=!status||(status==='failed'?(item.success===false||code>=400):Math.floor(code/100)===Number(status[0]));
    return (!query||hay.includes(query))&&(!action||String(item.action||'')===action)&&matchesStatus&&(!after||Number(item.created_at||0)>=after);
  });
  const sort=String($('requestHistorySort')?.value||'newest');
  visible.sort((a,b)=>{const time=Number(a.created_at||0)-Number(b.created_at||0);if(sort==='oldest')return time;if(sort==='duration-desc')return Number(b.duration_ms||0)-Number(a.duration_ms||0);if(sort==='status')return Number(b.status_code||0)-Number(a.status_code||0);if(sort==='endpoint')return String(a.action||'').localeCompare(String(b.action||''))||-time;return -time});
  const summary=$('requestHistorySummary');if(summary)summary.textContent=`${visible.length} of ${all.length} loaded · ${counts.size} endpoints`;
  return visible;
}
function workState(state){const value=String(state||'queued'),cls=value==='failed'||value==='error'?'bad':(value==='running'||value==='processing'?'live':'');return `<span class="work-state ${cls}">${esc(value)}</span>`}
function workSchedulerRow(job){const inner=`<td>${workState(job.state)}</td><td><strong>#${n(job.job_id)}</strong><div class="tiny">${esc(job.tenant||'—')}</div></td><td><strong>${esc(job.model||'—')}</strong><div class="tiny">${esc(job.source||'—')}</div></td><td><span class="timing-label">wait</span> ${ms(job.wait_ms)}<div><span class="timing-label">run</span> ${ms(job.service_ms)}</div></td><td>${esc(job.wait_reason||'ready')}</td>`;return schedulerRow(job,inner,5)}
function workActiveRequestRow(request){const inner=`<td><strong>${esc(request.request_id||'—')}</strong></td><td>${esc(request.agent||'—')}<div class="tiny">${esc(request.tenant||'—')}</div></td><td>${esc(request.action||'—')}</td><td>${age(request.age_ms)}</td>`;return requestRow(request,inner,4)}
function requestTrace(request){return lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''))}
function traceContextLabel(trace){
  if(!trace)return '';
  const source=trace.source&&trace.source!==trace.action?trace.source:'',summary=trace.summary||trace.description||trace.operation||trace.action_detail||'',requestId=trace.request_id?`req ${String(trace.request_id).slice(-8)}`:'',jobId=trace.async_job_id?`job ${String(trace.async_job_id).slice(-8)}`:'';
  return [...new Set([trace.request_summary,summary,source,trace.kind?humanLabel(trace.kind):'',trace.model?`model ${trace.model}`:'',requestId,jobId].filter(Boolean))].join(' · ');
}

async function setIncidentIgnoredAction(id,ignored){
  const action=ignored?'ignore':'unignore';
  try{
    const res=await post('/api/agent-state/incidents',{action,incident_id:id});
    if(res.success){
      await loadAgentOsView();
      if(res.incident)renderIncidentModal(res.incident);
    }else{
      alert('Unable to update incident: '+(res.error||'Unknown error'));
    }
  }catch(e){
    alert('Unable to update incident: '+(e.message||e));
  }
}
function requestTraceAvailability(request){
  const trace=requestTrace(request);
  if(trace)return {label:'Trace available',className:'ok',trace};
  if(request.trace_id)return {label:'Trace expired',className:'warn-t',trace:null};
  if(request.trace_available===false)return {label:'No trace recorded',className:'muted',trace:null};
  return {label:'No trace retained',className:'muted',trace:null};
}
function workRecentRequestRow(request){const trace=requestTrace(request),availability=requestTraceAvailability(request),failed=request.success===false||Number(request.status_code||0)>=400,context=trace?traceContextLabel(trace):(request.error_type||availability.label),requestId=String(request.request_id||'—'),inner=`<td>${request.created_at?new Date(request.created_at*1000).toLocaleString():'—'}</td><td><strong>${esc(requestId.slice(-12))}</strong><div class="tiny">${trace?'Trace linked · '+esc(String(trace.trace_id||'').slice(-8)):'Request-only record'}</div></td><td>${esc(request.agent||'—')}</td><td>${esc(request.tenant||'—')}</td><td><strong>${esc(request.action||'—')}</strong><div class="tiny">${esc(context)}</div></td><td><span class="${failed?'bad-t':'ok'}">${n(request.status_code)||'—'}</span>${request.error_type?`<div class="tiny">${esc(request.error_type)}</div>`:''}</td><td><span class="${availability.className}">${esc(availability.label)}</span></td><td>${ms(request.duration_ms)}</td>`;return requestRow(request,inner,8)}

function render(s){
  last=s;
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

  const firstProject=(p.projects||[]).find(x=>x.root);
  const worktreeRoot=$('worktreeRoot');
  if(firstProject&&worktreeRoot&&!worktreeRoot.value)worktreeRoot.value=firstProject.root;

  $('health').innerHTML=`<span class="${s.hub_online&&s.ollama_online?'ok':s.hub_online?'warn-t':'bad-t'}">${s.hub_online?'hub ✓':'hub ✗'} / ${s.ollama_online?'ollama ✓':'ollama ✗'} / ${esc(h.state||'n/a')}</span>`;
  $('uptime').textContent='uptime '+durSec(s.uptime_seconds)+' · supervisor restarts '+n(h.restarts);

  const ep=(rp.execution||{}).models||[];
  const httpTail=o.http_tail_latency||{};
  rows('httpTail',httpTail.by_action||[],x=>clickableRow(x,`<td>${esc(x.action)}</td><td>${n(x.events)}</td><td>${ms(x.p50_duration_ms)}</td><td>${ms(x.p95_duration_ms)}</td><td>${ms(x.p99_duration_ms)}</td><td>${n(x.failures)}</td>`,'http_tail'),6);

  $('fgQueue').textContent=n(q.foreground_queued)+' queued / '+n(q.foreground_inflight)+' running';
  $('bgQueue').textContent='background '+n(q.background_queued)+' queued / '+n(q.inflight_background)+' running · '+(q.background_allowed?'idle work allowed':'yielding');

  const http=o.http||{},cohorts=o.cohorts||{},agentHttp=cohorts.agent_http||{},inference=cohorts.inference||{},policy=cohorts.policy_rejection||{},compatibility=cohorts.compatibility||{},domains=o.cache_domains||{},generation=domains.generation||{},repository=domains.repository||{},commandCache=domains.command||{},netDelta=Number(o.net_cloud_token_delta_est??0),savedTokens=Math.max(0,netDelta),tokenOverhead=Math.max(0,Number(o.cloud_token_overhead_est||0)),grossSaved=Math.max(0,Number(o.gross_cloud_tokens_avoided_est||0)),protocolTokens=Math.max(0,Number(o.agent_protocol_tokens_est||0)),toolCallTokens=Math.max(0,Number(o.agent_tool_request_tokens_est||0)),toolReadTokens=Math.max(0,Number(o.agent_tool_response_tokens_est||0)),schemaTokens=Math.max(0,Number(o.tool_schema_tokens_exposure_est||0)),schemaDelta=Number(o.net_after_schema_token_delta_est??0),localComputeSaved=Math.max(0,Number(o.local_compute_tokens_avoided_est||0)),savedUsd=Number(o.estimated_savings_usd||0),inputSavedUsd=o.estimated_input_savings_usd,outputSavedUsd=o.estimated_output_savings_usd,inputRate=Number(o.cloud_input_token_cost_usd_per_million||0),outputRate=Number(o.cloud_output_token_cost_usd_per_million||0),rate=Number(o.cloud_token_cost_usd_per_million||0);
  $('handledRequests').textContent=n(agentHttp.events);
  $('handledRequestsSub').textContent=n(agentHttp.failures)+' operational failures · '+n(policy.events)+' policy rejections · '+n(compatibility.events)+' compatibility 404s';
  $('tokensSaved').textContent=n(netDelta);
  $('tokensSavedSub').textContent='baseline '+n(grossSaved)+' − protocol '+n(protocolTokens)+' (call '+n(toolCallTokens)+' + read '+n(toolReadTokens)+')'+(tokenOverhead?' · overhead '+n(tokenOverhead):'')+' · schema-adjusted '+n(schemaDelta)+' (catalog ≈'+n(schemaTokens)+')';
  $('dollarsSaved').textContent='≈ $'+savedUsd.toFixed(2);
  $('dollarsSavedSub').textContent=o.estimated_savings_pricing_mode==='input_output'?'input ≈ $'+Number(inputSavedUsd||0).toFixed(4)+' @ $'+inputRate.toFixed(2)+' / 1M · output ≈ $'+Number(outputSavedUsd||0).toFixed(4)+' @ $'+outputRate.toFixed(2)+' / 1M':'estimate · blended $'+rate.toFixed(2)+' / 1M';
  const qHitRate=(Number(o.preprocessed_query_hit_rate??p.query_hit_rate??0)*100).toFixed(1),ingReuse=(Number(p.ingestion_reuse_rate??0)*100).toFixed(1);
  $('cache').textContent=((o.generation_cache_hit_rate ?? o.cache_hit_rate ?? 0)*100).toFixed(1)+'%';
  $('cacheSub').textContent=n(generation.hits)+' generation · '+n(repository.hits)+' repository ('+qHitRate+'% index hit) · '+n(commandCache.hits)+' command hits · '+n(localComputeSaved)+' local tokens avoided';
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
  const liveChartEmpty=$('liveChartEmpty');
  const hasLiveChartSamples=Boolean(agentHttp.events||curP95||curWait),liveChartCanvas=$('liveChartCanvas'),liveChartSummary=$('liveChartSummary');
  if(liveChartEmpty)liveChartEmpty.style.display=hasLiveChartSamples?'none':'block';
  const liveChartLabel=hasLiveChartSamples?`Live telemetry graph. Current p95 latency ${ms(curP95)}. Current queue wait ${ms(curWait)}. ${liveChartLatency.length} rolling samples.`:'Live telemetry graph. No latency or queue samples yet.';
  if(liveChartCanvas)liveChartCanvas.setAttribute('aria-label',liveChartLabel);
  if(liveChartSummary)liveChartSummary.textContent=hasLiveChartSamples?`Current p95 latency ${ms(curP95)} · queue wait ${ms(curWait)} · ${liveChartLatency.length} rolling samples`:'No latency or queue samples yet.';

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
  $('prepSub').textContent=n(p.active_projects)+' active · '+n(p.processing_projects)+'/'+n(p.max_preprocessing_projects)+' preprocessing · card reuse '+ingReuse+'% · query hit '+qHitRate+'%';

  const allJobs=[...(q.inflight_jobs||[]),...(q.pending_jobs||[])];
  $('currentSummary').textContent=n(q.foreground_queued)+' queued · '+n(q.foreground_inflight)+' running';
  rows('overviewJobs',allJobs.slice(0,12),j=>schedulerRow(j,`<td>${esc(j.state)}</td><td>${esc(j.tenant)}</td><td>${esc(j.source)}</td><td>${esc(j.model)}</td><td>${ms(j.wait_ms)}</td><td>${ms(j.service_ms)}</td><td>${esc(j.wait_reason)}</td>`),7);

  const hs=o.hotspots||[];
  $('hotspots').innerHTML=hs.length?hs.map((x,i)=>`<div>${esc(x.type||'signal')}</div><div><span class="chip">${esc(x.signal||'')}</span> ${esc(x.value??x.value_ms??x.count??'')}</div>`).join(''):'<div>Status</div><div class="ok">No persistent hotspot detected</div>';

  const recentRequests=o.recent_http||[],visibleJobs=workVisible(allJobs),visibleActive=workVisible(o.active_requests||[]),visibleRecent=filterRecentRequests(workVisible(recentRequests),recentRequests);
  $('queueSummary').textContent=n(q.foreground_queued)+' fg + '+n(q.background_queued)+' bg queued · '+n(q.foreground_inflight)+' fg + '+n(q.inflight_background)+' bg running';
  $('workQueued').textContent=n((q.foreground_queued||0)+(q.background_queued||0));
  $('workRunning').textContent=n((q.foreground_inflight||0)+(q.inflight_background||0));
  $('workActive').textContent=n((o.active_requests||[]).length);
  $('workRetained').textContent=n(lastTraces.length);
  $('workFilterSummary').textContent=`showing ${visibleJobs.length+visibleActive.length+visibleRecent.length} live/history items`;

  rows('jobs',visibleJobs,j=>workSchedulerRow(j),5);
  rows('activeReq',visibleActive,x=>workActiveRequestRow(x),4);
  rows('recentReq',visibleRecent,x=>workRecentRequestRow(x),8);
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

  rows('executionProfiles',ep,x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${esc(x.tier)}</td><td>${n(x.num_ctx)}</td><td>${n(x.max_ctx)}</td><td>${n(x.parallel_limit)}</td><td>${x.think?'on':'role-gated/off'}</td><td>${n(x.prompt_budget_tokens)}</td>`,'execution_profile'),7);
  rows('models',o.by_model||[],x=>clickableRow(x,`<td>${esc(x.model)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${ms(x.avg_load_ms)}</td><td>${n(x.failures)}</td>`,'model_stat'),5);
  rows('cacheLayers',o.cache_layers||[],x=>clickableRow(x,`<td>${esc(x.layer)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.context_tokens_avoided_est)}</td>`,'cache_layer'),4);
  rows('agents',o.by_agent||[],x=>clickableRow(x,`<td>${esc(x.agent)}</td><td>${n(x.requests)}</td><td>${n(x.local_inference_calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`,'agent_stat'),5);
  rows('routes',o.execution_routes||[],x=>clickableRow(x,`<td>${esc(x.route)}</td><td>${esc(x.task_type)}</td><td>${esc(x.complexity)}</td><td>${n(x.calls)}</td><td>${ms(x.avg_ms)}</td><td>${n(x.failures)}</td>`,'route_stat'),6);

  $('commandState').textContent=n(cmd.active_count)+' running';
  rows('activeCommands',cmd.active||[],x=>clickableRow(x,`<td>${esc(x.command)}</td><td>${esc(x.cwd)}</td><td>${esc(x.tenant)}</td><td>${esc(x.class)}</td><td>${age(x.age_ms)}</td><td>${durSec(x.timeout_seconds)}</td>`,'command'),6);
  $('commandStats').innerHTML=`<div>Executed</div><div>${n(cmd.executed)}</div><div>Cache hits / misses</div><div>${n(cmd.hits)} / ${n(cmd.misses)}</div><div>Coalesced waiters</div><div>${n(cmd.coalesced_waiters)}</div><div>Policy blocked</div><div>${n(cmd.blocked)}</div>`;
  rows('blockedReasons',Object.entries(cmd.blocked_by_reason||{}),x=>clickableRow({reason:x[0],count:x[1]},`<td>${esc(x[0])}</td><td>${n(x[1])}</td>`,'blocked_reason'),2);

  renderReliabilitySummary(s);
  rows('errors',o.recent_errors||[],x=>clickableRow(x,`<td>${esc(x.component)}</td><td>${esc(x.operation)}</td><td>${n(x.count)}</td><td>${n(x.recovered_count)}</td><td>${x.last_seen?new Date(x.last_seen*1000).toLocaleTimeString():'—'}</td>`,'error'),5);
  $('runtimeCounters').innerHTML=`<div>Scheduler submitted</div><div>${n(ss.submitted)}</div><div>Completed / failed</div><div>${n(ss.completed)} / ${n(ss.failed)}</div><div>Model switches</div><div>${n(ss.model_switches)}</div><div>Queue rejections</div><div>${n(ss.queue_rejections)}</div><div>Caller timeouts</div><div>${n(ss.caller_timeouts)}</div><div>Background yields</div><div>${n(ss.background_yields)}</div><div>Supervisor restarts</div><div>${n(h.restarts)}</div>`;

  if($('hubHealthCard'))$('hubHealthCard').onclick=()=>switchTab('reliability');
  rows('sessionRows',o.sessions||[],x=>{
    const st=x.status||'unknown',stBadge=st==='active'?`<span class="badge ok">Active (PID ${n(x.pid)})</span>`:st==='clean_stop'?`<span class="badge" style="background:#1e293b;color:#94a3b8;border:1px solid #334155">Clean stop</span>`:`<span class="badge bad" title="Exit unclean or process terminated unexpectedly">Crashed / Killed</span>`,hitPct=((Number(x.cache_hit_rate||0))*100).toFixed(1),started=x.started_at?new Date(x.started_at*1000).toLocaleString():'—';
    return clickableRow(x,`<td>${started}</td><td>${durSec(x.duration_seconds)}</td><td>${stBadge}</td><td>${n(x.events)}</td><td>${hitPct}% <span class="tiny muted">(${n(x.cache_hits)})</span></td><td>${n(x.tokens_saved)}</td><td><code>${esc(x.version||'—')}</code></td>`,'session');
  },7);

  renderBundles(s);
}

function renderReliabilitySummary(snapshot){
  const observability=snapshot?.observability||{},cohorts=observability.cohorts||{},agent=cohorts.agent_http||{},runtime=snapshot?.headless||{},sessions=observability.sessions||[];
  const failures=Math.max(0,Number(agent.failures||0)),restarts=Math.max(0,Number(runtime.restarts||0)),crashes=sessions.filter(x=>!['active','clean_stop'].includes(String(x.status||''))).length;
  const severity=failures||crashes?'attention':restarts?'warning':'healthy';
  const label=severity==='attention'?'Needs attention':severity==='warning'?'Monitor':'Healthy';
  const headline=$('reliabilityHeadline'),trend=$('reliabilityTrend'),action=$('reliabilityAction');
  if(headline)headline.innerHTML=`<div>Current severity</div><div><span class="${severity==='healthy'?'ok':severity==='attention'?'bad-t':'warn-t'}"><b>${label}</b></span></div><div>Operational failures</div><div>${n(failures)}</div><div>Supervisor restarts</div><div>${n(restarts)}</div><div>Unclean sessions</div><div>${n(crashes)}</div>`;
  if(trend){const prior=sessions.slice(1),priorCrashes=prior.filter(x=>!['active','clean_stop'].includes(String(x.status||''))).length;trend.textContent=`Failure trend: ${failures?'active request failures need review':'no active request failures'}; ${crashes} unclean session${crashes===1?'':'s'} in retained history${priorCrashes?` (${priorCrashes} earlier)`:' '}.`;}
  if(action){action.textContent=failures?'Open failed request history':'Open restart history';action.onclick=()=>switchTab(failures?'work':'reliability');}
}

function schedulerRow(job,html,cols){const linked=lastTraces.find(x=>String(x.scheduler_job_id||'')===String(job.job_id||''));const id=linked?.trace_id||job.trace_id;if(id)return `<tr class="click" data-trace-id="${esc(id)}">${html}</tr>`;return clickableRow(job,html,'scheduler_job');}
function requestRow(request,html,cols){const linked=lastTraces.find(x=>String(x.request_id||'')===String(request.request_id||''));if(linked)return `<tr class="click" data-trace-id="${esc(linked.trace_id)}">${html}</tr>`;return clickableRow(request,html,'http_request');}

function renderTraceList(items){
  const base=workVisible(items||[]),kind=String($('traceKind')?.value||''),matching=base.filter(x=>!kind||x.kind===kind);
  const tableQuery=String($('traceTableSearch')?.value||'').trim().toLowerCase(),tableState=String($('traceTableState')?.value||''),tableSort=String($('traceTableSort')?.value||'newest');
  const tableVisible=matching.filter(x=>{const state=traceStatus(x),hay=[x.trace_id,x.request_id,x.action,x.source,x.kind,x.agent,x.tenant,x.model,x.error_type,x.error,traceContextLabel(x)].filter(Boolean).join(' ').toLowerCase();return (!tableQuery||hay.includes(tableQuery))&&(!tableState||state===tableState)});
  tableVisible.sort((a,b)=>{const time=Number(a.updated_at||a.created_at||0)-Number(b.updated_at||b.created_at||0);if(tableSort==='oldest')return -time;if(tableSort==='action')return String(a.action||'').localeCompare(String(b.action||''))||-time;if(tableSort==='duration'){const ad=Number(a.updated_at||a.created_at||0)-Number(a.created_at||0),bd=Number(b.updated_at||b.created_at||0)-Number(b.created_at||0);return bd-ad||-time}if(tableSort==='state')return String(traceStatus(a)).localeCompare(String(traceStatus(b)))||-time;return -time});
  const historyQuery=String($('traceHistorySearch')?.value||'').trim().toLowerCase(),historyState=$('traceHistoryState')?.value||'useful';
  const sidebarVisible=matching.filter(x=>{const state=traceStatus(x),hay=[x.trace_id,x.request_id,x.action,x.source,x.kind,x.agent,x.tenant,x.model,x.error,traceContextLabel(x)].filter(Boolean).join(' ').toLowerCase();return (!historyQuery||hay.includes(historyQuery))&&(historyState==='useful'?(state!=='interrupted'&&state!=='failed'):(!historyState||state===historyState))});
  $('traceSummary').textContent=`${tableVisible.length} shown · ${n(items?.length||0)} retained · full prompt/output · bounded retention`;
  if($('workRetained'))$('workRetained').textContent=n(items?.length||0);
  rows('traces',tableVisible,x=>{const state=traceStatus(x),cls='trace-'+state,links=[x.async_job_id&&('job '+String(x.async_job_id).slice(0,10)),x.scheduler_job_id&&('sched '+String(x.scheduler_job_id).slice(0,10))].filter(Boolean).join(' · '),activity=x.updated_at&&x.created_at?durSec(Math.max(0,Number(x.updated_at)-Number(x.created_at))):'—',context=traceContextLabel({...x,kind:'',model:''});return `<tr class="click" data-trace-id="${esc(x.trace_id)}"><td class="${cls}">${esc(humanLabel(state))}</td><td>${esc(humanLabel(x.kind||'trace'))}</td><td><strong>${esc(x.action||'—')}</strong><div class="tiny">${esc(context||'No request details')}</div></td><td>${esc(x.agent||'—')}<div class="tiny">${esc(x.tenant||'—')}</div></td><td>${esc(x.model||'—')}</td><td>${x.created_at?new Date(x.created_at*1000).toLocaleTimeString():'—'}</td><td>${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'}<div class="tiny">${esc(activity)} total</div></td><td class="tiny">${esc(links||'open trace')}</td></tr>`},8);
  $('traceSideSummary').textContent=`${sidebarVisible.length} trace${sidebarVisible.length===1?'':'s'} · click to inspect`;
  $('traceSidebarList').innerHTML=sidebarVisible.length?sidebarVisible.map(x=>{const state=traceStatus(x),label=state==='interrupted'?'Interrupted':state,cls=state==='interrupted'?'interrupted':(state==='failed'||state==='error'?'failed':(x.terminal||state==='completed'||state==='succeeded'?'done':'')),kindLabel=x.kind==='api_request'?'API request':humanLabel(x.kind||'trace'),context=traceContextLabel({...x,kind:'',model:''});return `<button class="trace-side-item ${String(x.trace_id)===activeTraceId?'active':''}" data-trace-page-id="${esc(x.trace_id)}"><span class="trace-side-top"><span class="trace-side-state ${cls}"></span><span class="trace-side-action">${esc(x.action||x.kind||'Trace')}</span><span class="tiny spacer">${esc(label)}</span></span><span class="trace-side-meta">${esc(context||x.agent||'unknown agent')}</span><span class="trace-side-meta">${esc(x.agent||'unknown agent')} · ${esc(kindLabel)} · ${x.updated_at?new Date(x.updated_at*1000).toLocaleTimeString():'—'} · ${esc(x.tenant||'no tenant')}</span></button>`}).join(''):'<div class="empty-human">No retained traces</div>';
}
async function pollTraces(){try{const kind=$('traceKind')?.value||'',suffix=kind?'&kind='+encodeURIComponent(kind):'',r=await apiFetch('/api/debug-traces?limit=200'+suffix,{cache:'no-store'}),d=await r.json();if(d.success){lastTraces=d.items||[];renderTraceList(lastTraces)}}catch(e){console.warn('trace refresh failed',e)}}
$('traceRefresh')?.addEventListener('click',pollTraces);$('traceKind')?.addEventListener('change',()=>renderTraceList(lastTraces));
$('traceHistorySearch')?.addEventListener('input',()=>renderTraceList(lastTraces));$('traceHistoryState')?.addEventListener('change',()=>renderTraceList(lastTraces));

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
    const r=await apiFetch('/api/live/status?light=1&scope='+sloScope,{cache:'no-store'}),s=await r.json();
    render(s);hasLiveStatus=true;$('conn').textContent='live';$('conn').className='pill ok';$('updated').textContent='updated '+new Date().toLocaleTimeString();
    try{
      const gr=await apiFetch('/api/hardware/system',{cache:'no-store'});
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
      }
    }catch{}
  }catch(e){console.error('dashboard status refresh failed',e);if(last&&lastOverviewReceivedAt)renderOverviewHealth(last,lastOverviewReceivedAt);$('conn').textContent=hasLiveStatus?'stale':'offline';$('conn').className=hasLiveStatus?'pill warn-t':'pill bad-t'}
  finally{statusPollInFlight=false}
}
let liveEvents=[];
function eventSeverity(event){
  if(event?.success===false||/fail|error|crash|reject/i.test([event?.kind,event?.event_type,event?.status].join(' ')))return 'failure';
  if(/warn|retry|degrad|stale/i.test([event?.kind,event?.event_type,event?.status].join(' ')))return 'warning';
  return 'success';
}
function renderEvents(events=liveEvents){
  if(Array.isArray(events)&&events.length){liveEvents=[...events,...liveEvents].slice(0,300);}
  if(paused)return;
  const box=$('eventList');if(!box)return;
  const severity=String($('eventSeverity')?.value||''),source=String($('eventSource')?.value||'').trim().toLowerCase();
  const filtered=liveEvents.filter(event=>{const kind=eventSeverity(event),hay=[event.agent,event.kind,event.event_type,event.action,event.stage,event.model,event.tenant].filter(Boolean).join(' ').toLowerCase();return (!severity||kind===severity)&&(!source||hay.includes(source));}).slice(0,120);
  const summary=$('eventSummary');if(summary)summary.textContent=`${filtered.length} of ${liveEvents.length} retained events`;
  const html=filtered.map(e=>{const id='d'+(++seq),severity=eventSeverity(e);dataStore.set(id,{data:e,type:'event'});if(dataStore.size>5000){dataStore.delete(dataStore.keys().next().value);}const label=severity==='failure'?'FAIL':severity==='warning'?'WARN':'OK';return `<div class="event click" data-detail="${id}" data-type="event"><span>${new Date((e.created_at||0)*1000).toLocaleTimeString()}</span><span>${esc(e.agent||e.kind||'')}</span><span>${esc(e.event_type||'')}</span><span>${esc(e.action||e.stage||'')}</span><span class="hide-sm">${esc(e.model||e.tenant||'')}</span><span>${e.duration_ms?ms(e.duration_ms):''}</span><span class="${severity==='failure'?'bad-t':severity==='warning'?'warn-t':'ok'}">${label}</span></div>`}).join('');
  box.innerHTML=html||'<div class="empty">No events match current severity/source filters.</div>';
}
$('eventSeverity')?.addEventListener('change',()=>renderEvents([]));
$('eventSource')?.addEventListener('input',()=>renderEvents([]));
async function pollEvents(){try{const r=await apiFetch('/api/live?after='+cursor+'&limit=200',{cache:'no-store'}),d=await r.json();cursor=Number(d.cursor||cursor);renderEvents(d.events||[])}catch{}}

probeHealth();pollStatus();pollEvents();pollTraces();
let isVisible=!document.hidden;
document.addEventListener('visibilitychange',()=>{
  isVisible=!document.hidden;
  if(isVisible){probeHealth();pollStatus();pollEvents();pollTraces();}
});
setInterval(()=>{if(isVisible)probeHealth();},5000);
setInterval(()=>{if(isVisible)pollStatus();},1000);
setInterval(()=>{if(isVisible)pollEvents();},1000);
setInterval(()=>{if(isVisible)pollTraces();},2000);

// ── Bundles ────────────────────────────────────────────────────────────────────
function renderBundles(s){
  const projs=groupedProjects(s?.preprocessing?.projects||[]);
  $('bundleExportTable').innerHTML=projs.length?projs.map(p=>{
    const state=projectState(p),progress=Math.round(Number(p.overall_progress_pct||0)),ready=state==='ready'||progress>=100;
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
  const r=await apiFetch('/api/bundle/export',{method:'POST',headers:{'Content-Type':'application/zip'},body:JSON.stringify({root})});
  if(!r.ok){alert('Export failed: '+(await r.text()));return;}
  const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bundle.zip';a.click();URL.revokeObjectURL(url);
}
$('bundleImport')?.addEventListener('click',async()=>{
  const file=$('bundleFile')?.files?.[0];if(!file){$('bundleImportStatus').textContent='Select a file first';return;}
  $('bundleImportStatus').textContent='Uploading…';
  const target=$('bundleTargetRoot')?.value?.trim()||'';const suffix=target?'?target_root='+encodeURIComponent(target):'';
  try{
    const r=await apiFetch('/api/bundle/import'+suffix,{method:'POST',headers:{'Content-Type':'application/zip'},body:await file.arrayBuffer()});
    const d=await r.json();
    $('bundleImportStatus').textContent=d.success?'Import successful: '+String(d.root||''):'Error: '+String(d.error||'failed');
  }catch(e){$('bundleImportStatus').textContent='Upload error: '+e.message}
});

// ── Agent OS ──────────────────────────────────────────────────────────────────
let agentOsTasks=[], agentOsMemories=[], agentOsIncidents=[];
async function loadAgentOsView(){
  try{
    const [tasksRes, memRes, incRes] = await Promise.all([
      apiFetch('/api/agent-state/tasks', {cache:'no-store'}).then(r=>r.json()).catch(()=>({tasks:[]})),
      apiFetch('/api/agent-state/memory', {cache:'no-store'}).then(r=>r.json()).catch(()=>({records:[]})),
      post('/api/agent-state/incidents', {action:'list', limit:100}).catch(()=>({incidents:[]})),
    ]);
    agentOsTasks=tasksRes.tasks||[];
    agentOsMemories=memRes.records||[];
    agentOsIncidents=incRes.incidents||[];
    renderAgentOsView();
  }catch(e){console.warn('Agent OS view load error', e)}
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
    const incidentStatus=String(i.status||(i.ignored?'ignored':i.resolved?'resolved':'unresolved'));
    if(incFilter!==''&&incidentStatus!==incFilter)return false;
    if(!incQuery)return true;
    const hay=[i.incident_id,i.error_class,i.redacted_message,i.root_cause,i.verified_fix,incidentStatus].join(' ').toLowerCase();
    return hay.includes(incQuery);
  });

  if($('agentOsSummary'))$('agentOsSummary').textContent=`${filteredTasks.length} tasks · ${filteredMem.length} memories · ${filteredInc.length} incidents`;
  if($('agentOsState')){
    const act=agentOsTasks.filter(t=>String(t.status).toLowerCase()==='active').length;
    $('agentOsState').textContent=`${act} active · ${agentOsTasks.length} total tasks · ${agentOsMemories.length} memories`;
  }

  rows('agentOsTasksBody',filteredTasks,t=>{
    const st=String(t.status||'planned').toLowerCase();
    const cls=st==='completed'?'badge-complete':(st==='failed'?'badge-error':(st==='active'?'badge-running':'badge-waiting'));
    const goal=esc(t.contract?.goal||'—');
    const chk=t.checkpoint?`${esc(t.checkpoint.phase||'')} ➔ ${esc(t.checkpoint.next_action||'')}`:'—';
    const crit=(t.contract?.acceptance_criteria||[]).length?(t.contract.acceptance_criteria.length+' criteria'):'—';
    const dt=t.updated_at?new Date(t.updated_at*1000).toLocaleTimeString():'—';
    return clickableRow(t,`<td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td><strong>${esc(t.task_id)}</strong></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${esc(t.contract?.scope||'task')}</span></td><td class="tiny">${chk}</td><td class="tiny">${esc(crit)}</td><td class="tiny">${dt}</td>`,'task',t.task_id);
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
    return clickableRow(m,`<td><span class="chip">${sc}</span></td><td><span class="chip">${kd}</span></td><td><strong>${k}</strong></td><td class="tiny mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${esc(v)}</td><td class="tiny">${conf}</td><td class="tiny">${src}</td><td class="tiny">${dt}</td>`,'memory',(m.scope||'task')+':'+m.key);
  },7);

  rows('agentOsIncBody',filteredInc,i=>{
    const id=esc(i.incident_id||'—');
    const status=String(i.status||(i.ignored?'ignored':i.resolved?'resolved':'unresolved'));
    const statusChip=status==='ignored'?'<span class="chip">ignored</span>':status==='resolved'?'<span class="chip ok">resolved</span>':'<span class="chip warn-t">unresolved</span>';
    const op=esc(i.outcome?.tool_name||'agent');
    const ec=esc(i.error_class||'Error');
    let msg=esc(i.redacted_message||'');
    if(msg.length>45)msg=msg.slice(0,42)+'...';
    const cause=esc(i.root_cause||'—');
    const fix=esc(i.verified_fix||'—');
    return clickableRow(i,`<td><strong>${id}</strong></td><td>${statusChip}</td><td>${n(i.attempts||1)}</td><td><span class="chip">${op}</span></td><td><span class="chip bad-t">${ec}</span></td><td class="tiny" title="${esc(i.redacted_message||'')}">${msg}</td><td class="tiny">${cause}</td><td class="tiny ok">${fix}</td>`,'incident',i.incident_id);
  },8);
}

$('agentOsRefresh')?.addEventListener('click',loadAgentOsView);
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
    const identity=ragWorkspaceIdentity(w),chunks=Number(w.chunks??w.document_count??w.count??0),state=String(w.status||w.state||(chunks?'ready':'empty')),stateClass=/error|failed/i.test(state)?'bad-t':chunks?'ok':'warn-t';
    const contents=[chunks&&`${n(chunks)} chunks`,w.files&&`${n(w.files)} files`,w.embedding_model&&String(w.embedding_model)].filter(Boolean).join(' · ')||'No indexed content reported';
    return `<tr><td><b>${esc(identity.split('/').filter(Boolean).pop()||identity)}</b><div class="tiny muted mono" title="${esc(identity)}">${esc(identity)}</div></td><td><span class="${stateClass}">${esc(humanLabel(state))}</span></td><td class="tiny">${esc(contents)}</td></tr>`;
  }).join('')}</tbody></table></div>`:'<span class="muted">No RAG workspace matches current search.</span>';
}
async function loadRagWorkspaces(){
  try{
    const r=await apiFetch('/api/rag/workspaces',{cache:'no-store'}),d=await r.json();
    ragWorkspaces=d.workspaces||[];
    renderRagWorkspaces();
  }catch(e){if($('ragWorkspacesList'))$('ragWorkspacesList').textContent='Failed to load workspaces'}
}
$('ragWorkspaceSearch')?.addEventListener('input',renderRagWorkspaces);

async function loadActiveLeases(){
  try{
    const r=await apiFetch('/api/leases',{cache:'no-store'}),d=await r.json();
    const leases=d.leases||[];
    rows('activeLeasesBody',leases,l=>{
      const id=esc(l.lease_id||'—');
      const paths=Array.isArray(l.paths)?l.paths.map(p=>`<span class="chip mono">${esc(p)}</span>`).join(' '):esc(l.path||'');
      const tenant=esc(l.tenant||'—');
      const purp=esc(l.purpose||'agent edit');
      const exp=l.expires_in_seconds?durSec(l.expires_in_seconds):'—';
      const action=`<button class="action-btn-sm danger" data-release-lease="${id}">Release</button>`;
      return clickableRow(l,`<td><strong>${id}</strong></td><td>${paths}</td><td>${tenant}</td><td class="tiny">${purp}</td><td class="tiny ok">${exp}</td><td>${action}</td>`,'lease',l.lease_id);
    },6);
  }catch(e){console.warn('Leases load error',e)}
}
document.addEventListener('click',async e=>{
  const btn=e.target.closest?.('[data-release-lease]');
  if(!btn)return;
  const leaseId=btn.dataset.releaseLease;
  try{
    await post('/api/leases/release',{lease_id:leaseId});
    await loadActiveLeases();
  }catch(err){alert('Release lease error: '+err)}
});

// ── Git Worktrees Manager ──────────────────────────────────────────────────
async function loadWorktrees(){
  try{
    const root=$('worktreeRoot')?.value?.trim()||'.';
    const r=await apiFetch('/api/coord/worktrees?root='+encodeURIComponent(root),{cache:'no-store'});
    const d=await r.json();
    const wts=d.worktrees||[];
    if($('worktreeSummary'))$('worktreeSummary').textContent=`${wts.length} active worktree${wts.length===1?'':'s'}`;
    rows('worktreesTable',wts,w=>{
      const dir=esc(w.worktree||'—');
      const br=esc(String(w.branch||'—').replace('refs/heads/',''));
      const head=esc(String(w.head||'—').slice(0,8));
      const isLocked=!!w.locked;
      const isPrunable=!!w.prunable;
      let statusBadge='<span class="chip ok">active</span>';
      if(isLocked) statusBadge='<span class="chip warn-t">locked</span>';
      else if(isPrunable) statusBadge='<span class="chip bad-t">prunable</span>';
      const act=`<button class="action-btn-sm danger" data-release-worktree="${dir}">Remove</button>`;
      return `<tr><td class="mono tiny">${dir}</td><td><span class="chip">${br}</span></td><td class="mono tiny">${head}</td><td>${statusBadge}</td><td>${act}</td></tr>`;
    },5);
  }catch(e){console.warn('Failed to load worktrees',e)}
}

$('refreshWorktreesBtn')?.addEventListener('click',loadWorktrees);
$('pruneWorktreesBtn')?.addEventListener('click',async()=>{
  if(!confirm('Prune stale Git worktrees?'))return;
  const root=$('worktreeRoot')?.value?.trim()||'.';
  try{
    await post('/api/coord/worktree_prune',{root});
    await loadWorktrees();
  }catch(err){alert('Prune worktrees error: '+err)}
});

document.addEventListener('click',async e=>{
  const btn=e.target.closest?.('[data-release-worktree]');
  if(!btn)return;
  const wtPath=btn.dataset.releaseWorktree;
  if(!wtPath)return;
  if(!confirm(`Remove worktree ${wtPath}?`))return;
  const root=$('worktreeRoot')?.value?.trim()||'.';
  try{
    await post('/api/coord/worktree_release',{root,worktree_path:wtPath});
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
      const lat=Math.round(performance.now()-t0);
      const model=res.route?.model||res.model||(complexity==='auto'?'qwen2.5-coder:1.5b':'qwen2.5-coder:3b');
      const gen=res.eval_count||res.tokens_generated||0;
      const tps=res.eval_duration?Math.round((gen/(res.eval_duration/1e9))*10)/10:(lat>0&&gen>0?Math.round((gen/(lat/1000))*10)/10:'—');
      if(labelEl)labelEl.textContent=`${complexity==='auto'?'Fast Tier':'Smart Tier'} (${model})`;
      if(statsEl)statsEl.innerHTML=`<span class="chip ok">⚡ ${lat}ms</span> <span class="chip">Tokens: ${gen}</span> <span class="chip">Speed: ${tps} t/s</span>`;
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
    const r=await apiFetch('/api/agent-state/tasks?limit=100',{cache:'no-store'});
    const d=await r.json();
    cachedTrajTasks=d.tasks||[];
    renderTrajectories();
  }catch(e){console.warn('Failed to load trajectories',e)}
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
    const stepsCount=(t.checkpoint?.affected_paths?.length||0)+Object.keys(t.verification_receipts||{}).length;
    const tokensUsed=t.checkpoint?.state_data?.tokens_used?n(t.checkpoint.state_data.tokens_used):'—';
    const act=`<button class="action-btn-sm" data-view-traj="${tid}">Inspect</button>`;
    return `<tr class="click" data-view-traj="${tid}"><td><strong>${tid}</strong></td><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis" title="${goal}">${goal}</td><td><span class="chip">${stepsCount} steps</span></td><td class="tiny mono">${tokensUsed}</td><td><span class="badge-status ${cls}">${esc(st.toUpperCase())}</span></td><td>${act}</td></tr>`;
  },6);
}

$('trajSearch')?.addEventListener('input',renderTrajectories);
$('trajRefreshBtn')?.addEventListener('click',loadTrajectories);

async function viewTrajectory(taskId){
  if(!taskId)return;
  const task=cachedTrajTasks.find(t=>t.task_id===taskId);
  const panel=$('trajDetailPanel');
  const title=$('trajDetailTitle');
  const list=$('trajStepsList');
  if(!panel||!list)return;
  panel.style.display='block';
  title.innerHTML=`Trajectory Inspection: <code>${esc(taskId)}</code> — <span class="muted">${esc(task?.contract?.goal||'')}</span>`;
  list.innerHTML='<div class="tiny muted">Loading event stream & trajectory steps…</div>';

  try{
    const r=await apiFetch('/api/agent-state/events?stream_id='+encodeURIComponent(taskId),{cache:'no-store'});
    const d=await r.json();
    const evs=d.events||[];
    if(!evs.length){
      const cp=task?.checkpoint||{};
      const receipts=Object.entries(task?.verification_receipts||{});
      list.innerHTML=`<div class="trace-event" style="border-left:2px solid var(--accent);padding:8px;margin-bottom:8px">
        <div style="font-weight:600;font-size:12px;margin-bottom:4px">Phase: ${esc(cp.phase||'init')} ➔ Next: ${esc(cp.next_action||'—')}</div>
        <div class="tiny muted">Affected Paths: ${esc((cp.affected_paths||[]).join(', ')||'none')}</div>
        <div class="tiny muted">Evidence IDs: ${esc((cp.evidence_ids||[]).join(', ')||'none')}</div>
        ${receipts.length?`<div style="margin-top:6px;font-size:11px"><b>Receipts:</b> ${receipts.map(([k,v])=>`<span class="chip ok">${esc(k)}</span>`).join(' ')}</div>`:''}
      </div>`;
      return;
    }
    list.innerHTML=evs.map(ev=>{
      const kind=esc(ev.event_type||ev.kind||'event');
      const time=ev.timestamp?new Date(ev.timestamp*1000).toLocaleTimeString():'';
      const payload=typeof ev.payload==='object'?JSON.stringify(ev.payload,null,2):String(ev.payload||'');
      return `<div class="trace-event" style="border-left:2px solid var(--accent);padding:8px;margin-bottom:8px;background:#0d1219;border-radius:4px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span class="chip"><b>${kind}</b></span>
          <span class="tiny muted">#${ev.seq||0} · ${time}</span>
        </div>
        <pre style="margin:0;font-size:11px;color:#d7e2ef;max-height:160px;overflow:auto">${esc(payload)}</pre>
      </div>`;
    }).join('');
  }catch(err){
    list.innerHTML=`<div class="bad-t">Failed to load trajectory events: ${esc(err.message||err)}</div>`;
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

const initTab = location.hash.replace('#','') || localStorage.getItem('activeTab') || 'overview';
switchTab(initTab);
</script></body></html>"""
