from local_ai_hub.app import _has_retired_bundle_tenant_field


def test_bundle_scope_metadata_rejects_retired_fields_by_presence():
    for value in (None, False, ""):
        assert _has_retired_bundle_tenant_field({"records": [{"provenance": {"tenant": value}}]})


def test_bundle_preserves_opaque_project_content():
    assert not _has_retired_bundle_tenant_field({"records": [{"value": {"tenant": "domain-model"}}]})
    assert not _has_retired_bundle_tenant_field({"rag_chunks": [{"text": {"tenant": "document"}}]})
