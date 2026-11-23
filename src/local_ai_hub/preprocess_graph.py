"""Dependency and call-graph centrality analyzer for repository architecture.

Computes PageRank and in-degree centrality across repository files based on import
and call dependencies stored in deterministic database or source imports.
Identifies core architectural hubs ('is_architectural_hub': true) to prioritize
in preprocessing, indexing, and context ranking.
"""

from __future__ import annotations

import collections
# import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class GraphNodeScore:
    """Centrality score for one file in the repository graph."""

    path: str
    pagerank: float
    in_degree: int
    out_degree: int
    is_architectural_hub: bool


@dataclass(frozen=True)
class GraphAnalysisResult:
    """Full repository dependency graph analysis."""

    nodes: Mapping[str, GraphNodeScore]
    top_backbones: tuple[str, ...]

    def is_hub(self, rel_path: str) -> bool:
        norm = str(rel_path).replace("\\", "/").strip("/")
        node = self.nodes.get(norm)
        return bool(node and node.is_architectural_hub)

    def get_score(self, rel_path: str) -> float:
        norm = str(rel_path).replace("\\", "/").strip("/")
        node = self.nodes.get(norm)
        return node.pagerank if node else 0.0


def compute_pagerank(
    edges: Mapping[str, Sequence[str]],
    all_nodes: Sequence[str],
    damping: float = 0.85,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> dict[str, float]:
    """Compute PageRank via power iteration without external dependencies."""
    n = len(all_nodes)
    if n == 0:
        return {}

    # Initialize uniform scores
    scores = {node: 1.0 / n for node in all_nodes}
    
    # Precompute out-degrees and reverse edges (in-edges)
    out_degree: dict[str, int] = {node: 0 for node in all_nodes}
    in_edges: dict[str, list[str]] = {node: [] for node in all_nodes}

    for src, targets in edges.items():
        targets_in_graph = [t for t in targets if t in scores]
        out_degree[src] = len(targets_in_graph)
        for t in targets_in_graph:
            in_edges[t].append(src)

    base = (1.0 - damping) / n

    for _ in range(max_iter):
        next_scores: dict[str, float] = {}
        # Dangling nodes (out-degree 0) distribute evenly to all nodes
        dangling_sum = sum(scores[node] for node in all_nodes if out_degree[node] == 0)
        dangling_contrib = damping * (dangling_sum / n)

        diff = 0.0
        for node in all_nodes:
            rank_sum = sum(scores[src] / out_degree[src] for src in in_edges[node] if out_degree[src] > 0)
            new_rank = base + dangling_contrib + damping * rank_sum
            diff += abs(new_rank - scores[node])
            next_scores[node] = new_rank

        scores = next_scores
        if diff < tol:
            break

    return scores


def build_graph_from_db(db_path: str | Path, root: str) -> tuple[dict[str, list[str]], list[str]]:
    """Build directed file->imported_file edges from deterministic sqlite3 database."""
    p = Path(db_path)
    if not p.is_file():
        return {}, []

    edges: dict[str, list[str]] = collections.defaultdict(list)
    all_files: set[str] = set()

    try:
        with sqlite3.connect(str(p)) as con:
            # Load known files
            rows = con.execute("SELECT path FROM files WHERE root=?", (root,)).fetchall()
            for r in rows:
                norm_p = str(r[0]).replace("\\", "/").strip("/")
                all_files.add(norm_p)

            # If no files filtered by root, load all files
            if not all_files:
                rows = con.execute("SELECT path FROM files").fetchall()
                for r in rows:
                    all_files.add(str(r[0]).replace("\\", "/").strip("/"))

            # Load import facts
            import_rows = con.execute(
                "SELECT path, value FROM facts WHERE kind='import'"
            ).fetchall()

            # Map module names to files (e.g., 'src.local_ai_hub.preprocess' -> 'src/local_ai_hub/preprocess.py')
            mod_to_file: dict[str, str] = {}
            for f in all_files:
                stem = Path(f).stem
                without_ext = str(f).replace("/", ".").rstrip(".py")
                mod_to_file[stem] = f
                mod_to_file[without_ext] = f

            for src_path, imp_val in import_rows:
                src_norm = str(src_path).replace("\\", "/").strip("/")
                all_files.add(src_norm)
                # Check direct match or module lookup
                imp_clean = str(imp_val).strip()
                target_file = mod_to_file.get(imp_clean)
                if target_file and target_file != src_norm:
                    edges[src_norm].append(target_file)
    except Exception:
        pass

    return dict(edges), sorted(list(all_files))


def analyze_repo_graph(
    edges: Mapping[str, Sequence[str]],
    all_nodes: Sequence[str],
    hub_top_percent: float = 0.15,
    min_in_degree_for_hub: int = 2,
) -> GraphAnalysisResult:
    """Analyze graph centrality and mark top architectural hubs."""
    pageranks = compute_pagerank(edges, all_nodes)
    
    in_degrees: dict[str, int] = collections.defaultdict(int)
    out_degrees: dict[str, int] = collections.defaultdict(int)

    for src, targets in edges.items():
        out_degrees[src] = len(targets)
        for t in targets:
            in_degrees[t] += 1

    sorted_by_pr = sorted(
        pageranks.items(), key=lambda kv: kv[1], reverse=True
    )
    
    hub_cutoff_idx = max(1, int(len(sorted_by_pr) * hub_top_percent))
    top_candidates = set(k for k, _ in sorted_by_pr[:hub_cutoff_idx])

    nodes: dict[str, GraphNodeScore] = {}
    for node in all_nodes:
        pr = pageranks.get(node, 0.0)
        indeg = in_degrees.get(node, 0)
        outdeg = out_degrees.get(node, 0)
        is_hub = (node in top_candidates) and (indeg >= min_in_degree_for_hub)
        nodes[node] = GraphNodeScore(
            path=node,
            pagerank=pr,
            in_degree=indeg,
            out_degree=outdeg,
            is_architectural_hub=is_hub,
        )

    top_backbones = tuple(k for k, _ in sorted_by_pr[:20] if nodes.get(k, None) and nodes[k].is_architectural_hub)
    return GraphAnalysisResult(nodes=nodes, top_backbones=top_backbones)
