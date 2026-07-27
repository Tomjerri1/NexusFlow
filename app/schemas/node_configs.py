from typing import Literal

from pydantic import BaseModel, Field
# from app.nodes.hello import HelloConfig
from app.schemas.workflow import Node


class ManualTriggerConfig(BaseModel):
    initial_data: dict = Field(default_factory=dict)

class ReadDirectoryConfig(BaseModel):
    path: str = Field(default="data")
    recursive: bool = Field(default=False)
    extension: str = Field(default="")
    name_contains: str = Field(default="")

class ReadFileConfig(BaseModel):
    """The path may be empty if it is passed via the `path` port (port mapping)."""

    path: str = ""
    encoding: str = "utf-8"


class WriteFileConfig(BaseModel):
    """The path/content may be empty if they are received via the `path`/`content` ports."""

    path: str = ""
    # If specified, this text is written (supports templates
    # `{input.x}` / `{nodes.id.y}`). If `None`, fallback to `content_key`.
    content: str | None = None
    content_key: str = "content"
    append: bool = False


class ConditionConfig(BaseModel):
    expression: str = Field(min_length=1)

class LogNodeConfig(BaseModel):
    """`message` supports placeholders such as {input.foo} and {nodes.id.bar}.
    If `message` is empty, the node logs the entire `current_input` as a JSON string
    (useful for debugging: connect to the port → see the data in the logs without any extra
    configuration).
    """
    message: str = ""
    level: Literal["info", "warning", "error"] = "info"


class CustomCodeConfig(BaseModel):
    """An orchestrator for an external Python script from the `scripts/` folder.
    `script_name` — the module name without the extension (e.g., `my_logic`).
    `entry_point` — the name of the async function in the module (by contract — a coroutine).
    `params` — kwargs passed to the function along with `input` and `nodes`.
    """

    script_name: str = Field(min_length=1)
    entry_point: str = "main"
    params: dict = Field(default_factory=dict)


class ExpressionConfig(BaseModel):
    """An arbitrary expression for `simpleeval`. `input` and `nodes` are available."""

    expression: str = Field(min_length=1)


class NoteConfig(BaseModel):
    """Visual sticker. Does not participate in graph execution.
    The engine completely ignores nodes of type `note` (via the
    `BaseNode.is_visual_only=True` flag): such nodes are filtered out even before
    topological sorting and the construction of the _RunState.
    """

    title: str = "Примітка"
    html_content: str = ""
    width: float = 240
    height: float = 160
    background_color: str = "#fef3c7"
    text_color: str = "#1f2937"
    font_family: str = "system-ui, sans-serif"
    font_size: float = 14.0

CONFIG_MAP: dict[str, type[BaseModel]] = {
    "manual_trigger": ManualTriggerConfig,
    "read_file": ReadFileConfig,
    "write_file": WriteFileConfig,
    "condition": ConditionConfig,
    "log": LogNodeConfig,
    "custom_code": CustomCodeConfig,
    "expression": ExpressionConfig,
    "note": NoteConfig,
    "read_directory": ReadDirectoryConfig,
    # "hello": HelloConfig,
}

def validate_node_config(node: Node) -> BaseModel:
    """Returns a typed configuration for the node. Raises a ValueError if the type is unknown."""
    cfg_cls = CONFIG_MAP.get(node.type)
    if cfg_cls is None:
        raise ValueError(f"Unknown node type: {node.type!r}")
    return cfg_cls(**node.config)
