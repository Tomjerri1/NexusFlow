"""Note (Примітка) — суто візуальний вузол-стікер.

Контракт:
  • `is_visual_only = True`. Рушій (`WorkflowEngine`) ОБОВ'ЯЗКОВО фільтрує
    такі вузли ще до `topological_sort` і до побудови `_RunState`. Вони
    не потрапляють у `nodes_by_id`, чергу `queue` та не впливають на
    `pending_count`. У логах від них не залишається жодного сліду.
  • `execute(...)` — заглушка, потрібна лише для того, щоб Python дозволив
    створити екземпляр класу (`@abstractmethod` у `BaseNode`). У штатному
    flow вона ніколи не викликається.
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
    """Стікер для коментарів на канвасі. У виконанні графа не бере участі."""

    type_name = "note"
    config_model = NoteConfig
    is_visual_only = True

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        return {"result": "note skipped"}
