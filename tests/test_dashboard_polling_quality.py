from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

DASHBOARD_HTML = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "dashboard.py")
)["DASHBOARD_HTML"]


def _run_polling_javascript(scenario: str, *, include_status: bool = False) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard polling")
    marker = "function createDashboardStatusPoller"
    if marker not in DASHBOARD_HTML:
        pytest.fail("dashboard polling controller is not implemented")
    start = DASHBOARD_HTML.index(marker)
    end = DASHBOARD_HTML.index("async function apiFetch", start)
    polling_source = DASHBOARD_HTML[start:end]
    if include_status:
        status_start = DASHBOARD_HTML.index("async function pollStatus(")
        status_end = DASHBOARD_HTML.index("const statusPoller=", status_start)
        status_source = DASHBOARD_HTML[status_start:status_end]
        setup = """
        const document = {visibilityState: 'visible'};
        const nodes = {conn: {}, updated: {}, sysUtil: {}, sysSub: {}};
        const $ = id => nodes[id];
        let apiFetch;
        let statusPollInFlight = false, hasLiveStatus = false, statusPollAbortController = null;
        let sloScope = '1h', last = null, lastOverviewReceivedAt = null, rendered = 0;
        function render() { rendered++; }
        """
        polling_source = setup + polling_source + status_source
    runnable_source = (
        polling_source
        + "\n(async () => {\n"
        + scenario
        + "\n})().catch(error => { console.error(error); process.exitCode = 1; });\n"
    )
    script = (
        "const vm = require('node:vm');\n"
        f"vm.runInNewContext({json.dumps(runnable_source)}, {{require, process, setImmediate, console, AbortController}});\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "dashboard_polling.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(script_path)], capture_output=True, text=True, timeout=5
        )
    assert result.returncode == 0, result.stderr or result.stdout


def test_agent_os_event_source_restores_last_composite_cursor() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard EventSource reconnect")
    marker = "let sseSource=null"
    start = DASHBOARD_HTML.index(marker)
    end = DASHBOARD_HTML.index("function handleAgentOsStreamEvent", start)
    stream_source = DASHBOARD_HTML[start:end]
    setup = r"""
      const assert = require('node:assert/strict');
      const stored = new Map([['agentOsStreamLastEventId', 'task%3Aone:6']]);
      const sessionStorage = {getItem: key => stored.get(key) || null, setItem: (key, value) => stored.set(key, value)};
      const nodes = {sseStreamBadge: {}};
      const $ = id => nodes[id];
      const getSavedToken = () => '';
      const apiToken = '';
      const received = [];
      function handleAgentOsStreamEvent(event) { received.push(event); }
      class EventSource {
        constructor(url) { this.url = url; EventSource.last = this; }
        close() { this.closed = true; }
      }
    """
    scenario = r"""
      connectAgentOsStream();
      const first = new URL(EventSource.last.url, 'http://localhost');
      assert.equal(first.searchParams.get('last_event_id'), 'task%3Aone:6');
      const old = EventSource.last;
      old.onmessage({lastEventId: 'task%3Aone:7', data: JSON.stringify({event_id: 'event-7'})});
      connectAgentOsStream();
      const resumed = new URL(EventSource.last.url, 'http://localhost');
      assert.equal(old.closed, true);
      assert.equal(resumed.searchParams.get('last_event_id'), 'task%3Aone:7');
      assert.equal(received.length, 1);
    """
    script = (
        "const vm = require('node:vm');\n"
        f"vm.runInNewContext({json.dumps(setup + stream_source + scenario)}, "
        "{require, process, URL, URLSearchParams, console});\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "dashboard_event_source.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(script_path)], capture_output=True, text=True, timeout=5
        )
    assert result.returncode == 0, result.stderr or result.stdout


