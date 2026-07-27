import asyncio
from collections import defaultdict

from app.schemas.job import LogEntry


class LogBroker:
    """In-memory pub/sub log channels — a separate queue for each subscriber.

    Each call to `subscribe(job_id)` returns a **new** `asyncio.Queue`,
    into which everything published for `job_id` is duplicated. Both the JobManager
    (for collecting `job.logs`) and each WS client receive the full stream
    independently of one another.

    The completion sentinel is a `LogEntry` with `level=“done”` (see `JobManager`).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[LogEntry]]] = defaultdict(list)

    def subscribe(self, job_id: str) -> asyncio.Queue[LogEntry]:
        queue: asyncio.Queue[LogEntry] = asyncio.Queue()
        self._subscribers[job_id].append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[LogEntry]) -> None:
        subs = self._subscribers.get(job_id)
        if not subs:
            return
        try:
            subs.remove(queue)
        except ValueError:
            pass
        if not subs:
            self._subscribers.pop(job_id, None)

    async def publish(self, job_id: str, entry: LogEntry) -> None:
        for queue in list(self._subscribers.get(job_id, [])):
            await queue.put(entry)
