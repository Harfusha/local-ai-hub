from __future__ import annotations

from typing import Any


def compare_api_definitions(
    file_path: str,
    old_defs: dict[str, dict[str, Any]],
    new_defs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    breaking: list[dict[str, Any]] = []
    for name, old_d in old_defs.items():
        kind = old_d.get("kind", "symbol")
        if name not in new_defs:
            breaking.append(
                {
                    "type": "removed_symbol",
                    "symbol": name,
                    "file": file_path,
                    "kind": kind,
                    "description": f"Public {kind} '{name}' was removed",
                }
            )
        else:
            new_d = new_defs[name]
            if kind in ("function", "method") and new_d.get("kind") in ("function", "method"):
                old_req = old_d.get("required_count", 0)
                new_req = new_d.get("required_count", 0)
                old_args = old_d.get("pos_args") or old_d.get("params") or []
                new_args = new_d.get("pos_args") or new_d.get("params") or []
                if new_req > old_req:
                    added_req = [a for a in new_args[:new_req] if a not in old_args[:old_req]]
                    detail = f": {', '.join(added_req)}" if added_req else ""
                    breaking.append(
                        {
                            "type": "signature_changed",
                            "symbol": name,
                            "file": file_path,
                            "kind": kind,
                            "description": f"Signature of {kind} '{name}' added required parameter(s){detail}",
                            "new_req": new_req,
                            "old_req": old_req,
                            "added_req": added_req,
                            "removed_args": [],
                        }
                    )
                elif old_args and new_args:
                    removed_args = [a for a in old_args if a not in new_args]
                    if removed_args:
                        breaking.append(
                            {
                                "type": "signature_changed",
                                "symbol": name,
                                "file": file_path,
                                "kind": kind,
                                "description": f"Signature of {kind} '{name}' removed or renamed parameter(s): {', '.join(removed_args)}",
                                "new_req": new_req,
                                "old_req": old_req,
                                "added_req": [],
                                "removed_args": removed_args,
                            }
                        )
    return breaking
