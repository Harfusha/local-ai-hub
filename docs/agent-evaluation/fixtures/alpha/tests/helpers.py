def normalize_path(path: str) -> str:
    """Test helper, intentionally not imported by production modules."""
    return path.strip().replace("\\", "/")
