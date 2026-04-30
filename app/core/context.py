import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Protocol

from app.schemas.job import LogEntry, LogLevel


class LogPublisher(Protocol):
    """Мінімальний інтерфейс брокера, від якого залежить ExecutionContext."""

    async def publish(self, job_id: str, entry: LogEntry) -> None: ...


# Тепер дозволяємо цифри одразу після крапки (наприклад, .0 або .1)
_TEMPLATE_PATTERN = re.compile(r"\{(input|nodes)\.([a-zA-Z0-9_][a-zA-Z0-9_.]*)\}")


class ExecutionContext:
    """Спільний стан, що передається між вузлами одного запуску workflow.

    У паралельному режимі двигун запускає кілька вузлів одночасно у
    воркер-пулі. Тому контекст спроєктовано потокобезпечно:

      • `lock` — `asyncio.Lock`, під яким відбуваються всі мутації
        `node_outputs` / `node_inputs`. Кожен воркер атомарно оновлює
        стан після завершення вузла.
      • `should_stop` — прапорець «м'якої зупинки». Виставляється у `True`
        при першій критичній помилці. Воркери, що збираються взяти нове
        завдання з черги, побачать прапорець і завершаться, не запускаючи
        нових вузлів. Уже працюючі вузли мають дограти до кінця.
      • `resolve_template(template, input_data)` створює локальний
        snapshot `dict(self.node_outputs)` перед ітерацією — це уникає
        `RuntimeError: dictionary changed size during iteration`, коли
        паралельний воркер довпише новий output під час підстановки.
      • Глобального `current_input` немає: вхідні дані формуються
        локально у двигуні й передаються вузлу через параметр
        `input_data`. Це усуває race-condition між паралельними вузлами.
    """

    def __init__(self, job_id: str, log_broker: LogPublisher):
        self.job_id = job_id
        self.log_broker = log_broker
        self.node_outputs: dict[str, dict] = {}
        self.node_inputs: dict[str, dict[str, Any]] = {}
        self.lock: asyncio.Lock = asyncio.Lock()
        self.should_stop: bool = False
        self.first_error: BaseException | None = None

    async def log(
        self,
        node_id: str | None,
        message: str,
        level: LogLevel = "info",
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            node_id=node_id,
            level=level,
            message=message,
        )
        await self.log_broker.publish(self.job_id, entry)

    # -----------------------------------------------------------------
    # Port-mapping API
    # -----------------------------------------------------------------

    def set_input(self, node_id: str, port_name: str, value: Any) -> None:
        """Занести значення у конкретний вхід вузла. Викликається двигуном
        під захистом `self.lock` (у engine), тому самостійних блокувань тут
        не потрібно — це просто dict-write."""
        self.node_inputs.setdefault(node_id, {})[port_name] = value

    def get_input(
        self,
        node_id: str,
        port_name: str,
        default: Any = None,
    ) -> Any:
        """Прочитати значення з конкретного вхідного порту вузла.
        Безлоковий read: бакет `node_inputs[node_id]` пише лише двигун
        перед `execute()` цього вузла, тож на момент читання він стабільний.
        """
        ports = self.node_inputs.get(node_id, {})
        return ports.get(port_name, default)

    def request_stop(self, error: BaseException | None = None) -> None:
        """М'яко зупинити подальше виконання: воркери, що візьмуть нове
        завдання, миттєво вийдуть. Уже запущені вузли дограють до кінця.
        """
        self.should_stop = True
        if error is not None and self.first_error is None:
            self.first_error = error

    def resolve_template(
        self,
        template: str,
        input_data: dict | None = None,
    ) -> str:
        """Підставляє значення у шаблон. Підтримує:
          - `{input.foo}` / `{input.foo.bar}` — з переданого `input_data`,
          - `{nodes.<node_id>.foo}` — з snapshot'у `node_outputs`.

        `input_data` — локальні вхідні дані вузла. Snapshot
        `dict(self.node_outputs)` створюється на вході у функцію, щоб
        паралельний воркер не зламав підстановку гонкою на запис.
        """
        nodes_snapshot: dict[str, dict] = dict(self.node_outputs)
        input_snapshot: dict = dict(input_data or {})

        def repl(match: re.Match[str]) -> str:
            scope, raw_path = match.group(1), match.group(2)
            keys = raw_path.split(".")
            if scope == "input":
                value = self._lookup(input_snapshot, keys, raw_path)
            else:  # nodes
                node_id, *rest = keys
                value = self._lookup(nodes_snapshot.get(node_id, {}), rest, raw_path)
            return str(value)

        return _TEMPLATE_PATTERN.sub(repl, template)

    @staticmethod
    def _lookup(data: Any, path: list[str], raw_path: str) -> Any:
        """Рекурсивний пошук значення. Підтримує ключі словників та індекси списків."""
        curr = data
        for k in path:
            # Якщо поточний об'єкт - словник, шукаємо за ключем
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            # Якщо поточний об'єкт - список, намагаємося перетворити ключ на індекс
            elif isinstance(curr, list):
                try:
                    idx = int(k)
                    if 0 <= idx < len(curr):
                        curr = curr[idx]
                    else:
                        return f"{{index_error:{raw_path}}}"
                except ValueError:
                    return f"{{not_an_index:{raw_path}}}"
            else:
                return f"{{missing:{raw_path}}}"
        return curr
