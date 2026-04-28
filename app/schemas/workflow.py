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


class Workflow(BaseModel):
    """JSON-граф workflow. Валідатор перевіряє унікальність id вузлів
    та цілісність ребер (від/до посилаються на наявні id).

    `is_readonly` — глобальний прапорець "лише для перегляду": усі ребра
    графа автоматично трактуються як readonly у двигуні та у фронтенді.
    """

    name: str = Field(min_length=1)
    nodes: list[Node]
    edges: list[Edge]
    is_readonly: bool = False

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
