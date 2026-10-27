def normalize_path(path: str) -> str:
    """Normalize separators and remove trailing separators."""
    return path.replace("\\", "/").rstrip("/")
