from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import uninstall
from install_ownership import record_external_block, record_external_json_key, read_install_manifest, write_install_manifest


def test_uninstall_path_containment_normalizes_traversal(tmp_path: Path) -> None:
    root = tmp_path / "install"
    nested = root / "rollback" / "snapshot.json"
    escaped = root / "rollback" / ".." / ".." / "outside.json"

    assert uninstall._is_within(nested, root)
    assert not uninstall._is_within(escaped, root)


def test_json_cleanup_removes_only_install_references(tmp_path: Path) -> None:
    install = tmp_path / "installed-hub"
    install.mkdir()
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {
        "local-ai": {"command": "python", "cwd": str(install)},
        "serena-local": {"command": "third-party-serena"},
    }}), encoding="utf-8")
    write_install_manifest(install)
    record_external_json_key(
        install, path, container="mcpServers", key="local-ai", preimage=None,
        postimage={"command": "python", "cwd": str(install)},
    )

    uninstall.clean_json(path, install)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "local-ai" not in data["mcpServers"]
    assert "serena-local" in data["mcpServers"]


def test_json_cleanup_preserves_edited_owned_entry_and_unowned_entry(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    path = tmp_path / "mcp.json"
    original = {"command": "python", "cwd": str(install)}
    data = {"mcpServers": {"local-ai": original, "other": {"command": "foreign"}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    write_install_manifest(install)
    record_external_json_key(
        install, path, container="mcpServers", key="local-ai", preimage=None, postimage=original,
    )
    data["mcpServers"]["local-ai"]["args"] = ["user-added-flag"]
    path.write_text(json.dumps(data), encoding="utf-8")

    uninstall.clean_json(path, install)

    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["mcpServers"]["local-ai"]["args"] == ["user-added-flag"]
    assert result["mcpServers"]["other"] == {"command": "foreign"}


def test_uninstall_plan_rejects_home_before_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="unsafe uninstall path"):
        uninstall.build_uninstall_plan(home, source_root=source, home=home)


def test_uninstall_plan_requires_install_ownership_marker(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    install = home / ".local-ai-hub"
    home.mkdir()
    source.mkdir()
    install.mkdir()

    with pytest.raises(ValueError, match="ownership marker"):
        uninstall.build_uninstall_plan(install, source_root=source, home=home)


def test_uninstall_plan_accepts_owned_install_and_lists_managed_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    install = tmp_path / "install"
    home.mkdir()
    source.mkdir()
    install.mkdir()
    write_install_manifest(install, ["tools/setup.py"])

    plan = uninstall.build_uninstall_plan(install, source_root=source, home=home)

    assert plan["install_dir"] == str(install)
    assert plan["managed_paths"] == ["tools/setup.py"]
    assert plan["owned_paths"] == [str(install), str(install / "tools" / "setup.py")]


def test_uninstall_plan_rejects_source_overlap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    install = source / "installed-child"
    source.mkdir()
    install.mkdir()
    write_install_manifest(install)

    with pytest.raises(ValueError, match="unsafe uninstall path"):
        uninstall.build_uninstall_plan(install, source_root=source, home=tmp_path / "home")


def test_uninstall_plan_rejects_symlink_component(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    real_install = tmp_path / "real-install"
    linked_parent = tmp_path / "linked-parent"
    home.mkdir()
    source.mkdir()
    real_install.mkdir()
    write_install_manifest(real_install)
    try:
        linked_parent.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink or junction"):
        uninstall.build_uninstall_plan(linked_parent / "real-install", source_root=source, home=home)


def test_main_stops_before_cleanup_when_hub_stop_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall, "stop_hub", lambda _install: "unconfirmed")
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    cleanup_calls: list[str] = []
    monkeypatch.setattr(uninstall, "clean_codex", lambda _path: cleanup_calls.append("codex"))
    monkeypatch.setattr(uninstall, "clean_json", lambda _path: cleanup_calls.append("json"))
    monkeypatch.setattr(uninstall, "clean_policy", lambda _path: cleanup_calls.append("policy"))
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda *_args, **_kwargs: cleanup_calls.append("rmtree"))

    assert uninstall.main() == 1
    assert cleanup_calls == []
    assert install.is_dir()


def test_policy_cleanup_requires_manifest_and_preserves_outside_edits(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    target = tmp_path / "AGENTS.md"
    begin, end = uninstall.POLICY_BEGIN, uninstall.POLICY_END
    owned_block = f"{begin}\nHub policy v1\n{end}"
    target.write_text(f"User intro\n{owned_block}\nUser tail\n", encoding="utf-8")
    write_install_manifest(install)
    record_external_block(
        install, target, kind="text_block", owner_marker={"begin": begin, "end": end},
        preimage=None, postimage=owned_block,
    )

    uninstall.clean_policy(target, install)

    assert target.read_text(encoding="utf-8") == "User intro\n\nUser tail\n"
    manifest = read_install_manifest(install)
    entry = manifest["external_ownership"][0]
    assert entry["created_by_hub"] is True
    assert entry["preimage_digest"] is None
    assert entry["last_hub_written_digest"]
    assert "Hub policy v1" not in (install / uninstall.MANIFEST_NAME).read_text(encoding="utf-8")


def test_policy_cleanup_preserves_conflicted_owned_block(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    target = tmp_path / "AGENTS.md"
    begin, end = uninstall.POLICY_BEGIN, uninstall.POLICY_END
    owned_block = f"{begin}\nHub policy v1\n{end}"
    target.write_text(f"User intro\n{owned_block}\nUser tail\n", encoding="utf-8")
    write_install_manifest(install)
    record_external_block(
        install, target, kind="text_block", owner_marker={"begin": begin, "end": end},
        preimage=None, postimage=owned_block,
    )
    target.write_text(target.read_text(encoding="utf-8").replace("Hub policy v1", "Hub policy plus user edit"), encoding="utf-8")
    conflicted = target.read_text(encoding="utf-8")

    uninstall.clean_policy(target, install)

    assert target.read_text(encoding="utf-8") == conflicted


def test_reinstall_keeps_original_ownership_origin_for_policy_block(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    target = tmp_path / "AGENTS.md"
    begin, end = uninstall.POLICY_BEGIN, uninstall.POLICY_END
    old_block = f"{begin}\nHub policy v1\n{end}"
    new_block = f"{begin}\nHub policy v2\n{end}"
    target.write_text(old_block, encoding="utf-8")
    write_install_manifest(install)
    marker = {"begin": begin, "end": end}
    record_external_block(
        install, target, kind="text_block", owner_marker=marker, preimage=None, postimage=old_block,
    )
    record_external_block(
        install, target, kind="text_block", owner_marker=marker, preimage=old_block, postimage=new_block,
    )

    manifest = read_install_manifest(install)
    assert manifest["external_ownership"][0]["created_by_hub"] is True
    assert manifest["external_ownership"][0]["preimage_digest"] is None
    target.write_text(new_block, encoding="utf-8")
    uninstall.clean_policy(target, install)
    assert target.read_text(encoding="utf-8") == ""


def test_schema_one_marker_migrates_without_claiming_legacy_external_blocks(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    manifest_path = install / uninstall.MANIFEST_NAME
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "product": "local-ai-hub",
        "install_id": "legacy-install",
        "install_root": str(install),
        "managed_paths": [],
    }), encoding="utf-8")

    write_install_manifest(install)

    manifest = read_install_manifest(install)
    assert manifest["schema_version"] == 2
    assert manifest["install_id"] == "legacy-install"
    assert manifest["external_ownership"] == []
