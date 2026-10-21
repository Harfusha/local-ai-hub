import json
import re
import shutil
import subprocess

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.process_utils import hidden_run_kwargs


def _project_phase_projection(project, complete=False):
    node = shutil.which("node")
    assert node, "Node is required for the dashboard runtime regression"
    phases = re.search(r"const PHASES\s*=\s*(\[[\s\S]*?\]);", DASHBOARD_HTML)
    assert phases
    start = DASHBOARD_HTML.index("const phaseObj=PHASES.find")
    end = DASHBOARD_HTML.index("\n    const variants=", start)
    script = "const PHASES=" + phases.group(1) + ";"
    script += "const x=" + json.dumps(project) + ";const isComplete=" + json.dumps(complete) + ";const n=String;"
    script += DASHBOARD_HTML[start:end]
    script += "console.log(JSON.stringify({title:phaseTitle,ids:PHASES.map(p=>p.id)}));"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10, check=True, **hidden_run_kwargs())
    return json.loads(result.stdout)


def test_dashboard_phase_order_matches_canonical_pipeline():
    actual = _project_phase_projection({"phase": "inventory", "phase_index": 1})
    assert tuple(actual["ids"]) == ProjectPreprocessor.PHASES


def test_completed_paused_project_phase_label_uses_canonical_phase_count():
    count = len(ProjectPreprocessor.PHASES)
    actual = _project_phase_projection({"phase": "complete", "phase_index": count, "paused": True})
    assert actual["title"] == f"{count}/{count} Ready"


def test_diagnostics_phase_has_its_own_step_and_correct_denominator():
    index = ProjectPreprocessor.PHASES.index("diagnostics") + 1
    actual = _project_phase_projection({"phase": "diagnostics", "phase_index": index})
    assert actual["title"].startswith(f"{index}/{len(ProjectPreprocessor.PHASES)} ")
    assert "Diagnostics" in actual["title"]
