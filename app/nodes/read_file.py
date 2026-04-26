import aiofiles

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode
from app.schemas.node_configs import ReadFileConfig


class ReadFileNode(BaseNode):
    type_name = "read_file"
    config_model = ReadFileConfig

    async def execute(self, context: ExecutionContext) -> dict:
        path = context.resolve_template(self.config.path)
        async with aiofiles.open(path, mode="r", encoding=self.config.encoding) as f:
            content = await f.read()
        return {"content": content, "size": len(content), "path": path}
