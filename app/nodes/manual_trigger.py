from app.core.context import ExecutionContext
from app.nodes.base import BaseNode
from app.schemas.node_configs import ManualTriggerConfig


class ManualTriggerNode(BaseNode):
    """Стартовий вузол. Просто емітить `initial_data` як свій output."""

    type_name = "manual_trigger"
    config_model = ManualTriggerConfig

    async def execute(self, context: ExecutionContext) -> dict:
        return dict(self.config.initial_data)
