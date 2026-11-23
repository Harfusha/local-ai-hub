"""Universal Memory Knowledge Graph.

Connects repository memories, architectural invariants, and historical incidents into a unified
semantic directed graph.
Key capabilities:
1. Multi-hop knowledge traversal across dependencies and invariants.
2. Automated Subsystem Memory Card generation for target modules.
3. Conflict and violation detection (e.g. active incident violating a core invariant).
4. Full interoperability with Agent OS memory store records and JSON persistence.
"""

from __future__ import annotations

import collections
# import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryNode:
    """A distinct knowledge entity in the memory graph."""

    id: str
    node_type: str  # "fact", "invariant", "incident", "architecture", "rule"
    content: str
    scope: str
    tags: Tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryEdge:
    """A directed semantic relationship between two memory nodes."""

    source: str
    target: str
    relation: str  # "depends_on", "violates", "mitigated_by", "applies_to", "supersedes", "related"
    weight: float = 1.0


class UniversalMemoryGraph:
    """Directed semantic knowledge graph over Agent OS memories and incidents."""

    def __init__(self) -> None:
        self._nodes: Dict[str, MemoryNode] = {}
        # source -> list of (target, edge)
        self._out_edges: Dict[str, List[MemoryEdge]] = collections.defaultdict(list)
        # target -> list of (source, edge)
        self._in_edges: Dict[str, List[MemoryEdge]] = collections.defaultdict(list)

    def add_node(self, node: MemoryNode) -> None:
        """Register or update a knowledge node."""
        self._nodes[node.id] = node

    def add_edge(self, edge: MemoryEdge) -> None:
        """Register a directed relation between nodes."""
        self._out_edges[edge.source].append(edge)
        self._in_edges[edge.target].append(edge)

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        """Fetch node by identifier."""
        return self._nodes.get(node_id)

    def neighbors(
        self,
        node_id: str,
        relation: Optional[str] = None,
        direction: str = "out",
    ) -> List[Tuple[MemoryNode, str]]:
        """Find immediate neighbors with relation label."""
        results: List[Tuple[MemoryNode, str]] = []
        if direction in ("out", "both"):
            for edge in self._out_edges.get(node_id, []):
                if relation is None or edge.relation == relation:
                    target_node = self._nodes.get(edge.target)
                    if target_node:
                        results.append((target_node, edge.relation))

        if direction in ("in", "both"):
            for edge in self._in_edges.get(node_id, []):
                if relation is None or edge.relation == relation:
                    src_node = self._nodes.get(edge.source)
                    if src_node:
                        results.append((src_node, edge.relation))

        return results

    def traverse(
        self,
        start_id: str,
        max_depth: int = 2,
        direction: str = "out",
    ) -> List[MemoryNode]:
        """Breadth-first search traversal starting from a node."""
        if start_id not in self._nodes:
            return []

        visited: Set[str] = {start_id}
        queue: collections.deque[Tuple[str, int]] = collections.deque([(start_id, 0)])
        result: List[MemoryNode] = []

        while queue:
            curr_id, depth = queue.popleft()
            if depth > 0:
                result.append(self._nodes[curr_id])

            if depth >= max_depth:
                continue

            for neighbor, _ in self.neighbors(curr_id, direction=direction):
                if neighbor.id not in visited:
                    visited.add(neighbor.id)
                    queue.append((neighbor.id, depth + 1))

        return result

    def generate_subsystem_card(self, subsystem: str) -> Dict[str, Any]:
        """Synthesize an architectural memory card for a module or subsystem."""
        subsystem_cf = subsystem.casefold()

        matching_nodes: List[MemoryNode] = []
        for node in self._nodes.values():
            if (
                subsystem_cf in node.scope.casefold()
                or any(subsystem_cf in t.casefold() for t in node.tags)
                or subsystem_cf in node.content.casefold()
            ):
                matching_nodes.append(node)

        invariants: List[str] = []
        facts: List[str] = []
        incidents: List[str] = []
        rules: List[str] = []

        for node in matching_nodes:
            if node.node_type == "invariant":
                invariants.append(node.content)
            elif node.node_type == "incident":
                incidents.append(node.content)
            elif node.node_type == "rule":
                rules.append(node.content)
            else:
                facts.append(node.content)

        return {
            "subsystem": subsystem,
            "total_nodes": len(matching_nodes),
            "invariants": invariants,
            "facts": facts,
            "incidents": incidents,
            "rules": rules,
        }

    def detect_conflicts(self) -> List[Dict[str, Any]]:
        """Identify contradictions, e.g. incidents violating known invariants."""
        conflicts: List[Dict[str, Any]] = []

        # Check explicit "violates" edges
        for src_id, edges in self._out_edges.items():
            for edge in edges:
                if edge.relation == "violates":
                    src_node = self._nodes.get(src_id)
                    tgt_node = self._nodes.get(edge.target)
                    if src_node and tgt_node:
                        conflicts.append(
                            {
                                "type": "explicit_violation",
                                "source": src_node.content,
                                "target": tgt_node.content,
                                "source_type": src_node.node_type,
                                "target_type": tgt_node.node_type,
                            }
                        )

        return conflicts

    @classmethod
    def from_memory_records(cls, records: List[Dict[str, Any]]) -> UniversalMemoryGraph:
        """Construct graph directly from Agent OS memory store records."""
        graph = cls()
        for rec in records:
            content = str(rec.get("content", ""))
            node_id = str(rec.get("id") or rec.get("key", ""))
            if not node_id:
                continue

            node_type = "fact"
            if "[INVARIANT]" in content or "invariant" in content.lower():
                node_type = "invariant"
            elif "[INCIDENT]" in content or "incident" in content.lower() or "error" in content.lower():
                node_type = "incident"
            elif "[RULE]" in content:
                node_type = "rule"

            scope = str(rec.get("scope_id") or rec.get("scope", "global"))
            tags = tuple(rec.get("tags", []))
            conf = float(rec.get("confidence", 1.0))

            node = MemoryNode(
                id=node_id,
                node_type=node_type,
                content=content,
                scope=scope,
                tags=tags,
                confidence=conf,
            )
            graph.add_node(node)

        return graph

    def to_dict(self) -> Dict[str, Any]:
        """Serialize memory graph to JSON-compatible dictionary."""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "node_type": n.node_type,
                    "content": n.content,
                    "scope": n.scope,
                    "tags": list(n.tags),
                    "confidence": n.confidence,
                    "created_at": n.created_at,
                    "metadata": n.metadata,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for edges in self._out_edges.values()
                for e in edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UniversalMemoryGraph:
        """Deserialize memory graph from JSON-compatible dictionary."""
        graph = cls()
        for nd in data.get("nodes", []):
            node = MemoryNode(
                id=nd["id"],
                node_type=nd["node_type"],
                content=nd["content"],
                scope=nd["scope"],
                tags=tuple(nd.get("tags", [])),
                confidence=float(nd.get("confidence", 1.0)),
                created_at=float(nd.get("created_at", time.time())),
                metadata=nd.get("metadata", {}),
            )
            graph.add_node(node)

        for ed in data.get("edges", []):
            edge = MemoryEdge(
                source=ed["source"],
                target=ed["target"],
                relation=ed["relation"],
                weight=float(ed.get("weight", 1.0)),
            )
            graph.add_edge(edge)

        return graph
