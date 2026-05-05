import importlib
import inspect
import logging
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.core.context import ExecutionContext

logger = logging.getLogger(__name__)


# Декларативні метадані: порти + UI-info

@dataclass(frozen=True)
class PortSpec:
    """Опис одного порту (вхідного або вихідного)."""

    name: str
    type_hint: str = "any"
    required: bool = False
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_hint,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class StaticConnection:
    """Декларативний (зашитий у код вузла) зв'язок порт→порт.

    Такі зв'язки серіалізуються в JSON-маніфест із прапорцем
    `is_readonly: true` — фронтенд забороняє редагування цих ліній.
    """

    source_port: str
    target_node: str
    target_port: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_port": self.source_port,
            "target_node": self.target_node,
            "target_port": self.target_port,
            "is_readonly": True,
        }


@dataclass(frozen=True)
class NodeInfo:
    """UI-метадані вузла, що повертаються у `/api/nodes/schema`."""

    display_name: str
    category: str = "general"
    color: str = "#64748b"
    icon: str = "circle"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "category": self.category,
            "color": self.color,
            "icon": self.icon,
            "description": self.description,
        }


def _ensure_own(cls: type, attr: str, default_factory):
    """Гарантує, що атрибут належить *цьому* класу (а не успадкований).

    Інакше @input_port на дочірньому класі мутував би список батька.
    """
    if attr not in cls.__dict__:
        setattr(cls, attr, default_factory())
    return getattr(cls, attr)


def input_port(
    name: str,
    type_hint: str = "any",
    required: bool = False,
    description: str | None = None,
):
    """Декоратор класу вузла: оголошує вхідний порт.

    Метадані зберігаються у `cls.__inputs__`.
    """

    def decorator(cls):
        ports: list[PortSpec] = _ensure_own(cls, "__inputs__", list)
        ports.insert(0, PortSpec(name=name, type_hint=type_hint, required=required, description=description))
        return cls

    return decorator


def output_port(
    name: str,
    type_hint: str = "any",
    description: str | None = None,
):
    """Декоратор класу вузла: оголошує вихідний порт. Метадані — у `cls.__outputs__`."""

    def decorator(cls):
        ports: list[PortSpec] = _ensure_own(cls, "__outputs__", list)
        ports.insert(0, PortSpec(name=name, type_hint=type_hint, required=False, description=description))
        return cls

    return decorator


def node_info(
    display_name: str,
    category: str = "general",
    color: str = "#64748b",
    icon: str = "circle",
    description: str = "",
):
    """Декоратор класу вузла: записує UI-метадані у `cls.__node_info__`."""

    def decorator(cls):
        cls.__node_info__ = NodeInfo(
            display_name=display_name,
            category=category,
            color=color,
            icon=icon,
            description=description,
        )
        return cls

    return decorator


def static_connection(source_port: str, target_node: str, target_port: str):
    """Декоратор класу вузла: жорстко зашитий зв'язок порт→порт.

    Серіалізується у схему з `is_readonly: true`. Двигун може використати
    цей список як fallback-маршрутизацію, якщо у Workflow немає
    відповідного explicit-ребра.
    """

    def decorator(cls):
        conns: list[StaticConnection] = _ensure_own(cls, "__static_connections__", list)
        conns.append(StaticConnection(source_port=source_port, target_node=target_node, target_port=target_port))
        return cls

    return decorator


# Базовий клас

class BaseNode(ABC):
    """Базовий клас для всіх вузлів workflow.

    Підкласи мають оголосити:
      - `type_name` — рядок-ідентифікатор (унікальний у `NODE_REGISTRY`).
      - `config_model` — Pydantic-клас для валідації `config`.
      - `execute(context)` — повертає dict-output, що передається наступним вузлам.

    Декларативні метадані (опційно):
      - `@input_port(...)`, `@output_port(...)` — порти.
      - `@node_info(...)` — UI-метадані.
      - `@static_connection(...)` — readonly-зв'язки.
    """

    type_name: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]

    is_visual_only: ClassVar[bool] = False

    __inputs__: ClassVar[list[PortSpec]] = []
    __outputs__: ClassVar[list[PortSpec]] = []
    __static_connections__: ClassVar[list[StaticConnection]] = []
    __node_info__: ClassVar[NodeInfo | None] = None

    def __init__(self, node_id: str, config: dict):
        self.id = node_id
        self.config = self.config_model(**config)

    @abstractmethod
    async def execute(
        self,
        context: "ExecutionContext",
        input_data: dict,
    ) -> dict:
        """Виконати логіку вузла.

        :param context: спільний (потокобезпечний) стан запуску.
        :param input_data: локальний словник вхідних даних, сформований
            двигуном саме для цього виклику. Замість колишнього
            `context.current_input`: data isolation на параметр функції,
            що знімає race-condition між паралельними воркерами.
        """
        ...

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """JSON-маніфест вузла для `/api/nodes/schema` та динамічного UI."""
        info = cls.__node_info__ or NodeInfo(display_name=cls.type_name)
        inputs = list(cls.__dict__.get("__inputs__", cls.__inputs__))
        outputs = list(cls.__dict__.get("__outputs__", cls.__outputs__))
        statics = list(cls.__dict__.get("__static_connections__", cls.__static_connections__))

        try:
            config_schema = cls.config_model.model_json_schema()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cannot build config schema for %s: %s", cls.type_name, exc)
            config_schema = {}

        return {
            "type_name": cls.type_name,
            "info": info.to_dict(),
            "inputs": [p.to_dict() for p in inputs],
            "outputs": [p.to_dict() for p in outputs],
            "static_connections": [c.to_dict() for c in statics],
            "config_schema": config_schema,
            "is_visual_only": bool(cls.is_visual_only),
        }


NODE_REGISTRY: dict[str, type[BaseNode]] = {}


def register_node(cls: type[BaseNode]) -> type[BaseNode]:
    """Опційний декоратор-аліас для явної реєстрації (поряд із auto-discovery)."""
    type_name = getattr(cls, "type_name", None)
    if not isinstance(type_name, str) or not type_name:
        raise ValueError(f"{cls.__name__} has no valid type_name")
    NODE_REGISTRY.setdefault(type_name, cls)
    return cls


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
