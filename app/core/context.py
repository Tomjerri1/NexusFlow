import re
from datetime import datetime
from typing import Any, Protocol

from app.schemas.job import LogEntry, LogLevel


class LogPublisher(Protocol):
    """Мінімальний інтерфейс брокера, від якого залежить ExecutionContext.

    Конкретна реалізація — `app/core/log_broker.py` (Етап 8).
    """

    async def publish(self, job_id: str, entry: LogEntry) -> None: ...


_TEMPLATE_PATTERN = re.compile(r"\{(input|nodes)\.([a-zA-Z_][a-zA-Z0-9_.]*)\}")

# Спеціальний sentinel-ключ для "усього вихідного словника" вузла,
# коли source_handle не вказано (legacy/wildcard поведінка).
WHOLE_OUTPUT = "__output__"


class ExecutionContext:
    """Спільний стан, що передається між вузлами одного запуску workflow.

    Дані ходять у двох канавах:
      - `node_outputs[node_id]`         — повний dict, який повернув execute().
      - `node_inputs[node_id][port]`    — значення, занесене у конкретний вхід
                                          вузла маршрутизатором двигуна.
      - `current_input`                 — legacy merged-вхід (зворотна сумісність).
    """

    def __init__(self, job_id: str, log_broker: LogPublisher):
        self.job_id = job_id
        self.log_broker = log_broker
        self.node_outputs: dict[str, dict] = {}
        self.node_inputs: dict[str, dict[str, Any]] = {}
        self.current_input: dict = {}
        self._current_node_id: str | None = None

    async def log(
        self,
        node_id: str | None,
        message: str,
        level: LogLevel = "info",
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.utcnow(),
            node_id=node_id,
            level=level,
            message=message,
        )
        await self.log_broker.publish(self.job_id, entry)

    # -----------------------------------------------------------------
    # Port-mapping API
    # -----------------------------------------------------------------

    def set_input(self, node_id: str, port_name: str, value: Any) -> None:
        """Занести значення у конкретний вхід вузла. Викликається двигуном."""
        self.node_inputs.setdefault(node_id, {})[port_name] = value

    def get_input(self, node_id: str, port_name: str, default: Any = None) -> Any:
        """Прочитати значення з конкретного вхідного порту вузла.

        Якщо для порту немає прямого мапінгу — пробуємо legacy-канал:
        merged-output попередніх вузлів, що зберігається у `current_input`
        під ключем `port_name`.
        """
        ports = self.node_inputs.get(node_id, {})
        if port_name in ports:
            return ports[port_name]
        if node_id == self._current_node_id and port_name in self.current_input:
            return self.current_input[port_name]
        return default

    def resolve_template(self, template: str) -> str:
        """Підставляє значення у шаблон. Підтримує:
          - `{input.foo}` / `{input.foo.bar}` — з self.current_input
          - `{nodes.<node_id>.foo}` — з self.node_outputs
        Якщо ключ відсутній, у місце підстановки потрапляє `<missing:...>`.
        """

        def repl(match: re.Match[str]) -> str:
            scope, raw_path = match.group(1), match.group(2)
            keys = raw_path.split(".")
            if scope == "input":
                value = self._lookup(self.current_input, keys, raw_path)
            else:  # nodes
                node_id, *rest = keys
                value = self._lookup(self.node_outputs.get(node_id, {}), rest, raw_path)
            return str(value)

        return _TEMPLATE_PATTERN.sub(repl, template)

    @staticmethod
    def _lookup(data: dict, path: list[str], raw_path: str) -> Any:
        cur: Any = data
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return f"<missing:{raw_path}>"
        return cur
