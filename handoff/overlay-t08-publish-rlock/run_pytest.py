from pathlib import Path
import sys

here = Path(__file__).resolve().parent
overlay_src = here / "src"
root_src = Path(r"C:\Users\Adam\.local-ai-hub\src")
sys.path.insert(0, str(root_src))
sys.path.insert(0, str(overlay_src))
import local_ai_hub.agent_events as event_module
import local_ai_hub.swarm as swarm_module
expected_event = (overlay_src / "local_ai_hub" / "agent_events.py").resolve()
expected_swarm = (overlay_src / "local_ai_hub" / "swarm.py").resolve()
if Path(event_module.__file__).resolve() != expected_event:
    raise SystemExit(f"unexpected event module: {event_module.__file__}")
if Path(swarm_module.__file__).resolve() != expected_swarm:
    raise SystemExit(f"unexpected swarm module: {swarm_module.__file__}")
print(f"agent_events_overlay={event_module.__file__}")
print(f"swarm_overlay={swarm_module.__file__}")
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
