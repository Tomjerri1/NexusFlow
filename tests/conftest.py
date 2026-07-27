"""Shared fixtures for the entire test suite."""

import sys
from pathlib import Path

# Allow pytest to be run from the root of the repository without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import app.nodes  # noqa: F401 — the import triggers discover_nodes()
from app.core.context import ExecutionContext
from app.schemas.job import LogEntry


class FakeBroker:
    """An in-memory accumulator instead of the actual LogBroker—for unit tests."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, LogEntry]] = []

    async def publish(self, job_id: str, entry: LogEntry) -> None:
        self.entries.append((job_id, entry))


@pytest.fixture
def fake_broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def ctx(fake_broker: FakeBroker) -> ExecutionContext:
    return ExecutionContext("test-job", fake_broker)
