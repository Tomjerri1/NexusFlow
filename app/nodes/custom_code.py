import importlib
import importlib.util
import sys
from pathlib import Path

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.schemas.node_configs import CustomCodeConfig

SCRIPTS_DIR = (Path(__file__).resolve().parent.parent.parent / "scripts").resolve()


class CustomCodeError(RuntimeError):
    """Помилка завантаження або виконання користувацького скрипта."""


def _load_script_module(script_name: str):
    """Динамічно імпортує модуль із sandbox-папки `scripts/`."""
    safe_name = Path(script_name).name
    if safe_name != script_name or not safe_name:
        raise CustomCodeError(f"invalid script_name {script_name!r}")

    script_path = (SCRIPTS_DIR / f"{safe_name}.py").resolve()
    try:
        script_path.relative_to(SCRIPTS_DIR)
    except ValueError as exc:
        raise CustomCodeError(
            f"script {script_name!r} resolves outside scripts dir"
        ) from exc

    if not script_path.is_file():
        raise CustomCodeError(f"script not found: {script_path}")

    module_name = f"nexusflow_scripts.{safe_name}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise CustomCodeError(f"cannot build import spec for {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise CustomCodeError(f"failed to import {script_name!r}: {exc}") from exc
    return module


@node_info(
    display_name="Custom Code",
    category="logic",
    color="#c026d3",
    icon="code",
    description="Runs an async function from scripts/<name>.py.",
)
@input_port("input", type_hint="dict", required=False)
@output_port("output", type_hint="dict", description="Whatever the user function returns.")
class CustomCodeNode(BaseNode):
    """Викликає async-функцію `entry_point` з модуля `scripts/<script_name>.py`.

    Контракт користувацької функції:
        async def main(input: dict, nodes: dict, **params) -> dict | None
    Якщо повертає None — нормалізуємо в `{}`.
    """

    type_name = "custom_code"
    config_model = CustomCodeConfig

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        module = _load_script_module(self.config.script_name)

        func = getattr(module, self.config.entry_point, None)
        if func is None:
            raise CustomCodeError(
                f"entry_point {self.config.entry_point!r} not found "
                f"in script {self.config.script_name!r}"
            )
        if not callable(func):
            raise CustomCodeError(
                f"entry_point {self.config.entry_point!r} is not callable"
            )

        result = await func(
            input=dict(input_data),
            nodes=dict(context.node_outputs),
            **self.config.params,
        )

        if result is None:
            return {}
        if not isinstance(result, dict):
            raise CustomCodeError(
                f"script {self.config.script_name!r} returned "
                f"{type(result).__name__}, expected dict or None"
            )
        return result