def test_trajectory_inspector_pages_with_cursor_and_reports_retention_gap() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard trajectory paging")
    marker = "async function viewTrajectory(taskId, afterSeq=0, append=false)"
    if marker not in DASHBOARD_HTML:
        pytest.fail("dashboard trajectory inspector is not implemented")
    start = DASHBOARD_HTML.index(marker)
    end = DASHBOARD_HTML.index("\ndocument.addEventListener('click',e=>{", start)
    trajectory_source = DASHBOARD_HTML[start:end]
    setup = r"""
      const assert = require('node:assert/strict');
      const list = {
        _innerHTML: '', children: [],
        get innerHTML() { return this._innerHTML; },
        set innerHTML(value) { this._innerHTML = value; this.children = []; },
        appendChild(node) {
          node.remove = () => { this.children = this.children.filter(item => item !== node); };
          this.children.push(node);
          this._innerHTML += node.textContent;
          return node;
        },
        querySelector(selector) {
          const className = selector === '.trajectory-load-more' ? 'trajectory-load-more'
            : selector === '.trajectory-gap' ? 'trajectory-gap' : '';
          return this.children.find(node => String(node.className || '').split(/\s+/).includes(className)) || null;
        },
        insertAdjacentHTML(_position, html) { this._innerHTML += html; },
      };
      const nodes = {trajDetailPanel: {style: {}}, trajDetailTitle: {}, trajStepsList: list};
      const $ = id => nodes[id];
      const cachedTrajTasks = [{task_id: 'task-1', checkpoint: {phase: 'test'}}];
      const document = {createElement: () => ({style: {}, dataset: {}, textContent: ''})};
      const esc = value => String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
      const traceOutputValueMarkup = value => JSON.stringify(value);
      let apiFetch;
    """
    scenario = r"""
      const asJson = page => JSON.stringify(page);
      const pages = [
        asJson({events: [{seq: 2, created_at: 1, kind: 'task.progress', payload: {phase: 'one', next_seq: 999}},
          {seq: 6, created_at: 1.5, kind: 'task.progress', payload: {phase: 'two'}}], next_seq: 6,
          first_retained_seq: 2, last_seq: 10, has_more: true, gap_ranges: [{from_seq: 3, to_seq: 5}]}),
        asJson({events: [{seq: 7, created_at: 2, kind: 'task.done', payload: {phase: 'two'}}], next_seq: 7,
          first_retained_seq: 4, last_seq: 10, has_more: false, gap_ranges: []}),
        asJson({events: [{seq: '<img src=x onerror=1>', created_at: 3, kind: 'task.started', payload: {phase: 'legacy'}}],
          next_seq: 6, has_more: true, gap_ranges: [], retention_gap_metadata_available: false}),
        asJson({events: [{seq: 7, created_at: 4, kind: 'task.done', payload: {phase: 'legacy'}}], next_seq: 7,
          has_more: false, gap_ranges: [], retention_gap_metadata_available: false}),
        '{"events":[{"seq":9007199254740995,"created_at":5,"kind":"task.progress","payload":{"phase":"large"}}],"next_seq":9007199254740995,"has_more":true,"gap_ranges":[]}',
        '{"events":[{"seq":9007199254740996,"created_at":6,"kind":"task.done","payload":{"phase":"large"}}],"next_seq":9007199254740996,"has_more":false,"gap_ranges":[]}',
        asJson({events: [{seq: 10, created_at: 7, kind: 'task.progress', payload: {phase: 'tail-gap'}}],
          next_seq: 13, first_retained_seq: 10, last_seq: 13, has_more: false,
          gap_ranges: [{from_seq: 11, to_seq: 13}]}),
        '{"events":[{"seq":9007199254740996,"created_at":8,"kind":"task.progress","payload":{"phase":"large-gap-order"}}],"next_seq":9007199254740996,"first_retained_seq":9007199254740994,"last_seq":9007199254740996,"has_more":false,"gap_ranges":[{"from_seq":9007199254740995,"to_seq":9007199254740995}]}',
        asJson({events: [], next_seq: 0, has_more: false}),
      ];
      const requests = [];
      apiFetch = async path => {
        requests.push(path);
        const body = pages.shift();
        return {json: async () => JSON.parse(body), text: async () => body};
      };
      await viewTrajectory('task-1');
      const eventTwoAt = list.innerHTML.indexOf('#2 ·');
      const internalGapAt = list.innerHTML.indexOf('#3–#5');
      const eventSixAt = list.innerHTML.indexOf('#6 ·');
      assert.ok(eventTwoAt >= 0 && internalGapAt > eventTwoAt && eventSixAt > internalGapAt,
        'events and internal retention gaps should render in sequence order');
      const next = list.children.find(node => node.className === 'trajectory-load-more');
      assert.ok(next, 'first page should expose cursor navigation');
      await next.onclick();
      assert.match(list.innerHTML, /task\.progress/);
      assert.match(list.innerHTML, /task\.done/);
      assert.match(requests[1], /after_seq=6/);
      assert.equal(list.children.some(node => node.className === 'trajectory-load-more'), false);
      await viewTrajectory('legacy-task');
      assert.ok(list.children.some(node => node.textContent.includes('cannot verify history completeness')));
      assert.doesNotMatch(list.innerHTML, /<img src=x/);
      assert.match(list.innerHTML, /&lt;img src=x onerror=1&gt;/);
      const escapedNext = list.children.find(node => node.className === 'trajectory-load-more');
      assert.ok(escapedNext);
      await escapedNext.onclick();
      assert.equal(list.children.filter(node => String(node.className || '').split(/\s+/).includes('trajectory-gap')).length, 1);
      await viewTrajectory('large-task', '9007199254740994');
      const largeNext = list.children.find(node => node.className === 'trajectory-load-more');
      assert.ok(largeNext, '64-bit sequence should retain a usable cursor');
      await largeNext.onclick();
      assert.match(requests[5], /after_seq=9007199254740995/);
      await viewTrajectory('gap-only-task');
      const gapOnly = list.querySelector('.trajectory-gap');
      assert.ok(gapOnly, 'canonical gap_ranges should be visible');
      assert.ok(list.innerHTML.indexOf('#10 ·') < list.innerHTML.indexOf('#11–#13'),
        'tail retention gaps should render after returned events');
      assert.match(gapOnly.textContent, /#11–#13/);
      assert.match(gapOnly.textContent, /first retained #10/);
      await viewTrajectory('high-sequence-task');
      const highGapAt = list.innerHTML.indexOf('#9007199254740995–#9007199254740995');
      const highEventAt = list.innerHTML.indexOf('#9007199254740996 ·');
      assert.ok(highGapAt >= 0 && highEventAt > highGapAt,
        '64-bit event and gap sequences should sort and render without rounding');
      await viewTrajectory('unknown-gap-task');
      const unknownGap = list.querySelector('.trajectory-gap');
      assert.ok(unknownGap, 'missing gap metadata should be disclosed');
      assert.match(unknownGap.textContent, /cannot verify history completeness/);
    """
    runnable_source = trajectory_source + "\n(async () => {\n" + scenario + "\n})().catch(error => { console.error(error); process.exitCode = 1; });\n"
    script = (
        "const vm = require('node:vm');\n"
        f"vm.runInNewContext({json.dumps(setup + runnable_source)}, {{require, process, console, URLSearchParams}});\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "dashboard_trajectory.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, str(script_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr or result.stdout


def test_dashboard_status_uses_only_adaptive_poller_for_periodic_refresh() -> None:
    assert "statusPoller.start();" in DASHBOARD_HTML
    assert "setInterval(()=>{if(isVisible)pollStatus();},1000);" not in DASHBOARD_HTML
    assert "probeHealth();pollStatus();pollEvents();pollTraces();" not in DASHBOARD_HTML
    assert "if(isVisible){probeHealth();pollStatus();pollEvents();pollTraces();}" not in DASHBOARD_HTML


def test_event_and_trace_pollers_share_visibility_aware_backoff() -> None:
    assert "const eventsPoller=createDashboardStatusPoller" in DASHBOARD_HTML
    assert "const tracesPoller=createDashboardStatusPoller" in DASHBOARD_HTML
    assert "traceDetailPoller=createDashboardStatusPoller" in DASHBOARD_HTML
    assert "eventsPoller.setVisible(isVisible)" in DASHBOARD_HTML
    assert "tracesPoller.setVisible(isVisible)" in DASHBOARD_HTML
    assert "traceDetailPoller?.setVisible(isVisible)" in DASHBOARD_HTML
    assert "setInterval(poll,1000)" not in DASHBOARD_HTML
    assert "setInterval(()=>{if(isVisible)pollEvents();},1000);" not in DASHBOARD_HTML
    assert "setInterval(()=>{if(isVisible)pollTraces();},2000);" not in DASHBOARD_HTML
    assert "setInterval(()=>{if(isVisible)probeHealth();},5000);" not in DASHBOARD_HTML
    assert "probeHealth();pollEvents();pollTraces();" not in DASHBOARD_HTML


def test_dashboard_status_fingerprint_ignores_cache_metadata() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        assert.equal(shouldRefreshDashboardStatus({success: true, status_age_ms: 0, snapshot_cached: false}), true);
        assert.equal(shouldRefreshDashboardStatus({success: true, status_age_ms: 1200, snapshot_cached: true}), false);
        """
    )


def test_trace_reveal_drains_event_pages_and_reconstructs_content_pages() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard trace paging")
    start = DASHBOARD_HTML.index("function appendBoundedTraceEvents(")
    end = DASHBOARD_HTML.index("function setTraceDetailsOpen(", start)
    source = DASHBOARD_HTML[start:end]
    setup = r"""
    const traceEventBufferLimit = 200;
    let activeTraceId = 'trace-id', traceEvents = [], activeTraceData = {}, traceEventTotal = 5;
    function renderTraceDetail(data) { activeTraceData = data; }
    function openModal() {}
    const fields = {
      request: '', effective_payload: '{}', output: 'full output text', response: '{"ok":true}',
      'event:1': '{"prompt":"complete first"}', 'event:2': '{"prompt":"complete second"}'
    };
    async function apiFetch(path) {
      const url = new URL(path, 'http://localhost');
      const since = Number(url.searchParams.get('since_seq') || 0);
      const before = Number(url.searchParams.get('before_seq') || 0);
      const field = url.searchParams.get('content_field');
      if (field) {
        const value = fields[field] || '';
        const offset = Number(url.searchParams.get('content_offset') || 0), size = 4;
        const text = value.slice(offset, offset + size), next = offset + text.length;
        return {json: async () => ({success: true, content_page: {field, encoding: field === 'output' ? 'text' : 'json', offset, next_offset: next, total_chars: value.length, has_more: next < value.length, storage_truncated: false, text}})};
      }
      if (before) return {json: async () => ({success: true, session: {}, events: [{seq: 2}, {seq: 3}], events_has_more: true, terminal: true})};
      const events = since === 0
        ? [{seq: 1, payload: {truncated: true, preview: 'first'}}]
        : since === 1
          ? [{seq: 2, payload: {truncated: true, preview: 'second'}}]
          : [{seq: 4}, {seq: 5}];
      return {json: async () => ({success: true, session: {output: {truncated: true, preview: 'short'}}, events, next_seq: events[events.length - 1].seq, events_has_more: since === 0, terminal: true})};
    }
    """;
    script_source = setup + source + r"""
    (async () => {
      const assert = require('node:assert/strict');
      const result = await fetchPrimaryTraceContent('trace-id', {session: {}, payload_truncated: false});
      assert.equal(result.session.output, fields.output);
      assert.deepEqual(result.session.request, {});
      assert.deepEqual(result.session.response, {ok: true});
      assert.equal(result.full_payload_requested, true);
      assert.equal(result.payload_truncated, false);
      const bounded = [];
      assert.equal(appendBoundedTraceEvents(bounded, Array.from({length: 250}, (_, index) => ({seq: index + 1}))), 250);
      assert.equal(bounded.length, 200);
      assert.equal(bounded[0].seq, 51);
      const budget = {used: 0, limit: 12};
      await assert.rejects(fetchTraceContentPages('trace-id', 'output', budget), /Dashboard reveal limit exceeded/);
      assert.equal(budget.used, 8);
      activeTraceData = result;
      traceEvents = [{seq: 4, payload: {index: 4}}, {seq: 5, payload: {index: 5}}];
      traceEvents = [{seq: 3}];
      await loadTraceEventPage('older');
      assert.deepEqual(traceEvents.map(event => event.seq), [2, 3]);
      assert.equal(activeTraceData.has_older_events, true);
      assert.equal(activeTraceData.has_newer_events, true);
      await loadTraceEventPage('newer');
      assert.deepEqual(traceEvents.map(event => event.seq), [4, 5]);
      assert.equal(activeTraceData.has_older_events, true);
      assert.equal(activeTraceData.has_newer_events, false);
    })().catch(error => { console.error(error); process.exitCode = 1; });
    """;
    script = "const vm = require('node:vm');\n" + f"vm.runInNewContext({json.dumps(script_source)}, {{require, process, console, URL}});\n"
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "trace_paging.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, str(script_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr or result.stdout


def test_trace_reveal_keeps_event_history_window_bounded() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard trace paging")
    start = DASHBOARD_HTML.index("function appendBoundedTraceEvents(")
    end = DASHBOARD_HTML.index("function setTraceDetailsOpen(", start)
    source = DASHBOARD_HTML[start:end]
    setup = r"""
    const traceEventBufferLimit = 200;
    async function apiFetch(path) {
      const url = new URL(path, 'http://localhost');
      const field = url.searchParams.get('content_field');
      if (field) return {json: async () => ({success: true, content_page: {field, encoding: 'json', offset: 0, next_offset: 0, total_chars: 0, has_more: false, storage_truncated: false, text: ''}})};
      const since = Number(url.searchParams.get('since_seq') || 0), first = since + 1, last = Math.min(first + 99, 205);
      const events = Array.from({length: Math.max(0, last - first + 1)}, (_, index) => ({seq: first + index}));
      return {json: async () => ({success: true, session: {}, events, next_seq: last, events_has_more: last < 205, terminal: true})};
    }
    """;
    script_source = setup + source + r"""
    (async () => {
      const assert = require('node:assert/strict');
      const result = [];
      appendBoundedTraceEvents(result, Array.from({length: 205}, (_, index) => ({seq: index + 1})));
      assert.equal(result.length, 200);
      assert.equal(result[0].seq, 6);
      assert.equal(result[result.length - 1].seq, 205);
    })().catch(error => { console.error(error); process.exitCode = 1; });
    """;
    script = "const vm = require('node:vm');\n" + f"vm.runInNewContext({json.dumps(script_source)}, {{require, process, console, URL}});\n"
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "trace_window.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, str(script_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr or result.stdout


def test_hidden_dashboard_stops_poll_timer_and_resume_starts_one_poll() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        let nextId = 0, timers = new Map(), calls = 0;
        const poller = createDashboardStatusPoller(async () => { calls++; }, {
          isVisible: () => visible, random: () => 0.5,
          setTimer: (fn, delay) => { const id = ++nextId; timers.set(id, {fn, delay}); return id; },
          clearTimer: id => timers.delete(id), baseDelay: 100, maxDelay: 400,
        });
        let visible = true;
        const fire = async () => { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.fn(); await new Promise(r => setImmediate(r)); };
        poller.start(); assert.equal(timers.size, 1); await fire(); assert.equal(calls, 1);
        visible = false; poller.setVisible(false); assert.equal(timers.size, 0);
        visible = true; poller.setVisible(true); assert.equal(timers.size, 1);
        await fire(); assert.equal(calls, 2);
        poller.stop(); assert.equal(timers.size, 0);
        """
    )


def test_poll_failures_use_jittered_exponential_backoff_with_a_hard_cap() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        let nextId = 0, timers = new Map();
        const poller = createDashboardStatusPoller(async () => { throw Error('offline'); }, {
          isVisible: () => true, random: () => 0,
          setTimer: (fn, delay) => { const id = ++nextId; timers.set(id, {fn, delay}); return id; },
          clearTimer: id => timers.delete(id), baseDelay: 100, maxDelay: 400,
        });
        const fire = async () => { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.fn(); await new Promise(r => setImmediate(r)); };
        poller.start(); await fire(); assert.equal([...timers.values()][0].delay, 80);
        await fire(); assert.equal([...timers.values()][0].delay, 160);
        await fire(); assert.equal([...timers.values()][0].delay, 320);
        await fire(); assert.equal([...timers.values()][0].delay, 320);
        for (let i = 0; i < 12; i++) await fire();
        assert.ok([...timers.values()][0].delay <= 400);
        poller.stop();
        """
    )


def test_unchanged_status_slows_polling_and_changed_status_resets_interval() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        let nextId = 0, timers = new Map();
        const outcomes = [{changed: true}, {changed: false}, {changed: false}, {changed: true}];
        const poller = createDashboardStatusPoller(async () => outcomes.shift(), {
          isVisible: () => true, random: () => 0.5,
          setTimer: (fn, delay) => { const id = ++nextId; timers.set(id, {fn, delay}); return id; },
          clearTimer: id => timers.delete(id), baseDelay: 100, maxDelay: 400,
        });
        const fire = async () => { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.fn(); await new Promise(r => setImmediate(r)); };
        poller.start(); await fire(); assert.equal([...timers.values()][0].delay, 100);
        await fire(); assert.equal([...timers.values()][0].delay, 200);
        await fire(); assert.equal([...timers.values()][0].delay, 400);
        await fire(); assert.equal([...timers.values()][0].delay, 100);
        poller.stop();
        """
    )


