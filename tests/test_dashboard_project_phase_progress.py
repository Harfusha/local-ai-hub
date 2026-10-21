import json
import re
import shutil
import subprocess

from local_ai_hub.dashboard import DASHBOARD_HTML


def test_completed_paused_project_phase_label_uses_dashboard_phase_count():
    node = shutil.which("node")
    assert node, "Node is required for the dashboard runtime regression"
    phases = re.search(r"const PHASES\s*=\s*(\[[\s\S]*?\]);", DASHBOARD_HTML)
    assert phases
    start = DASHBOARD_HTML.index("const phaseObj=PHASES.find")
    end = DASHBOARD_HTML.index("\n    const variants=", start)
    projection = DASHBOARD_HTML[start:end]
    script = "const PHASES=" + phases.group(1) + ";" + '''
const x={phase:'complete',phase_index:13};
const isComplete=false;
const n=String;
''' + projection + '''
console.log(JSON.stringify({title:phaseTitle,count:PHASES.length}));
'''
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    actual = json.loads(result.stdout)
    assert actual["title"] == f'{actual["count"]}/{actual["count"]} Ready'
