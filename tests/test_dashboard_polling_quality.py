from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML

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
