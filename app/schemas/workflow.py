from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal[
    "manual_trigger",
    "read_file",
    "write_file",
    "condition",
    "log",
    "custom_code",
    "expression",
]


# Правила активації вузла на основі стану вхідних ребер.
# `all_success` — fire лише якщо ВСІ вхідні ребра живі (AND).
# `one_success` — fire якщо ХОЧА Б ОДНЕ вхідне ребро живе (OR).
# Стартові вузли (без inbound) активуються завжди.
TriggerRule = Literal["all_success", "one_success"]


class Edge(BaseModel):
    """Спрямоване ребро графа: from_node -> to_node.

    `source_handle`:
      - для `condition` — "true"/"false" (умовне розгалуження),
      - для типізованого мапінгу — назва вихідного порту вузла-джерела.
    `target_handle` — назва вхідного порту вузла-приймача (port-mapping).
    Якщо `None` — використовується дефолтна merge-маршрутизація (legacy).
    """

    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    source_handle: str | None = None
    target_handle: str | None = None
    is_readonly: bool = False


# Спеціальні ключі для оголошення керуючих (control-flow) входів через
# скорочений запис `Node.inputs`. Не валідуються як target_handle —
# Workflow-валідатор розпізнає їх і генерує ребра від `condition.true`/
# `condition.false` без `target_handle`.
CONTROL_INPUT_KEYS = {
    "@on_true": "true",
    "@on_false": "false",
}


# Source-handle, який використовується, коли програміст пише лише id вузла
# (`inputs={"port": "trigger_1"}`) без явного source-порту. Більшість
# вузлів NexusFlow має output-порт із саме таким іменем (`custom_code`,
# `log`); для нестандартних випадків (`manual_trigger.data`,
# `read_file.content`) використовуйте tuple-форму.
DEFAULT_SOURCE_HANDLE = "output"


# Один елемент значення у `Node.inputs`: або просто id вузла-джерела,
# або кортеж `(source_node_id, source_handle)`. У JSON tuple
# серіалізується як список довжиною 2.
NodeInputAtom = str | tuple[str, str]


# Повне значення у `Node.inputs[<target_port>]`: одне джерело АБО список
# джерел (fan-in: декілька ребер у той самий target_handle).
NodeInputValue = NodeInputAtom | list[NodeInputAtom]


class Node(BaseModel):
    id: str
    type: NodeType
    config: dict = Field(default_factory=dict)
    # Системний (не-конфіг) атрибут вузла: визначає, як двигун розглядає
    # вхідні ребра. За замовчуванням — `all_success` (AND-семантика):
    # вузол виконається, лише якщо ВСІ вхідні ребра живі. Перемикайте на
    # `one_success` для merge-вузлів, які мають спрацьовувати, як тільки
    # хоч одна гілка живе (OR-семантика).
    trigger_rule: TriggerRule = "all_success"

    # Code-first скорочений запис підключень. Ключ — `target_handle`
    # (порт-приймач у цього вузла), значення — джерело АБО список джерел:
    #   • str  — id вузла-джерела (source_handle = "output" за замовч.);
    #   • (source_node_id, source_handle) — порт-у-порт;
    #   • list[...] — fan-in: кілька ребер у той самий target_handle
    #     (наприклад, condition зливає threshold + count в один "input").
    # Спеціальні ключі `@on_true`/`@on_false` створюють керуючі ребра
    # від condition'а (source_handle="true"/"false", без target_handle).
    # Поле `exclude=True`: не серіалізується у JSON — у файлі живе лише
    # canonical-список `edges`, який бачить фронтенд. Workflow-валідатор
    # розгортає `inputs` у `edges` під час model_validate.
    inputs: dict[str, NodeInputValue] | None = Field(default=None, exclude=True)


