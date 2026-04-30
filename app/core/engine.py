"""Async Ready Pool: паралельний виконавець DAG із обмеженою кількістю воркерів.

Архітектурний контур:
  • Замість послідовного обходу топологічно відсортованого списку — пул із
    `MAX_WORKERS` воркер-задач, які наввипередки беруть готові вузли із
    `asyncio.Queue`.
  • Готовність вузла (`in_degree == 0` для `all_success`, або «прийшов хоча
    б один живий батько» для `one_success`) обчислюється у момент, коли
    закінчує батьківський вузол. Перевід стану та push у чергу — атомарні
    під спільним `state.lock`, тому навіть якщо два батьки фінішують
    одночасно, нащадок потрапить у чергу рівно один раз.
  • `should_stop` — м'яка зупинка: при першій помилці виставляється у
    `True`, нові вузли не запускаються, але вже працюючі дограють. Це
    дає чисті завершення замість cancel'ів посеред I/O.
  • Data isolation: `current_input` зник. Двигун формує `input_data`
    локально перед кожним викликом і передає його у `execute()` як
    параметр — гонка на shared-state по входу неможлива в принципі.

Контракт «мертвих» гілок успадкований із попередньої версії: dead_edges
тримає ключі ребер, що не несуть даних (false-гілка condition'а, що видав
true; outbound-ребра від вузла, що впав), а dead_nodes — id вузлів, що
повністю пропускаються. «Смерть» поширюється через `_propagate_finish`:
як тільки батько завершується (success/fail/dead), всі його нащадки
переоцінюються; ті, кому вже не може допомогти жоден живий батько (за
правилом активації) — теж позначаються мертвими, що знову запускає
поширення.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic import ConfigDict, TypeAdapter, ValidationError

from app.core.context import ExecutionContext
from app.core.scheduler import topological_sort
from app.nodes.base import NODE_REGISTRY
from app.schemas.workflow import Edge, Node, Workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Виняток + утиліти типізації портів (без змін у поведінці)
# ---------------------------------------------------------------------------


class UnknownNodeTypeError(ValueError):
    """У `NODE_REGISTRY` немає типу, оголошеного у Workflow."""


# Ключ «мертвого» ребра — детермінований ідентифікатор, що враховує source_handle.
DeadEdgeKey = tuple[str, str, str | None]


def _edge_key(edge: Edge) -> DeadEdgeKey:
    return (edge.from_node, edge.to_node, edge.source_handle)


def _is_branching_handle(handle: str | None) -> bool:
    """`true`/`false` — це гілка condition-вузла, не назва порту даних."""
    return handle in ("true", "false")


# Мапінг рядкових імен портів-типів (як їх пише розробник у
# `@input_port(type_hint="...")`) у реальні Python-типи. Раніше тут була
# власна машинерія `_python_kind` + `_matches` + ручний `_try_convert`
# на 60 рядків — тепер за нас усе робить Pydantic.
TYPE_MAPPING: dict[str, Any] = {
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "str": str,
    "string": str,
    "bool": bool,
    "boolean": bool,
    "dict": dict,
    "object": dict,
    "list": list,
    "array": list,
    "any": Any,
    "": Any,
}

# Lax-конфіг: дозволяє конвертації `int/float → str` («42» → "42"),
# яких очікують вузли NexusFlow і які раніше робив ручний `str(value)`.
# Решта lax-перетворень («42»→42, "true"→True, tuple→list тощо)
# у Pydantic v2 ввімкнена за замовчуванням.
_LAX_CONFIG = ConfigDict(coerce_numbers_to_str=True)


def _try_convert(value: Any, expected: str) -> Any:
    """Спробувати конвертувати `value` у тип, що відповідає рядку `expected`.

    Логіка:
      • беремо реальний Python-тип з `TYPE_MAPPING`,
      • для `Any` (або невідомого типу) — повертаємо значення без змін,
      • інакше створюємо `TypeAdapter(target, config=_LAX_CONFIG)` і викликаємо
        `validate_python(value)` — це і є «офіційна» Pydantic-ова конвертація.

    Якщо Pydantic відкидає значення — піднімаємо `TypeError`, щоб блок
    `except (ValueError, TypeError)` у `_route_inputs` поводився ідентично
    до старої поведінки: логувати warning і пропускати оригінальне значення.
    """
    target = TYPE_MAPPING.get(expected.lower())
    if target is None or target is Any:
        return value
    try:
        return TypeAdapter(target, config=_LAX_CONFIG).validate_python(value)
    except ValidationError as exc:
        # Перший запис у `errors()` — найрелевантніше повідомлення.
        msg = exc.errors()[0]["msg"] if exc.errors() else str(exc)
        raise TypeError(
            f"cannot convert {type(value).__name__} to {expected!r}: {msg}"
        ) from exc


def _expected_port_type(node_type: str, port_name: str) -> str | None:
    cls = NODE_REGISTRY.get(node_type)
    if cls is None:
        return None
    inputs = cls.__dict__.get("__inputs__") or getattr(cls, "__inputs__", []) or []
    for spec in inputs:
        if spec.name == port_name:
            return spec.type_hint
    return None


def _collect_effective_edges(workflow: Workflow) -> list[Edge]:
    """Об'єднує explicit-ребра з декларативними static_connections вузлів."""
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