def test_repeated_status_payload_does_not_trigger_redundant_render_work() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        const first = {success: true, status: {active: 2, names: ['a', 'b']}};
        const fetches = [];
        apiFetch = async function(path) {
          fetches.push(path);
          return path.startsWith('/api/live/status')
            ? {ok: true, status: 200, json: async () => first}
            : {ok: true, json: async () => ({cpu_count: 1, ram: {}, gpu: {}})};
        }
        await pollStatus(() => true);
        await pollStatus(() => true);
        assert.equal(rendered, 1);
        assert.deepEqual(fetches, ['/api/live/status?light=1&scope=1h', '/api/hardware/system', '/api/live/status?light=1&scope=1h']);
        """,
        include_status=True,
    )


def test_warming_status_does_not_render_partial_dashboard_snapshot() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        apiFetch = async () => ({ok: true, status: 200, json: async () => ({success: false, degraded: true, snapshot_warming: true})});
        assert.equal(await pollStatus(() => true), false);
        assert.equal(rendered, 0);
        assert.equal(nodes.conn.textContent, 'warming');
        assert.equal(nodes.conn.className, 'pill warn-t');
        assert.equal(hasLiveStatus, false);
        """,
        include_status=True,
    )


def test_stale_status_keeps_degraded_connection_badge() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        const stale = {success: false, degraded: true, snapshot_cached: true, snapshot_stale: true};
        apiFetch = async path => path.startsWith('/api/live/status')
          ? {ok: true, status: 200, json: async () => stale}
          : {ok: true, json: async () => ({cpu_count: 1, ram: {}, gpu: {}})};
        await pollStatus(() => true);
        assert.equal(rendered, 1);
        assert.equal(nodes.conn.textContent, 'stale');
        assert.equal(nodes.conn.className, 'pill warn-t');
        """,
        include_status=True,
    )


def test_hidden_status_response_cannot_commit_after_visibility_changes() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        let resolveStatus;
        apiFetch = async function() {
          return new Promise(resolve => { resolveStatus = () => resolve({ok: true, status: 200, json: async () => ({success: true})}); });
        }
        const pending = pollStatus(() => true);
        document.visibilityState = 'hidden';
        statusPollAbortController.abort();
        resolveStatus();
        assert.equal(await pending, false);
        assert.equal(rendered, 0);
        assert.equal(statusPollInFlight, false);
        """,
        include_status=True,
    )


