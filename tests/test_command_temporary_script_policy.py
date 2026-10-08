import pytest

from local_ai_hub.commands import CommandBroker


@pytest.mark.parametrize("path", [
    "/tmp/arbitrary.py", "/home/project/pytest-payload/arbitrary.py",
    r"C:\Temp\arbitrary.py", r"C:\work\pytest-payload\arbitrary.py",
])
def test_temporary_path_does_not_authorize_unknown_python_script(path):
    broker = object.__new__(CommandBroker)
    broker.config = {"commands": {"allow_validation": True, "allow_mutating": False}}

    result = broker.classify(["python", path])

    assert result["class"] == "mutating"
    assert result["allowed"] is False
    assert result["cacheable"] is False
    assert result["replay_safe"] is False
