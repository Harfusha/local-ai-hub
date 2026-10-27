def export_task(task: dict[str, object]) -> dict[str, object]:
    return {"id": task["id"], "created_at": task["created_at"]}
