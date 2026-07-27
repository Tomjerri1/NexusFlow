import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Protocol
from app.schemas.job import LogEntry, LogLevel

class LogPublisher(Protocol):

    async def publish(self, job_id: str, entry: LogEntry) -> None: ...

_TEMPLATE_PATTERN = re.compile(r"\{(input|nodes)\.([a-zA-Z0-9_][a-zA-Z0-9_.]*)\}")

class ExecutionContext:

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

    def set_input(self, node_id: str, port_name: str, value: Any) -> None:
        """Set a value for a specific node input. Called by the engine
        under the protection of `self.lock` (in the engine)."""
        self.node_inputs.setdefault(node_id, {})[port_name] = value

    def get_input(
        self,
        node_id: str,
        port_name: str,
        default: Any = None,
    ) -> Any:
        """Read the value from a specific input port of a node.
        Lock-free read: The `node_inputs[node_id]` bucket is written to only by the engine
        before this node's `execute()`, so it is stable at the time of reading.
        """
        ports = self.node_inputs.get(node_id, {})
        return ports.get(port_name, default)

    def request_stop(self, error: BaseException | None = None) -> None:
        """Gently stop further execution: workers that take on a new
        task will exit immediately. Nodes that are already running will continue until they finish.
        """
        self.should_stop = True
        if error is not None and self.first_error is None:
            self.first_error = error

    def resolve_template(
        self,
        template: str,
        input_data: dict | None = None,
    ) -> str:
        """Plays values into a template. Supports:
          - `{input.foo}` / `{input.foo.bar}` - from the passed `input_data`,
          - `{nodes.<node_id>.foo}` - from the `node_outputs` snapshot.

        `input_data` - the node's local input data. A snapshot
        `dict(self.node_outputs)` is created at the function's entry point to prevent
        a concurrent worker from breaking the substitution by a race condition on writing.
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
        """Recursive value search. Supports dictionary keys and list indices."""
        curr = data
        for k in path:
            # If the current object is a dictionary, search by key
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            # If the current object is a list, we try to convert the key to an index
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
