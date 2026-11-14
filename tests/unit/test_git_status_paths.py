import pytest

from local_ai_hub.git_status_paths import parse_porcelain_status_paths


@pytest.mark.parametrize(
    "output,expected",
    [
        (b" M src/changed.py\0?? tests/new test.py\0", ["src/changed.py", "tests/new test.py"]),
        (b"R  new name.py\0old name.py\0", ["new name.py", "old name.py"]),
        (b"C  copy.py\0source.py\0", ["copy.py", "source.py"]),
        (b"", []),
    ],
)
def test_parse_porcelain_status_paths(output, expected):
    assert parse_porcelain_status_paths(output) == expected


@pytest.mark.parametrize(
    "output",
    [
        None,
        " M file.py\0",
        b" M file.py",
        b"??\0",
        b"R  new.py\0",
        b"C  copy.py\0",
    ],
)
def test_parse_porcelain_status_paths_rejects_malformed_records(output):
    assert parse_porcelain_status_paths(output) is None