def test_failed_hardware_poll_retries_for_unchanged_status_until_success() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        const status = {success: true, status: {active: 2}};
        let hardwareAttempts = 0;
        apiFetch = async function(path) {
          if (path.startsWith('/api/live/status')) return {ok: true, status: 200, json: async () => status};
          hardwareAttempts++;
          if (hardwareAttempts === 1) throw Error('temporary hardware failure');
          return {
            ok: true,
            json: async () => ({cpu_utilization_pct: 12, cpu_count: 4, ram: {used_pct: 50, used_gb: 8, total_gb: 16}}),
          };
        };
        await pollStatus(() => true);
        assert.equal(rendered, 1);
        assert.equal(hardwareAttempts, 1);
        await pollStatus(() => true);
        assert.equal(hardwareAttempts, 2);
        assert.match(nodes.sysUtil.innerHTML, /CPU 12%/);
        assert.ok(nodes.sysSub.textContent.includes('RAM 8 / 16 GB'));
        await pollStatus(() => true);
        assert.equal(hardwareAttempts, 2);
        assert.equal(rendered, 1);
        """,
        include_status=True,
    )


def test_hidden_inflight_response_is_stale_and_never_overlaps() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        let nextId = 0, timers = new Map(), calls = 0, resolvePoll;
        let visible = true;
        const poller = createDashboardStatusPoller(() => { calls++; return new Promise(resolve => { resolvePoll = resolve; }); }, {
          isVisible: () => visible, random: () => 0.5,
          setTimer: (fn, delay) => { const id = ++nextId; timers.set(id, {fn, delay}); return id; },
          clearTimer: id => timers.delete(id), baseDelay: 100, maxDelay: 400,
        });
        const fire = () => { const [id, timer] = timers.entries().next().value; timers.delete(id); timer.fn(); };
        poller.start(); fire(); assert.equal(calls, 1);
        visible = false; poller.setVisible(false); visible = true; poller.setVisible(true); fire();
        assert.equal(calls, 1);
        resolvePoll(); await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));
        fire(); assert.equal(calls, 2);
        poller.stop();
        """
    )