# ---------------------------------------------------------------------------
# Внутрішній стан запуску
# ---------------------------------------------------------------------------


@dataclass
class _RunState:
    """Інкапсулює увесь стан одного запуску воркфлоу.

    Усі мутації полів-словників/множин (`dead_edges`, `dead_nodes`,
    `scheduled`, `finished`, `pending_count`) відбуваються лише під
    `lock`. Це гарантує атомарність тріади «зменшити лічильник →
    переоцінити готовність → додати в чергу», що і є вимогою задачі.
    """

    nodes_by_id: dict[str, Node]
    edges: list[Edge]
    inbound: dict[str, list[Edge]]
    outbound: dict[str, list[Edge]]

    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    scheduled: set[str] = field(default_factory=set)
    finished: set[str] = field(default_factory=set)
    dead_nodes: set[str] = field(default_factory=set)
    dead_edges: set[DeadEdgeKey] = field(default_factory=set)
    pending_count: int = 0
    # Скільки воркерів зараз ВСЕРЕДИНІ `_process_node` (між інкрементом
    # та `finally`-декрементом). Потрібно для м'якої зупинки: коли
    # `should_stop=True`, нові вузли не беремо, але вже запущені дограють.
    # Як тільки `running_count` падає до 0 під should_stop — двигун може
    # завершитися, навіть якщо в черзі лишилися «не-стартовані» вузли.
    running_count: int = 0

    @classmethod
    def build(cls, workflow: Workflow, edges: list[Edge]) -> "_RunState":
        inbound: dict[str, list[Edge]] = defaultdict(list)
        outbound: dict[str, list[Edge]] = defaultdict(list)
        for e in edges:
            inbound[e.to_node].append(e)
            outbound[e.from_node].append(e)
        return cls(
            nodes_by_id={n.id: n for n in workflow.nodes},
            edges=edges,
            inbound=inbound,
            outbound=outbound,
            pending_count=len(workflow.nodes),
        )


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Async Ready Pool executor.

    Параметри:
      • `max_workers` — фіксована кількість паралельних воркерів. Дефолт
        6: компроміс між паралелізмом для I/O-важких графів і захистом
        від OOM на гігантських графах. Передайте інше значення в
        конструктор для тюнінгу під своє навантаження.

    Контракти:
      • Підтримувані `trigger_rule`: `all_success` (AND), `one_success` (OR).
      • Гарантує, що нащадок потрапить у `ready_queue` рівно один раз —
        захищено `state.lock`.
      • На першій критичній помилці виставляє `context.should_stop=True`
        і re-raise помилку після того, як активні воркери дограли.
    """

    DEFAULT_MAX_WORKERS = 6

    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers or self.DEFAULT_MAX_WORKERS

    # -----------------------------------------------------------------
    # Публічний вхід
    # -----------------------------------------------------------------

    async def run(
        self,
        workflow: Workflow,
        job_id: str,
        context: ExecutionContext,
    ) -> dict:
        edges = _collect_effective_edges(workflow)

        # Pre-flight: усі типи мають бути зареєстровані.
        for n in workflow.nodes:
            if n.type not in NODE_REGISTRY:
                raise UnknownNodeTypeError(f"Unknown node type: {n.type!r}")

        # Pre-flight: топологічна сортування лише як перевірка ациклічності
        # (порядок виконання тепер диктує черга готовності, не список).
        topological_sort(workflow.nodes, edges)

        await context.log(None, f"Starting workflow {workflow.name!r}")

        if not workflow.nodes:
            await context.log(None, "Workflow completed successfully")
            return context.node_outputs

        state = _RunState.build(workflow, edges)

        # Початкове наповнення черги: усі вузли без вхідних ребер.
        async with state.lock:
            for n in workflow.nodes:
                if not state.inbound[n.id]:
                    state.scheduled.add(n.id)
                    state.queue.put_nowait(n.id)
            if state.pending_count == 0:
                state.done_event.set()

        worker_count = max(1, min(self.max_workers, len(workflow.nodes)))
        workers = [
            asyncio.create_task(self._worker(state, context, worker_id=i))
            for i in range(worker_count)
        ]

        try:
            await state.done_event.wait()
        finally:
            # Сигнал воркерам завершитися — кожному свій sentinel.
            for _ in workers:
                state.queue.put_nowait(None)
            await asyncio.gather(*workers, return_exceptions=True)

        # Якщо була критична помилка — пробрасуємо її назовні (job → FAILED).
        if context.first_error is not None:
            raise context.first_error

        await context.log(None, "Workflow completed successfully")
        return context.node_outputs

    # -----------------------------------------------------------------
    # Воркер
    # -----------------------------------------------------------------

    async def _worker(
        self,
        state: _RunState,
        context: ExecutionContext,
        worker_id: int,
    ) -> None:
        while True:
            # Перед кожним новим вузлом — перевірка прапорця м'якої зупинки.
            # Робимо це ДО `queue.get()`, щоби зайняті воркери не тягнули
            # на себе нові вузли, поки інші ще працюють після помилки.
            if context.should_stop:
                return

            item = await state.queue.get()
            if item is None:  # sentinel — кінець роботи
                return
            if context.should_stop:
                # Прийшов задовго чи паралельно з помилкою — не запускаємо.
                continue

            async with state.lock:
                state.running_count += 1
            try:
                await self._process_node(state, context, item)
            finally:
                async with state.lock:
                    state.running_count -= 1
                    # М'яка зупинка: якщо більше ніхто не виконується і
                    # запит на стоп виставлений — будимо main, навіть якщо
                    # у черзі лишилися «не-стартовані» вузли (їх не запустимо).
                    if (
                        context.should_stop
                        and state.running_count == 0
                        and not state.done_event.is_set()
                    ):
                        state.done_event.set()

    # -----------------------------------------------------------------
    # Виконання одного вузла
    # -----------------------------------------------------------------

    async def _process_node(
        self,
        state: _RunState,
        context: ExecutionContext,
        node_id: str,
    ) -> None:
        node_def = state.nodes_by_id[node_id]
        node_cls = NODE_REGISTRY[node_def.type]
        node = node_cls(node_def.id, node_def.config)

        success = False
        output: dict = {}
        try:
            # 1) Зібрати локальні input_data + порти на момент старту.
            #    Це snapshot: батьки, що ще не завершилися (для one_success),
            #    просто не потраплять у вхід — і це правильна семантика.
            input_data, mapped = await self._route_inputs(state, context, node_def)

            async with state.lock:
                # Записуємо порти у спільний контекст — атомарно з рештою стану,
                # щоб інші паралельні читачі не побачили half-write.
                for port_name, value in mapped.items():
                    context.set_input(node_def.id, port_name, value)

            # 2) Універсальний міст port-mapping → шаблонний `input`.
            #    Дублюємо port-значення в input_data, щоб шаблони
            #    `{input.<port>}` працювали без переписування вузлів.
            for port_name, value in mapped.items():
                if isinstance(value, dict):
                    for k, v in value.items():
                        input_data.setdefault(k, v)
                input_data[port_name] = value

            await context.log(node.id, f"Executing ({node.type_name})")
            output = await node.execute(context, input_data)
            if not isinstance(output, dict):
                raise TypeError(
                    f"node {node.id!r} returned {type(output).__name__}, expected dict"
                )
            success = True
        except Exception as exc:  # noqa: BLE001 — навмисно ловимо все
            await context.log(node.id, f"Error: {exc}", level="error")
            # М'яка зупинка: запам'ятовуємо першу помилку і ставимо прапорець.
            context.request_stop(exc)
        finally:
            # Атомарне оновлення стану + поширення «фінішу» на нащадків.
            await self._finalize_node(state, context, node_def, success, output)

    # -----------------------------------------------------------------
    # Маршрутизація даних
    # -----------------------------------------------------------------

    async def _route_inputs(
        self,
        state: _RunState,
        context: ExecutionContext,
        node: Node,
    ) -> tuple[dict, dict]:
        """Збирає `(legacy_merged_input, mapped_ports)` для конкретного запуску.

        Snapshot під `state.lock`:
          • dead_edges/dead_nodes — щоб не бачити частково оновленого стану,
          • node_outputs — узгоджений зріз виходів усіх батьків, що
            завершилися до цього моменту.

        Тип-перевірка / автоконвертація port-mapping залишилися без змін.
        """
        async with state.lock:
            dead_edges_snap = set(state.dead_edges)
            dead_nodes_snap = set(state.dead_nodes)
            outputs_snap = {
                k: dict(v) if isinstance(v, dict) else v
                for k, v in context.node_outputs.items()
            }

        merged: dict = {}
        mapped: dict = {}

        for edge in state.inbound[node.id]:
            if _edge_key(edge) in dead_edges_snap:
                continue
            if edge.from_node in dead_nodes_snap:
                continue
            source_output = outputs_snap.get(edge.from_node)
            if source_output is None:
                # Для one_success: батько ще не завершився — пропускаємо.
                continue
            if isinstance(source_output, dict):
                merged.update(source_output)

            if edge.target_handle is None:
                continue

            if edge.source_handle is None or _is_branching_handle(edge.source_handle):
                value = source_output
            else:
                value = (
                    source_output.get(edge.source_handle)
                    if isinstance(source_output, dict)
                    else None
                )

            expected = _expected_port_type(node.type, edge.target_handle)
            if expected and value is not None:
                # `_try_convert` тепер сам — no-op для збігу типів, бо
                # `TypeAdapter.validate_python` без модифікацій повертає
                # коректне значення. Тому окрема `_matches`-перевірка зайва.
                try:
                    value = _try_convert(value, expected)
                except (ValueError, TypeError) as exc:
                    await context.log(
                        node.id,
                        (
                            f"Type mismatch on port '{edge.target_handle}': "
                            f"expected {expected}, got {type(value).__name__} "
                            f"(auto-convert failed: {exc}) — passing original value"
                        ),
                        level="warning",
                    )

            if edge.target_handle in mapped:
                if not isinstance(mapped[edge.target_handle], list):
                    mapped[edge.target_handle] = [mapped[edge.target_handle]]
                mapped[edge.target_handle].append(value)
            else:
                mapped[edge.target_handle] = value

        return merged, mapped

    # -----------------------------------------------------------------
    # Атомарне завершення вузла + поширення
    # -----------------------------------------------------------------

    async def _finalize_node(
        self,
        state: _RunState,
        context: ExecutionContext,
        node: Node,
        success: bool,
        output: dict,
    ) -> None:
        """Записати результат та оновити стан нащадків.

        Цей метод викликається у блоці `finally` `_process_node`, тож
        його контракт — НЕ кидати винятків (інакше воркер впаде з
        unhandled exception, а інші продовжать виконання). Усі помилки
        тут конвертуємо у warning-лог.
        """
        try:
            ready_now: list[str] = []

            async with state.lock:
                if success:
                    context.node_outputs[node.id] = output
                    state.finished.add(node.id)
                    await context.log(
                        node.id,
                        f"Done. output keys: {list(output)}",
                    )
                    # Condition-вузол: вбиваємо ребро з протилежним handle.
                    if node.type == "condition":
                        chosen = "true" if output.get("result") else "false"
                        for e in state.outbound[node.id]:
                            if (
                                e.source_handle is not None
                                and _is_branching_handle(e.source_handle)
                                and e.source_handle != chosen
                            ):
                                state.dead_edges.add(_edge_key(e))
                else:
                    # Помилка/виняток: вузол мертвий, усі outbound-ребра — мертві.
                    state.finished.add(node.id)
                    state.dead_nodes.add(node.id)
                    for e in state.outbound[node.id]:
                        state.dead_edges.add(_edge_key(e))

                state.pending_count -= 1
                if state.pending_count == 0:
                    state.done_event.set()

                # Поширюємо «фініш» на нащадків. Може каскадно вбити
                # кілька рівнів вглиб (через _propagate_dead).
                ready_now = await self._propagate_finish(state, context, node.id)

            for child_id in ready_now:
                state.queue.put_nowait(child_id)
        except Exception as exc:  # noqa: BLE001 — захист воркера
            logger.exception(
                "Internal error while finalizing node %s: %s", node.id, exc
            )

    # -----------------------------------------------------------------
    # Поширення «фініш-сигналу» по графу (під state.lock)
    # -----------------------------------------------------------------

    async def _propagate_finish(
        self,
        state: _RunState,
        context: ExecutionContext,
        finished_id: str,
    ) -> list[str]:
        """Перевірити кожного нащадка `finished_id` та повернути список тих,
        кого треба покласти у чергу. Викликається ПІД `state.lock`.

        Може каскадно позначати інших як мертвих (через _kill).
        """
        to_enqueue: list[str] = []
        # Стек для каскаду «смерті»: коли вузол позначається мертвим,
        # його нащадки теж переоцінюються в наступних ітераціях.
        pending_finished: list[str] = [finished_id]

        while pending_finished:
            parent_id = pending_finished.pop()
            for edge in state.outbound[parent_id]:
                child_id = edge.to_node
                if child_id in state.scheduled or child_id in state.finished:
                    continue

                verdict = self._evaluate_child(state, child_id)
                if verdict == "ready":
                    state.scheduled.add(child_id)
                    to_enqueue.append(child_id)
                elif verdict == "dead":
                    # Каскадна смерть: позначити, додати в стек, щоб
                    # переоцінити нащадків саме цього вузла.
                    self._kill(state, child_id)
                    await context.log(
                        child_id,
                        "Skipped due to dead branch",
                        level="info",
                    )
                    state.pending_count -= 1
                    if state.pending_count == 0:
                        state.done_event.set()
                    pending_finished.append(child_id)
                # verdict == "wait": просто чекаємо ще батьків

        return to_enqueue

    @staticmethod
    def _evaluate_child(state: _RunState, child_id: str) -> str:
        """Повертає 'ready' / 'dead' / 'wait' для нащадка.

        Семантика:
          • all_success: усі батьки мають фінішувати живими; перший
            мертвий батько → дитина мертва (швидкий short-circuit).
          • one_success: достатньо хоч одного живого фінішованого батька;
            поки живі батьки лишаються в роботі — чекаємо; якщо всі
            батьки фінішували й жоден не живий — мертва.
        """
        node = state.nodes_by_id[child_id]
        rule = getattr(node, "trigger_rule", "all_success")
        inbound = state.inbound[child_id]
        if not inbound:
            return "ready"

        alive_finished = 0
        dead_finished = 0
        unfinished = 0
        for e in inbound:
            edge_dead = (
                _edge_key(e) in state.dead_edges
                or e.from_node in state.dead_nodes
            )
            parent_done = e.from_node in state.finished
            if edge_dead and parent_done:
                dead_finished += 1
            elif parent_done:
                alive_finished += 1
            else:
                unfinished += 1

        if rule == "one_success":
            if alive_finished >= 1:
                return "ready"
            if unfinished == 0:
                return "dead"
            return "wait"
        # all_success
        if dead_finished >= 1:
            return "dead"
        if unfinished == 0 and alive_finished == len(inbound):
            return "ready"
        return "wait"

    @staticmethod
    def _kill(state: _RunState, node_id: str) -> None:
        """Позначити вузол мертвим + проштампувати його outbound-ребра.
        Викликається ПІД `state.lock`."""
        if node_id in state.dead_nodes:
            return
        state.dead_nodes.add(node_id)
        state.finished.add(node_id)
        state.scheduled.add(node_id)  # щоб нащадки бачили «батько фінішував»
        for e in state.outbound[node_id]:
            state.dead_edges.add(_edge_key(e))
