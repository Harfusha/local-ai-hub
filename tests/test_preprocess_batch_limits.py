from contextlib import closing
import hashlib
from types import SimpleNamespace

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def test_file_phase_respects_configured_file_batch_size(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": False,
            "model": "configured-model",
            "disable_llm_card_synthesis": False,
            "prefer_deterministic_cards": False,
            "exclusive": {"enrich_stub_cards": True},
        },
        "background_gpu": {"enabled": True, "file_batch_size": 2},
    }
    submitted_batches = []

    def generate_many(tasks, **_kwargs):
        submitted_batches.append(list(tasks))
        return [{"success": False, "error": "test deferral"} for _ in tasks]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate_many)
    prep = ProjectPreprocessor(
        config,
        _Noop(),
        SimpleNamespace(index_reset=False),
        _Noop(),
        _Noop(),
        RepositoryTools(config),
        background_gpu=gpu,
    )
    try:
        with closing(prep._connect()) as con:
            for index in range(3):
                name = f"part_{index}.py"
                source = f"def function_{index}():\n    return {index}\n".encode("utf-8")
                (root / name).write_bytes(source)
                digest = hashlib.sha256(source).hexdigest()
                con.execute(
                    """INSERT INTO file_refs(
                           root,path,content_hash,size,needs_hash,generation,card_key,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (str(root), name, digest, len(source), 0, 1, None, 0),
                )
            con.commit()

        prep._step_file_card({"root": str(root), "phase": "files"})
        assert len(submitted_batches) == 1
        assert len(submitted_batches[0]) == config["background_gpu"]["file_batch_size"]
    finally:
        prep.close()
