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


class Node(BaseModel):
    id: str
    type: NodeType
    config: dict = Field(default_factory=dict)


class Workflow(BaseModel):
    """JSON-граф workflow. Валідатор перевіряє унікальність id вузлів
    та цілісність ребер (від/до посилаються на наявні id).
    """

    name: str = Field(min_length=1)
    nodes: list[Node]
    edges: list[Edge]

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
