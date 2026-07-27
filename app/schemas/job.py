from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

LogLevel = Literal["info", "warning", "error", "done"]

class LogEntry(BaseModel):
    timestamp: datetime
    node_id: str | None = None
    level: LogLevel = "info"
    message: str

class Job(BaseModel):
    id: str
    workflow_name: str
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None = None
    logs: list[LogEntry] = Field(default_factory=list)
    result: dict | None = None
    error: str | None = None
