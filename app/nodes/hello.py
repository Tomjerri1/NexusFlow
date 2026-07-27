from pydantic import BaseModel
from app.nodes.base import BaseNode, input_port, output_port, node_info

class HelloConfig(BaseModel):
    pass

@node_info(
    display_name="Hello",
    description="Вивожу слово 'Привіт'",
)
@output_port("output", type_hint="str", description="Вихід слова 'Привіт'")
class HelloNode(BaseNode):
    type_name = "hello"
    config_model = HelloConfig

    async def execute(self, context, input_data: dict) -> dict:
        return {"output": "Привіт"}