class Workflow(BaseModel):
    """JSON-граф workflow. Валідатор перевіряє унікальність id вузлів
    та цілісність ребер (від/до посилаються на наявні id).

    `is_readonly` — глобальний прапорець "лише для перегляду": усі ребра
    графа автоматично трактуються як readonly у двигуні та у фронтенді.
    """

    name: str = Field(min_length=1)
    nodes: list[Node]
    edges: list[Edge] = Field(default_factory=list)
    is_readonly: bool = False

    @model_validator(mode="after")
    def _resolve_inputs_to_edges(self) -> "Workflow":
        """Розгортає `Node.inputs`-скорочення у явні `Edge`-обʼєкти.

        Запускається ПЕРЕД `_check_graph_integrity`, тож згенеровані ребра
        також проходять перевірку цілісності графа (referenced nodes мають
        існувати). Уже наявні explicit-ребра не дублюються — порівняння
        йде за ключем `(from, to, source_handle, target_handle)`.

        Підтримувані формати значень у `inputs`:
          • `target: "src_id"` → Edge(src_id.output → self.target);
          • `target: ("src_id", "port")` → Edge(src_id.port → self.target);
          • `target: [src1, src2, ...]` → fan-in: окремий Edge для кожного
            джерела зі списку, всі з тим самим target_handle. Кожен елемент
            списку — або str, або (str, str).
          • `"@on_true": "cond_id"` → керуюче ребро `cond_id.true → self`
            (без target_handle); `"@on_false"` — аналогічно для false-гілки.

        Якщо джерело вказано як просто id вузла (str) — `source_handle`
        автоматично виставляється у `DEFAULT_SOURCE_HANDLE` ("output").
        """
        existing: set[tuple[str, str, str | None, str | None]] = {
            (e.from_node, e.to_node, e.source_handle, e.target_handle)
            for e in self.edges
        }
        added: list[Edge] = []

        for node in self.nodes:
            if not node.inputs:
                continue
            for key, value in node.inputs.items():
                # Контрольні (керуючі) входи: значення — лише id вузла,
                # списки тут не підтримуються, бо умова має одне джерело.
                if key in CONTROL_INPUT_KEYS:
                    if not isinstance(value, str):
                        raise ValueError(
                            f"Control-flow input {key!r} on node {node.id!r} "
                            f"expects a node-id string, got {value!r}"
                        )
                    self._append_edge(
                        added,
                        existing,
                        from_node=value,
                        to_node=node.id,
                        source_handle=CONTROL_INPUT_KEYS[key],
                        target_handle=None,
                    )
                    continue

                # Звичайні дані-входи: атомарне значення або список атомів.
                atoms = value if isinstance(value, list) else [value]
                for atom in atoms:
                    from_node, source_handle = self._parse_input_atom(
                        atom, key, node.id
                    )
                    self._append_edge(
                        added,
                        existing,
                        from_node=from_node,
                        to_node=node.id,
                        source_handle=source_handle,
                        target_handle=key,
                    )

        if added:
            self.edges = list(self.edges) + added
        return self

    @staticmethod
    def _parse_input_atom(
        atom: object, key: str, node_id: str
    ) -> tuple[str, str]:
        """str → (atom, "output"); (str, str) → as-is. Інакше ValueError."""
        if isinstance(atom, str):
            return atom, DEFAULT_SOURCE_HANDLE
        if isinstance(atom, (tuple, list)) and len(atom) == 2:
            from_node, source_handle = atom
            if isinstance(from_node, str) and isinstance(source_handle, str):
                return from_node, source_handle
        raise ValueError(
            f"Invalid input value for {key!r} on node {node_id!r}: "
            f"expected str or (str, str), got {atom!r}"
        )

    @staticmethod
    def _append_edge(
        bucket: list[Edge],
        existing: set[tuple[str, str, str | None, str | None]],
        *,
        from_node: str,
        to_node: str,
        source_handle: str | None,
        target_handle: str | None,
    ) -> None:
        edge_key = (from_node, to_node, source_handle, target_handle)
        if edge_key in existing:
            return
        bucket.append(
            Edge(
                from_node=from_node,
                to_node=to_node,
                source_handle=source_handle,
                target_handle=target_handle,
            )
        )
        existing.add(edge_key)

    @model_validator(mode="after")
    def _check_graph_integrity(self) -> "Workflow":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"Duplicate node ids: {duplicates}")

        node_id_set = set(ids)
        for edge in self.edges:
            if edge.from_node not in node_id_set:
                raise ValueError(f"Edge references unknown source node: {edge.from_node!r}")
            if edge.to_node not in node_id_set:
                raise ValueError(f"Edge references unknown target node: {edge.to_node!r}")
        return self
