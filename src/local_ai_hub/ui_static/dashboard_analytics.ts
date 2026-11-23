// @ts-nocheck
// ── Long-Term Endpoint & MCP Analytics ────────────────────────────────────────
let cachedEndpointStats = null;
let endpointStatsLoading = false;
let epCurrentScope = 'active';
let epSortCol = 'p95';
let epSortAsc = false;

function setEpTableSort(col) {
  if (epSortCol === col) {
    epSortAsc = !epSortAsc;
  } else {
    epSortCol = col;
    epSortAsc = (col === 'name' || col === 'type');
  }
  syncEpSortSelect();
  renderEndpointStatsView();
}

function syncEpSortSelect() {
  const sel = $('epStatsSortSelect');
  if (!sel) return;
  let key = `${epSortCol}_${epSortAsc ? 'asc' : 'desc'}`;
  if (epSortCol === 'success') {
    key = epSortAsc ? 'fail_desc' : 'succ_desc';
  }
  for (let i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === key) {
      sel.selectedIndex = i;
      return;
    }
  }
}

function epSortIndicator(col) {
  if (epSortCol !== col) return '<span style="color:var(--muted);opacity:0.35;margin-left:3px;font-size:9px">⇅</span>';
  return epSortAsc ? '<span style="color:var(--accent);margin-left:3px;font-size:10px;font-weight:bold">▲</span>' : '<span style="color:var(--accent);margin-left:3px;font-size:10px;font-weight:bold">▼</span>';
}

async function loadEndpointStatsView() {
  if (endpointStatsLoading) return;
  endpointStatsLoading = true;
  const project = $('epStatsProjectSelect')?.value || '';
  const statusMsg = $('epStatsStatusMsg');
  if (statusMsg) statusMsg.textContent = 'Aktualizace…';

  try {
    const url = '/api/telemetry/endpoint-stats' + (project ? '?root=' + encodeURIComponent(project) : '');
    const res = await fetchDashboardJson(url, { cache: 'no-store' });
    if (!res || !res.success) {
      if ($('epStatsList')) $('epStatsList').innerHTML = '<div class="tiny bad-t">Chyba načítání: ' + esc(res?.error || 'unknown') + '</div>';
      return;
    }
    cachedEndpointStats = res;
    const statsSub = $('endpointStatsSub');
    if (statsSub) {
      const windowLabel = res.window === 'stored_since_reset' ? 'souhrn od posledního resetu' : 'časové okno neuvedeno';
      const methodLabel = res.latency_method === 'fixed_histogram_bucket_estimate' ? 'odhady z histogramu' : 'metoda latence neuvedena';
      const ceilingMs = Number(res.histogram_bucket_ceiling_ms);
      const bucketLabel = res.histogram_top_bucket_open_ended === true && Number.isFinite(ceilingMs) && ceilingMs > 0
        ? ` · horní koš otevřený, odhadovaný strop ${Math.round(ceilingMs / 1000)} s`
        : '';
      statsSub.textContent = `p50 / p95 / p99: ${methodLabel} · ${windowLabel}${bucketLabel}`;
    }

    const projSelect = $('epStatsProjectSelect');
    if (projSelect && Array.isArray(res.projects)) {
      const currentVal = projSelect.value;
      const opts = ['<option value="">Globální (Všechny projekty)</option>'];
      for (const p of res.projects) {
        let label = p;
        try {
          if (p.startsWith('legacy:')) label = 'historické: ' + decodeURIComponent(p.slice(7));
          else if (p.startsWith('root:')) { const parts = p.split(':'); label = decodeURIComponent(parts.slice(2).join(':')) + ' · ' + parts[1].slice(0, 8); }
        } catch {}
        opts.push(`<option value="${esc(p)}"${p === currentVal ? ' selected' : ''}>${esc(label)}</option>`);
      }
      projSelect.innerHTML = opts.join('');
    }

    renderEndpointStatsView();
    if (statusMsg) statusMsg.textContent = 'Aktualizováno ' + new Date().toLocaleTimeString();
  } catch (err) {
    if ($('epStatsList')) $('epStatsList').innerHTML = '<div class="tiny bad-t">Chyba načítání: ' + esc(String(err)) + '</div>';
  } finally {
    endpointStatsLoading = false;
  }
}

