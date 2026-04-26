import asyncio
from datetime import datetime
from uuid import uuid4

from app.core.context import ExecutionContext
from app.core.engine import WorkflowEngine
from app.core.log_broker import LogBroker
from app.schemas.job import Job, JobStatus, LogEntry
from app.schemas.workflow import Workflow


class JobManager:
    """In-memory реєстр запусків + супервайзер.

    Запуски не персистяться — після рестарту сервера втрачаються
    (TODO для розширення: SQLite). Для MVP цього достатньо.

    Контракт із WS-клієнтом: по завершенні job у broker публікується
    sentinel `LogEntry(level="done")` — клієнт читає його і закриває з'єднання.
    """

    def __init__(self, broker: LogBroker, engine: WorkflowEngine | None = None):
        self.broker = broker
        self.engine = engine or WorkflowEngine()
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def submit(self, workflow: Workflow) -> Job:
        job = Job(
            id=str(uuid4()),
            workflow_name=workflow.name,
            status=JobStatus.PENDING,
            started_at=datetime.utcnow(),
        )
        self._jobs[job.id] = job
        self._tasks[job.id] = asyncio.create_task(self._run(workflow, job))
        return job

    async def _run(self, workflow: Workflow, job: Job) -> None:
        # Локальна підписка — дублює потік логів у `job.logs`,
        # щоб GET /jobs/{id} віддавав повну історію.
        log_queue = self.broker.subscribe(job.id)
        collector = asyncio.create_task(self._collect_logs(job, log_queue))

        job.status = JobStatus.RUNNING
        ctx = ExecutionContext(job.id, self.broker)
        try:
            job.result = await self.engine.run(workflow, job.id, ctx)
            job.status = JobStatus.SUCCESS
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
        finally:
            job.finished_at = datetime.utcnow()
            sentinel = LogEntry(
                timestamp=datetime.utcnow(),
                node_id=None,
                level="done",
                message=f"Job {job.id} finished: {job.status.value}",
            )
            await self.broker.publish(job.id, sentinel)
            await collector
            self.broker.unsubscribe(job.id, log_queue)

    @staticmethod
    async def _collect_logs(job: Job, queue: asyncio.Queue[LogEntry]) -> None:
        while True:
            entry = await queue.get()
            job.logs.append(entry)
            if entry.level == "done":
                break

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        # Беремо останні `limit` запусків у порядку додавання.
        items = list(self._jobs.values())
        return items[-limit:]
