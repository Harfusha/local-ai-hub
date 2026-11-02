"""Prepare case 081 using the isolated case 076 Hub configuration."""
import argparse
import importlib.util
import json
import shutil
from pathlib import Path

fixture = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("case076_prepare", fixture.parent / "case-076" / "prepare.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

parser = argparse.ArgumentParser()
parser.add_argument("target", type=Path)
parser.add_argument("--port", required=True, type=int)
parser.add_argument("--provider-port", required=True, type=int)
parser.add_argument("--source", required=True, type=Path)
args = parser.parse_args()
if not 1024 <= args.provider_port <= 65535 or args.provider_port in {args.port, 11434, 11435}:
    raise ValueError("choose a separate, unprivileged, non-production provider port")
root = module.prepare(args.target, args.port, args.source)
with (root / "config.toml").open("a", encoding="utf-8") as file:
    file.write(f'''\n[ollama]\nenabled = true\n[llama_cpp]\nmode = "off"\n[openvino]\nenabled = false\n[models]\nfast_code = "qwen2.5-coder:3b"\nheavy_code = "qwen2.5-coder:3b"\nreasoning = "qwen2.5-coder:3b"\ngeneral = "qwen2.5-coder:3b"\n''')
    # Existing [server] is not reopened: insert its provider URL explicitly.
config = (root / "config.toml").read_text(encoding="utf-8")
config = config.replace('bind = "127.0.0.1"', f'bind = "127.0.0.1"\nollama_url = "http://127.0.0.1:{args.provider_port}"', 1)
(root / "config.toml").write_text(config, encoding="utf-8")
shutil.copyfile(fixture / "call_mcp.py", root / "call_mcp.py")
shutil.copyfile(fixture / "provider.py", root / "provider.py")
(root / "workspace" / "zadani.md").write_text((fixture / "zadani.md").read_text(encoding="utf-8"), encoding="utf-8")
(root / "workspace" / "zadani-preflight.md").write_text((fixture / "zadani-preflight.md").read_text(encoding="utf-8"), encoding="utf-8")
print(json.dumps({"root": str(root), "hub_port": args.port, "provider_port": args.provider_port}))
