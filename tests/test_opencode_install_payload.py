from pathlib import Path
import shutil

from tools.update_transaction import replace_install_payload


def test_install_and_update_bundle_goal_without_touching_user_plugins(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    source, target = tmp_path / "source", tmp_path / "install"
    for name in ("src", "skills", "tools"):
        (source / name).mkdir(parents=True)
    shutil.copytree(repo / "tools" / "opencode_goal", source / "tools" / "opencode_goal")
    target.mkdir()
    config = target / "config.toml"
    config.write_text("user setting", encoding="utf-8")
    user_plugin = target / "plugins" / "personal" / "index.js"
    user_plugin.parent.mkdir(parents=True)
    user_plugin.write_text("user plugin", encoding="utf-8")

    for _ in range(2):
        success, detail = replace_install_payload(source, target, config, ())
        assert success, detail
        assert (target / "tools" / "opencode_goal" / "index.js").read_bytes() == (source / "tools" / "opencode_goal" / "index.js").read_bytes()
        assert user_plugin.read_text(encoding="utf-8") == "user plugin"
        assert config.read_text(encoding="utf-8") == "user setting"
