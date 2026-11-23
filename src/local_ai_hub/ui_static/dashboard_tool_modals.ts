// @ts-nocheck
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

