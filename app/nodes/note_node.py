"""Note — a purely visual sticker node.
Contract:
  • `is_visual_only = True`. The engine (`WorkflowEngine`) MUST filter
    such nodes before `topological_sort` and before constructing `_RunState`. They
    do not appear in `nodes_by_id`, the `queue`, and do not affect
    `pending_count`. They leave no trace in the logs.
  • `execute(...)` — a dummy method, needed only so that Python allows
    the creation of an instance of the class (`@abstractmethod` in `BaseNode`). In the standard
    flow, it is never called.
"""

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, node_info
from app.schemas.node_configs import NoteConfig


@node_info(
    display_name="Note",
    category="visual",
    color="#fbbf24",
    icon="sticky-note",
    description="Visual-only sticky note for documenting the graph. Ignored by the engine.",
)
class NoteNode(BaseNode):
    """A sticker for comments on the canvas. The count is not involved in its creation."""

    type_name = "note"
    config_model = NoteConfig
    is_visual_only = True

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        return {"result": "note skipped"}
