from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, model_validator

from app.core.job_manager import JobManager
from app.core.scheduler import CycleDetectedError, topological_sort
from app.schemas.job import Job
from app.schemas.workflow import Workflow
from app.storage import file_storage as fs

router = APIRouter()


class RunJobRequest(BaseModel):
    """Тіло POST /jobs/run. Треба вказати **або** `workflow_name` (для
    запуску збереженого), **або** `workflow` (інлайн)."""

    workflow_name: str | None = None
    workflow: Workflow | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "RunJobRequest":
        if bool(self.workflow_name) == bool(self.workflow):
            raise ValueError(
                "exactly one of 'workflow_name' or 'workflow' must be provided"
            )
        return self


def _get_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


_RUN_EXAMPLES = {
    "saved_by_name": {
        "summary": "Run a previously saved workflow by name",
        "value": {"workflow_name": "hello_world"},
    },
    "inline_hello": {
        "summary": "Run an inline workflow (manual_trigger -> log)",
        "value": {
            "workflow": {
                "name": "hello_inline",
                "nodes": [
                    {
                        "id": "t1",
                        "type": "manual_trigger",
                        "config": {"initial_data": {"user": "Student"}},
                    },
                    {
                        "id": "l1",
                        "type": "log",
                        "config": {"message": "Hello, {input.user}!"},
                    },
                ],
                "edges": [{"from": "t1", "to": "l1"}],
            }
        },
    },
}


@router.post(
    "/run",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a workflow for asynchronous execution",
)
async def run_job(
    req: Annotated[RunJobRequest, Body(openapi_examples=_RUN_EXAMPLES)],
    manager: Annotated[JobManager, Depends(_get_manager)],
) -> Job:
    if req.workflow is not None:
        wf = req.workflow
    else:
        try:
            wf = fs.load_workflow(req.workflow_name)  # type: ignore[arg-type]
        except fs.WorkflowNameError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except fs.WorkflowNotFoundError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"workflow {req.workflow_name!r} not found",
            ) from exc

    # Pre-check на цикл — даємо 400 одразу, а не FAILED-job з аутентичним статусом.
    try:
        topological_sort(wf.nodes, wf.edges)
    except CycleDetectedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return manager.submit(wf)


@router.get(
    "",
    response_model=list[Job],
    summary="List up to 50 most recent jobs",
)
def list_jobs(manager: Annotated[JobManager, Depends(_get_manager)]) -> list[Job]:
    return manager.list()


@router.get("/{job_id}", response_model=Job, summary="Get job status + logs")
def get_job(
    job_id: str, manager: Annotated[JobManager, Depends(_get_manager)]
) -> Job:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job {job_id!r} not found")
    return job
