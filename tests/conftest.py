"""Спільні фікстури для всього test-пакета."""

import sys
from pathlib import Path

# Дозволяємо запуск pytest з кореня репозиторію без `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import app.nodes  # noqa: F401  — імпорт запускає discover_nodes()
from app.core.context import ExecutionContext
from app.schemas.job import LogEntry


class FakeBroker:
    """In-memory accumulator замість справжнього LogBroker — для unit-тестів."""

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
