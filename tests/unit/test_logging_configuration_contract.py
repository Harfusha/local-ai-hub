"""Malformed configuration must not disturb an operational logger."""

import logging
import sys

import pytest

from local_ai_hub import logging_setup


@pytest.mark.parametrize("field", ["queue_size", "max_bytes", "backup_count"])
@pytest.mark.parametrize("value", [True, False, "5000", None, 1.5, 0, -1, float("inf"), float("nan"), sys.maxsize + 1])
def test_invalid_logging_size_has_no_side_effects(tmp_path, field, value):
    logger = logging.getLogger("local_ai_hub")
    original = (logger.level, logger.propagate, tuple(logger.handlers), logging_setup._listener, logging_setup._log_path)
    destination = tmp_path / "uncreated"
    with pytest.raises(ValueError):
        logging_setup.configure_logging(destination, {"logging": {field: value}})
    assert not destination.exists()
    assert (logger.level, logger.propagate, tuple(logger.handlers), logging_setup._listener, logging_setup._log_path) == original


@pytest.mark.parametrize("value", [None, 10, True, "", "getLogger", "__dict__", "unknown", "INFO\x00"])
def test_invalid_logging_level_rejects_before_storage(tmp_path, value):
    destination = tmp_path / "uncreated"
    with pytest.raises(ValueError):
        logging_setup.configure_logging(destination, {"logging": {"level": value}})
    assert not destination.exists()


@pytest.mark.parametrize("config", [None, [], {"logging": None}, {"logging": []}])
def test_invalid_logging_mapping_rejects(tmp_path, config):
    with pytest.raises(TypeError):
        logging_setup.configure_logging(tmp_path / "uncreated", config)
    assert not (tmp_path / "uncreated").exists()


def test_valid_logging_configuration_keeps_supported_sizes(tmp_path, monkeypatch):
    isolated_logger = logging.Logger("local-ai-hub-test")
    monkeypatch.setattr(logging_setup, "_listener", None)
    monkeypatch.setattr(logging_setup, "_log_path", None)
    monkeypatch.setattr(logging_setup, "_previous_propagate", None)
    with monkeypatch.context() as context:
        context.setattr(logging_setup.logging, "getLogger", lambda name=None: isolated_logger)
        try:
            configured = logging_setup.configure_logging(tmp_path, {"logging": {
                "level": "DEBUG", "queue_size": 200, "max_bytes": 300_000, "backup_count": 2,
            }})
            assert configured is isolated_logger
            assert configured.level == logging.DEBUG
            assert configured.handlers[0].queue.maxsize == 200
            handler = logging_setup._listener.handlers[0]
            assert handler.maxBytes == 300_000
            assert handler.backupCount == 2
            assert logging_setup._log_path == (tmp_path / "logs" / "hub.log").resolve()
        finally:
            logging_setup.shutdown_logging()