def _run_dashboard_health_javascript(scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise dashboard health rendering")
    marker = "function dashboardHealthBadge("
    if marker not in DASHBOARD_HTML:
        pytest.fail("dashboard health badge helper is not implemented")
    start = DASHBOARD_HTML.index(marker)
    end = DASHBOARD_HTML.index("\nfunction dashboardHealth(", start)
    health_source = DASHBOARD_HTML[start:end]
    runnable_source = (
        health_source
        + "\n(async () => {\n"
        + scenario
        + "\n})().catch(error => { console.error(error); process.exitCode = 1; });\n"
    )
    script = (
        "const vm = require('node:vm');\n"
        f"vm.runInNewContext({json.dumps(runnable_source)}, {{require, process, console}});\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        script_path = Path(directory) / "dashboard_health.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(script_path)], capture_output=True, text=True, timeout=5
        )
    assert result.returncode == 0, result.stderr or result.stdout


def test_dashboard_health_badge_surfaces_degraded_checks() -> None:
    _run_dashboard_health_javascript(
        """
        const assert = require('node:assert/strict');
        assert.deepEqual(
          dashboardHealthBadge({hub_online: true, ollama_online: true, success: true, dependency_status: {runtime: {degraded: false}}}),
          {className: 'ok', degradedCount: 0, degradedLabel: ''},
        );
        assert.deepEqual(
          dashboardHealthBadge({hub_online: true, ollama_online: true, success: false, dependency_status: {
            runtime: {degraded: true}, cache: {degraded: true}, scheduler: {degraded: false},
          }}),
          {className: 'warn-t', degradedCount: 2, degradedLabel: ' / 2 degraded checks'},
        );
        assert.deepEqual(
          dashboardHealthBadge({hub_online: true, ollama_online: true, success: false}),
          {className: 'warn-t', degradedCount: 0, degradedLabel: ' / status degraded'},
        );
        assert.deepEqual(
          dashboardHealthBadge({hub_online: false, ollama_online: false, success: false, dependency_status: {runtime: {degraded: true}}}),
          {className: 'bad-t', degradedCount: 1, degradedLabel: ' / 1 degraded check'},
        );
        """
    )
