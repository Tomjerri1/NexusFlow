from pathlib import Path

import aiofiles

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.schemas.node_configs import WriteFileConfig

# Sandbox-каталог: дозволяємо запис лише в `<repo>/data/`.
# Будь-який шлях (відносний чи абсолютний) має після нормалізації
# опинитися всередині цього каталогу — інакше PathTraversalError.
SANDBOX_DIR = (Path(__file__).resolve().parent.parent.parent / "data").resolve()


class PathTraversalError(ValueError):
    """Шлях виходить за межі дозволеного sandbox-каталогу."""


def _resolve_safe_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    full = candidate if candidate.is_absolute() else (SANDBOX_DIR / candidate)
    resolved = full.resolve()
    try:
        resolved.relative_to(SANDBOX_DIR)
    except ValueError as exc:
        raise PathTraversalError(
            f"path {raw_path!r} resolves outside sandbox {str(SANDBOX_DIR)!r}"
        ) from exc
    return resolved


@node_info(
    display_name="Write File",
    category="io",
    color="#7c3aed",
    icon="file-pen",
    description="Writes text content to a sandboxed file under data/.",
)
@input_port("path", type_hint="str", required=True, description="Target file path inside sandbox.")
@input_port("content", type_hint="str", required=False, description="Text payload to write.")
@output_port("path", type_hint="str", description="Resolved absolute path.")
@output_port("bytes_written", type_hint="int")
@output_port("append", type_hint="bool")
class WriteFileNode(BaseNode):
    type_name = "write_file"
    config_model = WriteFileConfig

    def _port_str(self, context: ExecutionContext, port: str) -> str | None:
        """Повертає непорожній рядок саме з port-mapping, інакше None.

        Бере значення безпосередньо з `node_inputs[self.id][port]`, щоб
        відрізнити «порт не приєднаний» від «значення взялося з legacy
        merged-input» — це важливо для коректного fallback на config.
        """
        port_map = context.node_inputs.get(self.id, {})
        value = port_map.get(port)
        if isinstance(value, str) and value:
            return value
        return None

    async def execute(self, context: ExecutionContext) -> dict:
        # Пріоритет джерел даних (як для path, так і для content):
        #   1. Значення з порту (port-mapping від попереднього вузла).
        #   2. Поле з config.
        #   3. Ключ із current_input (legacy merge).
        raw_path = (
            self._port_str(context, "path")
            or self.config.path
            or str(context.current_input.get("path", ""))
        )
        if not raw_path:
            raise ValueError("write_file: no path provided (port/config/input all empty)")
        rendered = context.resolve_template(raw_path)
        path = _resolve_safe_path(rendered)

        port_content = self._port_str(context, "content")
        if port_content is not None:
            content = context.resolve_template(port_content)
        elif self.config.content is not None:
            content = context.resolve_template(self.config.content)
        else:
            raw_content = context.current_input.get(self.config.content_key, "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content)

        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.config.append else "w"
        async with aiofiles.open(path, mode=mode, encoding="utf-8") as f:
            await f.write(content)

        return {
            "path": str(path),
            "bytes_written": len(content.encode("utf-8")),
            "append": self.config.append,
        }
