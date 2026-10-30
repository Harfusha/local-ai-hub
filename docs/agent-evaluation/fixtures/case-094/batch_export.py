"""Intentionally faulty evaluation seed; copy to a disposable directory."""


class ExportCancelled(Exception):
    """The exporter reports cancellation before completing an item."""


def process_batch(items, exporter):
    results = []
    for item in items:
        try:
            value = exporter(item)
            if item.get("retry"):
                value = exporter(item)
            results.append({"id": item["id"], "status": "ok", "value": value})
        except Exception as exc:
            results.append({"id": item["id"], "status": "error", "error": str(exc)})
    return {"success": True, "items": results}
