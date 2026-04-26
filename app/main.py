from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.nodes  # noqa: F401  — імпорт запускає discover_nodes()
from app.api import jobs, websocket, workflows
from app.core.job_manager import JobManager
from app.core.log_broker import LogBroker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    broker = LogBroker()
    app.state.broker = broker
    app.state.job_manager = JobManager(broker)
    yield


app = FastAPI(
    title="NexusFlow API",
    description="Visual workflow engine — backend for the React Flow editor.",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

# Дозволяємо лише dev-origin Vite. Якщо у майбутньому буде продакшн-домен —
# додавай його сюди (або читай зі змінної середовища).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(websocket.router, tags=["websocket"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
