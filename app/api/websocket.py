from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.job_manager import JobManager
from app.core.log_broker import LogBroker

router = APIRouter()


@router.websocket("/ws/jobs/{job_id}")
async def stream_job_logs(websocket: WebSocket, job_id: str) -> None:
    broker: LogBroker = websocket.app.state.broker
    manager: JobManager = websocket.app.state.job_manager

    await websocket.accept()
    queue = broker.subscribe(job_id)
    seen_ids: set[int] = set()
    try:
        job = manager.get(job_id)
        if job is not None:
            for entry in list(job.logs):  # snapshot
                seen_ids.add(id(entry))
                await websocket.send_json(entry.model_dump(mode="json"))
                if entry.level == "done":
                    return

        while True:
            entry = await queue.get()
            if id(entry) in seen_ids:
                continue
            await websocket.send_json(entry.model_dump(mode="json"))
            if entry.level == "done":
                break
    except WebSocketDisconnect:
        pass
    finally:
        broker.unsubscribe(job_id, queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass
