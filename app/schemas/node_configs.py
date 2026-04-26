from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.workflow import Node


class ManualTriggerConfig(BaseModel):
    initial_data: dict = Field(default_factory=dict)


class ReadFileConfig(BaseModel):
    """Шлях може бути порожнім, якщо він прийде через порт `path` (port-mapping)."""

    path: str = ""
    encoding: str = "utf-8"


class WriteFileConfig(BaseModel):
    """Шлях/вміст можуть бути порожніми, якщо приходять через порти `path`/`content`."""

    path: str = ""
    # Якщо задано — записується саме цей текст (підтримує шаблони
    # `{input.x}` / `{nodes.id.y}`). Якщо `None` — fallback на `content_key`.
    content: str | None = None
    content_key: str = "content"
    append: bool = False


class ConditionConfig(BaseModel):
    """Безпечне булеве вираження. Приклад: 'input.size > 100'."""

    expression: str = Field(min_length=1)


class LogNodeConfig(BaseModel):
    """`message` підтримує плейсхолдери {input.foo} / {nodes.id.bar}.

    Якщо `message` порожнє — вузол логує весь `current_input` як JSON-рядок
    (зручно для дебагу: підключив порт → побачив дані в логах без зайвих
    налаштувань).
    """

    message: str = ""
    level: Literal["info", "warning", "error"] = "info"


class CustomCodeConfig(BaseModel):
    """Оркестратор зовнішнього Python-скрипта з папки `scripts/`.

    `script_name` — ім'я модуля без розширення (напр. `my_logic`).
    `entry_point` — назва async-функції у модулі (за контрактом — корутина).
    `params` — kwargs, що передаються у функцію разом із `input` та `nodes`.
    """

    script_name: str = Field(min_length=1)
    entry_point: str = "main"
    params: dict = Field(default_factory=dict)


class ExpressionConfig(BaseModel):
    """Довільний вираз для simpleeval. Доступні `input` та `nodes`."""

    expression: str = Field(min_length=1)


CONFIG_MAP: dict[str, type[BaseModel]] = {
    "manual_trigger": ManualTriggerConfig,
    "read_file": ReadFileConfig,
    "write_file": WriteFileConfig,
    "condition": ConditionConfig,
    "log": LogNodeConfig,
    "custom_code": CustomCodeConfig,
    "expression": ExpressionConfig,
}


def validate_node_config(node: Node) -> BaseModel:
    """Повертає типізований конфіг для вузла. Кидає ValueError, якщо тип невідомий."""
    cfg_cls = CONFIG_MAP.get(node.type)
    if cfg_cls is None:
        raise ValueError(f"Unknown node type: {node.type!r}")
    return cfg_cls(**node.config)
