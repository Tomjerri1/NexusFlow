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


# Імена type_hint, для яких ми вміємо робити автоматичну конвертацію.
# "any" і відсутнє значення — пропускаємо без перевірки.
_NUMERIC_TYPES = {"int", "float", "number", "integer"}
_STR_TYPES = {"str", "string"}
_BOOL_TYPES = {"bool", "boolean"}
_DICT_TYPES = {"dict", "object"}
_LIST_TYPES = {"list", "array"}


def _python_kind(value) -> str:
    """Грубе ім'я типу значення у термінах декларативних type_hint'ів."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def _matches(expected: str, actual_kind: str) -> bool:
    expected = expected.lower()
    if expected in ("any", ""):
        return True
    if actual_kind == "bool" and expected in _NUMERIC_TYPES:
        # bool — підтип int у Python, але для UX краще явно конвертувати.
        return False
    groups = (_NUMERIC_TYPES, _STR_TYPES, _BOOL_TYPES, _DICT_TYPES, _LIST_TYPES)
    for group in groups:
        if expected in group:
            return actual_kind in group or actual_kind == expected
    return expected == actual_kind


def _try_convert(value, expected: str):
    """Найкраща спроба конвертації. Кидає `ValueError`/`TypeError`, якщо неможливо."""
    expected = expected.lower()
    if expected in _STR_TYPES:
        return str(value)
    if expected == "int" or expected == "integer":
        if isinstance(value, str):
            return int(value.strip())
        return int(value)
    if expected in ("float", "number"):
        if isinstance(value, str):
            return float(value.strip())
        return float(value)
    if expected in _BOOL_TYPES:
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "on"):
                return True
            if v in ("false", "0", "no", "off", ""):
                return False
            raise ValueError(f"cannot parse {value!r} as bool")
        return bool(value)
    if expected in _DICT_TYPES:
        if isinstance(value, dict):
            return value
        raise TypeError(f"cannot convert {_python_kind(value)} to dict")
    if expected in _LIST_TYPES:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        raise TypeError(f"cannot convert {_python_kind(value)} to list")
    # Невідомий тип — нема куди конвертувати.
    raise TypeError(f"unknown target type {expected!r}")


def _expected_port_type(node_type: str, port_name: str) -> str | None:
    """Дістає `type_hint` для вхідного порту з декларативної мета-схеми вузла."""
    cls = NODE_REGISTRY.get(node_type)
    if cls is None:
        return None
    inputs = cls.__dict__.get("__inputs__") or getattr(cls, "__inputs__", []) or []
    for spec in inputs:
        if spec.name == port_name:
            return spec.type_hint
    return None


def _collect_effective_edges(workflow: Workflow) -> list[Edge]:
    """Об'єднує explicit-ребра з декларативними static_connections вузлів.

    Static-зв'язки додаються лише якщо source/target присутні у графі та
    завжди мають `is_readonly=True`. Якщо сам Workflow позначено як
    `is_readonly`, цей прапорець каскадно виставляється всім ребрам —
    і двигун, і фронтенд трактуватимуть граф як такий, що лише для перегляду.
    """
    workflow_readonly = bool(getattr(workflow, "is_readonly", False))

    edges: list[Edge] = []
    for edge in workflow.edges:
        if workflow_readonly and not edge.is_readonly:
            edges.append(edge.model_copy(update={"is_readonly": True}))
        else:
            edges.append(edge)

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
                    is_readonly=True,
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

    Контракт «мертвих» гілок:
      - `dead_edges` — множина ключів ребер, які не повинні нести даних
        (наприклад, false-гілка condition, що видав True).
      - `dead_nodes` — множина id вузлів, які повністю пропускаються
        (`execute` не викликається). Вузол стає мертвим, коли всі його
        вхідні ребра — мертві (або немає живих батьків). Як тільки вузол
        опиняється у `dead_nodes`, ВСІ його вихідні ребра одразу
        проштамповуються у `dead_edges` — це і є каскадне поширення
        «смерті» вглиб графа.
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

        dead_nodes: set[str] = set()
        dead_edges: set[DeadEdgeKey] = set()

        for node_def in sorted_nodes:
            if not self._is_alive(node_def, edges, dead_nodes, dead_edges):
                self._mark_node_dead(node_def, edges, dead_nodes, dead_edges)
                await context.log(
                    node_def.id,
                    "Skipped due to dead branch",
                    level="info",
                )
                continue

            node_cls = NODE_REGISTRY.get(node_def.type)
            if node_cls is None:
                raise UnknownNodeTypeError(f"Unknown node type: {node_def.type!r}")

            node = node_cls(node_def.id, node_def.config)

            # --- Маршрутизація даних: legacy merge + port-mapping ---
            try:
                merged, mapped = await self._route_inputs(
                    node_def, edges, context, dead_nodes, dead_edges
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
        dead_nodes: set[str],
        dead_edges: set[DeadEdgeKey],
    ) -> bool:
        """Вузол живий, якщо ХОЧА Б одне його вхідне ребро не в `dead_edges`
        і його джерело не в `dead_nodes`. Стартові вузли (без inbound) — живі.

        Іншими словами: якщо всі вхідні ребра мертві — вузол мертвий і має
        бути пропущений. Це автоматично каскадно поширює пропуск униз
        графа разом із `_mark_node_dead` (який стампує outbound-ребра).
        """
        inbound = [e for e in edges if e.to_node == node.id]
        if not inbound:
            return True  # стартовий вузол
        for edge in inbound:
            if _edge_key(edge) in dead_edges:
                continue
            if edge.from_node in dead_nodes:
                continue
            return True
        return False

    @staticmethod
    def _mark_node_dead(
        node: Node,
        edges: list[Edge],
        dead_nodes: set[str],
        dead_edges: set[DeadEdgeKey],
    ) -> None:
        """Каскадне поширення «смерті»: вузол → `dead_nodes`,
        усі його вихідні ребра → `dead_edges`. Завдяки цьому подальші
        нащадки автоматично визначаться як мертві у `_is_alive`,
        навіть якщо мають інші (теж мертві) вхідні ребра.
        """
        dead_nodes.add(node.id)
        for edge in edges:
            if edge.from_node == node.id:
                dead_edges.add(_edge_key(edge))

    @staticmethod
    async def _route_inputs(
        node: Node,
        edges: list[Edge],
        context: ExecutionContext,
        dead_nodes: set[str],
        dead_edges: set[DeadEdgeKey],
    ) -> tuple[dict, dict]:
        """Повертає (legacy_merged_input, mapped_ports).

        - legacy: повний merge dict-виходів (зворотна сумісність із
          `context.current_input`/шаблонами).
        - mapped: значення, що мають потрапити у `node_inputs[node.id][port]`.

        Для кожного port-mapping (`target_handle`) перевіряє очікуваний
        `type_hint` із метаданих вузла-приймача. Якщо тип не збігається —
        пробує автоматичну конвертацію (int↔str, str→float, тощо).
        Невдала конвертація — лише warning у `context.log`, виконання не
        зупиняється: значення проходить як є.
        """
        merged: dict = {}
        mapped: dict = {}

        for edge in edges:
            if edge.to_node != node.id:
                continue
            if _edge_key(edge) in dead_edges:
                continue
            if edge.from_node in dead_nodes:
                continue
            source_output = context.node_outputs.get(edge.from_node, {})
            merged.update(source_output)

            if edge.target_handle is None:
                continue  # нема порт-мапінгу — лише legacy merge

            # Branching-handle ("true"/"false") не іменує порт даних —
            # пропихуємо весь output на вказаний target_handle.
            if edge.source_handle is None or _is_branching_handle(edge.source_handle):
                value = source_output
            else:
                value = source_output.get(edge.source_handle)

            expected = _expected_port_type(node.type, edge.target_handle)
            if expected and value is not None:
                actual = _python_kind(value)
                if not _matches(expected, actual):
                    try:
                        value = _try_convert(value, expected)
                    except (ValueError, TypeError) as exc:
                        await context.log(
                            node.id,
                            (
                                f"Type mismatch on port '{edge.target_handle}': "
                                f"expected {expected}, got {actual} "
                                f"(auto-convert failed: {exc}) — passing original value"
                            ),
                            level="warning",
                        )

            mapped[edge.target_handle] = value

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
