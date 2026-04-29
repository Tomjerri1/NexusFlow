from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, node_info, output_port
from app.schemas.node_configs import ManualTriggerConfig


@node_info(
    display_name="Manual Trigger",
    category="trigger",
    color="#059669",
    icon="play",
    description="Workflow entry point. Emits config.initial_data as output.",
)
@output_port("data", type_hint="dict", description="Initial payload propagated downstream.")
class ManualTriggerNode(BaseNode):
    """Стартовий вузол. Просто емітить `initial_data` як свій output."""

    type_name = "manual_trigger"
    config_model = ManualTriggerConfig

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        return dict(self.config.initial_data)
