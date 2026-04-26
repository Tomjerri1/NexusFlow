import asyncio
from collections import defaultdict

from app.schemas.job import LogEntry


class LogBroker:
    """In-memory pub/sub каналів логів — окрема черга для кожного підписника.

    Кожен виклик `subscribe(job_id)` повертає **нову** `asyncio.Queue`,
    у яку дублюється все, що публікується для `job_id`. Так і JobManager
    (для збору `job.logs`), і кожен WS-клієнт отримують повний потік
    незалежно один від одного.

    Сентинель завершення — `LogEntry` із `level="done"` (див. `JobManager`).
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
