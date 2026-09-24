from types import SimpleNamespace

from local_ai_hub.services import LocalAIServices


def _service_for_batch(model_by_task, active_model, delegate):
    service = object.__new__(LocalAIServices)
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": active_model})
    service.router = SimpleNamespace(
        classify=lambda task, *_args: {"model": model_by_task[task]}
    )
    service.delegate = delegate
    return service


def test_batch_delegate_keeps_input_order_after_model_grouping():
    calls = []
    model_by_task = {"first": "slow", "middle": "fast", "last": "slow"}

    def delegate(item, _tenant):
        calls.append(item["task"])
        return {"success": True, "task": item["task"]}

    service = _service_for_batch(model_by_task, "fast", delegate)
    result = service.batch_delegate(
        {"tasks": [{"task": "first"}, {"task": "middle"}, {"task": "last"}]},
        "tenant",
    )

    assert calls == ["middle", "first", "last"]
    assert result["success"] is True
    assert [item["task"] for item in result["results"]] == ["first", "middle", "last"]


def test_batch_delegate_returns_per_item_failure_and_continues_after_exception():
    calls = []
    model_by_task = {
        "first": "resident",
        "raises": "resident",
        "middle": "other",
        "last": "resident",
    }

    def delegate(item, _tenant):
        task = item["task"]
        calls.append(task)
        if task == "raises":
            raise RuntimeError("private model detail")
        return {"success": True, "task": task}

    service = _service_for_batch(model_by_task, "resident", delegate)
    result = service.batch_delegate(
        {"tasks": [{"task": task} for task in model_by_task]},
        "tenant",
    )

    assert calls == ["first", "raises", "last", "middle"]
    assert result["success"] is False
    assert [item.get("task") for item in result["results"]] == [
        "first",
        None,
        "middle",
        "last",
    ]
    assert result["results"][1]["success"] is False
    assert result["results"][1]["error"] == "batch item failed (RuntimeError)"
    assert "private model detail" not in str(result)
