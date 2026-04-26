import logging

from app.core.context import ExecutionContext
from app.core.scheduler import topological_sort
from app.nodes.base import NODE_REGISTRY
from app.schemas.workflow import Edge, Node, Workflow

logger = logging.getLogger(__name__)


class UnknownNodeTypeError(ValueError):
    """У `NODE_REGISTRY` немає типу, оголошеного у Workflow."""


# Ключ "мертвого" ребра — детермінований ідентифікатор, що враховує source_handle.
DeadEdgeKey = tuple[str, str, str | None]


def _edge_key(edge: Edge) -> DeadEdgeKey:
    return (edge.from_node, edge.to_node, edge.source_handle)


def _is_branching_handle(handle: str | None) -> bool:
    """`true`/`false` — це гілка condition-вузла, не назва порту даних."""
    return handle in ("true", "false")


def _collect_effective_edges(workflow: Workflow) -> list[Edge]:
    """Об'єднує explicit-ребра з декларативними static_connections вузлів.

    Static-зв'язки додаються лише якщо source/target присутні у графі.
    """
    edges = list(workflow.edges)
    node_ids = {n.id for n in workflow.nodes}

    for node_def in workflow.nodes:
        node_cls = NODE_REGISTRY.get(node_def.type)
        if node_cls is None:
            continue
        statics = getattr(node_cls, "__static_connections__", []) or []
        for sc in statics:
            if sc.target_node not in node_ids:
                continue
            edges.append(
                Edge(
                    from_node=node_def.id,
                    to_node=sc.target_node,
                    source_handle=sc.source_port,
                    target_handle=sc.target_port,
                )
            )
    return edges


class WorkflowEngine:
    """Виконує граф у топологічному порядку.

    Підтримує:
      - умовні розгалуження condition (`source_handle="true"/"false"`),
      - port-mapping: `source_handle` (порт-джерело) + `target_handle`
        (порт-приймач) — двигун перед `execute()` копіює значення з
        `node_outputs[from][source_handle]` у `node_inputs[to][target_handle]`,
      - static-connections, оголошені у коді вузла декоратором
        `@static_connection(...)` — додаються до набору ребер як readonly.
    """

    async def run(
        self,
        workflow: Workflow,
        job_id: str,
        context: ExecutionContext,
    ) -> dict:
        edges = _collect_effective_edges(workflow)
        sorted_nodes = topological_sort(workflow.nodes, edges)
        await context.log(None, f"Starting workflow '{workflow.name}'")

        skipped: set[str] = set()
        dead_edges: set[DeadEdgeKey] = set()

        for node_def in sorted_nodes:
            if not self._is_alive(node_def, edges, skipped, dead_edges):
                skipped.add(node_def.id)
                await context.log(node_def.id, "Skipped (dead branch)")
                continue

            node_cls = NODE_REGISTRY.get(node_def.type)
            if node_cls is None:
                raise UnknownNodeTypeError(f"Unknown node type: {node_def.type!r}")

            node = node_cls(node_def.id, node_def.config)

            # --- Маршрутизація даних: legacy merge + port-mapping ---
            try:
                merged, mapped = self._route_inputs(
                    node_def, edges, context, skipped, dead_edges
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Routing failed for node %s: %s — falling back to empty input",
                    node_def.id,
                    exc,
                    exc_info=True,
                )
                await context.log(node_def.id, f"Routing warning: {exc}", level="warning")
                merged, mapped = {}, {}

            context.current_input = merged
            for port_name, value in mapped.items():
                context.set_input(node_def.id, port_name, value)
            context._current_node_id = node_def.id

            # --- Універсальний міст: port-mapping → шаблонний `input` ---
            # Виливаємо вміст усіх вхідних портів у current_input, щоб
            # condition / expression / log могли бачити дані через
            # `input.<port>` без переписування своїх обчислень. Явний
            # port-mapping має перевагу над legacy merge: port-значення
            # перетирає одноіменні ключі з merged.
            for port_name, value in context.node_inputs.get(node_def.id, {}).items():
                if isinstance(value, dict):
                    # Розгортаємо dict-значення першого рівня — щоб
                    # `input.size` працювало навіть коли весь вихід прийшов
                    # на цей порт (типово для condition/log без явного source_handle).
                    for k, v in value.items():
                        context.current_input.setdefault(k, v)
                context.current_input[port_name] = value

            await context.log(node.id, f"Executing ({node.type_name})")
            try:
                output = await node.execute(context)
            except Exception as exc:
                await context.log(node.id, f"Error: {exc}", level="error")
                raise

            context.node_outputs[node.id] = output
            await context.log(node.id, f"Done. output keys: {list(output)}")

            if node.type_name == "condition":
                self._mark_dead_edges(node_def, output, edges, dead_edges)

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
    def _route_inputs(
        node: Node,
        edges: list[Edge],
        context: ExecutionContext,
        skipped: set[str],
        dead_edges: set[DeadEdgeKey],
    ) -> tuple[dict, dict]:
        """Повертає (legacy_merged_input, mapped_ports).

        - legacy: повний merge dict-виходів (зворотна сумісність із
          `context.current_input`/шаблонами).
        - mapped: значення, що мають потрапити у `node_inputs[node.id][port]`.
        """
        merged: dict = {}
        mapped: dict = {}

        for edge in edges:
            if edge.to_node != node.id:
                continue
            if _edge_key(edge) in dead_edges:
                continue
            if edge.from_node in skipped:
                continue
            source_output = context.node_outputs.get(edge.from_node, {})
            merged.update(source_output)

            if edge.target_handle is None:
                continue  # нема порт-мапінгу — лише legacy merge

            # Branching-handle ("true"/"false") не іменує порт даних —
            # пропихуємо весь output на вказаний target_handle.
            if edge.source_handle is None or _is_branching_handle(edge.source_handle):
                mapped[edge.target_handle] = source_output
            else:
                mapped[edge.target_handle] = source_output.get(edge.source_handle)

        return merged, mapped

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
                and _is_branching_handle(edge.source_handle)
                and edge.source_handle != chosen
            ):
                dead_edges.add(_edge_key(edge))
