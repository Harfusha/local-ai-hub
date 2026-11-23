"""Hierarchical GraphRAG Community Detection (Louvain / Leiden Modularity Clustering).

Decomposes the repository dependency graph into multi-level architectural communities:
Level 0: Granular files and symbols
Level 1: Functional components and feature groups
Level 2: Major architectural subsystems (e.g., preprocessing, storage, routing, inference)

Provides O(1) architectural subsystem context synthesis for high-level repository queries
without brute-forcing dozens of granular code chunks.
"""

from __future__ import annotations

import collections
import logging
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommunitySummary:
    """Summary of a detected architectural community."""

    community_id: str
    level: int
    name: str
    members: Tuple[str, ...]
    hub_nodes: Tuple[str, ...]
    density: float
    keywords: Tuple[str, ...]


class HierarchicalGraphRAG:
    """Hierarchical graph clustering and architectural context synthesizer."""

    def __init__(self, resolution: float = 1.0):
        self.resolution = resolution
        self._adj: Dict[str, Dict[str, float]] = collections.defaultdict(dict)
        self._node_weights: Dict[str, float] = collections.defaultdict(float)
        self._total_edge_weight: float = 0.0

    def add_edge(self, u: str, v: str, weight: float = 1.0) -> None:
        """Add undirected weighted dependency edge."""
        if u == v:
            return
        w = float(weight)
        self._adj[u][v] = self._adj[u].get(v, 0.0) + w
        self._adj[v][u] = self._adj[v].get(u, 0.0) + w
        self._node_weights[u] += w
        self._node_weights[v] += w
        self._total_edge_weight += w

    def detect_communities(self, max_levels: int = 2) -> Dict[int, List[CommunitySummary]]:
        """Run hierarchical Louvain modularity clustering up to max_levels."""
        if self._total_edge_weight == 0.0 or not self._adj:
            return {0: []}

        levels: Dict[int, List[CommunitySummary]] = {}
        # Level 0: nodes directly
        m = self._total_edge_weight  # total weight of all edges

        # Current node -> community mapping
        # current_partition: Dict[str, int] = {node: i for i, node in enumerate(self._adj.keys())}
        current_adj = {u: dict(neighbors) for u, neighbors in self._adj.items()}
        current_weights = dict(self._node_weights)

        for lvl in range(1, max_levels + 1):
            partition = self._louvain_pass(current_adj, current_weights, m)
            if len(set(partition.values())) == len(current_adj):
                # No further clustering possible
                break

            # Map communities back to original nodes
            comm_to_members: Dict[int, List[str]] = collections.defaultdict(list)
            for node, comm in partition.items():
                comm_to_members[comm].append(node)

            summaries: List[CommunitySummary] = []
            for comm_id, members in comm_to_members.items():
                # Find hub node in this community
                hub_nodes = sorted(members, key=lambda n: self._node_weights.get(n, 0.0), reverse=True)[:3]

                # Synthesize label from common path prefix or top hubs
                comm_name = self._synthesize_label(members, hub_nodes)

                # Compute density: internal edges / possible edges
                internal_w = 0.0
                member_set = set(members)
                for u in members:
                    for v, w in self._adj.get(u, {}).items():
                        if v in member_set:
                            internal_w += w
                internal_w /= 2.0  # undirected
                possible_edges = (len(members) * (len(members) - 1)) / 2.0
                density = (internal_w / possible_edges) if possible_edges > 0 else 1.0

                summaries.append(
                    CommunitySummary(
                        community_id=f"comm_l{lvl}_{comm_id}",
                        level=lvl,
                        name=comm_name,
                        members=tuple(sorted(members)),
                        hub_nodes=tuple(hub_nodes),
                        density=round(density, 3),
                        keywords=tuple(self._extract_keywords(members)),
                    )
                )

            levels[lvl] = summaries

            # Build contracted graph for next hierarchical level
            current_adj, current_weights = self._aggregate_graph(current_adj, partition)

        return levels

    def _louvain_pass(
        self,
        adj: Dict[str, Dict[str, float]],
        weights: Dict[str, float],
        total_m: float,
    ) -> Dict[str, int]:
        """Single optimization pass moving nodes to maximize modularity gain."""
        partition: Dict[str, int] = {node: i for i, node in enumerate(adj.keys())}
        comm_tot: Dict[int, float] = {i: weights[node] for i, node in enumerate(adj.keys())}

        improved = True
        iterations = 0
        nodes = list(adj.keys())

        while improved and iterations < 15:
            improved = False
            iterations += 1

            for u in nodes:
                current_comm = partition[u]
                k_u = weights[u]

                # Weight of links from u to current community
                k_u_in = sum(w for v, w in adj[u].items() if partition[v] == current_comm)

                # Remove u from current community
                comm_tot[current_comm] -= k_u

                # Find candidate neighbor communities
                neighbor_comms: Set[int] = {partition[v] for v in adj[u].keys()}

                # Current community total degree (excluding node u)
                tot_curr = comm_tot.get(current_comm, 0.0)
                # Gain of staying in current community
                curr_gain = k_u_in - self.resolution * (tot_curr * k_u) / (2.0 * total_m)

                best_comm = current_comm
                best_gain = curr_gain

                for c in neighbor_comms:
                    if c == current_comm:
                        continue
                    k_u_c = sum(w for v, w in adj[u].items() if partition[v] == c)
                    tot_c = comm_tot.get(c, 0.0)

                    gain = k_u_c - self.resolution * (tot_c * k_u) / (2.0 * total_m)
                    if gain > best_gain:
                        best_gain = gain
                        best_comm = c

                # Move u to best community
                partition[u] = best_comm
                comm_tot[best_comm] += k_u
                if best_comm != current_comm:
                    improved = True

        return partition

    def _aggregate_graph(
        self,
        adj: Dict[str, Dict[str, float]],
        partition: Dict[str, int],
    ) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
        """Contract nodes belonging to the same community into super-nodes."""
        new_adj: Dict[str, Dict[str, float]] = collections.defaultdict(dict)
        new_weights: Dict[str, float] = collections.defaultdict(float)

        for u, neighbors in adj.items():
            c_u = f"c_{partition[u]}"
            for v, w in neighbors.items():
                c_v = f"c_{partition[v]}"
                if c_u != c_v:
                    new_adj[c_u][c_v] = new_adj[c_u].get(c_v, 0.0) + w
                    new_weights[c_u] += w

        return new_adj, new_weights

    def _synthesize_label(self, members: List[str], hub_nodes: List[str]) -> str:
        """Derive meaningful subsystem label from member paths."""
        # Check for common directory prefixes
        prefixes = [m.split("/")[0] if "/" in m else m.split(".")[0] for m in members]
        counts = collections.Counter(prefixes)
        top_prefix, count = counts.most_common(1)[0]
        if count >= len(members) * 0.4:
            return f"Subsystem::{top_prefix}"
        if hub_nodes:
            return f"Subsystem::{hub_nodes[0]}"
        return "Subsystem::General"

    def _extract_keywords(self, members: List[str]) -> List[str]:
        """Extract dominant terms from member names."""
        words: List[str] = []
        for m in members:
            clean = m.replace("/", "_").replace(".", "_").replace("\\", "_")
            words.extend([p.casefold() for p in clean.split("_") if len(p) > 2])
        counts = collections.Counter(words)
        return [w for w, _ in counts.most_common(5)]
