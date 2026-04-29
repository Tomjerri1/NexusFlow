import aiofiles

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.schemas.node_configs import ReadFileConfig


@node_info(
    display_name="Read File",
    category="io",
    color="#0284c7",
    icon="file-text",
    description="Reads UTF-8 (or configured encoding) text file.",
)
@input_port("path", type_hint="str", required=False, description="Override of config.path.")
@output_port("content", type_hint="str")
@output_port("size", type_hint="int")
@output_port("path", type_hint="str")
class ReadFileNode(BaseNode):
    type_name = "read_file"
    config_model = ReadFileConfig

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        # Пріоритет: port `path` → config.path → ключ `path` з input_data.
        port_value = context.get_input(self.id, "path")
        if isinstance(port_value, str) and port_value:
            raw_path = port_value
        elif self.config.path:
            raw_path = self.config.path
        else:
            raw_path = str(input_data.get("path", ""))
        if not raw_path:
            raise ValueError("read_file: no path provided (port/config/input all empty)")

        path = context.resolve_template(raw_path, input_data)
        async with aiofiles.open(path, mode="r", encoding=self.config.encoding) as f:
            content = await f.read()
        return {"content": content, "size": len(content), "path": path}
