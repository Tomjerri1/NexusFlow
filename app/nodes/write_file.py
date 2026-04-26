from pathlib import Path

import aiofiles

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode
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


class WriteFileNode(BaseNode):
    type_name = "write_file"
    config_model = WriteFileConfig

    async def execute(self, context: ExecutionContext) -> dict:
        rendered = context.resolve_template(self.config.path)
        path = _resolve_safe_path(rendered)

        if self.config.content is not None:
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
