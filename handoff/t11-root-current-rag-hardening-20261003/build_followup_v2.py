from __future__ import annotations

import difflib
import hashlib
from pathlib import Path


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
PACKET_DIR = Path(__file__).parent


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def update_rag(source: str) -> str:
    rag = source
    rag = replace_once(
        rag,
        '        except Exception as exc:\n            result = {"success": False, "error": str(exc), "retryable": True}\n',
        '        except Exception as exc:\n            result = {\n                "success": False, "error": str(exc),\n                "retryable": bool(getattr(exc, "retryable", is_busy_error(exc))),\n            }\n',
        "classify non-busy index exceptions",
    )
    rag = replace_once(
        rag,
        "                changed_all = sorted(set(changed_all) | (norm_dirty & set(current_meta)))\n            else:\n                changed_all.sort()\n",
        "                changed_all = sorted(set(changed_all) | (norm_dirty & set(current_meta)))\n                changed_all.sort(key=lambda rel: (rel not in norm_dirty, rel))\n            else:\n                changed_all.sort()\n",
        "prioritize explicit same-stat dirty paths",
    )
    return rag


def update_ingestion_test(source: str) -> str:
    source = replace_once(
        source,
        '    assert requests[0][1] == {\n        "workspace": "specs",\n        "content": "Explicit content",\n        "title": "Explicit title",\n        "metadata": {"owner": "team"},\n    }\n    assert requests[1][1] == {\n        "workspace": "diagrams",\n        "image_path": str(tmp_path / "diagram.png"),\n        "caption": "Explicit caption",\n        "metadata": {"owner": "team"},\n    }\n',
        '    rag_requests = [\n        payload for path, payload in requests\n        if path in {"/api/rag/ingest_document", "/api/rag/ingest_diagram"}\n    ]\n    assert rag_requests == [\n        {\n            "workspace": "specs",\n            "content": "Explicit content",\n            "title": "Explicit title",\n            "metadata": {"owner": "team"},\n        },\n        {\n            "workspace": "diagrams",\n            "image_path": str(tmp_path / "diagram.png"),\n            "caption": "Explicit caption",\n            "metadata": {"owner": "team"},\n        },\n    ]\n',
        "filter MCP telemetry while asserting document and diagram payloads",
    )
    return replace_once(
        source,
        '    assert calls == [\n        (\n            "/api/rag/ingest_document",\n',
        '    rag_calls = [\n        (path, payload) for path, payload in calls\n        if path in {"/api/rag/ingest_document", "/api/rag/ingest_diagram"}\n    ]\n    assert rag_calls == [\n        (\n            "/api/rag/ingest_document",\n',
        "filter telemetry while preserving explicit field assertions",
    )


def main() -> None:
    relpaths = {
        "src/local_ai_hub/rag.py": update_rag,
        "tests/test_t11_rag_ingestion_contract.py": update_ingestion_test,
    }
    patch_parts: list[str] = []
    for rel, transform in relpaths.items():
        path = ROOT / rel
        preimage = path.read_bytes()
        original = preimage.decode("utf-8").replace("\r\n", "\n")
        updated = transform(original)
        newline = "\r\n" if b"\r\n" in preimage else "\n"
        postimage = updated.replace("\n", newline).encode("utf-8")
        out = PACKET_DIR / "followup-v2-postimages-20261005" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(postimage)
        patch_parts.append(
            "diff --git a/" + rel + " b/" + rel + "\n"
            + "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile="a/" + rel,
                tofile="b/" + rel,
                n=3,
            ))
        )
        print(f"pre:{rel}={hashlib.sha256(preimage).hexdigest().upper()}")
        print(f"post:{rel}={hashlib.sha256(postimage).hexdigest().upper()}")
    patch_path = PACKET_DIR / "t11-root-current-followup-20261005-v2.patch"
    patch_path.write_text("".join(patch_parts), encoding="utf-8", newline="")
    print(f"patch_sha256={hashlib.sha256(patch_path.read_bytes()).hexdigest().upper()}")
    print(f"patch_bytes={patch_path.stat().st_size}")
    print(f"patch_path={patch_path}")


if __name__ == "__main__":
    main()
