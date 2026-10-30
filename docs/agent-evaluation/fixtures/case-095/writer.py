"""Intentionally loses original bytes if the injected operation fails."""
from pathlib import Path

def replace_bytes(path, data, before_replace=lambda: None):
    Path(path).write_bytes(data)
    before_replace()
