from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.services import LocalAIServices


PLAYWRIGHT = Path(
    r"C:\Users\Adam\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright"
)
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class TemporaryArtifacts:
    def put(self, *_args: object, **_kwargs: object) -> str:
        return "temporary-live-vision-output"


def main() -> int:
    node_source = r'''import { createRequire } from 'node:module';
const require = createRequire(process.argv[1]);
const { chromium } = require(process.argv[2]);
const browser = await chromium.launch({headless:true, executablePath:process.argv[3]});
const page = await browser.newPage({viewport:{width:800,height:450}});
await page.setContent('<!doctype html><title>Settings</title><main><h1>Settings</h1><button>Continue</button></main>');
await page.screenshot({path:process.argv[4]});
await browser.close();'''
    with tempfile.TemporaryDirectory(prefix="t17-live-vision-") as temp:
        temp_path = Path(temp)
        image = temp_path / "ui.png"
        renderer = temp_path / "render.mjs"
        renderer.write_text(node_source, encoding="utf-8")
        subprocess.run(
            ["node", str(renderer), str(PLAYWRIGHT), str(EDGE), str(image)],
            check=True,
            timeout=30,
        )
        config = {
            "server": {
                "state_dir": str(temp_path / "state"),
                "ollama_url": "http://127.0.0.1:11434",
                "request_timeout_seconds": 180,
            },
            "ollama": {"enabled": True, "request_attempts": 1, "retry_delay_seconds": 0},
            "models": {"vision": "qwen2.5vl:3b"},
            "features": {"vision": True},
        }
        service = object.__new__(LocalAIServices)
        service.config = config
        service.runtime = OllamaRuntime(config, managed_name="t17-live-vision")
        service.model_policy = ModelExecutionPolicy(config)
        service.artifacts = TemporaryArtifacts()
        service.repo_tools = None
        result = service.vision(
            {
                "image": str(image),
                "model": "qwen2.5vl:3b",
                "max_tokens": 512,
                "prompt": (
                    "The supplied DOM is authoritative. The button's exact text is Continue. "
                    "This matches the requested text. There is no issue. Return summary "
                    "'The button text is Continue.' and an empty findings array. Do not invent "
                    "a concern or bbox."
                ),
                "dom": {
                    "redaction": "none",
                    "elements": [
                        {"element_id": "button-1", "tag": "button", "text": "Continue"}
                    ],
                },
            },
            "t17-live-vision",
        )
        review = result.get("review") or {}
        findings = review.get("findings", [])
        passed = bool(result.get("success")) and not findings
        print(
            json.dumps(
                {
                    "acceptance": "PASS" if passed else "FAIL",
                    "success": result.get("success"),
                    "model": result.get("model"),
                    "error_code": result.get("error_code"),
                    "error": result.get("error"),
                    "summary": review.get("summary"),
                    "findings": findings,
                },
                ensure_ascii=False,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
