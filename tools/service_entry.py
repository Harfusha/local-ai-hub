from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.chdir(str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
config_arg = None
if "--config" in sys.argv:
    idx = sys.argv.index("--config")
    if idx + 1 < len(sys.argv):
        config_arg = Path(sys.argv[idx + 1]).resolve()
if config_arg and config_arg.is_file():
    os.environ["LOCAL_AI_CONFIG"] = str(config_arg)
elif "LOCAL_AI_CONFIG" not in os.environ:
    root_config = ROOT / "config.toml"
    if root_config.is_file():
        os.environ["LOCAL_AI_CONFIG"] = str(root_config)
from local_ai_hub.supervisor import main
raise SystemExit(main())
