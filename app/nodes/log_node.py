from app.core.context import ExecutionContext
from app.nodes.base import BaseNode
from app.schemas.node_configs import LogNodeConfig


class LogNode(BaseNode):
    """Логує повідомлення (з підстановкою шаблонів) і пробрасує input далі."""

    type_name = "log"
    config_model = LogNodeConfig

    async def execute(self, context: ExecutionContext) -> dict:
        message = context.resolve_template(self.config.message)
        await context.log(self.id, message, level=self.config.level)
        return dict(context.current_input)
