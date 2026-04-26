import re
from pathlib import Path

from app.schemas.workflow import Workflow

WORKFLOWS_DIR = (Path(__file__).resolve().parent.parent.parent / "workflows").resolve()

# Тільки літери/цифри/_/-, від 1 до 64 символів — щоб ім'я не могло втекти з папки.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class WorkflowNotFoundError(FileNotFoundError):
    pass


class WorkflowNameError(ValueError):
    pass


def _safe_path(name: str) -> Path:
    if not _NAME_RE.match(name):
        raise WorkflowNameError(
            f"invalid workflow name {name!r}: only [A-Za-z0-9_-], 1-64 chars"
        )
    candidate = (WORKFLOWS_DIR / f"{name}.json").resolve()
    try:
        candidate.relative_to(WORKFLOWS_DIR)
    except ValueError as exc:
        raise WorkflowNameError(f"name {name!r} escapes workflows storage") from exc
    return candidate


def list_workflows() -> list[str]:
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(p.stem for p in WORKFLOWS_DIR.glob("*.json"))


def save_workflow(workflow: Workflow) -> Path:
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    path = _safe_path(workflow.name)
    payload = workflow.model_dump_json(by_alias=True, indent=2)
    path.write_text(payload, encoding="utf-8")
    return path


def load_workflow(name: str) -> Workflow:
    path = _safe_path(name)
    if not path.exists():
        raise WorkflowNotFoundError(name)
    return Workflow.model_validate_json(path.read_text(encoding="utf-8"))


def delete_workflow(name: str) -> bool:
    path = _safe_path(name)
    if not path.exists():
        return False
    path.unlink()
    return True
