from .paths import normalize_path


def load_project(path: str, catalog):
    normalized = normalize_path(path)
    return catalog.lookup(normalized)
