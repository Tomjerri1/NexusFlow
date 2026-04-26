from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.nodes  # noqa: F401  — імпорт запускає discover_nodes()
from app.api import jobs, websocket, workflows
from app.core.job_manager import JobManager
from app.core.log_broker import LogBroker
from app.nodes.base import NODE_REGISTRY


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


@app.get("/api/nodes/schema", tags=["meta"])
async def nodes_schema() -> dict[str, list[dict]]:
    """JSON-маніфест усіх зареєстрованих вузлів для динамічного UI.

    Кожен елемент містить порти (in/out), UI-метадані (`info`),
    декларативні static-зв'язки (`is_readonly: true`) та pydantic-схему
    конфігу. Помилка побудови схеми одного вузла не валить ендпоінт.
    """
    schemas: list[dict] = []
    for type_name, cls in sorted(NODE_REGISTRY.items()):
        try:
            schemas.append(cls.get_schema())
        except Exception as exc:  # noqa: BLE001
            schemas.append({
                "type_name": type_name,
                "error": f"failed to build schema: {exc}",
            })
    return {"nodes": schemas}
