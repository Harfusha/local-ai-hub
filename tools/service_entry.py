from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["LOCAL_AI_CONFIG"] = str(ROOT / "config.toml")
from local_ai_hub.supervisor import main
raise SystemExit(main())
