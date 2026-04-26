import importlib
import inspect
import logging
import pkgutil
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.core.context import ExecutionContext

logger = logging.getLogger(__name__)


class BaseNode(ABC):
    """Базовий клас для всіх вузлів workflow.

    Підкласи мають оголосити:
      - `type_name` — рядок-ідентифікатор (унікальний у `NODE_REGISTRY`).
      - `config_model` — Pydantic-клас для валідації `config`.
      - `execute(context)` — повертає dict-output, що передається наступним вузлам.
    """

    type_name: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]

    def __init__(self, node_id: str, config: dict):
        self.id = node_id
        self.config = self.config_model(**config)

    @abstractmethod
    async def execute(self, context: "ExecutionContext") -> dict:
        ...


NODE_REGISTRY: dict[str, type[BaseNode]] = {}


def discover_nodes(package_path: str) -> dict[str, type[BaseNode]]:
    """Скан-сканер вузлів: обходить усі модулі у пакеті `package_path` (dotted name,
    напр. `"app.nodes"`), імпортує їх та реєструє у `NODE_REGISTRY` усі класи,
    що задовольняють контракт `BaseNode`.

    Контракт реєстрації:
      - клас є підкласом `BaseNode` і не самим `BaseNode`,
      - має непорожній `type_name`,
      - визначений саме у поточному модулі (щоб не реєструвати re-export).

    Помилковий модуль (синтаксис, відсутня залежність) не валить весь застосунок —
    лише логуються `WARNING` + повне трейсбек повідомлення.
    """
    package = importlib.import_module(package_path)

    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name == "base":
            continue
        full_name = f"{package_path}.{module_info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:  # noqa: BLE001 — навмисно широко
            logger.warning("Skipping node module %s: %s", full_name, exc, exc_info=True)
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseNode or not issubclass(obj, BaseNode):
                continue
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            type_name = getattr(obj, "type_name", None)
            if not isinstance(type_name, str) or not type_name:
                continue
            existing = NODE_REGISTRY.get(type_name)
            if existing is obj:
                continue
            if existing is not None:
                logger.warning(
                    "Node type %r already registered by %s; ignoring %s",
                    type_name,
                    existing.__module__,
                    obj.__module__,
                )
                continue
            NODE_REGISTRY[type_name] = obj

    print(f"Found {len(NODE_REGISTRY)} nodes: {sorted(NODE_REGISTRY)}")
    return NODE_REGISTRY