function renderEndpointStatsView() {
  const data = cachedEndpointStats;
  if (!data || !Array.isArray(data.items)) return;

  const totalCount = data.total_items || data.items.length;
  const unusedCount = data.unused_count || 0;
  const activeCount = totalCount - unusedCount;

  if ($('epCountTotal')) $('epCountTotal').textContent = totalCount;
  if ($('epCountActive')) $('epCountActive').textContent = activeCount;
  if ($('epCountUnused')) $('epCountUnused').textContent = unusedCount;

  const slowEl = $('epStatsSlowCount');
  if (slowEl) {
    if (data.slow_count > 0) {
      slowEl.style.display = 'inline-block';
      slowEl.textContent = `${data.slow_count} pomalé (>1s)`;
    } else {
      slowEl.style.display = 'none';
    }
  }

  const failEl = $('epStatsFailingCount');
  if (failEl) {
    if (data.failing_count > 0) {
      failEl.style.display = 'inline-block';
      failEl.textContent = `${data.failing_count} padající (<90%)`;
    } else {
      failEl.style.display = 'none';
    }
  }

  $('epScopeActive')?.classList.toggle('active', epCurrentScope === 'active');
  $('epScopeAll')?.classList.toggle('active', epCurrentScope === 'all');
  $('epScopeUnused')?.classList.toggle('active', epCurrentScope === 'unused');

  const typeFilter = $('epStatsTypeSelect')?.value || 'all';

  let items = data.items.slice();
  if (typeFilter !== 'all') {
    items = items.filter(it => it.type === typeFilter);
  }

  if (epCurrentScope === 'active') {
    items = items.filter(it => (it.calls || 0) > 0);
  } else if (epCurrentScope === 'unused') {
    items = items.filter(it => (it.calls || 0) === 0);
  }

  items.sort((a, b) => {
    let diff = 0;
    if (epSortCol === 'calls') {
      diff = (a.calls || 0) - (b.calls || 0);
    } else if (epSortCol === 'p95') {
      diff = (a.p95_ms || 0) - (b.p95_ms || 0);
    } else if (epSortCol === 'p50') {
      diff = (a.p50_ms || 0) - (b.p50_ms || 0);
    } else if (epSortCol === 'p99') {
      diff = (a.p99_ms || 0) - (b.p99_ms || 0);
    } else if (epSortCol === 'success') {
      const aSucc = a.calls > 0 ? (a.success_rate != null ? a.success_rate : 100) : -1;
      const bSucc = b.calls > 0 ? (b.success_rate != null ? b.success_rate : 100) : -1;
      diff = aSucc - bSucc;
    } else if (epSortCol === 'type') {
      diff = a.type.localeCompare(b.type);
    } else if (epSortCol === 'name') {
      diff = a.name.localeCompare(b.name);
    }
    if (diff === 0) {
      diff = a.name.localeCompare(b.name);
    }
    return epSortAsc ? diff : -diff;
  });

  const activeItems = data.items.filter(it => (it.calls || 0) > 0);
  let maxActiveP95 = 10.0;
  let maxActiveCalls = 1;
  for (const it of activeItems) {
    if (it.p95_ms > maxActiveP95) maxActiveP95 = it.p95_ms;
    if (it.calls > maxActiveCalls) maxActiveCalls = it.calls;
  }

  const topGrid = $('epTopChartsGrid');
  if (topGrid) {
    if (epCurrentScope === 'unused' || activeItems.length === 0) {
      topGrid.style.display = 'none';
    } else {
      topGrid.style.display = 'grid';

      const topLatency = activeItems.slice().sort((a, b) => (b.p95_ms || 0) - (a.p95_ms || 0)).slice(0, 5);
      const latHtml = topLatency.map(it => {
        const isMcp = it.type === 'mcp';
        const p50 = it.p50_ms || 0;
        const p95 = it.p95_ms || 0;
        const p99 = it.p99_ms || 0;
        const barWidth = Math.max(8, Math.min(100, (p95 / maxActiveP95) * 100));
        const p50Pct = p95 > 0 ? Math.min(100, (p50 / p95) * 100) : 50;

        return `
        <div style="font-size:11px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">
            <div style="display:flex;align-items:center;gap:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:65%">
              <span class="pill" style="font-size:9px;padding:1px 4px;background:${isMcp ? '#2e1065;color:#c084fc' : '#082f49;color:#38bdf8'}">${isMcp ? 'MCP' : 'HTTP'}</span>
              <code style="font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis" title="${esc(it.name)}">${esc(it.name)}</code>
            </div>
            <div style="font-family:monospace;font-size:10px;color:var(--muted)">
              <span style="color:#38bdf8">${p50 >= 1000 ? (p50/1000).toFixed(1)+'s' : p50.toFixed(0)+'ms'}</span> / 
              <span style="color:#f59e0b;font-weight:600">${p95 >= 1000 ? (p95/1000).toFixed(1)+'s' : p95.toFixed(0)+'ms'}</span> / 
              <span style="color:#f43f5e">${p99 >= 1000 ? (p99/1000).toFixed(1)+'s' : p99.toFixed(0)+'ms'}</span>
            </div>
          </div>
          <div style="background:var(--bg);height:12px;border-radius:3px;overflow:hidden;display:flex">
            <div style="width:${barWidth}%;height:100%;display:flex;border-radius:3px;overflow:hidden">
              <div style="width:${p50Pct}%;background:#38bdf8;height:100%" title="p50: ${p50.toFixed(1)}ms"></div>
              <div style="flex:1;background:#f59e0b;height:100%" title="p95: ${p95.toFixed(1)}ms"></div>
            </div>
          </div>
        </div>`;
      }).join('');
      if ($('epLatencyBenchmarkChart')) $('epLatencyBenchmarkChart').innerHTML = latHtml || '<div class="tiny muted">Žádná aktivní data</div>';

      const topCalls = activeItems.slice().sort((a, b) => (b.calls || 0) - (a.calls || 0)).slice(0, 5);
      const trafHtml = topCalls.map(it => {
        const isMcp = it.type === 'mcp';
        const calls = it.calls || 0;
        const succ = it.success_rate != null ? it.success_rate : 100;
        const barWidth = Math.max(8, Math.min(100, (calls / maxActiveCalls) * 100));
        const color = succ >= 98 ? '#10b981' : (succ >= 90 ? '#f59e0b' : '#ef4444');

        return `
        <div style="font-size:11px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">
            <div style="display:flex;align-items:center;gap:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:65%">
              <span class="pill" style="font-size:9px;padding:1px 4px;background:${isMcp ? '#2e1065;color:#c084fc' : '#082f49;color:#38bdf8'}">${isMcp ? 'MCP' : 'HTTP'}</span>
              <code style="font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis" title="${esc(it.name)}">${esc(it.name)}</code>
            </div>
            <div style="font-family:monospace;font-size:10px">
              <strong>${n(calls)}</strong> <span style="color:${color}">(${succ.toFixed(1)}%)</span>
            </div>
          </div>
          <div style="background:var(--bg);height:12px;border-radius:3px;overflow:hidden">
            <div style="width:${barWidth}%;background:${color};height:100%;border-radius:3px" title="${calls} volání, ${succ.toFixed(1)}% úspěch"></div>
          </div>
        </div>`;
      }).join('');
      if ($('epTrafficBenchmarkChart')) $('epTrafficBenchmarkChart').innerHTML = trafHtml || '<div class="tiny muted">Žádná aktivní data</div>';
    }
  }

  const listEl = $('epStatsList');
  if (!listEl) return;
  if (items.length === 0) {
    listEl.innerHTML = '<div class="tiny muted" style="padding:24px;text-align:center">Žádné endpointy neodpovídají zvolenému filtru.</div>';
    return;
  }

  let tableHtml = `
  <div class="table-wrap">
    <table style="width:100%;border-collapse:collapse;font-size:11px">
      <thead>
        <tr style="border-bottom:1px solid var(--line);color:var(--muted);text-align:left">
          <th style="width:52px;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('type')" title="Řadit podle typu">Typ ${epSortIndicator('type')}</th>
          <th style="padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('name')" title="Řadit podle názvu">Endpoint / Nástroj ${epSortIndicator('name')}</th>
          <th style="width:115px;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('calls')" title="Řadit podle volání">Volání ${epSortIndicator('calls')}</th>
          <th style="width:85px;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('success')" title="Řadit podle úspěšnosti">Úspěšnost ${epSortIndicator('success')}</th>
          <th style="width:26%;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('p95')" title="Řadit podle p95 latence">Relativní latence (p50 / p95) ${epSortIndicator('p95')}</th>
          <th style="width:75px;text-align:right;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('p50')" title="Řadit podle p50">p50 ${epSortIndicator('p50')}</th>
          <th style="width:75px;text-align:right;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('p95')" title="Řadit podle p95">p95 ${epSortIndicator('p95')}</th>
          <th style="width:75px;text-align:right;padding:6px 8px;cursor:pointer;user-select:none" onclick="setEpTableSort('p99')" title="Řadit podle p99">p99 ${epSortIndicator('p99')}</th>
        </tr>
      </thead>
      <tbody>`;

  for (const item of items) {
    const isMcp = item.type === 'mcp';
    const calls = item.calls || 0;
    const p50 = item.p50_ms || 0;
    const p95 = item.p95_ms || 0;
    const p99 = item.p99_ms || 0;
    const issues = Array.isArray(item.issues) ? item.issues : [item.status];

    let succClass = 'ok';
    let succText = `${item.success_rate != null ? item.success_rate.toFixed(1) : 100}%`;
    if (calls === 0) {
      succClass = 'muted';
      succText = '0 volání';
    } else if (item.success_rate != null && item.success_rate < 90) {
      succClass = 'bad-t';
    } else if (item.success_rate != null && item.success_rate < 98) {
      succClass = 'warn-t';
    }

    const relCallsWidth = Math.max(2, Math.min(100, (calls / maxActiveCalls) * 100));
    const relLatWidth = calls > 0 ? Math.max(4, Math.min(100, (p95 / maxActiveP95) * 100)) : 0;
    const p50Pct = p95 > 0 ? Math.min(100, (p50 / p95) * 100) : 50;

    tableHtml += `
    <tr style="border-bottom:1px solid var(--line);background:var(--panel2)">
      <td style="padding:6px 8px">
        <span class="pill" style="font-size:9px;padding:1px 5px;font-weight:600;background:${isMcp ? '#2e1065;color:#c084fc' : '#082f49;color:#38bdf8'}">${isMcp ? 'MCP' : 'HTTP'}</span>
      </td>
      <td style="padding:6px 8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
        <code style="font-size:12px;font-weight:600;color:var(--text)" title="${esc(item.name)}">${esc(item.name)}</code>
        ${issues.includes('slow') ? '<span class="pill warn-t" style="font-size:9px;margin-left:4px">SLOW</span>' : ''}
        ${issues.includes('failing') ? '<span class="pill bad-t" style="font-size:9px;margin-left:4px">FAILING</span>' : ''}
      </td>
      <td style="padding:6px 8px">
        ${calls > 0 ? `
        <div style="display:flex;align-items:center;gap:6px">
          <span style="font-family:monospace;width:32px">${n(calls)}</span>
          <div style="flex:1;background:var(--bg);height:6px;border-radius:2px;overflow:hidden">
            <div style="width:${relCallsWidth}%;background:#64748b;height:100%"></div>
          </div>
        </div>
        ` : `<span style="color:var(--muted)">0</span>`}
      </td>
      <td style="padding:6px 8px">
        <span class="pill ${succClass}" style="font-size:10px;font-weight:600">${succText}</span>
      </td>
      <td style="padding:6px 8px">
        ${calls > 0 ? `
        <div style="display:flex;align-items:center;gap:6px">
          <div style="flex:1;background:var(--bg);height:10px;border-radius:2px;overflow:hidden;display:flex">
            <div style="width:${relLatWidth}%;height:100%;display:flex">
              <div style="width:${p50Pct}%;background:#38bdf8;height:100%" title="p50: ${p50.toFixed(1)}ms"></div>
              <div style="flex:1;background:#f59e0b;height:100%" title="p95: ${p95.toFixed(1)}ms"></div>
            </div>
          </div>
        </div>
        ` : `<span class="tiny muted">—</span>`}
      </td>
      <td style="padding:6px 8px;text-align:right;font-family:monospace;color:${calls > 0 ? 'var(--text)' : 'var(--muted)'}">
        ${calls > 0 ? (p50 >= 1000 ? (p50/1000).toFixed(2)+'s' : p50.toFixed(1)+'ms') : '—'}
      </td>
      <td style="padding:6px 8px;text-align:right;font-family:monospace;font-weight:600;color:${calls > 0 ? (p95 >= 1000 ? '#f59e0b' : 'var(--text)') : 'var(--muted)'}">
        ${calls > 0 ? (p95 >= 1000 ? (p95/1000).toFixed(2)+'s' : p95.toFixed(1)+'ms') : '—'}
      </td>
      <td style="padding:6px 8px;text-align:right;font-family:monospace;color:${calls > 0 ? (p99 >= 2000 ? '#f43f5e' : 'var(--muted)') : 'var(--muted)'}">
        ${calls > 0 ? (p99 >= 1000 ? (p99/1000).toFixed(2)+'s' : p99.toFixed(1)+'ms') : '—'}
      </td>
    </tr>`;
  }

  tableHtml += `</tbody></table></div>`;
  listEl.innerHTML = tableHtml;
}

