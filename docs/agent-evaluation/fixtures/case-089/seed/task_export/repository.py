import json
from pathlib import Path


def load_tasks(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("task file must contain a list")
    return data
