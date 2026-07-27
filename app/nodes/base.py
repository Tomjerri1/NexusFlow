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


# Declarative metadata: ports + UI information

@dataclass(frozen=True)
class PortSpec:
    """Description of a single port (inbound or outbound)."""

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
    """Declarative (hard-coded into the node) port-to-port connection.

    Such connections are serialized into the JSON manifest with the flag
    `is_readonly: true` — the frontend prevents editing of these lines.
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
    """The node's UI metadata, returned at `/api/nodes/schema`."""

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
    """Ensures that the attribute belongs to *this* class (rather than being inherited).
    Otherwise, @input_port on the child class would modify the parent's list.
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
    """Node class decorator: declares the input port.
    The metadata is stored in `cls.__inputs__`.
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
    """Node class decorator: declares the output port. The metadata is in `cls.__outputs__`."""

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
    """Node class decorator: records UI metadata in `cls.__node_info__`."""

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
    """Node-class decorator: a hard-coded port-to-port connection.
    Serialized into a diagram with `is_readonly: true`. The engine can use
    this list as fallback routing if the Workflow does not have
    a corresponding explicit edge.
    """

    def decorator(cls):
        conns: list[StaticConnection] = _ensure_own(cls, "__static_connections__", list)
        conns.append(StaticConnection(source_port=source_port, target_node=target_node, target_port=target_port))
        return cls

    return decorator

# Basic class

class BaseNode(ABC):
    """The base class for all workflow nodes.
    Subclasses must declare:
      - `type_name` — a string identifier (unique in `NODE_REGISTRY`).
      - `config_model` — a Pydantic class for validating `config`.
      - `execute(context)` — returns a dict-output that is passed to subsequent nodes.
    Declarative metadata (optional):
      - `@input_port(...)`, `@output_port(...)` — ports.
      - `@node_info(...)` — UI metadata.
      - `@static_connection(...)` — read-only connections.
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
        """Execute the node's logic.
        :param context: shared (thread-safe) execution state.
        :param input_data: local input data dictionary generated
            by the engine specifically for this call. Replaces the former
            `context.current_input`: data isolation for the function parameter,
            which eliminates race conditions between parallel workers.
        """
        ...

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """The JSON manifest for the `/api/nodes/schema` endpoint and the dynamic UI."""
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
    """An optional decorator alias for explicit registration (in addition to auto-discovery)."""
    type_name = getattr(cls, "type_name", None)
    if not isinstance(type_name, str) or not type_name:
        raise ValueError(f"{cls.__name__} has no valid type_name")
    NODE_REGISTRY.setdefault(type_name, cls)
    return cls


def discover_nodes(package_path: str) -> dict[str, type[BaseNode]]:
    """Node scanner: iterates through all modules in the `package_path` (dotted name,
    e.g., `“app.nodes”`), imports them, and registers all classes
    that satisfy the `BaseNode` contract in `NODE_REGISTRY`.
    Registration contract:
      - the class is a subclass of `BaseNode` and not `BaseNode` itself,
      - has a non-empty `type_name`,
      - is defined specifically in the current module (to avoid registering re-exports).
    An invalid module (syntax error, missing dependency) does not crash the entire application —
    only `WARNING` + a full traceback message are logged.
    """
    package = importlib.import_module(package_path)

    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name == "base":
            continue
        full_name = f"{package_path}.{module_info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:  # noqa: BLE001 — intentionally wide
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
