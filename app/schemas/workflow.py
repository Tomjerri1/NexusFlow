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
    "note",
]


# Node activation rules based on the state of the incoming edges.
# `all_success` — fire only if ALL incoming edges are alive (AND).
# `one_success` — fire if ANY ONE incoming edge is alive (OR).
# Start nodes (without inbound) are always activated.
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


CONTROL_INPUT_KEYS = {
    "@on_true": "true",
    "@on_false": "false",
}


# Source-handle, used when the programmer writes only the node id
# (`inputs={"port": "trigger_1"}`) without an explicit source-port. Most
# NexusFlow nodes have an output-port with exactly this name (`custom_code`,
# `log`); for non-standard cases (`manual_trigger.data`,
# `read_file.content`) use the tuple-form.
DEFAULT_SOURCE_HANDLE = "output"


NodeInputAtom = str | tuple[str, str]

NodeInputValue = NodeInputAtom | list[NodeInputAtom]


class Node(BaseModel):
    id: str
    type: NodeType
    config: dict = Field(default_factory=dict)

    trigger_rule: TriggerRule = "all_success"


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
        """Expands `Node.inputs`-shortcuts into explicit `Edge`-objects.

        Runs BEFORE `_check_graph_integrity`, so generated edges
        also pass the graph integrity check (referenced nodes must
        exist). Existing explicit edges are not duplicated — comparison
        is by key `(from, to, source_handle, target_handle)`.

        Supported value formats in `inputs`:
        • `target: "src_id"` → Edge(src_id.output → self.target);
        • `target: ("src_id", "port")` → Edge(src_id.port → self.target);
        • `target: [src1, src2, ...]` → fan-in: separate Edge for each
        source in the list, all with the same target_handle. Each element
        of the list is either str or (str, str).
        • `"@on_true": "cond_id"` → control edge `cond_id.true → self`
        (without target_handle); `"@on_false"` — similarly for false-branch.

        If the source is specified as just a node id (str) — `source_handle`
        is automatically set to `DEFAULT_SOURCE_HANDLE` ("output").
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
                # Control inputs: value is only node id,
                # lists are not supported here because the condition has a single source.
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

                # Common input data: atomic value or list of atoms.
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

        # Acyclicity check — guaranteed by DAG before the job starts.
        # Lazy import: `app.core.scheduler` itself imports `Edge`/`Node`
        # from the same module, so top-level import would give a circular
        # dependency at module load time. Lazy form is safe,
        # because the validator is called only during `model_validate`.
        from app.core.scheduler import CycleDetectedError, topological_sort

        try:
            topological_sort(self.nodes, self.edges)
        except CycleDetectedError as exc:
            raise ValueError(
                f"Workflow graph is not a DAG — cycle detected involving "
                f"nodes: {exc.cycle_node_ids}"
            ) from exc

        return self
