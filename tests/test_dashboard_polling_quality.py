from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML


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


def test_dashboard_status_uses_only_adaptive_poller_for_periodic_refresh() -> None:
    assert "statusPoller.start();" in DASHBOARD_HTML
    assert "setInterval(()=>{if(isVisible)pollStatus();},1000);" not in DASHBOARD_HTML
    assert "probeHealth();pollStatus();pollEvents();pollTraces();" not in DASHBOARD_HTML
    assert "if(isVisible){probeHealth();pollStatus();pollEvents();pollTraces();}" not in DASHBOARD_HTML


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
    let activeTraceId = 'trace-id', traceEvents = [], traceRevealRedactedDetails = false, activeTraceData = {}, traceEventTotal = 5;
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
      const result = await fetchFullTracePayload('trace-id');
      assert.equal(result.session.output, fields.output);
      assert.deepEqual(result.session.request, {});
      assert.deepEqual(result.session.response, {ok: true});
      assert.deepEqual(result.events.map(event => event.payload.prompt), ['complete first', 'complete second']);
      assert.equal(result.next_seq, 2);
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
      const result = await fetchFullTracePayload('trace-id');
      assert.equal(result.events.length, 200);
      assert.equal(result.events[0].seq, 6);
      assert.equal(result.events[result.events.length - 1].seq, 205);
      assert.equal(result.has_older_events, true);
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
            ? {json: async () => first}
            : {ok: true, json: async () => ({cpu_count: 1, ram: {}, gpu: {}})};
        }
        await pollStatus(() => true);
        await pollStatus(() => true);
        assert.equal(rendered, 1);
        assert.deepEqual(fetches, ['/api/live/status?light=1&scope=1h', '/api/hardware/system', '/api/live/status?light=1&scope=1h']);
        """,
        include_status=True,
    )


def test_hidden_status_response_cannot_commit_after_visibility_changes() -> None:
    _run_polling_javascript(
        """
        const assert = require('node:assert/strict');
        let resolveStatus;
        apiFetch = async function() {
          return new Promise(resolve => { resolveStatus = () => resolve({json: async () => ({success: true})}); });
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
          if (path.startsWith('/api/live/status')) return {json: async () => status};
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
