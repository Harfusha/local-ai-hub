import json
import shutil
import subprocess

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.process_utils import hidden_run_kwargs


def test_progress_counts_distinguish_unknown_empty_and_remaining():
    node = shutil.which("node")
    assert node
    start = DASHBOARD_HTML.index("function preprocessingCounts(")
    end = DASHBOARD_HTML.index("\nfunction ", start + 1)
    script = DASHBOARD_HTML[start:end] + "\nconsole.log(JSON.stringify([preprocessingCounts({files:10,hashed_files:4}),preprocessingCounts({files:0,hashed_files:0}),preprocessingCounts({}),preprocessingCounts({phase:'inventory',status:'running',files:10,hashed_files:4}),preprocessingCounts({phase:'inventory',status:'paused',files:10,hashed_files:4})]));"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=10, check=True, **hidden_run_kwargs())
    partial, empty, unknown, discovering, paused_inventory = json.loads(result.stdout)
    assert partial["hash"] == {"done": 4, "total": 10, "remaining": 6}
    assert empty["hash"] == {"done": 0, "total": 0, "remaining": 0}
    assert unknown["hash"] == {"done": None, "total": None, "remaining": None}
    assert discovering["hash"]["total"] is None
    assert paused_inventory["hash"]["total"] is None


def test_progress_and_status_do_not_invent_completion():
    node = shutil.which("node")
    assert node
    start = DASHBOARD_HTML.index("function preprocessingProgress(")
    end = DASHBOARD_HTML.index("\nfunction ", start + 1)
    state_start = DASHBOARD_HTML.index("function projectState(")
    state_end = DASHBOARD_HTML.index("\nfunction groupedProjects", state_start)
    script = DASHBOARD_HTML[start:end] + DASHBOARD_HTML[state_start:state_end]
    script += "\nconsole.log(JSON.stringify([preprocessingProgress({}),preprocessingProgress({overall_progress_pct:25.7}),projectState({overall_progress_pct:100}),projectState({status:'running',overall_progress_pct:100})]));"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=10, check=True, **hidden_run_kwargs())
    assert json.loads(result.stdout) == [None, 25.7, "queued", "running"]


def test_project_detail_has_a_keyboard_accessible_control():
    render_start = DASHBOARD_HTML.index("function renderProjects(items)")
    render_end = DASHBOARD_HTML.index("async function projectAction", render_start)
    assert 'data-project-details' in DASHBOARD_HTML[render_start:render_end]
    assert "closest?.('[data-project-details]')" in DASHBOARD_HTML
