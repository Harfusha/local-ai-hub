import pytest
from pathlib import Path
from unittest.mock import MagicMock
from local_ai_hub.repository_test_impact import RepositoryTestImpactService


def test_validate_root_hardening():
    engine = MagicMock()
    runner = MagicMock()
    service = RepositoryTestImpactService(engine, runner)

    # Boolean or non-string/Path should raise ValueError or TypeError
    with pytest.raises((ValueError, TypeError)):
        service._validate_root(True)
    with pytest.raises((ValueError, TypeError)):
        service._validate_root(False)
    with pytest.raises((ValueError, TypeError)):
        service._validate_root(12345)
    with pytest.raises(ValueError):
        service._validate_root("")
    with pytest.raises(ValueError):
        service._validate_root("   ")
    with pytest.raises(ValueError):
        service._validate_root("foo\x00bar")

    assert service._validate_root("valid/path") == "valid/path"
    assert service._validate_root(" valid/path ") == " valid/path "
    assert service._validate_root(Path("valid/path")) == str(Path("valid/path"))


def test_affected_tests_hardening():
    engine = MagicMock()
    runner = MagicMock(side_effect=lambda op, root, params, fn: fn())
    service = RepositoryTestImpactService(engine, runner)

    # Boolean changed_paths should raise TypeError
    with pytest.raises(TypeError):
        service.affected_tests("valid/root", changed_paths=True)

    for invalid_path in (True, None, 123):
        with pytest.raises(TypeError):
            service.affected_tests("valid/root", changed_paths=[invalid_path])
    with pytest.raises(ValueError, match="NUL"):
        service.affected_tests("valid/root", changed_paths=["valid\x00/test.py"])
    with pytest.raises(TypeError):
        service.affected_tests("valid/root", changed_paths=["valid/test.py"], base=True)
    with pytest.raises(ValueError, match="NUL"):
        service.affected_tests("valid/root", changed_paths=["valid/test.py"], base="feat\x00branch")
    with pytest.raises(ValueError, match="nonempty"):
        service.affected_tests("valid/root", changed_paths=["valid/test.py"], base="   ")
    with pytest.raises(TypeError):
        service.affected_tests("valid/root", changed_paths=["valid/test.py"], params=True)

    service.affected_tests("valid/root", changed_paths=["valid/test.py"], base="feature", params=None)
    engine.affected_tests.assert_called_once_with(
        "valid/root",
        ["valid/test.py"],
        "feature",
    )
