from app.core.context import ExecutionContext
from app.core.scheduler import topological_sort
from app.nodes.base import NODE_REGISTRY
from app.schemas.workflow import Edge, Node, Workflow


class UnknownNodeTypeError(ValueError):
    """У `NODE_REGISTRY` немає типу, оголошеного у Workflow."""


# Ключ "мертвого" ребра — детермінований ідентифікатор, що враховує source_handle.
DeadEdgeKey = tuple[str, str, str | None]


def _edge_key(edge: Edge) -> DeadEdgeKey:
    return (edge.from_node, edge.to_node, edge.source_handle)


class WorkflowEngine:
    """Виконує граф у топологічному порядку.

    Підтримує умовні розгалуження: якщо `condition`-вузол повернув
    `result=False`, ребра з `source_handle="true"` (і навпаки) стають
    "мертвими"; нащадок виконується лише якщо до нього існує хоча б один
    живий шлях.
    """

    async def run(
        self,
        workflow: Workflow,
        job_id: str,
        context: ExecutionContext,
    ) -> dict:
        sorted_nodes = topological_sort(workflow.nodes, workflow.edges)
        await context.log(None, f"Starting workflow '{workflow.name}'")

        skipped: set[str] = set()
        dead_edges: set[DeadEdgeKey] = set()

        for node_def in sorted_nodes:
            if not self._is_alive(node_def, workflow.edges, skipped, dead_edges):
                skipped.add(node_def.id)
                await context.log(node_def.id, "Skipped (dead branch)")
                continue

            node_cls = NODE_REGISTRY.get(node_def.type)
            if node_cls is None:
                raise UnknownNodeTypeError(f"Unknown node type: {node_def.type!r}")

            node = node_cls(node_def.id, node_def.config)
            context.current_input = self._collect_input(
                node_def, workflow.edges, context, skipped, dead_edges
            )

            await context.log(node.id, f"Executing ({node.type_name})")
            try:
                output = await node.execute(context)
            except Exception as exc:
                await context.log(node.id, f"Error: {exc}", level="error")
                raise

            context.node_outputs[node.id] = output
            await context.log(node.id, f"Done. output keys: {list(output)}")

            if node.type_name == "condition":
                self._mark_dead_edges(node_def, output, workflow.edges, dead_edges)

        await context.log(None, "Workflow completed successfully")
        return context.node_outputs

    @staticmethod
    def _is_alive(
        node: Node,
        edges: list[Edge],
        skipped: set[str],
        dead_edges: set[DeadEdgeKey],
    ) -> bool:
        inbound = [e for e in edges if e.to_node == node.id]
        if not inbound:
            return True  # стартовий вузол
        for edge in inbound:
            if _edge_key(edge) in dead_edges:
                continue
            if edge.from_node in skipped:
                continue
            return True
        return False

    @staticmethod
    def _collect_input(
        node: Node,
        edges: list[Edge],
        context: ExecutionContext,
        skipped: set[str],
        dead_edges: set[DeadEdgeKey],
    ) -> dict:
        merged: dict = {}
        for edge in edges:
            if edge.to_node != node.id:
                continue
            if _edge_key(edge) in dead_edges:
                continue
            if edge.from_node in skipped:
                continue
            merged.update(context.node_outputs.get(edge.from_node, {}))
        return merged

    @staticmethod
    def _mark_dead_edges(
        condition_node: Node,
        output: dict,
        edges: list[Edge],
        dead_edges: set[DeadEdgeKey],
    ) -> None:
        chosen = "true" if output.get("result") else "false"
        for edge in edges:
            if (
                edge.from_node == condition_node.id
                and edge.source_handle is not None
                and edge.source_handle != chosen
            ):
                dead_edges.add(_edge_key(edge))
