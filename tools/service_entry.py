from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.chdir(str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
root_config = ROOT / "config.toml"
if root_config.is_file():
    os.environ["LOCAL_AI_CONFIG"] = str(root_config)
from local_ai_hub.supervisor import main
raise SystemExit(main())
