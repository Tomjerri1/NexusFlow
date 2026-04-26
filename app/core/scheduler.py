from collections import deque

from app.schemas.workflow import Edge, Node


class CycleDetectedError(ValueError):
    """Граф workflow містить цикл — DAG-вимога порушена."""

    def __init__(self, cycle_node_ids: list[str]):
        self.cycle_node_ids = cycle_node_ids
        super().__init__(f"Cycle detected involving nodes: {cycle_node_ids}")


def topological_sort(nodes: list[Node], edges: list[Edge]) -> list[Node]:
    """Kahn's algorithm. Повертає вузли в порядку виконання.

    Кидає `CycleDetectedError`, якщо граф не є DAG.
    """
    nodes_by_id: dict[str, Node] = {n.id: n for n in nodes}
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}
    adjacency: dict[str, list[str]] = {n.id: [] for n in nodes}

    for edge in edges:
        adjacency[edge.from_node].append(edge.to_node)
        in_degree[edge.to_node] += 1

    queue: deque[str] = deque(nid for nid, d in in_degree.items() if d == 0)
    sorted_ids: list[str] = []

    while queue:
        nid = queue.popleft()
        sorted_ids.append(nid)
        for neighbour in adjacency[nid]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    if len(sorted_ids) != len(nodes):
        unresolved = sorted(nid for nid, d in in_degree.items() if d > 0)
        raise CycleDetectedError(unresolved)

    return [nodes_by_id[nid] for nid in sorted_ids]
