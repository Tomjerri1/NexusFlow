import json

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.schemas.node_configs import LogNodeConfig


def _json_safe(value):
    """JSON-серіалізатор для типів, які стандартний json не вміє."""
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return repr(value)


@node_info(
    display_name="Log",
    category="util",
    color="#64748b",
    icon="terminal",
    description="Logs a message and forwards input downstream.",
)
@input_port("input", type_hint="dict", required=False)
@input_port("message", type_hint="str", required=False, description="Override of config.message.")
@output_port("output", type_hint="dict", description="Pass-through of the input.")
class LogNode(BaseNode):
    """Логує повідомлення (з підстановкою шаблонів) і пробрасує input далі.

    Якщо ні з порту `message`, ні з `config.message` нічого не прийшло —
    замість порожнього рядка дампимо весь `current_input` як JSON. Це
    робить вузол корисним «з коробки»: достатньо підключити лінію.
    """

    type_name = "log"
    config_model = LogNodeConfig

    async def execute(self, context: ExecutionContext) -> dict:
        port_message = context.get_input(self.id, "message")
        raw = port_message if isinstance(port_message, str) and port_message else self.config.message

        if raw:
            message = context.resolve_template(raw)
        else:
            try:
                message = json.dumps(
                    context.current_input,
                    ensure_ascii=False,
                    default=_json_safe,
                )
            except Exception as exc:  # noqa: BLE001
                message = f"<input not serializable: {exc}>"

        await context.log(self.id, message, level=self.config.level)
        return dict(context.current_input)
