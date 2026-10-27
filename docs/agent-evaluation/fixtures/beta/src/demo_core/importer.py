def import_export(payload: dict[str, object]) -> dict[str, object]:
    """Intentional mismatch: importer expects camelCase timestamp."""
    return {"id": payload["id"], "created_at": payload["createdAt"]}
