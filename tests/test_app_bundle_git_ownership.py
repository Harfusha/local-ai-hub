import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from local_ai_hub import __version__
from local_ai_hub.agent_identity import AgentScope, MemoryKind
from local_ai_hub.agent_memory import MemoryRecord, MemoryStatus
from local_ai_hub.app import BundleValidationError
from local_ai_hub.app_bundle import AppBundleMixin


class _BundleHarness(AppBundleMixin):
    def _bundle_limits(self):
        return 1_000_000, 1_000_000, 100


def _repository_memory(root):
    return MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id="project-id",
        key="fact",
        value="Git-owned project fact",
        status=MemoryStatus.CONFIRMED,
        provenance={"root": str(root), "repository_id": "project-id"},
    )


def _agent_state_bundle(record):
    records = [{"type": "memory", "data": record.to_dict()}]
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    payload = {
        "format": "local-ai-hub-agent-state-bundle",
        "version": __version__,
        "records": records,
        "records_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", json.dumps(payload, separators=(",", ":")))
    return output.getvalue()


def test_export_rejects_repository_memory_from_sqlite(tmp_path):
    record = _repository_memory(tmp_path)
    harness = _BundleHarness()
    harness.agent_memory = SimpleNamespace(get=lambda *_args, **_kwargs: record)

    with pytest.raises(BundleValidationError, match="Git-owned"):
        harness.export_bundle(
            agent_state_record_ids=[record.record_id],
            agent_state_contexts={record.record_id: {
                "scope": "repository", "root": str(tmp_path), "repository_id": "project-id",
            }},
        )


def test_import_rejects_repository_memory_bundle(tmp_path):
    harness = _BundleHarness()
    harness.agent_memory = object()
    result = harness.import_bundle(_agent_state_bundle(_repository_memory(tmp_path)))

    assert result == {
        "success": False,
        "error": "repository memory is Git-owned and cannot be imported from a bundle",
    }
