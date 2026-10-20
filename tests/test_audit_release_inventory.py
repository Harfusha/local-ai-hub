from __future__ import annotations

import pytest

from tools.release_inventory import assess_response, lock_from_report


def test_release_constraints_cover_every_resolved_dependency():
    from tools.release_inventory import validate_constraints
    report = {"install": [{"metadata": {"name": "Example_Package", "version": "1.2"}}]}
    validate_constraints(report, "example-package==1.2\n")
    for constraints in ("", "example-package==1.3\n", "example-package>=1.0\n"):
        with pytest.raises(ValueError):
            validate_constraints(report, constraints)


def test_sbom_identifies_python_components_and_declares_incomplete_scope():
    from tools.release_inventory import make_sbom
    result = make_sbom([{"name": "Example_Package", "version": "1.0+cpu"}])
    assert result["bomFormat"] == "CycloneDX"
    assert result["specVersion"] == "1.6"
    assert result["components"][0]["purl"] == "pkg:pypi/example-package@1.0%2Bcpu"
    assert result["compositions"] == [{"aggregate": "incomplete"}]


@pytest.mark.parametrize("packages", [[], [{"name": "Example", "version": "1\nother"}],
    [{"name": "Example_Package", "version": "1"}, {"name": "example-package", "version": "2"}]])
def test_sbom_rejects_invalid_or_duplicate_inventory(packages):
    from tools.release_inventory import make_sbom
    with pytest.raises(ValueError):
        make_sbom(packages)


def test_advisory_scan_rejects_partial_and_malformed_results():
    packages = [{"name": "example", "version": "1.0"}]
    assert assess_response(packages, {"results": [{}]})["status"] == "no_known_advisories"
    for response in ({}, {"results": []}, {"results": [{"next_page_token": "next"}]},
                     {"results": [{"vulns": "wrong"}]}):
        result = assess_response(packages, response)
        assert result["success"] is False
        assert result["complete"] is False
    result = assess_response(packages, {"results": [{"vulns": [{"id": "GHSA-123", "modified": "2026-10-20"}]}]})
    assert result["success"] is False
    assert result["status"] == "advisories_found"
    assert result["complete"] is True


def test_resolver_lock_preserves_exact_versions_and_hashes():
    report = {"install": [{"metadata": {"name": "Example", "version": "1.2.3"},
                          "download_info": {"archive_info": {"hashes": {"sha256": "a" * 64}}}}]}
    assert lock_from_report(report) == "Example==1.2.3 --hash=sha256:" + "a" * 64 + "\n"
    for metadata in ({}, {"name": "Example", "version": "1.2.3\nextra==2"}):
        with pytest.raises(ValueError):
            lock_from_report({"install": [{"metadata": metadata}]})
