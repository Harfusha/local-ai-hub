from types import SimpleNamespace
import threading
import pytest

from local_ai_hub.services import LocalAIServices
from local_ai_hub import mcp_server


def _service_for_batch(model_by_task, active_model, delegate):
    service = object.__new__(LocalAIServices)
    service.scheduler = SimpleNamespace(status=lambda: {"active_model": active_model})
    service.router = SimpleNamespace(
        classify=lambda task, *_args: {"model": model_by_task[task]}
    )
    service.delegate = delegate
    return service


def test_cancelled_batch_preserves_ids_for_unsent_items():
    cancel = threading.Event()
    calls = []

    def delegate(item, *, cancel_event=None):
        calls.append(item['task'])
        cancel.set()
        return {'success': True}

    service = _service_for_batch({'first': 'same', 'second': 'same'}, 'same', delegate)
    result = service.batch_delegate({'tasks': [
        {'id': 'item-a', 'task': 'first'}, {'id': 'item-b', 'task': 'second'},
    ]}, cancel_event=cancel)
    assert calls == ['first']
    assert result['success'] is False and result['cancelled'] is True
    assert [item['id'] for item in result['results']] == ['item-a', 'item-b']
    assert result['results'][1]['request_not_sent'] is True


def test_batch_delegate_keeps_input_order_after_model_grouping():
    calls = []
    model_by_task = {"first": "slow", "middle": "fast", "last": "slow"}

    def delegate(item):
        calls.append(item["task"])
        return {"success": True, "task": item["task"]}

    service = _service_for_batch(model_by_task, "fast", delegate)
    result = service.batch_delegate(
        {"tasks": [{"task": "first"}, {"task": "middle"}, {"task": "last"}]},
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

    def delegate(item):
        task = item["task"]
        calls.append(task)
        if task == "raises":
            raise RuntimeError("private model detail")
        return {"success": True, "task": task}

    service = _service_for_batch(model_by_task, "resident", delegate)
    result = service.batch_delegate(
        {"tasks": [{"task": task} for task in model_by_task]},
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


def test_batch_preserves_explicit_ids_and_failures_in_original_order():
    calls = []
    def delegate(item):
        calls.append(item['task'])
        if item['task'] == 'second':
            raise RuntimeError('private')
        return {'success': True, 'id': 'untrusted model id', 'text': item['task']}
    service = _service_for_batch({'first':'slow', 'second':'fast', 'third':'slow'}, 'fast', delegate)
    result = service.batch_delegate({'tasks': [
        {'id':'one', 'task':'first'}, {'id':'two', 'task':'second'}, {'id':'three', 'task':'third'},
    ]})
    assert calls == ['second', 'first', 'third']
    assert [item['id'] for item in result['results']] == ['one', 'two', 'three']
    assert [item['success'] for item in result['results']] == [True, False, True]


def test_batch_rejects_invalid_or_duplicate_ids_before_dispatch():
    calls = []
    service = _service_for_batch({'first':'fast', 'second':'fast'}, 'fast', lambda item: calls.append(item))
    for ids in [('same', 'same'), ('', 'other'), (False, 'other'), (' spaced ', 'other')]:
        result = service.batch_delegate({'tasks':[{'id':ids[0], 'task':'first'}, {'id':ids[1], 'task':'second'}]})
        assert result['success'] is False
        assert result['request_not_sent'] is True
        assert calls == []


def test_batch_reports_malformed_worker_result_per_item():
    service = _service_for_batch({'first':'fast'}, 'fast', lambda item: None)
    result = service.batch_delegate({'tasks':[{'id':'one', 'task':'first'}]})
    assert result['success'] is False
    assert result['results'] == [{'id':'one', 'success':False, 'error':'batch item returned an invalid result'}]


@pytest.mark.parametrize('value', ['false', 1, None])
def test_batch_rejects_nonboolean_item_success(value):
    service = _service_for_batch({'first':'fast'}, 'fast', lambda item: {'success':value})
    result = service.batch_delegate({'tasks':[{'id':'one', 'task':'first'}]})
    assert result['success'] is False
    assert result['results'][0]['success'] is False
    assert result['results'][0]['id'] == 'one'


def test_batch_ids_survive_mcp_response(monkeypatch):
    service = _service_for_batch({'first':'fast', 'second':'fast'}, 'fast', lambda item: {'success': True, 'text':item['task']})
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kwargs: service.batch_delegate(payload))
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server.FEATURES, 'tasks', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'has_any_model', lambda: True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    result = mcp_server.local_ai_task(action='batch', tasks=[{'id':'a','task':'first'}, {'id':'b','task':'second'}], max_response_tokens=1200)
    assert result['success'] is True, result
    assert [item['id'] for item in result['results']] == ['a', 'b']


def test_invalid_batch_ids_remain_preflight_failure_through_mcp(monkeypatch):
    calls = []
    service = _service_for_batch({'first':'fast', 'second':'fast'}, 'fast', lambda item: calls.append(item))
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kwargs: service.batch_delegate(payload))
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server.FEATURES, 'tasks', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'has_any_model', lambda: True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    result = mcp_server.local_ai_task(action='batch', tasks=[{'id':'a','task':'first'}, {'id':'a','task':'second'}], max_response_tokens=1200)
    assert result['success'] is False
    assert result['request_not_sent'] is True
    assert calls == []