$('epScopeActive')?.addEventListener('click', () => { epCurrentScope = 'active'; renderEndpointStatsView(); });
$('epScopeAll')?.addEventListener('click', () => { epCurrentScope = 'all'; renderEndpointStatsView(); });
$('epScopeUnused')?.addEventListener('click', () => { epCurrentScope = 'unused'; renderEndpointStatsView(); });
$('epStatsProjectSelect')?.addEventListener('change', () => loadEndpointStatsView());
$('epStatsTypeSelect')?.addEventListener('change', () => renderEndpointStatsView());
$('epStatsSortSelect')?.addEventListener('change', () => {
  const val = $('epStatsSortSelect')?.value || 'p95_desc';
  const parts = val.split('_');
  if (parts.length >= 2) {
    const dir = parts.pop();
    const col = parts.join('_');
    if (col === 'fail') {
      epSortCol = 'success';
      epSortAsc = true;
    } else if (col === 'succ') {
      epSortCol = 'success';
      epSortAsc = false;
    } else {
      epSortCol = col;
      epSortAsc = (dir === 'asc');
    }
  }
  renderEndpointStatsView();
});
$('epStatsRefreshBtn')?.addEventListener('click', () => loadEndpointStatsView());
$('subtabEndpointStatsJump')?.addEventListener('click', () => {
  $('endpointStatsSection')?.scrollIntoView({ behavior: 'smooth' });
  loadEndpointStatsView();
});
$('epStatsResetBtn')?.addEventListener('click', async () => {
  const project = $('epStatsProjectSelect')?.value || '';
  const label = project ? (project.startsWith('legacy:') ? 'historickou skupinu se stejným názvem složky' : 'vybraný kořen projektu') : 'VŠECHNY projekty globálně';
  if (!confirm(`Opravdu chcete resetovat dlouhodobé statistiky pro ${label}?`)) return;
  const res = await post('/api/telemetry/endpoint-stats/reset', { root: project });
  if (res && res.success) {
    await loadEndpointStatsView();
  } else {
    alert('Resetování selhalo: ' + (res?.error || 'neznámá chyba'));
  }
});

