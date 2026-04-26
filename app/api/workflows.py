from fastapi import APIRouter, HTTPException, status

from app.schemas.workflow import Workflow
from app.storage import file_storage as fs

router = APIRouter()


@router.get("", response_model=list[str], summary="List saved workflow names")
def list_workflows() -> list[str]:
    return fs.list_workflows()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Save a workflow under its `name`",
)
def save_workflow(workflow: Workflow) -> dict:
    try:
        path = fs.save_workflow(workflow)
    except fs.WorkflowNameError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"name": workflow.name, "saved": True, "path": str(path)}


@router.get("/{name}", response_model=Workflow, summary="Load a saved workflow")
def get_workflow(name: str) -> Workflow:
    try:
        return fs.load_workflow(name)
    except fs.WorkflowNameError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except fs.WorkflowNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workflow {name!r} not found"
        ) from exc


@router.delete("/{name}", summary="Delete a saved workflow")
def delete_workflow(name: str) -> dict:
    try:
        deleted = fs.delete_workflow(name)
    except fs.WorkflowNameError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workflow {name!r} not found"
        )
    return {"name": name, "deleted": True}
